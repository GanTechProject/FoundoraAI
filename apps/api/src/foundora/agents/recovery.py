from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import or_, select

from foundora.agents.service import _enqueue_sync
from foundora.infrastructure.database import get_session_factory
from foundora.models import AgentMessage, AgentRun

logger = logging.getLogger(__name__)
MAX_WORKER_RECOVERIES = 3
STALE_RUNNING_AFTER = timedelta(seconds=360)
RECOVERY_BATCH_SIZE = 500


def _now() -> datetime:
    return datetime.now(UTC)


def _recover_stale_state(run: AgentRun, now: datetime) -> Literal["requeued", "failed"]:
    if run.worker_recovery_count >= MAX_WORKER_RECOVERIES:
        run.status = "failed"
        run.error_type = "worker_recovery_exhausted"
        run.error_message = "The agent worker was interrupted repeatedly before completion"
        run.completed_at = now
        return "failed"
    run.status = "queued"
    run.worker_recovery_count += 1
    run.queued_at = now
    run.started_at = None
    run.model_operation_id = None
    return "requeued"


async def recover_agent_runs() -> tuple[int, int]:
    """Restore queue delivery and reclaim runs left by a terminated work horse."""
    session_factory = get_session_factory()
    now = _now()
    stale_before = now - STALE_RUNNING_AFTER
    recovered = 0
    failed = 0
    async with session_factory() as database:
        async with database.begin():
            candidates = list(
                await database.scalars(
                    select(AgentRun)
                    .where(
                        or_(
                            AgentRun.status == "queued",
                            (
                                (AgentRun.status == "running")
                                & (AgentRun.started_at.is_not(None))
                                & (AgentRun.started_at <= stale_before)
                            ),
                        )
                    )
                    .order_by(AgentRun.queued_at)
                    .limit(RECOVERY_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            )
            for run in candidates:
                if run.status != "running":
                    continue
                outcome = _recover_stale_state(run, now)
                if outcome == "failed":
                    database.add(
                        AgentMessage(
                            id=uuid.uuid4(),
                            run_id=run.id,
                            sequence=2,
                            role="system",
                            message_type="error",
                            content={
                                "error_type": run.error_type,
                                "message": run.error_message,
                            },
                            created_at=now,
                        )
                    )
                    failed += 1
                    continue
                recovered += 1
            queued_deliveries = [
                (run.id, run.worker_recovery_count) for run in candidates if run.status == "queued"
            ]

    for run_id, worker_recovery_count in queued_deliveries:
        try:
            _enqueue_sync(run_id, worker_recovery_count)
        except Exception:
            logger.exception(
                "Agent run reconciliation could not ensure its queue job",
                extra={"event": "agent.run.recovery_enqueue_failed"},
            )
    return recovered, failed
