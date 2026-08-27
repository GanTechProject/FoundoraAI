from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.sandbox.service import (
    SandboxConflict,
    SandboxExecutionNotFound,
    SandboxExecutionPage,
    SandboxExecutionRecord,
    SandboxNotCancellable,
    SandboxNotReady,
    SandboxProfileMismatch,
    SandboxQueueUnavailable,
    SandboxService,
)

router = APIRouter(prefix="/sandbox", tags=["generated-code sandbox"])
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
GovernanceStatus = Literal[
    "approval_required", "approved", "rejected", "authorized", "denied", "blocked"
]


class RequestSandboxExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )


class SandboxApprovalView(BaseModel):
    id: UUID
    status: Literal["pending", "approved", "rejected", "cancelled"]
    prompt: str
    decision_reason: str | None
    requested_at: datetime
    decided_at: datetime | None


class SandboxExecutionSummaryView(BaseModel):
    id: UUID
    business_id: UUID
    website_project_id: UUID
    website_project_version: int
    website_specification_id: UUID
    website_specification_version: int
    profile_id: str
    profile_version: int
    governance_action_id: UUID
    governance_status: GovernanceStatus
    status: ExecutionStatus
    cleanup_status: Literal["pending", "verified", "failed"]
    final_labeled_resource_count: int | None
    cancellation_requested_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class SandboxExecutionDetailView(SandboxExecutionSummaryView):
    harness_contract_version: int
    source_digest: str
    build_digest: str
    source_archive_sha256: str
    source_archive_size_bytes: int
    routes: list[str]
    request_digest: str
    policy_version_id: UUID
    governance_risk_class: Literal["R0", "R1", "R2", "R3", "R4", "R5"]
    governance_rationale: str
    governance_authorized_at: datetime | None
    approval: SandboxApprovalView | None
    worker_recovery_count: int
    attempt_started_at: datetime | None
    heartbeat_at: datetime | None
    runtime_image_id: str | None
    effective_limits: dict[str, object] | None
    effective_limits_digest: str | None
    termination_reason: str | None
    exit_code: int | None
    route_results: list[dict[str, object]] | None
    process_results: dict[str, object] | None
    stdout_excerpt: str | None
    stderr_excerpt: str | None
    stdout_sha256: str | None
    stderr_sha256: str | None
    cleanup_attempts: int
    cleanup_started_at: datetime | None
    cleanup_finished_at: datetime | None
    cleanup_receipt_digest: str | None


class SandboxExecutionPageView(BaseModel):
    business_id: UUID
    executions: list[SandboxExecutionSummaryView]
    total_executions: int
    limit: int
    offset: int


def _summary_view(record: SandboxExecutionRecord) -> SandboxExecutionSummaryView:
    execution = record.execution
    return SandboxExecutionSummaryView(
        id=execution.id,
        business_id=execution.business_id,
        website_project_id=execution.website_project_id,
        website_project_version=execution.website_project_version,
        website_specification_id=execution.website_specification_id,
        website_specification_version=execution.website_specification_version,
        profile_id=execution.profile_id,
        profile_version=execution.profile_version,
        governance_action_id=execution.governance_action_id,
        governance_status=record.action.status,  # type: ignore[arg-type]
        status=execution.status,  # type: ignore[arg-type]
        cleanup_status=execution.cleanup_status,  # type: ignore[arg-type]
        final_labeled_resource_count=execution.final_labeled_resource_count,
        cancellation_requested_at=execution.cancellation_requested_at,
        created_at=execution.created_at,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        updated_at=execution.updated_at,
    )


def _detail_view(record: SandboxExecutionRecord) -> SandboxExecutionDetailView:
    execution = record.execution
    action = record.action
    approval = record.approval
    summary = _summary_view(record).model_dump()
    return SandboxExecutionDetailView(
        **summary,
        harness_contract_version=execution.harness_contract_version,
        source_digest=execution.source_digest,
        build_digest=execution.build_digest,
        source_archive_sha256=execution.source_archive_sha256,
        source_archive_size_bytes=execution.source_archive_size_bytes,
        routes=execution.routes,
        request_digest=execution.request_digest,
        policy_version_id=execution.policy_version_id,
        governance_risk_class=action.risk_class,  # type: ignore[arg-type]
        governance_rationale=action.rationale,
        governance_authorized_at=action.authorized_at,
        approval=(
            SandboxApprovalView(
                id=approval.id,
                status=approval.status,  # type: ignore[arg-type]
                prompt=approval.prompt,
                decision_reason=approval.decision_reason,
                requested_at=approval.requested_at,
                decided_at=approval.decided_at,
            )
            if approval is not None
            else None
        ),
        worker_recovery_count=execution.worker_recovery_count,
        attempt_started_at=execution.attempt_started_at,
        heartbeat_at=execution.heartbeat_at,
        runtime_image_id=execution.runtime_image_id,
        effective_limits=execution.effective_limits,
        effective_limits_digest=execution.effective_limits_digest,
        termination_reason=execution.termination_reason,
        exit_code=execution.exit_code,
        route_results=execution.route_results,
        process_results=execution.process_results,
        stdout_excerpt=execution.stdout_excerpt,
        stderr_excerpt=execution.stderr_excerpt,
        stdout_sha256=execution.stdout_sha256,
        stderr_sha256=execution.stderr_sha256,
        cleanup_attempts=execution.cleanup_attempts,
        cleanup_started_at=execution.cleanup_started_at,
        cleanup_finished_at=execution.cleanup_finished_at,
        cleanup_receipt_digest=execution.cleanup_receipt_digest,
    )


def _page_view(page: SandboxExecutionPage) -> SandboxExecutionPageView:
    return SandboxExecutionPageView(
        business_id=page.business_id,
        executions=[_summary_view(record) for record in page.executions],
        total_executions=page.total_executions,
        limit=page.limit,
        offset=page.offset,
    )


def _handle(error: Exception) -> HTTPException:
    if isinstance(error, SandboxExecutionNotFound):
        return HTTPException(status_code=404, detail="Sandbox execution not found")
    if isinstance(error, SandboxNotCancellable):
        return HTTPException(status_code=409, detail="Sandbox execution is already terminal")
    if isinstance(error, SandboxConflict):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, (SandboxNotReady, SandboxProfileMismatch)):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, SandboxQueueUnavailable):
        return HTTPException(
            status_code=503,
            detail={"code": "queue_unavailable"},
        )
    return HTTPException(status_code=500, detail="Sandbox operation failed")


@router.get("/executions", response_model=SandboxExecutionPageView)
async def list_sandbox_executions(
    context: Annotated[AuthContext, Depends(require_auth)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SandboxExecutionPageView:
    page = await SandboxService().list_executions(context, limit=limit, offset=offset)
    response.headers["Cache-Control"] = "no-store"
    return _page_view(page)


@router.get("/executions/{execution_id}", response_model=SandboxExecutionDetailView)
async def get_sandbox_execution(
    execution_id: UUID,
    context: Annotated[AuthContext, Depends(require_auth)],
    response: Response,
) -> SandboxExecutionDetailView:
    try:
        record = await SandboxService().get_execution(context, execution_id)
    except SandboxExecutionNotFound as error:
        raise _handle(error) from error
    response.headers["Cache-Control"] = "no-store"
    return _detail_view(record)


@router.post(
    "/executions",
    response_model=SandboxExecutionDetailView,
    status_code=status.HTTP_201_CREATED,
)
async def request_sandbox_execution(
    payload: RequestSandboxExecution,
    context: Annotated[AuthContext, Depends(require_csrf)],
    response: Response,
) -> SandboxExecutionDetailView:
    service = SandboxService()
    try:
        execution = await service.request_execution(
            context,
            idempotency_key=payload.idempotency_key,
        )
        record = await service.get_execution(context, execution.id)
    except (SandboxConflict, SandboxNotReady, SandboxProfileMismatch) as error:
        raise _handle(error) from error
    response.headers["Cache-Control"] = "no-store"
    return _detail_view(record)


@router.post(
    "/executions/{execution_id}/start",
    response_model=SandboxExecutionDetailView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_sandbox_execution(
    execution_id: UUID,
    context: Annotated[AuthContext, Depends(require_csrf)],
    response: Response,
) -> SandboxExecutionDetailView:
    service = SandboxService()
    try:
        await service.start_execution(context, execution_id)
        record = await service.get_execution(context, execution_id)
    except (
        SandboxConflict,
        SandboxExecutionNotFound,
        SandboxNotReady,
        SandboxProfileMismatch,
        SandboxQueueUnavailable,
    ) as error:
        raise _handle(error) from error
    response.headers["Cache-Control"] = "no-store"
    return _detail_view(record)


@router.post(
    "/executions/{execution_id}/cancel",
    response_model=SandboxExecutionDetailView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_sandbox_execution(
    execution_id: UUID,
    context: Annotated[AuthContext, Depends(require_csrf)],
    response: Response,
) -> SandboxExecutionDetailView:
    service = SandboxService()
    try:
        await service.cancel_execution(context, execution_id)
        record = await service.get_execution(context, execution_id)
    except (
        SandboxExecutionNotFound,
        SandboxNotCancellable,
        SandboxQueueUnavailable,
    ) as error:
        raise _handle(error) from error
    response.headers["Cache-Control"] = "no-store"
    return _detail_view(record)
