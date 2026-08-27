import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from test_sandbox_runner_client import _receipt

import foundora.sandbox.runtime as sandbox_runtime_module
from foundora.events.contracts import AUDIT_CONSUMER, consumers_for, validate_event
from foundora.logging import JsonFormatter
from foundora.models import SandboxExecution
from foundora.sandbox.contracts import SandboxExecutePayload, SandboxExecuteRequest
from foundora.sandbox.runner_client import RunnerAbsenceProof, RunnerProtocolError, RunnerReceipt
from foundora.sandbox.runtime import (
    SandboxClaim,
    SandboxRuntime,
    SqlSandboxRuntimeRepository,
    sandbox_finished_event_payload,
)


class _AsyncContext:
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *_: object) -> None:
        return None


def _request(execution_id: uuid.UUID) -> SandboxExecuteRequest:
    return SandboxExecuteRequest.create(
        SandboxExecutePayload(
            execution_id=execution_id,
            business_id=uuid.uuid4(),
            website_project_id=uuid.uuid4(),
            website_project_version=1,
            website_specification_id=uuid.uuid4(),
            website_specification_version=1,
            profile_id="static-website",
            profile_version=1,
            source_digest="1" * 64,
            build_digest="1" * 64,
            source_archive_sha256=hashlib.sha256(b"{}").hexdigest(),
            source_archive_size_bytes=2,
            routes=("/",),
        )
    )


def _terminal(request: SandboxExecuteRequest) -> RunnerReceipt:
    return RunnerReceipt.model_validate(_receipt(request), strict=False)


def _absence(execution_id: uuid.UUID) -> RunnerAbsenceProof:
    receipt = _receipt(_request(execution_id))
    return RunnerAbsenceProof.model_validate(
        {
            "contract_version": 1,
            "execution_id": str(execution_id),
            "status": "absent",
            "cleanup": receipt["cleanup"],
        },
        strict=False,
    )


def _durable_execution(request: SandboxExecuteRequest) -> SandboxExecution:
    now = datetime.now(UTC)
    payload = request.payload
    return SandboxExecution(
        id=payload.execution_id,
        business_id=payload.business_id,
        idempotency_key="sandbox-runtime-event",
        website_project_id=payload.website_project_id,
        website_project_version=payload.website_project_version,
        website_specification_id=payload.website_specification_id,
        website_specification_version=payload.website_specification_version,
        source_digest=payload.source_digest,
        build_digest=payload.build_digest,
        source_archive_sha256=payload.source_archive_sha256,
        source_archive_size_bytes=payload.source_archive_size_bytes,
        routes=list(payload.routes),
        profile_id=payload.profile_id,
        profile_version=payload.profile_version,
        harness_contract_version=1,
        request_digest=request.request_digest,
        governance_action_id=uuid.uuid4(),
        policy_version_id=uuid.uuid4(),
        status="cleaning",
        worker_recovery_count=1,
        cleanup_status="pending",
        cleanup_attempts=0,
        created_at=now,
        started_at=now,
        updated_at=now,
    )


@dataclass
class FakeRepository:
    claim_value: SandboxClaim | None
    cancellation_requested: bool = False
    completed: list[RunnerReceipt] = field(default_factory=list)
    absences: list[tuple[str, str]] = field(default_factory=list)
    claims: int = 0
    progress: int = 0

    async def claim(self, _: uuid.UUID) -> SandboxClaim | None:
        self.claims += 1
        return self.claim_value

    async def record_progress(self, _: uuid.UUID, __: RunnerReceipt | None) -> bool:
        self.progress += 1
        return self.cancellation_requested

    async def complete_receipt(self, _: uuid.UUID, receipt: RunnerReceipt) -> bool:
        self.completed.append(receipt)
        return True

    async def complete_absence(
        self,
        _: uuid.UUID,
        __: RunnerAbsenceProof,
        *,
        outcome: str,
        reason: str,
    ) -> bool:
        self.absences.append((outcome, reason))
        return True


@dataclass
class FakeRunner:
    inspections: list[RunnerReceipt | None]
    execute_result: RunnerReceipt | None = None
    cancel_result: RunnerReceipt | RunnerAbsenceProof | None = None
    execute_calls: int = 0
    cancel_calls: int = 0
    acknowledge_calls: int = 0

    async def inspect(self, _: uuid.UUID) -> RunnerReceipt | None:
        if len(self.inspections) > 1:
            return self.inspections.pop(0)
        return self.inspections[0]

    async def execute(self, _: SandboxExecuteRequest, __: bytes) -> RunnerReceipt:
        self.execute_calls += 1
        assert self.execute_result is not None
        return self.execute_result

    async def cancel(self, _: uuid.UUID) -> RunnerReceipt | RunnerAbsenceProof:
        self.cancel_calls += 1
        assert self.cancel_result is not None
        return self.cancel_result

    async def acknowledge(self, _: uuid.UUID) -> RunnerReceipt:
        self.acknowledge_calls += 1
        assert self.execute_result is not None
        return self.execute_result


@pytest.mark.asyncio
async def test_worker_submits_once_and_persists_terminal_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox_runtime_module, "MONITOR_INTERVAL_SECONDS", 0)
    request = _request(uuid.uuid4())
    terminal = _terminal(request)
    repository = FakeRepository(
        SandboxClaim(request.payload.execution_id, request, b"{}", False, None)
    )
    runner = FakeRunner([None, terminal], execute_result=terminal)

    await SandboxRuntime(repository, runner).execute(request.payload.execution_id)

    assert runner.execute_calls == 1
    assert runner.acknowledge_calls == 1
    assert repository.completed == [terminal]


@pytest.mark.asyncio
async def test_prelaunch_cancellation_proves_absence_without_submission() -> None:
    execution_id = uuid.uuid4()
    proof = _absence(execution_id)
    repository = FakeRepository(SandboxClaim(execution_id, None, None, True, None))
    runner = FakeRunner([None], cancel_result=proof)

    await SandboxRuntime(repository, runner).execute(execution_id)

    assert runner.execute_calls == 0
    assert runner.cancel_calls == 1
    assert repository.absences == [("cancelled", "owner cancelled before runner submission")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "governance approval is missing or rejected",
        "The global kill switch is engaged",
        "Tool foundora.sandbox.website is disabled",
        "sandbox governance evidence is stale",
        "sandbox governance target is stale",
        "pinned sandbox evidence belongs to another business",
    ],
)
async def test_prelaunch_authorization_failures_prove_absence_without_submission(
    reason: str,
) -> None:
    execution_id = uuid.uuid4()
    proof = _absence(execution_id)
    repository = FakeRepository(SandboxClaim(execution_id, None, None, False, reason))
    runner = FakeRunner([None], cancel_result=proof)

    await SandboxRuntime(repository, runner).execute(execution_id)

    assert runner.execute_calls == 0
    assert runner.cancel_calls == 1
    assert repository.absences == [("infrastructure_failed", reason)]


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint", ["running", "cleaning"])
async def test_worker_restart_reattaches_to_existing_receipt_without_resubmission(
    checkpoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox_runtime_module, "MONITOR_INTERVAL_SECONDS", 0)
    request = _request(uuid.uuid4())
    terminal = _terminal(request)
    pending_values = _receipt(request)
    pending_values.update(
        {
            "state": checkpoint,
            "status": "pending",
            "finished_at": None,
            "cleanup": {
                "status": "pending",
                "cleanup_attempts": 0,
                "final_labeled_resource_count": None,
                "receipt_digest": None,
                "started_at": None,
                "finished_at": None,
            },
        }
    )
    pending = RunnerReceipt.model_validate(pending_values, strict=False)
    repository = FakeRepository(None)
    runner = FakeRunner([pending, terminal], execute_result=terminal)

    await SandboxRuntime(repository, runner).execute(request.payload.execution_id)

    assert repository.claims == 0
    assert runner.execute_calls == 0
    assert repository.completed == [terminal]


@pytest.mark.asyncio
async def test_result_return_checkpoint_commits_without_resubmission() -> None:
    request = _request(uuid.uuid4())
    terminal = _terminal(request)
    repository = FakeRepository(None)
    runner = FakeRunner([terminal], execute_result=terminal)

    await SandboxRuntime(repository, runner).execute(request.payload.execution_id)

    assert repository.claims == 0
    assert runner.execute_calls == 0
    assert repository.completed == [terminal]


@pytest.mark.asyncio
async def test_terminal_receipt_publishes_one_bounded_transactional_event() -> None:
    request = _request(uuid.uuid4())
    terminal = _terminal(request)
    execution = _durable_execution(request)
    database = MagicMock()
    database.begin.return_value = _AsyncContext(None)
    database.scalar = AsyncMock(return_value=execution)
    session_factory = MagicMock(return_value=_AsyncContext(database))

    with patch("foundora.sandbox.runtime.publish_event", new=AsyncMock()) as publish:
        completed = await SqlSandboxRuntimeRepository(  # type: ignore[arg-type]
            session_factory=session_factory
        ).complete_receipt(execution.id, terminal)

    assert completed is True
    event = publish.await_args.kwargs
    assert event["event_type"] == "sandbox.execution.finished"
    assert event["idempotency_key"] == f"sandbox:{execution.id}:finished:v1"
    assert "stdout_excerpt" not in event["payload"]
    assert "stderr_excerpt" not in event["payload"]
    contract = validate_event(
        event["event_type"],
        1,
        event["aggregate_type"],
        event["payload"],
    )
    assert [consumer.name for consumer in consumers_for(contract.event_type)] == [
        AUDIT_CONSUMER.name
    ]


def test_terminal_event_requires_complete_cleanup_evidence() -> None:
    execution = _durable_execution(_request(uuid.uuid4()))
    execution.status = "infrastructure_failed"
    execution.finished_at = datetime.now(UTC)

    with pytest.raises(RunnerProtocolError, match="cleanup evidence"):
        sandbox_finished_event_payload(execution)


def test_structured_sandbox_logging_exposes_metrics_without_untrusted_output() -> None:
    record = logging.LogRecord("sandbox", logging.INFO, __file__, 1, "finished", (), None)
    record.event = "sandbox.execution.finished"
    record.sandbox_execution_id = str(uuid.uuid4())
    record.sandbox_outcome = "succeeded"
    record.sandbox_duration_ms = 125
    record.sandbox_cleanup_status = "verified"
    record.sandbox_cleanup_attempts = 1
    record.sandbox_remaining_resources = 0
    record.stdout_excerpt = "credential-like untrusted output"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["sandbox_outcome"] == "succeeded"
    assert payload["sandbox_remaining_resources"] == 0
    assert "stdout_excerpt" not in payload
    assert "credential-like" not in json.dumps(payload)
