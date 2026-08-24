from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from foundora.infrastructure.database import get_session_factory
from foundora.models import WorkflowRun, WorkflowStepRun
from foundora.workflows.service import _enqueue_sync

logger = logging.getLogger(__name__)
MAX_WORKER_RECOVERIES = 3
STALE_RUNNING_AFTER = timedelta(seconds=360)
RECOVERY_BATCH_SIZE = 500


def _now() -> datetime:
    return datetime.now(UTC)


async def recover_workflow_runs() -> tuple[int, int]:
    """Reconcile durable queue delivery and reclaim interrupted workflow steps."""
    session_factory = get_session_factory()
    now = _now()
    stale_before = now - STALE_RUNNING_AFTER
    recovered = 0
    failed = 0
    async with session_factory() as database:
        async with database.begin():
            candidates = list(
                await database.scalars(
                    select(WorkflowRun)
                    .where(
                        or_(
                            WorkflowRun.status == "queued",
                            (
                                (WorkflowRun.status == "running")
                                & (WorkflowRun.started_at.is_not(None))
                                & (WorkflowRun.started_at <= stale_before)
                            ),
                        )
                    )
                    .order_by(WorkflowRun.queued_at)
                    .limit(RECOVERY_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            )
            for run in candidates:
                if run.status != "running":
                    continue
                if run.worker_recovery_count >= MAX_WORKER_RECOVERIES:
                    run.status = "failed"
                    run.error_type = "workflow_worker_recovery_exhausted"
                    run.error_message = (
                        "The workflow worker was interrupted repeatedly before a checkpoint"
                    )
                    run.completed_at = now
                    failed += 1
                    continue
                running_steps = list(
                    await database.scalars(
                        select(WorkflowStepRun).where(
                            WorkflowStepRun.workflow_run_id == run.id,
                            WorkflowStepRun.status == "running",
                        )
                    )
                )
                for step in running_steps:
                    step.status = "pending"
                run.status = "queued"
                run.worker_recovery_count += 1
                run.queued_at = now
                run.current_step_key = None
                recovered += 1
            queued = [
                (run.id, run.worker_recovery_count) for run in candidates if run.status == "queued"
            ]
    for run_id, recovery_count in queued:
        try:
            _enqueue_sync(run_id, recovery_count)
        except Exception:
            logger.exception("Workflow queue reconciliation failed")
    return recovered, failed
