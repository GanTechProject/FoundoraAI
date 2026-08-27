from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.config import get_settings
from foundora.events.service import publish_event
from foundora.governance.service import GovernanceService
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    GovernanceAction,
    SandboxExecution,
    SandboxProfile,
    WebsiteProjectVersion,
    WebsiteSpecificationVersion,
)
from foundora.sandbox.contracts import SandboxExecuteRequest
from foundora.sandbox.runner_client import (
    TERMINAL_RUNNER_STATUSES,
    RunnerAbsenceProof,
    RunnerCancellation,
    RunnerConflict,
    RunnerProtocolError,
    RunnerReceipt,
    RunnerUnavailable,
    SandboxRunnerClient,
)
from foundora.sandbox.service import (
    TERMINAL_STATUSES,
    ExecutionStatus,
    SandboxNotReady,
    SandboxProfileMismatch,
    assert_pinned_execution,
    assert_profile_parity,
    governance_target,
    prepare_execution_submission,
    transition_execution,
)

logger = logging.getLogger(__name__)
MONITOR_INTERVAL_SECONDS = 1.0
MONITOR_TIMEOUT_SECONDS = 80.0
type AbsenceOutcome = Literal["cancelled", "infrastructure_failed"]
FINISHED_EVENT_STATUSES = TERMINAL_STATUSES - {"rejected"}


def _now() -> datetime:
    return datetime.now(UTC)


def sandbox_finished_event_payload(execution: SandboxExecution) -> dict[str, object]:
    if execution.status not in FINISHED_EVENT_STATUSES or execution.finished_at is None:
        raise RunnerProtocolError("Sandbox execution is not ready for its terminal event")
    if (
        execution.cleanup_status not in {"verified", "failed"}
        or execution.cleanup_attempts < 1
        or execution.final_labeled_resource_count is None
        or execution.cleanup_receipt_digest is None
    ):
        raise RunnerProtocolError("Sandbox terminal cleanup evidence is incomplete")
    duration_ms = (
        min(
            max(
                int((execution.finished_at - execution.started_at).total_seconds() * 1000),
                0,
            ),
            120_000,
        )
        if execution.started_at is not None
        else None
    )
    return {
        "business_id": str(execution.business_id),
        "sandbox_execution_id": str(execution.id),
        "website_project_id": str(execution.website_project_id),
        "website_project_version": execution.website_project_version,
        "profile_id": execution.profile_id,
        "profile_version": execution.profile_version,
        "outcome": execution.status,
        "termination_reason": execution.termination_reason,
        "duration_ms": duration_ms,
        "runtime_image_id": execution.runtime_image_id,
        "effective_limits_digest": execution.effective_limits_digest,
        "cleanup_status": execution.cleanup_status,
        "cleanup_attempts": execution.cleanup_attempts,
        "final_labeled_resource_count": execution.final_labeled_resource_count,
        "cleanup_receipt_digest": execution.cleanup_receipt_digest,
        "governance_action_id": str(execution.governance_action_id),
        "policy_version_id": str(execution.policy_version_id),
        "request_digest": execution.request_digest,
        "worker_recovery_count": execution.worker_recovery_count,
    }


async def publish_sandbox_finished_event(
    database: AsyncSession, execution: SandboxExecution
) -> None:
    await publish_event(
        database,
        business_id=execution.business_id,
        event_type="sandbox.execution.finished",
        aggregate_type="sandbox_execution",
        aggregate_id=str(execution.id),
        idempotency_key=f"sandbox:{execution.id}:finished:v1",
        payload=sandbox_finished_event_payload(execution),
        occurred_at=execution.finished_at,
    )


def create_runner_client() -> SandboxRunnerClient:
    settings = get_settings()
    if settings.sandbox_runner_token is None:
        raise RunnerUnavailable("Sandbox runner token is not configured")
    return SandboxRunnerClient(
        base_url=settings.sandbox_runner_url,
        token=settings.sandbox_runner_token.get_secret_value(),
    )


@dataclass(frozen=True)
class SandboxClaim:
    execution_id: uuid.UUID
    request: SandboxExecuteRequest | None
    source_archive: bytes | None
    cancellation_requested: bool
    failure_reason: str | None


class SandboxRuntimeRepository(Protocol):
    async def claim(self, execution_id: uuid.UUID) -> SandboxClaim | None: ...

    async def record_progress(
        self, execution_id: uuid.UUID, receipt: RunnerReceipt | None
    ) -> bool: ...

    async def complete_receipt(self, execution_id: uuid.UUID, receipt: RunnerReceipt) -> bool: ...

    async def complete_absence(
        self,
        execution_id: uuid.UUID,
        proof: RunnerAbsenceProof,
        *,
        outcome: AbsenceOutcome,
        reason: str,
    ) -> bool: ...


class SandboxRuntimeClient(Protocol):
    async def execute(
        self, request: SandboxExecuteRequest, source_archive: bytes
    ) -> RunnerReceipt: ...

    async def inspect(self, execution_id: uuid.UUID) -> RunnerReceipt | None: ...

    async def cancel(self, execution_id: uuid.UUID) -> RunnerCancellation: ...

    async def acknowledge(self, execution_id: uuid.UUID) -> RunnerReceipt: ...


class SqlSandboxRuntimeRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        governance: GovernanceService | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._governance = governance or GovernanceService(self._session_factory)

    async def claim(self, execution_id: uuid.UUID) -> SandboxClaim | None:
        async with self._session_factory() as database:
            async with database.begin():
                execution = await database.scalar(
                    select(SandboxExecution)
                    .where(SandboxExecution.id == execution_id)
                    .with_for_update()
                )
                if execution is None or execution.status in TERMINAL_STATUSES:
                    return None
                now = _now()
                execution.attempt_started_at = now
                execution.heartbeat_at = now
                execution.updated_at = now
                if execution.status == "queued":
                    transition_execution(execution, "authorizing", now=now)
                elif execution.status not in {"authorizing", "running", "cleaning"}:
                    return SandboxClaim(
                        execution.id,
                        None,
                        None,
                        execution.cancellation_requested_at is not None,
                        "sandbox execution is not queued",
                    )
                if execution.cancellation_requested_at is not None:
                    return SandboxClaim(execution.id, None, None, True, None)
                if execution.status in {"running", "cleaning"}:
                    return SandboxClaim(
                        execution.id,
                        None,
                        None,
                        False,
                        "runner receipt disappeared after execution started",
                    )
                project = await database.get(WebsiteProjectVersion, execution.website_project_id)
                specification = await database.get(
                    WebsiteSpecificationVersion,
                    execution.website_specification_id,
                )
                profile = await database.get(
                    SandboxProfile,
                    {
                        "profile_id": execution.profile_id,
                        "version": execution.profile_version,
                    },
                )
                action = await database.scalar(
                    select(GovernanceAction)
                    .where(
                        GovernanceAction.id == execution.governance_action_id,
                        GovernanceAction.business_id == execution.business_id,
                    )
                    .with_for_update()
                )
                if project is None or specification is None or profile is None or action is None:
                    return SandboxClaim(
                        execution.id, None, None, False, "pinned sandbox evidence is unavailable"
                    )
                try:
                    assert_profile_parity(profile)
                    request, source_archive = prepare_execution_submission(
                        execution_id=execution.id,
                        business_id=execution.business_id,
                        project=project,
                        specification=specification,
                    )
                    assert_pinned_execution(execution, request)
                except (SandboxNotReady, SandboxProfileMismatch) as error:
                    return SandboxClaim(execution.id, None, None, False, str(error))
                expected_target = governance_target(request)
                if any(
                    (
                        action.policy_version_id != execution.policy_version_id,
                        action.action_type != "internal.code.execute",
                        action.tool_id != "foundora.sandbox.website",
                        action.execution_mode != "manual",
                        action.data_classification != "confidential",
                        action.target != expected_target,
                        action.requested_spend_microusd != 0,
                    )
                ):
                    return SandboxClaim(
                        execution.id,
                        None,
                        None,
                        False,
                        "sandbox governance evidence is stale",
                    )
                authorization = await self._governance.authorize_in_session(
                    database,
                    business_id=execution.business_id,
                    action_id=execution.governance_action_id,
                    idempotency_key=(
                        f"sandbox:{execution.id}:authorize:{execution.worker_recovery_count}"
                    ),
                    owner_id=None,
                    force_recheck=True,
                )
                if authorization.action.status != "authorized":
                    return SandboxClaim(
                        execution.id,
                        None,
                        None,
                        False,
                        f"governance denied execution: {authorization.action.rationale}"[:120],
                    )
                return SandboxClaim(execution.id, request, source_archive, False, None)

    @staticmethod
    def _validate_receipt_identity(execution: SandboxExecution, receipt: RunnerReceipt) -> None:
        if any(
            (
                receipt.execution_id != execution.id,
                receipt.request_digest != execution.request_digest,
                receipt.source_archive_sha256 != execution.source_archive_sha256,
                receipt.profile_id != execution.profile_id,
                receipt.profile_version != execution.profile_version,
                execution.runtime_image_id is not None
                and execution.runtime_image_id != receipt.runtime_image_id,
            )
        ):
            raise RunnerProtocolError("Runner receipt does not match the durable execution")

    @staticmethod
    def _persist_receipt(execution: SandboxExecution, receipt: RunnerReceipt) -> None:
        SqlSandboxRuntimeRepository._validate_receipt_identity(execution, receipt)
        execution.runtime_image_id = receipt.runtime_image_id
        execution.effective_limits = (
            receipt.effective_limits.model_dump(mode="json")
            if receipt.effective_limits is not None
            else None
        )
        execution.effective_limits_digest = receipt.effective_limits_digest
        execution.termination_reason = receipt.termination_reason
        execution.exit_code = receipt.exit_code
        execution.route_results = [item.model_dump(mode="json") for item in receipt.route_results]
        execution.process_results = cast(dict[str, object] | None, receipt.process_results)
        execution.stdout_excerpt = receipt.stdout_excerpt
        execution.stderr_excerpt = receipt.stderr_excerpt
        execution.stdout_sha256 = receipt.stdout_sha256
        execution.stderr_sha256 = receipt.stderr_sha256
        execution.cleanup_status = receipt.cleanup.status
        execution.cleanup_attempts = receipt.cleanup.cleanup_attempts
        execution.cleanup_started_at = receipt.cleanup.started_at
        execution.cleanup_finished_at = receipt.cleanup.finished_at
        execution.final_labeled_resource_count = receipt.cleanup.final_labeled_resource_count
        execution.cleanup_receipt_digest = receipt.cleanup.receipt_digest
        execution.started_at = receipt.started_at or execution.started_at
        execution.finished_at = receipt.finished_at or execution.finished_at

    async def record_progress(self, execution_id: uuid.UUID, receipt: RunnerReceipt | None) -> bool:
        async with self._session_factory() as database:
            async with database.begin():
                execution = await database.scalar(
                    select(SandboxExecution)
                    .where(SandboxExecution.id == execution_id)
                    .with_for_update()
                )
                if execution is None or execution.status in TERMINAL_STATUSES:
                    return False
                now = _now()
                execution.heartbeat_at = now
                execution.updated_at = now
                if receipt is not None:
                    self._validate_receipt_identity(execution, receipt)
                    execution.runtime_image_id = receipt.runtime_image_id
                    execution.effective_limits = (
                        receipt.effective_limits.model_dump(mode="json")
                        if receipt.effective_limits is not None
                        else execution.effective_limits
                    )
                    execution.effective_limits_digest = (
                        receipt.effective_limits_digest or execution.effective_limits_digest
                    )
                    if receipt.state == "running" and execution.status == "authorizing":
                        transition_execution(execution, "running", now=receipt.started_at or now)
                    if receipt.state == "cleaning" and execution.status in {
                        "authorizing",
                        "running",
                    }:
                        transition_execution(execution, "cleaning", now=now)
                return execution.cancellation_requested_at is not None

    async def complete_receipt(self, execution_id: uuid.UUID, receipt: RunnerReceipt) -> bool:
        if receipt.status not in TERMINAL_RUNNER_STATUSES:
            raise RunnerProtocolError("Cannot persist a nonterminal runner receipt")
        log_fields: dict[str, object] | None = None
        async with self._session_factory() as database:
            async with database.begin():
                execution = await database.scalar(
                    select(SandboxExecution)
                    .where(SandboxExecution.id == execution_id)
                    .with_for_update()
                )
                if execution is None:
                    return False
                if execution.status in TERMINAL_STATUSES:
                    return execution.status == receipt.status
                self._persist_receipt(execution, receipt)
                now = receipt.finished_at or _now()
                if execution.status == "queued":
                    transition_execution(execution, "authorizing", now=now)
                if execution.status in {"authorizing", "running"}:
                    transition_execution(execution, "cleaning", now=now)
                if execution.status != "cleaning":
                    raise RunnerProtocolError("Durable execution cannot accept terminal receipt")
                transition_execution(execution, cast(ExecutionStatus, receipt.status), now=now)
                execution.heartbeat_at = now
                execution.updated_at = now
                await publish_sandbox_finished_event(database, execution)
                log_fields = {
                    "event": "sandbox.execution.finished",
                    "sandbox_execution_id": str(execution.id),
                    "sandbox_outcome": execution.status,
                    "sandbox_duration_ms": receipt.duration_ms,
                    "sandbox_cleanup_status": execution.cleanup_status,
                    "sandbox_cleanup_attempts": execution.cleanup_attempts,
                    "sandbox_remaining_resources": execution.final_labeled_resource_count,
                    "sandbox_worker_recoveries": execution.worker_recovery_count,
                }
        logger.info("Sandbox execution reached a terminal outcome", extra=log_fields)
        return True

    async def complete_absence(
        self,
        execution_id: uuid.UUID,
        proof: RunnerAbsenceProof,
        *,
        outcome: AbsenceOutcome,
        reason: str,
    ) -> bool:
        if outcome not in {"cancelled", "infrastructure_failed"}:
            raise ValueError("absence can only resolve cancellation or infrastructure failure")
        log_fields: dict[str, object] | None = None
        async with self._session_factory() as database:
            async with database.begin():
                execution = await database.scalar(
                    select(SandboxExecution)
                    .where(SandboxExecution.id == execution_id)
                    .with_for_update()
                )
                if execution is None or execution.status in TERMINAL_STATUSES:
                    return False
                if proof.execution_id != execution.id:
                    raise RunnerProtocolError("Runner absence proof identity mismatched")
                cleanup = proof.cleanup
                execution.cleanup_status = cleanup.status
                execution.cleanup_attempts = cleanup.cleanup_attempts
                execution.cleanup_started_at = cleanup.started_at
                execution.cleanup_finished_at = cleanup.finished_at
                execution.final_labeled_resource_count = cleanup.final_labeled_resource_count
                execution.cleanup_receipt_digest = cleanup.receipt_digest
                execution.termination_reason = reason[:120]
                now = cleanup.finished_at or _now()
                if execution.status in {"running", "cleaning"}:
                    if execution.status == "running":
                        transition_execution(execution, "cleaning", now=now)
                    transition_execution(execution, outcome, now=now)
                else:
                    transition_execution(execution, outcome, now=now)
                execution.heartbeat_at = now
                execution.updated_at = now
                await publish_sandbox_finished_event(database, execution)
                log_fields = {
                    "event": "sandbox.execution.finished",
                    "sandbox_execution_id": str(execution.id),
                    "sandbox_outcome": execution.status,
                    "sandbox_duration_ms": None,
                    "sandbox_cleanup_status": execution.cleanup_status,
                    "sandbox_cleanup_attempts": execution.cleanup_attempts,
                    "sandbox_remaining_resources": execution.final_labeled_resource_count,
                    "sandbox_worker_recoveries": execution.worker_recovery_count,
                }
        logger.info("Sandbox execution absence reached a terminal outcome", extra=log_fields)
        return True


class SandboxRuntime:
    def __init__(
        self,
        repository: SandboxRuntimeRepository | None = None,
        runner: SandboxRuntimeClient | None = None,
    ) -> None:
        self._repository = repository or SqlSandboxRuntimeRepository()
        self._runner = runner or create_runner_client()

    async def _finish_receipt(self, receipt: RunnerReceipt) -> None:
        await self._repository.complete_receipt(receipt.execution_id, receipt)
        try:
            await self._runner.acknowledge(receipt.execution_id)
        except (RunnerUnavailable, RunnerProtocolError):
            logger.warning(
                "Sandbox receipt acknowledgement failed",
                extra={
                    "event": "sandbox.execution.acknowledge_failed",
                    "sandbox_execution_id": str(receipt.execution_id),
                },
            )

    async def _resolve_cancellation(self, execution_id: uuid.UUID, *, reason: str) -> bool:
        cancellation = await self._runner.cancel(execution_id)
        if isinstance(cancellation, RunnerAbsenceProof):
            await self._repository.complete_absence(
                execution_id,
                cancellation,
                outcome="cancelled",
                reason=reason,
            )
            return True
        if cancellation.status in TERMINAL_RUNNER_STATUSES:
            await self._finish_receipt(cancellation)
            return True
        return False

    async def _monitor(
        self,
        execution_id: uuid.UUID,
        *,
        initial: RunnerReceipt | None = None,
        submission: asyncio.Task[RunnerReceipt] | None = None,
    ) -> None:
        receipt = initial
        cancellation_sent = False
        deadline = asyncio.get_running_loop().time() + MONITOR_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            if submission is not None and submission.done():
                receipt = await submission
                submission = None
            if receipt is not None and receipt.status in TERMINAL_RUNNER_STATUSES:
                await self._finish_receipt(receipt)
                return
            cancellation_requested = await self._repository.record_progress(execution_id, receipt)
            if cancellation_requested and not cancellation_sent:
                cancellation_sent = True
                if await self._resolve_cancellation(
                    execution_id, reason="owner cancellation requested"
                ):
                    if submission is not None:
                        try:
                            await submission
                        except (RunnerUnavailable, RunnerProtocolError):
                            logger.warning(
                                "Sandbox submission response failed after cancellation completed",
                                extra={
                                    "event": "sandbox.execution.cancel_submission_failed",
                                    "sandbox_execution_id": str(execution_id),
                                },
                            )
                    return
            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
            inspected = await self._runner.inspect(execution_id)
            if inspected is not None:
                receipt = inspected
        raise RunnerUnavailable("Sandbox runner did not reach a terminal receipt")

    async def execute(self, execution_id: uuid.UUID) -> None:
        try:
            existing = await self._runner.inspect(execution_id)
            if existing is not None:
                if existing.status in TERMINAL_RUNNER_STATUSES:
                    await self._finish_receipt(existing)
                else:
                    await self._monitor(execution_id, initial=existing)
                return
            claim = await self._repository.claim(execution_id)
            if claim is None:
                return
            if claim.cancellation_requested:
                await self._resolve_cancellation(
                    execution_id, reason="owner cancelled before runner submission"
                )
                return
            if claim.failure_reason is not None:
                proof = await self._runner.cancel(execution_id)
                if isinstance(proof, RunnerReceipt):
                    if proof.status in TERMINAL_RUNNER_STATUSES:
                        await self._finish_receipt(proof)
                    else:
                        await self._monitor(execution_id, initial=proof)
                else:
                    await self._repository.complete_absence(
                        execution_id,
                        proof,
                        outcome="infrastructure_failed",
                        reason=claim.failure_reason,
                    )
                return
            if claim.request is None or claim.source_archive is None:
                raise RunnerProtocolError("Sandbox claim omitted its pinned submission")
            submission = asyncio.create_task(
                self._runner.execute(claim.request, claim.source_archive)
            )
            await self._monitor(execution_id, submission=submission)
        except RunnerConflict:
            proof = await self._runner.cancel(execution_id)
            if isinstance(proof, RunnerAbsenceProof):
                await self._repository.complete_absence(
                    execution_id,
                    proof,
                    outcome="infrastructure_failed",
                    reason="runner execution identity conflicted",
                )
                return
            if proof.status in TERMINAL_RUNNER_STATUSES:
                await self._finish_receipt(proof)
                return
            raise
