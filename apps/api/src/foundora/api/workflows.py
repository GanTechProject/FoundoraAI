from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from foundora.agents.schema import AgentSchemaError
from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.workflows.definition import WorkflowDefinitionError
from foundora.workflows.service import (
    WorkflowDashboard,
    WorkflowDefinitionRecord,
    WorkflowNotFound,
    WorkflowQueueUnavailable,
    WorkflowResumeNotAllowed,
    WorkflowRunNotCancellable,
    WorkflowRunNotFound,
    WorkflowRunRecord,
    WorkflowService,
    WorkflowTaskNotFound,
)

router = APIRouter(prefix="/workflows", tags=["workflow engine"])
RunStatus = Literal[
    "queued",
    "running",
    "waiting",
    "waiting_approval",
    "waiting_agent",
    "completed",
    "failed",
    "cancelled",
]
StepStatus = Literal[
    "pending",
    "running",
    "waiting",
    "waiting_approval",
    "waiting_agent",
    "completed",
    "skipped",
    "failed",
    "cancelled",
    "compensated",
]
StepType = Literal["tool", "agent", "approval", "wait"]


class StartWorkflowRequest(BaseModel):
    input: dict[str, object]
    task_id: UUID | None = None


class ResumeWorkflowRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    decision: Literal["approved", "rejected"] | None = None
    input: dict[str, object] = Field(default_factory=dict)


class WorkflowStepDefinitionView(BaseModel):
    key: str
    type: StepType
    depends_on: list[str]
    max_retries: int
    condition: dict[str, object] | None
    tool: str | None
    agent_id: str | None
    agent_version_id: UUID | None
    compensation: str | None


class WorkflowDefinitionView(BaseModel):
    workflow_id: str
    display_name: str
    enabled: bool
    version_id: UUID
    version: int
    description: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    steps: list[WorkflowStepDefinitionView]


class WorkflowStepRunView(BaseModel):
    id: UUID
    key: str
    sequence: int
    type: StepType
    status: StepStatus
    attempt_count: int
    max_retries: int
    agent_run_id: UUID | None
    input: dict[str, object] | None
    output: dict[str, object] | None
    error_type: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None


class WorkflowEventView(BaseModel):
    id: UUID
    sequence: int
    event_type: str
    step_key: str | None
    idempotency_key: str | None
    details: dict[str, object]
    created_at: datetime


class WorkflowRunView(BaseModel):
    id: UUID
    business_id: UUID
    workflow_id: str
    workflow_version_id: UUID
    workflow_version: int
    task_id: UUID | None
    status: RunStatus
    input: dict[str, object]
    output: dict[str, object] | None
    current_step_key: str | None
    error_type: str | None
    error_message: str | None
    worker_recovery_count: int
    created_at: datetime
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    steps: list[WorkflowStepRunView]
    events: list[WorkflowEventView]


class WorkflowDashboardView(BaseModel):
    business_id: UUID
    definitions: list[WorkflowDefinitionView]
    runs: list[WorkflowRunView]


def _definition_view(record: WorkflowDefinitionRecord) -> WorkflowDefinitionView:
    def optional_string(value: object) -> str | None:
        return value if isinstance(value, str) else None

    def optional_dict(value: object) -> dict[str, object] | None:
        return value if isinstance(value, dict) else None

    return WorkflowDefinitionView(
        workflow_id=record.workflow.id,
        display_name=record.workflow.display_name,
        enabled=record.workflow.enabled,
        version_id=record.version.id,
        version=record.version.version,
        description=record.version.description,
        input_schema=record.version.input_schema,
        output_schema=record.version.output_schema,
        steps=[
            WorkflowStepDefinitionView(
                key=step.key,
                type=step.step_type,  # type: ignore[arg-type]
                depends_on=list(step.depends_on),
                max_retries=step.max_retries,
                condition=optional_dict(step.config.get("condition")),
                tool=optional_string(step.config.get("tool")),
                agent_id=optional_string(step.config.get("agent_id")),
                agent_version_id=(
                    UUID(value)
                    if (value := optional_string(step.config.get("agent_version_id")))
                    else None
                ),
                compensation=optional_string(step.config.get("compensation")),
            )
            for step in record.steps
        ],
    )


def _run_view(record: WorkflowRunRecord) -> WorkflowRunView:
    run = record.run
    return WorkflowRunView(
        id=run.id,
        business_id=run.business_id,
        workflow_id=run.workflow_id,
        workflow_version_id=run.workflow_version_id,
        workflow_version=record.version.version,
        task_id=run.task_id,
        status=run.status,  # type: ignore[arg-type]
        input=run.structured_input,
        output=run.structured_output,
        current_step_key=run.current_step_key,
        error_type=run.error_type,
        error_message=run.error_message,
        worker_recovery_count=run.worker_recovery_count,
        created_at=run.created_at,
        queued_at=run.queued_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        cancelled_at=run.cancelled_at,
        steps=[
            WorkflowStepRunView(
                id=step.id,
                key=step.step_key,
                sequence=step.sequence,
                type=step.step_type,  # type: ignore[arg-type]
                status=step.status,  # type: ignore[arg-type]
                attempt_count=step.attempt_count,
                max_retries=step.max_retries,
                agent_run_id=step.agent_run_id,
                input=step.structured_input,
                output=step.structured_output,
                error_type=step.error_type,
                error_message=step.error_message,
                started_at=step.started_at,
                completed_at=step.completed_at,
            )
            for step in record.steps
        ],
        events=[
            WorkflowEventView(
                id=event.id,
                sequence=event.sequence,
                event_type=event.event_type,
                step_key=event.step_key,
                idempotency_key=event.idempotency_key,
                details=event.details,
                created_at=event.created_at,
            )
            for event in record.events
        ],
    )


def _dashboard_view(dashboard: WorkflowDashboard) -> WorkflowDashboardView:
    return WorkflowDashboardView(
        business_id=dashboard.business_id,
        definitions=[_definition_view(item) for item in dashboard.definitions],
        runs=[_run_view(item) for item in dashboard.runs],
    )


@router.get("", response_model=WorkflowDashboardView)
async def workflow_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> WorkflowDashboardView:
    response.headers["Cache-Control"] = "no-store"
    return _dashboard_view(await WorkflowService().dashboard(context))


@router.post(
    "/{workflow_id}/runs",
    response_model=WorkflowRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_workflow(
    workflow_id: str,
    payload: StartWorkflowRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> WorkflowRunView:
    try:
        record = await WorkflowService().start(context, workflow_id, payload.input, payload.task_id)
    except WorkflowNotFound as error:
        raise HTTPException(status_code=404, detail="Enabled workflow not found") from error
    except WorkflowTaskNotFound as error:
        raise HTTPException(status_code=404, detail="Selected-business task not found") from error
    except (AgentSchemaError, WorkflowDefinitionError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except WorkflowQueueUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "workflow_queue_unavailable",
                "run_id": str(error.run_id),
            },
        ) from error
    return _run_view(record)


@router.get("/runs/{run_id}", response_model=WorkflowRunView)
async def inspect_workflow(
    run_id: UUID,
    context: Annotated[AuthContext, Depends(require_auth)],
    response: Response,
) -> WorkflowRunView:
    try:
        record = await WorkflowService().inspect(context, run_id)
    except WorkflowRunNotFound as error:
        raise HTTPException(status_code=404, detail="Workflow run not found") from error
    response.headers["Cache-Control"] = "no-store"
    return _run_view(record)


@router.post("/runs/{run_id}/resume", response_model=WorkflowRunView)
async def resume_workflow(
    run_id: UUID,
    payload: ResumeWorkflowRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> WorkflowRunView:
    try:
        record = await WorkflowService().resume(
            context,
            run_id,
            idempotency_key=payload.idempotency_key,
            decision=payload.decision,
            structured_input=payload.input,
        )
    except WorkflowRunNotFound as error:
        raise HTTPException(status_code=404, detail="Workflow run not found") from error
    except WorkflowResumeNotAllowed as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except WorkflowQueueUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "workflow_queue_unavailable", "run_id": str(error.run_id)},
        ) from error
    return _run_view(record)


@router.post("/runs/{run_id}/cancel", response_model=WorkflowRunView)
async def cancel_workflow(
    run_id: UUID,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> WorkflowRunView:
    try:
        record = await WorkflowService().cancel(context, run_id)
    except WorkflowRunNotFound as error:
        raise HTTPException(status_code=404, detail="Workflow run not found") from error
    except WorkflowRunNotCancellable as error:
        raise HTTPException(
            status_code=409, detail="Terminal workflow cannot be cancelled"
        ) from error
    return _run_view(record)
