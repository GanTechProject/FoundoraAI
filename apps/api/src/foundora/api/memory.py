from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.memory.service import (
    EPISTEMIC_BY_TYPE,
    MEMORY_TYPES,
    MemoryConflict,
    MemoryDashboard,
    MemoryEntry,
    MemoryProposalNotFound,
    MemoryRecordNotFound,
    MemoryService,
)
from foundora.models import MemoryPolicy, MemoryProposal

router = APIRouter(prefix="/memory", tags=["memory system"])
MemoryType = Literal[
    "working", "episodic", "semantic", "decision", "preference", "workflow", "evaluation"
]
EpistemicStatus = Literal[
    "observation", "assumption", "fact", "decision", "preference", "procedure", "evaluation"
]
ProposalStatus = Literal["pending", "accepted", "rejected", "merged"]
MemoryStatus = Literal["active", "expired", "invalidated"]
AcceptanceRoute = Literal["founder", "automatic"]
SourceKind = Literal["founder_input", "knowledge_chunk", "task", "agent_run", "workflow_run"]


class PolicyUpdateRequest(BaseModel):
    automatic_accept_types: list[MemoryType] = Field(max_length=4)
    minimum_confidence: float = Field(ge=0, le=1)
    expected_revision: int = Field(ge=0)


class ProposalRequest(BaseModel):
    memory_type: MemoryType
    epistemic_status: EpistemicStatus
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)
    confidence: float = Field(ge=0, le=1)
    execution_type: Literal["task", "agent_run", "workflow_run"] | None = None
    execution_id: UUID | None = None
    expires_at: datetime | None = None
    source_kind: SourceKind
    source_id: str | None = Field(default=None, max_length=160)
    source_uri: str | None = Field(default=None, max_length=2048)
    source_label: str = Field(min_length=1, max_length=200)
    source_excerpt: str | None = Field(default=None, max_length=1000)
    source_metadata: dict[str, object] = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class PolicyView(BaseModel):
    automatic_accept_types: list[MemoryType]
    minimum_confidence: float
    revision: int
    persisted: bool


class ProposalView(BaseModel):
    id: UUID
    memory_type: MemoryType
    epistemic_status: EpistemicStatus
    title: str
    content: str
    confidence: float
    status: ProposalStatus
    acceptance_route: AcceptanceRoute
    execution_type: str | None
    execution_id: UUID | None
    expires_at: datetime | None
    source_kind: SourceKind
    source_id: str | None
    source_uri: str | None
    source_label: str
    source_excerpt: str | None
    source_metadata: dict[str, object]
    resolution_memory_id: UUID | None
    decision_reason: str | None
    revision: int
    created_at: datetime
    decided_at: datetime | None


class RevisionView(BaseModel):
    revision: int
    proposal_id: UUID
    change_type: Literal["accepted", "merged"]
    confidence: float
    created_by: AcceptanceRoute
    created_at: datetime


class ProvenanceView(BaseModel):
    revision: int
    source_kind: SourceKind
    source_id: str | None
    source_uri: str | None
    source_label: str
    source_excerpt: str | None
    source_metadata: dict[str, object]
    created_at: datetime


class MemoryView(BaseModel):
    id: UUID
    memory_type: MemoryType
    epistemic_status: EpistemicStatus
    title: str
    content: str
    confidence: float
    status: MemoryStatus
    accepted_via: AcceptanceRoute
    execution_type: str | None
    execution_id: UUID | None
    expires_at: datetime | None
    current_revision: int
    created_at: datetime
    updated_at: datetime
    invalidated_at: datetime | None
    invalidation_reason: str | None
    revisions: list[RevisionView]
    provenance: list[ProvenanceView]


class MemoryDashboardView(BaseModel):
    business_id: UUID
    memory_types: list[MemoryType]
    epistemic_statuses_by_type: dict[str, list[EpistemicStatus]]
    policy: PolicyView
    proposals: list[ProposalView]
    memories: list[MemoryView]


class MemoryMutationView(BaseModel):
    id: UUID
    status: Literal["invalidated"]
    current_revision: int


def _proposal_view(record: MemoryProposal) -> ProposalView:
    return ProposalView(
        id=record.id,
        memory_type=record.memory_type,  # type: ignore[arg-type]
        epistemic_status=record.epistemic_status,  # type: ignore[arg-type]
        title=record.title,
        content=record.content,
        confidence=record.confidence,
        status=record.status,  # type: ignore[arg-type]
        acceptance_route=record.acceptance_route,  # type: ignore[arg-type]
        execution_type=record.execution_type,
        execution_id=record.execution_id,
        expires_at=record.expires_at,
        source_kind=record.source_kind,  # type: ignore[arg-type]
        source_id=record.source_id,
        source_uri=record.source_uri,
        source_label=record.source_label,
        source_excerpt=record.source_excerpt,
        source_metadata=record.source_metadata,
        resolution_memory_id=record.resolution_memory_id,
        decision_reason=record.decision_reason,
        revision=record.revision,
        created_at=record.created_at,
        decided_at=record.decided_at,
    )


def _memory_view(entry: MemoryEntry) -> MemoryView:
    record = entry.record
    effective_status = (
        "expired"
        if record.status == "active"
        and record.expires_at is not None
        and record.expires_at <= datetime.now(UTC)
        else record.status
    )
    return MemoryView(
        id=record.id,
        memory_type=record.memory_type,  # type: ignore[arg-type]
        epistemic_status=record.epistemic_status,  # type: ignore[arg-type]
        title=record.title,
        content=record.content,
        confidence=record.confidence,
        status=effective_status,  # type: ignore[arg-type]
        accepted_via=record.accepted_via,  # type: ignore[arg-type]
        execution_type=record.execution_type,
        execution_id=record.execution_id,
        expires_at=record.expires_at,
        current_revision=record.current_revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
        invalidated_at=record.invalidated_at,
        invalidation_reason=record.invalidation_reason,
        revisions=[
            RevisionView(
                revision=item.revision,
                proposal_id=item.proposal_id,
                change_type=item.change_type,  # type: ignore[arg-type]
                confidence=item.confidence,
                created_by=item.created_by,  # type: ignore[arg-type]
                created_at=item.created_at,
            )
            for item in entry.revisions
        ],
        provenance=[
            ProvenanceView(
                revision=item.revision,
                source_kind=item.source_kind,  # type: ignore[arg-type]
                source_id=item.source_id,
                source_uri=item.source_uri,
                source_label=item.source_label,
                source_excerpt=item.source_excerpt,
                source_metadata=item.source_metadata,
                created_at=item.created_at,
            )
            for item in entry.provenance
        ],
    )


def _dashboard_view(record: MemoryDashboard) -> MemoryDashboardView:
    return MemoryDashboardView(
        business_id=record.business_id,
        memory_types=sorted(MEMORY_TYPES),  # type: ignore[arg-type]
        epistemic_statuses_by_type={
            name: sorted(values)  # type: ignore[arg-type]
            for name, values in EPISTEMIC_BY_TYPE.items()
        },
        policy=PolicyView(
            automatic_accept_types=list(record.policy.automatic_accept_types),  # type: ignore[arg-type]
            minimum_confidence=record.policy.minimum_confidence,
            revision=record.policy.revision,
            persisted=record.policy.persisted,
        ),
        proposals=[_proposal_view(item) for item in record.proposals],
        memories=[_memory_view(item) for item in record.memories],
    )


def _conflict(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


def _set(value: str | None) -> frozenset[str]:
    return frozenset(item.strip() for item in (value or "").split(",") if item.strip())


@router.get("", response_model=MemoryDashboardView)
async def memory_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)],
    response: Response,
    memory_types: Annotated[str | None, Query(max_length=256)] = None,
    epistemic_statuses: Annotated[str | None, Query(max_length=256)] = None,
    query: Annotated[str | None, Query(max_length=500)] = None,
    include_inactive: bool = True,
    execution_type: Literal["task", "agent_run", "workflow_run"] | None = None,
    execution_id: UUID | None = None,
) -> MemoryDashboardView:
    response.headers["Cache-Control"] = "no-store"
    try:
        result = await MemoryService().dashboard(
            context,
            memory_types=_set(memory_types),
            epistemic_statuses=_set(epistemic_statuses),
            query=query.strip() if query else None,
            include_inactive=include_inactive,
            execution_type=execution_type,
            execution_id=execution_id,
        )
    except MemoryConflict as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _dashboard_view(result)


@router.post("/policy", response_model=PolicyView)
async def update_memory_policy(
    payload: PolicyUpdateRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> PolicyView:
    try:
        policy: MemoryPolicy = await MemoryService().update_policy(context, **payload.model_dump())
    except MemoryConflict as error:
        raise _conflict(error) from error
    return PolicyView(
        automatic_accept_types=policy.automatic_accept_types,  # type: ignore[arg-type]
        minimum_confidence=policy.minimum_confidence,
        revision=policy.revision,
        persisted=True,
    )


@router.post("/proposals", response_model=ProposalView, status_code=status.HTTP_201_CREATED)
async def propose_memory(
    payload: ProposalRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> ProposalView:
    try:
        proposal = await MemoryService().propose(context, **payload.model_dump())
    except MemoryConflict as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_memory_proposal", "message": str(error)},
        ) from error
    return _proposal_view(proposal)


@router.post("/proposals/{proposal_id}/accept", response_model=ProposalView)
async def accept_memory(
    proposal_id: UUID,
    payload: DecisionRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> ProposalView:
    try:
        record = await MemoryService().decide_proposal(
            context, proposal_id, accept=True, **payload.model_dump()
        )
    except MemoryProposalNotFound as error:
        raise HTTPException(status_code=404, detail="Memory proposal not found") from error
    except MemoryConflict as error:
        raise _conflict(error) from error
    return _proposal_view(record)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalView)
async def reject_memory(
    proposal_id: UUID,
    payload: DecisionRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> ProposalView:
    try:
        record = await MemoryService().decide_proposal(
            context, proposal_id, accept=False, **payload.model_dump()
        )
    except MemoryProposalNotFound as error:
        raise HTTPException(status_code=404, detail="Memory proposal not found") from error
    except MemoryConflict as error:
        raise _conflict(error) from error
    return _proposal_view(record)


@router.post("/records/{memory_id}/invalidate", response_model=MemoryMutationView)
async def invalidate_memory(
    memory_id: UUID,
    payload: DecisionRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> MemoryMutationView:
    try:
        record = await MemoryService().invalidate(context, memory_id, **payload.model_dump())
    except MemoryRecordNotFound as error:
        raise HTTPException(status_code=404, detail="Memory record not found") from error
    except MemoryConflict as error:
        raise _conflict(error) from error
    return MemoryMutationView(
        id=record.id, status="invalidated", current_revision=record.current_revision
    )
