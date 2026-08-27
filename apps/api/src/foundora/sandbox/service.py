from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from redis import Redis
from rq import Queue
from rq.job import JobStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.config import get_settings
from foundora.governance.service import GovernanceService
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    ApprovalRequest,
    GovernanceAction,
    SandboxExecution,
    WebsiteProjectVersion,
    WebsiteSpecificationVersion,
)
from foundora.models import SandboxProfile as SandboxProfileRecord
from foundora.sandbox.contracts import (
    STATIC_WEBSITE_PROFILE,
    SandboxExecutePayload,
    SandboxExecuteRequest,
    canonical_json_bytes,
)

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset(
    {
        "rejected",
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
        "resource_exhausted",
        "infrastructure_failed",
        "cleanup_failed",
    }
)
ExecutionStatus = Literal[
    "requested",
    "waiting_approval",
    "queued",
    "authorizing",
    "running",
    "cleaning",
    "rejected",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "resource_exhausted",
    "infrastructure_failed",
    "cleanup_failed",
]
LEGAL_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "requested": frozenset({"waiting_approval", "rejected"}),
    "waiting_approval": frozenset({"queued", "rejected", "cancelled"}),
    "queued": frozenset({"authorizing", "cancelled", "infrastructure_failed"}),
    "authorizing": frozenset({"running", "cleaning", "cancelled", "infrastructure_failed"}),
    "running": frozenset({"cleaning"}),
    "cleaning": frozenset(TERMINAL_STATUSES - {"rejected"}),
}
_PROFILE_FIELDS = tuple(type(STATIC_WEBSITE_PROFILE).model_fields)


class SandboxConflict(Exception):
    pass


class SandboxNotReady(Exception):
    pass


class SandboxProfileMismatch(Exception):
    pass


class SandboxIllegalTransition(Exception):
    pass


class SandboxExecutionNotFound(Exception):
    pass


class SandboxNotCancellable(Exception):
    pass


class SandboxQueueUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SandboxExecutionRecord:
    execution: SandboxExecution
    action: GovernanceAction
    approval: ApprovalRequest | None


@dataclass(frozen=True)
class SandboxExecutionPage:
    business_id: uuid.UUID
    executions: list[SandboxExecutionRecord]
    total_executions: int
    limit: int
    offset: int


def _now() -> datetime:
    return datetime.now(UTC)


def _tree_digest(files: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    try:
        ordered = sorted(files, key=lambda value: cast(str, value["path"]))
        for item in ordered:
            digest.update(cast(str, item["path"]).encode("utf-8"))
            digest.update(b"\0")
            digest.update(cast(str, item["sha256"]).encode("ascii"))
            digest.update(b"\0")
    except (KeyError, TypeError, UnicodeError) as error:
        raise SandboxNotReady("The stored website tree is malformed") from error
    return digest.hexdigest()


def _validated_source_archive(project: WebsiteProjectVersion) -> tuple[bytes, str]:
    paths: set[str] = set()
    normalized: list[dict[str, object]] = []
    for item in project.source_files:
        path = item.get("path")
        media_type = item.get("media_type")
        content = item.get("content")
        size_bytes = item.get("size_bytes")
        sha256 = item.get("sha256")
        if (
            not isinstance(path, str)
            or not isinstance(media_type, str)
            or not isinstance(content, str)
            or not isinstance(size_bytes, int)
            or not isinstance(sha256, str)
            or path in paths
        ):
            raise SandboxNotReady("The stored website source is malformed")
        encoded = content.encode("utf-8")
        actual_hash = hashlib.sha256(encoded).hexdigest()
        if size_bytes != len(encoded) or sha256 != actual_hash:
            raise SandboxNotReady("The stored website source no longer matches its evidence")
        paths.add(path)
        normalized.append(
            {
                "content": content,
                "media_type": media_type,
                "path": path,
                "sha256": sha256,
                "size_bytes": size_bytes,
            }
        )
    if not normalized or _tree_digest(normalized) != project.source_digest:
        raise SandboxNotReady("The stored website source digest is stale")
    if _tree_digest(project.build_manifest) != project.build_digest:
        raise SandboxNotReady("The stored website build digest is stale")
    if (
        project.dependency_manifest.get("manager") != "none"
        or project.dependency_manifest.get("dependencies") != []
    ):
        raise SandboxNotReady("The static sandbox does not allow package dependencies")
    archive = canonical_json_bytes(
        {
            "contract_version": 1,
            "files": sorted(normalized, key=lambda value: cast(str, value["path"])),
        }
    )
    return archive, hashlib.sha256(archive).hexdigest()


def _routes(specification: WebsiteSpecificationVersion) -> tuple[str, ...]:
    sitemap = specification.specification.get("sitemap")
    if not isinstance(sitemap, list):
        raise SandboxNotReady("The approved website sitemap is missing")
    routes: list[str] = []
    for page in sitemap:
        route = page.get("path") if isinstance(page, dict) else None
        if not isinstance(route, str):
            raise SandboxNotReady("The approved website sitemap is malformed")
        routes.append(route)
    return tuple(routes)


def assert_profile_parity(record: SandboxProfileRecord) -> None:
    actual = {field: getattr(record, field) for field in _PROFILE_FIELDS}
    if actual != STATIC_WEBSITE_PROFILE.model_dump():
        raise SandboxProfileMismatch(
            "The database sandbox profile disagrees with the reviewed code catalog"
        )


def prepare_execution_request(
    *,
    execution_id: uuid.UUID,
    business_id: uuid.UUID,
    project: WebsiteProjectVersion,
    specification: WebsiteSpecificationVersion,
) -> SandboxExecuteRequest:
    request, _ = prepare_execution_submission(
        execution_id=execution_id,
        business_id=business_id,
        project=project,
        specification=specification,
    )
    return request


def prepare_execution_submission(
    *,
    execution_id: uuid.UUID,
    business_id: uuid.UUID,
    project: WebsiteProjectVersion,
    specification: WebsiteSpecificationVersion,
) -> tuple[SandboxExecuteRequest, bytes]:
    if project.business_id != business_id or specification.business_id != business_id:
        raise SandboxNotReady("Sandbox inputs do not belong to the selected business")
    if project.status != "active" or specification.status != "active":
        raise SandboxNotReady("Sandbox inputs must be the current active versions")
    if (
        project.source_website_specification_id != specification.id
        or project.source_website_specification_version != specification.version
    ):
        raise SandboxNotReady("The active website project is stale")
    archive, archive_digest = _validated_source_archive(project)
    payload = SandboxExecutePayload(
        execution_id=execution_id,
        business_id=business_id,
        website_project_id=project.id,
        website_project_version=project.version,
        website_specification_id=specification.id,
        website_specification_version=specification.version,
        profile_id="static-website",
        profile_version=1,
        source_digest=project.source_digest,
        build_digest=project.build_digest,
        source_archive_sha256=archive_digest,
        source_archive_size_bytes=len(archive),
        routes=_routes(specification),
    )
    return SandboxExecuteRequest.create(payload), archive


def governance_target(request: SandboxExecuteRequest) -> str:
    payload = request.payload
    return (
        f"website-project:{payload.website_project_id}:v{payload.website_project_version}:"
        f"profile:{payload.profile_id}@{payload.profile_version}:request:{request.request_digest}"
    )


def assert_idempotent_request(existing: SandboxExecution, request: SandboxExecuteRequest) -> None:
    if existing.request_digest != request.request_digest:
        raise SandboxConflict("Idempotency key was already used for another sandbox request")


def assert_pinned_execution(execution: SandboxExecution, request: SandboxExecuteRequest) -> None:
    payload = request.payload
    if any(
        (
            execution.id != payload.execution_id,
            execution.business_id != payload.business_id,
            execution.website_project_id != payload.website_project_id,
            execution.website_project_version != payload.website_project_version,
            execution.website_specification_id != payload.website_specification_id,
            execution.website_specification_version != payload.website_specification_version,
            execution.profile_id != payload.profile_id,
            execution.profile_version != payload.profile_version,
            execution.source_digest != payload.source_digest,
            execution.build_digest != payload.build_digest,
            execution.source_archive_sha256 != payload.source_archive_sha256,
            execution.source_archive_size_bytes != payload.source_archive_size_bytes,
            execution.routes != list(payload.routes),
            execution.request_digest != request.request_digest,
            execution.policy_version_id is None,
        )
    ):
        raise SandboxNotReady("The pinned sandbox execution evidence is stale")


def _sandbox_job_id(execution_id: uuid.UUID, worker_recovery_count: int) -> str:
    base = f"sandbox-execution-{execution_id}"
    return base if worker_recovery_count == 0 else f"{base}-recovery-{worker_recovery_count}"


def _enqueue_sync(execution_id: uuid.UUID, worker_recovery_count: int = 0) -> None:
    settings = get_settings()
    connection = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        queue = Queue(settings.worker_queue, connection=connection)
        job_id = _sandbox_job_id(execution_id, worker_recovery_count)
        existing = queue.fetch_job(job_id)
        if existing is not None:
            if existing.get_status(refresh=True) in {
                JobStatus.QUEUED,
                JobStatus.STARTED,
                JobStatus.DEFERRED,
                JobStatus.SCHEDULED,
            }:
                return
            existing.delete(remove_from_queue=True)
        queue.enqueue(
            "foundora.sandbox.jobs.execute_sandbox",
            str(execution_id),
            job_id=job_id,
            job_timeout=120,
            result_ttl=0,
            failure_ttl=86_400,
        )
    finally:
        connection.close()


async def enqueue_sandbox_execution(execution_id: uuid.UUID) -> None:
    await asyncio.to_thread(_enqueue_sync, execution_id)


def transition_execution(
    execution: SandboxExecution,
    status: ExecutionStatus,
    *,
    now: datetime | None = None,
) -> None:
    if status not in LEGAL_TRANSITIONS.get(execution.status, frozenset()):
        raise SandboxIllegalTransition(
            f"Illegal sandbox transition: {execution.status} -> {status}"
        )
    if status == "succeeded" and not (
        execution.cleanup_status == "verified" and execution.final_labeled_resource_count == 0
    ):
        raise SandboxIllegalTransition("Success requires verified zero-resource cleanup")
    if status == "cleanup_failed" and execution.cleanup_status != "failed":
        raise SandboxIllegalTransition("cleanup_failed requires failed cleanup evidence")
    changed_at = now or _now()
    execution.status = status
    execution.updated_at = changed_at
    if status == "running" and execution.started_at is None:
        execution.started_at = changed_at
    if status in TERMINAL_STATUSES:
        execution.finished_at = changed_at


class SandboxService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        governance: GovernanceService | None = None,
        enqueue: Callable[[uuid.UUID], Awaitable[None]] = enqueue_sandbox_execution,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._governance = governance or GovernanceService(self._session_factory)
        self._enqueue = enqueue

    async def list_executions(
        self,
        context: AuthContext,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> SandboxExecutionPage:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            total = await database.scalar(
                select(func.count())
                .select_from(SandboxExecution)
                .where(SandboxExecution.business_id == business.id)
            )
            rows = (
                await database.execute(
                    select(SandboxExecution, GovernanceAction, ApprovalRequest)
                    .join(
                        GovernanceAction,
                        GovernanceAction.id == SandboxExecution.governance_action_id,
                    )
                    .outerjoin(
                        ApprovalRequest,
                        ApprovalRequest.action_id == GovernanceAction.id,
                    )
                    .where(SandboxExecution.business_id == business.id)
                    .order_by(SandboxExecution.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return SandboxExecutionPage(
                business_id=business.id,
                executions=[SandboxExecutionRecord(row[0], row[1], row[2]) for row in rows],
                total_executions=int(total or 0),
                limit=limit,
                offset=offset,
            )

    async def get_execution(
        self, context: AuthContext, execution_id: uuid.UUID
    ) -> SandboxExecutionRecord:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            row = (
                await database.execute(
                    select(SandboxExecution, GovernanceAction, ApprovalRequest)
                    .join(
                        GovernanceAction,
                        GovernanceAction.id == SandboxExecution.governance_action_id,
                    )
                    .outerjoin(
                        ApprovalRequest,
                        ApprovalRequest.action_id == GovernanceAction.id,
                    )
                    .where(
                        SandboxExecution.id == execution_id,
                        SandboxExecution.business_id == business.id,
                    )
                )
            ).one_or_none()
            if row is None:
                raise SandboxExecutionNotFound
            return SandboxExecutionRecord(row[0], row[1], row[2])

    async def request_execution(
        self, context: AuthContext, *, idempotency_key: str
    ) -> SandboxExecution:
        if not idempotency_key or len(idempotency_key) > 128:
            raise SandboxConflict("Sandbox idempotency key must contain 1 to 128 characters")
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                existing = await database.scalar(
                    select(SandboxExecution)
                    .where(
                        SandboxExecution.business_id == business.id,
                        SandboxExecution.idempotency_key == idempotency_key,
                    )
                    .with_for_update()
                )
                if existing is not None:
                    return existing
                project = await database.scalar(
                    select(WebsiteProjectVersion)
                    .where(
                        WebsiteProjectVersion.business_id == business.id,
                        WebsiteProjectVersion.status == "active",
                    )
                    .with_for_update()
                )
                specification = await database.scalar(
                    select(WebsiteSpecificationVersion)
                    .where(
                        WebsiteSpecificationVersion.business_id == business.id,
                        WebsiteSpecificationVersion.status == "active",
                    )
                    .with_for_update()
                )
                if project is None or specification is None:
                    raise SandboxNotReady(
                        "An active website project and specification are required"
                    )
                profile = await database.scalar(
                    select(SandboxProfileRecord).where(
                        SandboxProfileRecord.profile_id == STATIC_WEBSITE_PROFILE.profile_id,
                        SandboxProfileRecord.version == STATIC_WEBSITE_PROFILE.version,
                    )
                )
                if profile is None:
                    raise SandboxProfileMismatch("The reviewed sandbox profile is not seeded")
                assert_profile_parity(profile)
                execution_id = uuid.uuid4()
                request = prepare_execution_request(
                    execution_id=execution_id,
                    business_id=business.id,
                    project=project,
                    specification=specification,
                )
                governance_key = f"sandbox:{execution_id}"
                target = governance_target(request)
                authorization = await self._governance.evaluate_in_session(
                    database,
                    business_id=business.id,
                    action_type="internal.code.execute",
                    actor_type="owner",
                    actor_id=str(context.owner.id),
                    tool_id="foundora.sandbox.website",
                    execution_mode="manual",
                    data_classification="confidential",
                    requested_spend_microusd=0,
                    frequency_key="sandbox:website",
                    target=target,
                    idempotency_key=governance_key,
                    created_by_owner_id=context.owner.id,
                    minimum_risk_class="R2",
                    force_approval=True,
                    approval_prompt="Approve isolated execution of this exact website project?",
                )
                now = _now()
                status = (
                    "waiting_approval"
                    if authorization.action.status == "approval_required"
                    else "rejected"
                )
                execution = SandboxExecution(
                    id=execution_id,
                    business_id=business.id,
                    idempotency_key=idempotency_key,
                    website_project_id=project.id,
                    website_project_version=project.version,
                    website_specification_id=specification.id,
                    website_specification_version=specification.version,
                    source_digest=project.source_digest,
                    build_digest=project.build_digest,
                    source_archive_sha256=request.payload.source_archive_sha256,
                    source_archive_size_bytes=request.payload.source_archive_size_bytes,
                    routes=list(request.payload.routes),
                    profile_id=profile.profile_id,
                    profile_version=profile.version,
                    harness_contract_version=profile.harness_contract_version,
                    runtime_image_id=None,
                    request_digest=request.request_digest,
                    governance_action_id=authorization.action.id,
                    policy_version_id=authorization.action.policy_version_id,
                    status=status,
                    worker_recovery_count=0,
                    cleanup_status="pending",
                    cleanup_attempts=0,
                    created_at=now,
                    updated_at=now,
                )
                database.add(execution)
                await database.flush()
                return execution

    async def start_execution(
        self, context: AuthContext, execution_id: uuid.UUID
    ) -> SandboxExecution:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                execution = await database.scalar(
                    select(SandboxExecution)
                    .where(
                        SandboxExecution.id == execution_id,
                        SandboxExecution.business_id == business.id,
                    )
                    .with_for_update()
                )
                if execution is None:
                    raise SandboxExecutionNotFound
                if execution.status in TERMINAL_STATUSES:
                    return execution
                if execution.status == "queued":
                    recovery_count = execution.worker_recovery_count
                else:
                    if execution.status != "waiting_approval":
                        raise SandboxConflict("Sandbox execution is not ready to start")
                    action = await database.scalar(
                        select(GovernanceAction)
                        .where(
                            GovernanceAction.id == execution.governance_action_id,
                            GovernanceAction.business_id == business.id,
                        )
                        .with_for_update()
                    )
                    if action is None or action.status not in {"approved", "authorized"}:
                        raise SandboxNotReady("Sandbox execution still requires owner approval")
                    project = await database.get(
                        WebsiteProjectVersion, execution.website_project_id
                    )
                    specification = await database.get(
                        WebsiteSpecificationVersion,
                        execution.website_specification_id,
                    )
                    if project is None or specification is None:
                        raise SandboxNotReady("Pinned sandbox inputs are unavailable")
                    request, _ = prepare_execution_submission(
                        execution_id=execution.id,
                        business_id=business.id,
                        project=project,
                        specification=specification,
                    )
                    assert_pinned_execution(execution, request)
                    transition_execution(execution, "queued")
                    execution.termination_reason = None
                    recovery_count = execution.worker_recovery_count
        try:
            await self._enqueue(execution_id)
        except Exception:
            logger.exception(
                "Sandbox execution enqueue failed",
                extra={
                    "event": "sandbox.execution.enqueue_failed",
                    "sandbox_execution_id": str(execution_id),
                    "worker_recovery_count": recovery_count,
                },
            )
            await self._record_enqueue_failure(execution_id)
            raise SandboxQueueUnavailable from None
        return execution

    async def cancel_execution(
        self, context: AuthContext, execution_id: uuid.UUID
    ) -> SandboxExecution:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                execution = await database.scalar(
                    select(SandboxExecution)
                    .where(
                        SandboxExecution.id == execution_id,
                        SandboxExecution.business_id == business.id,
                    )
                    .with_for_update()
                )
                if execution is None:
                    raise SandboxExecutionNotFound
                if execution.status in TERMINAL_STATUSES:
                    raise SandboxNotCancellable
                now = _now()
                execution.cancellation_requested_at = now
                execution.updated_at = now
                if execution.status == "waiting_approval":
                    transition_execution(execution, "queued", now=now)
        try:
            await self._enqueue(execution_id)
        except Exception:
            await self._record_enqueue_failure(execution_id)
            raise SandboxQueueUnavailable from None
        return execution

    async def _record_enqueue_failure(self, execution_id: uuid.UUID) -> None:
        async with self._session_factory() as database:
            async with database.begin():
                execution = await database.scalar(
                    select(SandboxExecution)
                    .where(SandboxExecution.id == execution_id)
                    .with_for_update()
                )
                if execution is None or execution.status in TERMINAL_STATUSES:
                    return
                execution.termination_reason = "background queue delivery failed"
                execution.updated_at = _now()
