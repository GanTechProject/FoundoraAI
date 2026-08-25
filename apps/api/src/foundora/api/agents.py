from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

from foundora.agents.executive import EXECUTIVE_AGENT_IDS
from foundora.agents.research import RESEARCH_AGENT_IDS
from foundora.agents.schema import AgentSchemaError
from foundora.agents.service import (
    AgentDashboard,
    AgentDefinitionRecord,
    AgentNotFound,
    AgentQueueUnavailable,
    AgentRunNotCancellable,
    AgentRunNotFound,
    AgentRunRecord,
    AgentService,
    BrandEvidenceInvalid,
    ProductOfferEvidenceInvalid,
    ResearchQueryInvalid,
    ResearchSearchRecord,
    ResearchSearchUnavailable,
    SkillDefinitionRecord,
    SkillNotAssigned,
    StrategyEvidenceInvalid,
)
from foundora.agents.strategy import BUSINESS_STRATEGIST_AGENT_ID, evidence_allowlists
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
    skill_id: str | None = Field(default=None, min_length=1, max_length=80)
    skill_input: dict[str, object] = Field(default_factory=dict)
    research_query: str | None = Field(default=None, max_length=500)
    research_run_ids: list[uuid.UUID] = Field(default_factory=list, max_length=3)

    @field_validator("objective")
    @classmethod
    def clean_objective(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("objective cannot be blank")
        return cleaned

    @field_validator("research_query")
    @classmethod
    def clean_research_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.strip().split())
        return cleaned or None


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
    assigned_skills: list[AssignedSkillView]


class AssignedSkillView(BaseModel):
    skill_id: str
    version_id: uuid.UUID
    version: int


class SkillDefinitionView(BaseModel):
    skill_id: str
    display_name: str
    enabled: bool
    version_id: uuid.UUID
    version: int
    description: str
    compatible_agents: list[str]
    prerequisites: list[str]
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    tool_requirements: list[str]
    workflow: list[str]
    permissions: list[str]
    risk_class: str
    test_fixtures: list[dict[str, object]]
    evaluation_rubric: list[str]


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


class ExecutivePlanTraceView(BaseModel):
    run_id: uuid.UUID
    agent_version_id: uuid.UUID
    context_id: str
    context_sha256: str
    source_references: list[str]
    output_context_matches: bool
    advisory_only: Literal[True] = True


class ResearchEvidenceView(BaseModel):
    evidence_id: str
    source: str
    source_title: str
    retrieval_date: str
    retrieved_at: str
    excerpt: str
    content_sha256: str


class ResearchTraceView(BaseModel):
    provider: str
    query: str
    evidence: list[ResearchEvidenceView]
    output_validated: bool
    advisory_only: Literal[True] = True


class StrategyTraceView(BaseModel):
    approved_fact_refs: list[str]
    research_finding_refs: list[str]
    output_context_matches: bool
    proposed_only: Literal[True] = True


class ResearchSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("query cannot be blank")
        return cleaned


class ResearchSearchView(BaseModel):
    provider: str
    query: str
    evidence: list[ResearchEvidenceView]


class AgentRunView(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    agent_id: str
    agent_version_id: uuid.UUID
    agent_version: int
    skill_id: str | None
    skill_version_id: uuid.UUID | None
    skill_version: int | None
    status: RunStatus
    structured_input: dict[str, object]
    structured_output: dict[str, object] | None
    model_operation_id: uuid.UUID | None
    error_type: str | None
    error_message: str | None
    worker_recovery_count: int
    created_at: datetime
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancellation_requested_at: datetime | None
    cancelled_at: datetime | None
    messages: list[AgentMessageView]
    usage: AgentUsageView
    executive_plan_trace: ExecutivePlanTraceView | None
    research_trace: ResearchTraceView | None
    strategy_trace: StrategyTraceView | None


class AgentDashboardView(BaseModel):
    business_id: uuid.UUID
    definitions: list[AgentDefinitionView]
    skills: list[SkillDefinitionView]
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
        assigned_skills=[
            AssignedSkillView(
                skill_id=skill.skill_id,
                version_id=skill.id,
                version=skill.version,
            )
            for skill in record.assigned_skills
        ],
    )


def _skill_view(record: SkillDefinitionRecord) -> SkillDefinitionView:
    skill = record.skill
    version = record.version
    return SkillDefinitionView(
        skill_id=skill.id,
        display_name=skill.display_name,
        enabled=skill.enabled,
        version_id=version.id,
        version=version.version,
        description=version.description,
        compatible_agents=version.compatible_agents,
        prerequisites=version.prerequisites,
        input_schema=version.input_schema,
        output_schema=version.output_schema,
        tool_requirements=version.tool_requirements,
        workflow=version.workflow,
        permissions=version.permissions,
        risk_class=version.risk_class,
        test_fixtures=version.test_fixtures,
        evaluation_rubric=version.evaluation_rubric,
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
    trace: ExecutivePlanTraceView | None = None
    if run.agent_id in EXECUTIVE_AGENT_IDS:
        context_id = run.structured_input.get("context_id")
        context_sha256 = run.structured_input.get("context_sha256")
        business_context = run.structured_input.get("business_context")
        source_references: list[str] = []
        if isinstance(business_context, dict):
            sources = business_context.get("sources")
            if isinstance(sources, list):
                source_references = sorted(
                    {
                        reference
                        for item in sources
                        if isinstance(item, dict)
                        and isinstance((reference := item.get("source_reference")), str)
                    }
                )
        if isinstance(context_id, str) and isinstance(context_sha256, str):
            output_context_id = (
                run.structured_output.get("context_id")
                if isinstance(run.structured_output, dict)
                else None
            )
            trace = ExecutivePlanTraceView(
                run_id=run.id,
                agent_version_id=run.agent_version_id,
                context_id=context_id,
                context_sha256=context_sha256,
                source_references=source_references,
                output_context_matches=output_context_id == context_id,
            )
    research_trace: ResearchTraceView | None = None
    if run.agent_id in RESEARCH_AGENT_IDS:
        research = run.structured_input.get("research")
        if isinstance(research, dict):
            provider = research.get("provider")
            query = research.get("query")
            evidence = research.get("evidence")
            if isinstance(provider, str) and isinstance(query, str) and isinstance(evidence, list):
                evidence_views: list[ResearchEvidenceView] = []
                for item in evidence:
                    if not isinstance(item, dict):
                        continue
                    try:
                        evidence_views.append(ResearchEvidenceView.model_validate(item))
                    except ValueError:
                        continue
                research_trace = ResearchTraceView(
                    provider=provider,
                    query=query,
                    evidence=evidence_views,
                    output_validated=run.status == "completed",
                )
    strategy_trace: StrategyTraceView | None = None
    if run.agent_id == BUSINESS_STRATEGIST_AGENT_ID:
        try:
            approved_refs, research_refs = evidence_allowlists(run.structured_input)
            strategy_trace = StrategyTraceView(
                approved_fact_refs=sorted(approved_refs),
                research_finding_refs=sorted(research_refs),
                output_context_matches=(
                    isinstance(run.structured_output, dict)
                    and run.structured_output.get("context_id")
                    == run.structured_input.get("context_id")
                ),
            )
        except AgentSchemaError:
            strategy_trace = None
    return AgentRunView(
        id=run.id,
        business_id=run.business_id,
        agent_id=run.agent_id,
        agent_version_id=run.agent_version_id,
        agent_version=record.version.version,
        skill_id=(record.skill_version.skill_id if record.skill_version is not None else None),
        skill_version_id=run.skill_version_id,
        skill_version=(record.skill_version.version if record.skill_version is not None else None),
        status=run.status,  # type: ignore[arg-type]
        structured_input=run.structured_input,
        structured_output=run.structured_output,
        model_operation_id=run.model_operation_id,
        error_type=run.error_type,
        error_message=run.error_message,
        worker_recovery_count=run.worker_recovery_count,
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
        executive_plan_trace=trace,
        research_trace=research_trace,
        strategy_trace=strategy_trace,
    )


def _dashboard_view(dashboard: AgentDashboard) -> AgentDashboardView:
    return AgentDashboardView(
        business_id=dashboard.business_id,
        definitions=[_definition_view(record) for record in dashboard.definitions],
        skills=[_skill_view(record) for record in dashboard.skills],
        runs=[_run_view(record) for record in dashboard.runs],
    )


def _research_search_view(record: ResearchSearchRecord) -> ResearchSearchView:
    return ResearchSearchView(
        provider=record.provider,
        query=record.query,
        evidence=[
            ResearchEvidenceView.model_validate(item, from_attributes=True)
            for item in record.evidence
        ],
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


@router.post("/research/search", response_model=ResearchSearchView)
async def preview_research_evidence(
    payload: ResearchSearchRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
    response: Response,
) -> ResearchSearchView:
    try:
        record = await AgentService().search_research_evidence(context, payload.query)
    except ResearchQueryInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_research_query", "message": "Search query is invalid"},
        ) from error
    except ResearchSearchUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "research_search_unavailable",
                "message": "The registered-knowledge search boundary is unavailable",
            },
        ) from error
    response.headers["Cache-Control"] = "no-store"
    return _research_search_view(record)


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
        record = await AgentService().create_run(
            context,
            agent_id,
            payload.objective,
            payload.skill_id,
            payload.skill_input,
            payload.research_query,
            payload.research_run_ids,
        )
    except AgentNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enabled agent definition not found",
        ) from error
    except SkillNotAssigned as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "skill_not_assigned",
                "message": "The requested skill is not assigned to this agent version",
            },
        ) from error
    except AgentSchemaError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_skill_input", "message": str(error)},
        ) from error
    except ResearchQueryInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_research_query",
                "message": (
                    "Research agents require a 1 to 500 character query; "
                    "other agents do not accept one"
                ),
            },
        ) from error
    except ResearchSearchUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "research_search_unavailable",
                "message": "The registered-knowledge search boundary is unavailable",
            },
        ) from error
    except StrategyEvidenceInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_strategy_evidence",
                "message": (
                    "Business strategy requires one completed, validated, supported run from "
                    "each Phase 16 research specialist plus founder-approved business facts"
                ),
            },
        ) from error
    except ProductOfferEvidenceInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_product_offer_evidence",
                "message": (
                    "Product and offer proposals require the current founder-approved "
                    "business strategy"
                ),
            },
        ) from error
    except BrandEvidenceInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_brand_evidence",
                "message": (
                    "Brand proposals require the current approved strategy and an active "
                    "approved product and offer portfolio derived from that strategy"
                ),
            },
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
