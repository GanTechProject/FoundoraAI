from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.brand.service import (
    BrandApprovalConflict,
    BrandRunInvalid,
    BrandRunNotFound,
    BrandService,
)
from foundora.models import AgentRun, BrandSystemVersion

router = APIRouter(prefix="/brand", tags=["brand"])


class ApproveBrandRequest(BaseModel):
    run_id: uuid.UUID
    expected_version: int = Field(ge=0)


class BrandSystemVersionView(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    version: int
    status: Literal["active", "superseded"]
    source_agent_run_id: uuid.UUID
    source_strategy_version: int
    source_product_offer_id: uuid.UUID
    source_product_offer_version: int
    context_id: str
    brand_system: dict[str, object]
    evidence_refs: dict[str, object]
    approved_by_owner_id: uuid.UUID
    approved_at: datetime
    superseded_at: datetime | None


class BrandCandidateView(BaseModel):
    run_id: uuid.UUID
    context_id: str
    brand_title: str
    source_strategy_version: int
    source_product_offer_version: int
    completed_at: datetime


class BrandDashboardView(BaseModel):
    business_id: uuid.UUID
    current_version: int
    current: BrandSystemVersionView | None
    versions: list[BrandSystemVersionView]
    candidate_runs: list[BrandCandidateView]


def _version_view(value: BrandSystemVersion) -> BrandSystemVersionView:
    return BrandSystemVersionView.model_validate(value, from_attributes=True)


def _candidate_view(value: AgentRun) -> BrandCandidateView:
    output = value.structured_output or {}
    evidence = value.structured_input.get("brand_evidence")
    return BrandCandidateView(
        run_id=value.id,
        context_id=str(value.structured_input.get("context_id", "")),
        brand_title=str(output.get("brand_title", "Untitled brand system")),
        source_strategy_version=(
            int(evidence.get("strategy_version", 0)) if isinstance(evidence, dict) else 0
        ),
        source_product_offer_version=(
            int(evidence.get("product_offer_version", 0)) if isinstance(evidence, dict) else 0
        ),
        completed_at=value.completed_at or value.created_at,
    )


@router.get("", response_model=BrandDashboardView)
async def brand_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> BrandDashboardView:
    dashboard = await BrandService().dashboard(context)
    response.headers["Cache-Control"] = "no-store"
    return BrandDashboardView(
        business_id=dashboard.business_id,
        current_version=dashboard.current.version if dashboard.current is not None else 0,
        current=_version_view(dashboard.current) if dashboard.current is not None else None,
        versions=[_version_view(item) for item in dashboard.versions],
        candidate_runs=[_candidate_view(run) for run in dashboard.candidate_runs],
    )


@router.post("/approve", response_model=BrandSystemVersionView)
async def approve_brand(
    payload: ApproveBrandRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> BrandSystemVersionView:
    try:
        approved = await BrandService().approve(
            context, run_id=payload.run_id, expected_version=payload.expected_version
        )
    except BrandRunNotFound as error:
        raise HTTPException(status_code=404, detail="Run not found") from error
    except BrandApprovalConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Brand version changed or this run is already current",
        ) from error
    except BrandRunInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Only a completed Brand Strategist proposal tied to the current approved "
                "strategy and active product offer can be approved"
            ),
        ) from error
    return _version_view(approved)
