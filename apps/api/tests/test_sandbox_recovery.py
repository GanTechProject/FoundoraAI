import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest
from test_sandbox_runtime import _absence, _request, _terminal

from foundora.sandbox.recovery import RecoveryDecision, recover_sandbox_executions
from foundora.sandbox.runner_client import RunnerAbsenceProof, RunnerReceipt


@dataclass
class RecoveryRunner:
    inspections: list[RunnerReceipt | None]
    cancellation: RunnerReceipt | RunnerAbsenceProof | None = None
    cancel_calls: int = 0

    async def inspect(self, _: uuid.UUID) -> RunnerReceipt | None:
        return self.inspections.pop(0)

    async def cancel(self, _: uuid.UUID) -> RunnerReceipt | RunnerAbsenceProof:
        self.cancel_calls += 1
        assert self.cancellation is not None
        return self.cancellation


@dataclass
class RecoveryRepository:
    completed: list[uuid.UUID] = field(default_factory=list)
    absences: list[tuple[uuid.UUID, str, str]] = field(default_factory=list)

    async def complete_receipt(self, execution_id: uuid.UUID, _: RunnerReceipt) -> bool:
        self.completed.append(execution_id)
        return True

    async def complete_absence(
        self,
        execution_id: uuid.UUID,
        _: RunnerAbsenceProof,
        *,
        outcome: str,
        reason: str,
    ) -> bool:
        self.absences.append((execution_id, outcome, reason))
        return True


@pytest.mark.asyncio
async def test_recovery_commits_existing_terminal_receipt_without_queue_delivery() -> None:
    execution_id = uuid.uuid4()
    receipt = _terminal(_request(execution_id))
    runner = RecoveryRunner([receipt])
    repository = RecoveryRepository()

    with (
        patch(
            "foundora.sandbox.recovery._candidate_ids",
            new=AsyncMock(return_value=[execution_id]),
        ),
        patch(
            "foundora.sandbox.recovery.SqlSandboxRuntimeRepository",
            return_value=repository,
        ),
        patch("foundora.sandbox.recovery._enqueue_sync") as enqueue,
    ):
        result = await recover_sandbox_executions(runner)  # type: ignore[arg-type]

    assert result == (1, 0)
    assert repository.completed == [execution_id]
    assert runner.cancel_calls == 0
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_exhausted_lost_execution_requires_absence_proof_before_failure() -> None:
    execution_id = uuid.uuid4()
    runner = RecoveryRunner([None], cancellation=_absence(execution_id))
    repository = RecoveryRepository()

    with (
        patch(
            "foundora.sandbox.recovery._candidate_ids",
            new=AsyncMock(return_value=[execution_id]),
        ),
        patch(
            "foundora.sandbox.recovery._prepare_recovery",
            new=AsyncMock(return_value=RecoveryDecision("exhausted", 3)),
        ),
        patch(
            "foundora.sandbox.recovery.SqlSandboxRuntimeRepository",
            return_value=repository,
        ),
        patch("foundora.sandbox.recovery._enqueue_sync") as enqueue,
    ):
        result = await recover_sandbox_executions(runner)  # type: ignore[arg-type]

    assert result == (0, 1)
    assert runner.cancel_calls == 1
    assert repository.absences == [
        (
            execution_id,
            "infrastructure_failed",
            "sandbox worker recovery attempts exhausted",
        )
    ]
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_missing_queued_execution_receives_one_deterministic_recovery_delivery() -> None:
    execution_id = uuid.uuid4()
    runner = RecoveryRunner([None])
    repository = RecoveryRepository()

    with (
        patch(
            "foundora.sandbox.recovery._candidate_ids",
            new=AsyncMock(return_value=[execution_id]),
        ),
        patch(
            "foundora.sandbox.recovery._prepare_recovery",
            new=AsyncMock(return_value=RecoveryDecision("deliver", 2)),
        ),
        patch(
            "foundora.sandbox.recovery.SqlSandboxRuntimeRepository",
            return_value=repository,
        ),
        patch("foundora.sandbox.recovery._enqueue_sync") as enqueue,
    ):
        result = await recover_sandbox_executions(runner)  # type: ignore[arg-type]

    assert result == (1, 0)
    enqueue.assert_called_once_with(execution_id, 2)
    assert repository.completed == []
    assert repository.absences == []
