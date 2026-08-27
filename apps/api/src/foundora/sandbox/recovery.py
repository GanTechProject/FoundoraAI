from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import or_, select

from foundora.infrastructure.database import get_session_factory
from foundora.models import SandboxExecution
from foundora.sandbox.runner_client import (
    TERMINAL_RUNNER_STATUSES,
    RunnerAbsenceProof,
    RunnerReceipt,
)
from foundora.sandbox.runtime import (
    SandboxRuntimeClient,
    SqlSandboxRuntimeRepository,
    create_runner_client,
)
from foundora.sandbox.service import TERMINAL_STATUSES, _enqueue_sync

logger = logging.getLogger(__name__)
MAX_WORKER_RECOVERIES = 3
STALE_EXECUTION_AFTER = timedelta(seconds=90)
RECOVERY_BATCH_SIZE = 100


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RecoveryDecision:
    action: Literal["deliver", "cancel", "exhausted", "skip"]
    worker_recovery_count: int


async def _prepare_recovery(execution_id: uuid.UUID, *, now: datetime) -> RecoveryDecision:
    session_factory = get_session_factory()
    async with session_factory() as database:
        async with database.begin():
            execution = await database.scalar(
                select(SandboxExecution)
                .where(SandboxExecution.id == execution_id)
                .with_for_update()
            )
            if execution is None or execution.status in TERMINAL_STATUSES:
                return RecoveryDecision("skip", 0)
            if execution.cancellation_requested_at is not None:
                return RecoveryDecision("cancel", execution.worker_recovery_count)
            if execution.status == "queued":
                return RecoveryDecision("deliver", execution.worker_recovery_count)
            if execution.worker_recovery_count >= MAX_WORKER_RECOVERIES:
                return RecoveryDecision("exhausted", execution.worker_recovery_count)
            execution.status = "queued"
            execution.worker_recovery_count += 1
            execution.attempt_started_at = None
            execution.heartbeat_at = None
            execution.updated_at = now
            execution.termination_reason = "recovering interrupted sandbox worker"
            return RecoveryDecision("deliver", execution.worker_recovery_count)


async def _candidate_ids(now: datetime) -> list[uuid.UUID]:
    session_factory = get_session_factory()
    stale_before = now - STALE_EXECUTION_AFTER
    async with session_factory() as database:
        return list(
            await database.scalars(
                select(SandboxExecution.id)
                .where(
                    or_(
                        SandboxExecution.status == "queued",
                        (
                            SandboxExecution.status.in_({"authorizing", "running", "cleaning"})
                            & or_(
                                SandboxExecution.heartbeat_at.is_(None),
                                SandboxExecution.heartbeat_at <= stale_before,
                            )
                        ),
                    )
                )
                .order_by(SandboxExecution.updated_at)
                .limit(RECOVERY_BATCH_SIZE)
            )
        )


async def recover_sandbox_executions(
    runner: SandboxRuntimeClient | None = None,
) -> tuple[int, int]:
    """Reconcile runner receipts before restoring any deterministic queue delivery."""
    active_runner = runner or create_runner_client()
    repository = SqlSandboxRuntimeRepository()
    now = _now()
    recovered = 0
    failed = 0
    for execution_id in await _candidate_ids(now):
        try:
            receipt = await active_runner.inspect(execution_id)
            if receipt is not None and receipt.status in TERMINAL_RUNNER_STATUSES:
                if await repository.complete_receipt(execution_id, receipt):
                    recovered += 1
                continue
            if receipt is not None:
                cancellation = await active_runner.cancel(execution_id)
                if isinstance(cancellation, RunnerReceipt) and (
                    cancellation.status in TERMINAL_RUNNER_STATUSES
                ):
                    if await repository.complete_receipt(execution_id, cancellation):
                        recovered += 1
                    continue
                decision = await _prepare_recovery(execution_id, now=now)
                if decision.action != "skip":
                    _enqueue_sync(execution_id, decision.worker_recovery_count)
                    recovered += 1
                continue
            decision = await _prepare_recovery(execution_id, now=now)
            if decision.action == "deliver":
                _enqueue_sync(execution_id, decision.worker_recovery_count)
                recovered += 1
                continue
            if decision.action in {"cancel", "exhausted"}:
                proof = await active_runner.cancel(execution_id)
                if isinstance(proof, RunnerAbsenceProof):
                    outcome: Literal["cancelled", "infrastructure_failed"] = (
                        "cancelled" if decision.action == "cancel" else "infrastructure_failed"
                    )
                    reason = (
                        "owner cancelled before runner submission"
                        if decision.action == "cancel"
                        else "sandbox worker recovery attempts exhausted"
                    )
                    if await repository.complete_absence(
                        execution_id,
                        proof,
                        outcome=outcome,
                        reason=reason,
                    ):
                        failed += decision.action == "exhausted"
                        recovered += decision.action == "cancel"
                    continue
                if proof.status in TERMINAL_RUNNER_STATUSES:
                    if await repository.complete_receipt(execution_id, proof):
                        recovered += 1
                    continue
                _enqueue_sync(execution_id, decision.worker_recovery_count)
                recovered += 1
        except Exception:
            logger.exception(
                "Sandbox execution recovery failed",
                extra={
                    "event": "sandbox.execution.recovery_failed",
                    "sandbox_execution_id": str(execution_id),
                },
            )
    return recovered, failed
