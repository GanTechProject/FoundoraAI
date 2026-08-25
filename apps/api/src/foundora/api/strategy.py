from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.models import AgentRun, ApprovedBusinessStrategy
from foundora.strategy.service import (
    StrategyApprovalConflict,
    StrategyRunInvalid,
    StrategyRunNotFound,
    StrategyService,
)

router = APIRouter(prefix="/strategy", tags=["strategy"])


class ApproveStrategyRequest(BaseModel):
    run_id: uuid.UUID
    expected_version: int = Field(ge=0)


class ApprovedStrategyView(BaseModel):
    business_id: uuid.UUID
    version: int
    source_agent_run_id: uuid.UUID
    context_id: str
    strategy: dict[str, object]
    evidence_refs: dict[str, object]
    approved_by_owner_id: uuid.UUID
    approved_at: datetime


class StrategyCandidateView(BaseModel):
    run_id: uuid.UUID
    context_id: str
    strategy_title: str
    completed_at: datetime


class StrategyDashboardView(BaseModel):
    business_id: uuid.UUID
    current_version: int
    approved: ApprovedStrategyView | None
    candidate_runs: list[StrategyCandidateView]


def _approved_view(value: ApprovedBusinessStrategy) -> ApprovedStrategyView:
    return ApprovedStrategyView.model_validate(value, from_attributes=True)


def _candidate_view(value: AgentRun) -> StrategyCandidateView:
    output = value.structured_output or {}
    return StrategyCandidateView(
        run_id=value.id,
        context_id=str(value.structured_input.get("context_id", "")),
        strategy_title=str(output.get("strategy_title", "Untitled strategy")),
        completed_at=value.completed_at or value.created_at,
    )


@router.get("", response_model=StrategyDashboardView)
async def strategy_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> StrategyDashboardView:
    dashboard = await StrategyService().dashboard(context)
    response.headers["Cache-Control"] = "no-store"
    return StrategyDashboardView(
        business_id=dashboard.business_id,
        current_version=dashboard.approved.version if dashboard.approved is not None else 0,
        approved=(_approved_view(dashboard.approved) if dashboard.approved is not None else None),
        candidate_runs=[_candidate_view(run) for run in dashboard.candidate_runs],
    )


@router.post("/approve", response_model=ApprovedStrategyView)
async def approve_strategy(
    payload: ApproveStrategyRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> ApprovedStrategyView:
    try:
        approved = await StrategyService().approve(
            context, run_id=payload.run_id, expected_version=payload.expected_version
        )
    except StrategyRunNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found"
        ) from error
    except StrategyApprovalConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approved strategy version changed or this run is already current",
        ) from error
    except StrategyRunInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only a completed, evidence-valid Business Strategist run can be approved",
        ) from error
    return _approved_view(approved)
