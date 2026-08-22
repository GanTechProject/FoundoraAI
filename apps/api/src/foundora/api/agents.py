from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

from foundora.agents.service import (
    AgentDashboard,
    AgentDefinitionRecord,
    AgentNotFound,
    AgentQueueUnavailable,
    AgentRunNotCancellable,
    AgentRunNotFound,
    AgentRunRecord,
    AgentService,
)
from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext

router = APIRouter(prefix="/agents", tags=["agents"])
RunStatus = Literal[
    "queued",
    "running",
    "waiting_tool",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
]


class CreateAgentRunRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=500)

    @field_validator("objective")
    @classmethod
    def clean_objective(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("objective cannot be blank")
        return cleaned


class AgentDefinitionView(BaseModel):
    agent_id: str
    display_name: str
    enabled: bool
    version_id: uuid.UUID
    version: int
    role: str
    purpose: str
    responsibilities: list[str]
    non_responsibilities: list[str]
    allowed_task_types: list[str]
    allowed_skills: list[str]
    allowed_tools: list[str]
    forbidden_actions: list[str]
    model_policy: dict[str, object]
    data_access_scope: dict[str, object]
    risk_level: str
    maximum_autonomy: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    evaluation_criteria: list[str]
    escalation_criteria: list[str]


class AgentMessageView(BaseModel):
    sequence: int
    role: Literal["user", "assistant", "system"]
    message_type: Literal["input", "output", "error"]
    content: dict[str, object]
    created_at: datetime


class AgentUsageCallView(BaseModel):
    operation_id: uuid.UUID
    provider: str
    model: str
    status: Literal["succeeded", "failed"]
    attempt_number: int
    input_tokens: int
    output_tokens: int
    estimated_cost_microusd: int
    error_type: str | None
    created_at: datetime


class AgentUsageView(BaseModel):
    calls: int
    total_tokens: int
    estimated_cost_microusd: int
    attempts: list[AgentUsageCallView]


class AgentRunView(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    agent_id: str
    agent_version_id: uuid.UUID
    agent_version: int
    status: RunStatus
    structured_input: dict[str, object]
    structured_output: dict[str, object] | None
    model_operation_id: uuid.UUID | None
    error_type: str | None
    error_message: str | None
    created_at: datetime
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancellation_requested_at: datetime | None
    cancelled_at: datetime | None
    messages: list[AgentMessageView]
    usage: AgentUsageView


class AgentDashboardView(BaseModel):
    business_id: uuid.UUID
    definitions: list[AgentDefinitionView]
    runs: list[AgentRunView]


def _definition_view(record: AgentDefinitionRecord) -> AgentDefinitionView:
    agent = record.agent
    version = record.version
    return AgentDefinitionView(
        agent_id=agent.id,
        display_name=agent.display_name,
        enabled=agent.enabled,
        version_id=version.id,
        version=version.version,
        role=version.role,
        purpose=version.purpose,
        responsibilities=version.responsibilities,
        non_responsibilities=version.non_responsibilities,
        allowed_task_types=version.allowed_task_types,
        allowed_skills=version.allowed_skills,
        allowed_tools=version.allowed_tools,
        forbidden_actions=version.forbidden_actions,
        model_policy=version.model_policy,
        data_access_scope=version.data_access_scope,
        risk_level=version.risk_level,
        maximum_autonomy=version.maximum_autonomy,
        input_schema=version.input_schema,
        output_schema=version.output_schema,
        evaluation_criteria=version.evaluation_criteria,
        escalation_criteria=version.escalation_criteria,
    )


def _run_view(record: AgentRunRecord) -> AgentRunView:
    run = record.run
    attempts = [
        AgentUsageCallView(
            operation_id=call.operation_id,
            provider=call.provider,
            model=call.model,
            status=call.status,  # type: ignore[arg-type]
            attempt_number=call.attempt_number,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            estimated_cost_microusd=call.estimated_cost_microusd,
            error_type=call.error_type,
            created_at=call.created_at,
        )
        for call in record.gateway_calls
    ]
    return AgentRunView(
        id=run.id,
        business_id=run.business_id,
        agent_id=run.agent_id,
        agent_version_id=run.agent_version_id,
        agent_version=record.version.version,
        status=run.status,  # type: ignore[arg-type]
        structured_input=run.structured_input,
        structured_output=run.structured_output,
        model_operation_id=run.model_operation_id,
        error_type=run.error_type,
        error_message=run.error_message,
        created_at=run.created_at,
        queued_at=run.queued_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        cancellation_requested_at=run.cancellation_requested_at,
        cancelled_at=run.cancelled_at,
        messages=[
            AgentMessageView(
                sequence=message.sequence,
                role=message.role,  # type: ignore[arg-type]
                message_type=message.message_type,  # type: ignore[arg-type]
                content=message.content,
                created_at=message.created_at,
            )
            for message in record.messages
        ],
        usage=AgentUsageView(
            calls=len(attempts),
            total_tokens=sum(item.input_tokens + item.output_tokens for item in attempts),
            estimated_cost_microusd=sum(item.estimated_cost_microusd for item in attempts),
            attempts=attempts,
        ),
    )


def _dashboard_view(dashboard: AgentDashboard) -> AgentDashboardView:
    return AgentDashboardView(
        business_id=dashboard.business_id,
        definitions=[_definition_view(record) for record in dashboard.definitions],
        runs=[_run_view(record) for record in dashboard.runs],
    )


def _not_found(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")


@router.get("", response_model=AgentDashboardView)
async def agent_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> AgentDashboardView:
    dashboard = await AgentService().dashboard(context)
    response.headers["Cache-Control"] = "no-store"
    return _dashboard_view(dashboard)


@router.post(
    "/{agent_id}/runs",
    response_model=AgentRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_agent_run(
    agent_id: str,
    payload: CreateAgentRunRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> AgentRunView:
    try:
        record = await AgentService().create_run(context, agent_id, payload.objective)
    except AgentNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enabled agent definition not found",
        ) from error
    except AgentQueueUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "agent_queue_unavailable",
                "message": "The run was persisted as failed because the queue was unavailable",
                "run_id": str(error.run_id),
            },
        ) from error
    return _run_view(record)


@router.get("/runs/{run_id}", response_model=AgentRunView)
async def inspect_agent_run(
    run_id: uuid.UUID,
    context: Annotated[AuthContext, Depends(require_auth)],
    response: Response,
) -> AgentRunView:
    try:
        record = await AgentService().inspect_run(context, run_id)
    except AgentRunNotFound as error:
        raise _not_found(error) from error
    response.headers["Cache-Control"] = "no-store"
    return _run_view(record)


@router.post("/runs/{run_id}/cancel", response_model=AgentRunView)
async def cancel_agent_run(
    run_id: uuid.UUID,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> AgentRunView:
    try:
        record = await AgentService().cancel_run(context, run_id)
    except AgentRunNotFound as error:
        raise _not_found(error) from error
    except AgentRunNotCancellable as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Terminal agent runs cannot be cancelled",
        ) from error
    return _run_view(record)
