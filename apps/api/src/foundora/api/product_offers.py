from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.models import AgentRun, ProductOfferVersion
from foundora.product_offers.service import (
    ProductOfferApprovalConflict,
    ProductOfferRunInvalid,
    ProductOfferRunNotFound,
    ProductOfferService,
)

router = APIRouter(prefix="/products-offers", tags=["products-offers"])


class ApproveProductOfferRequest(BaseModel):
    run_id: uuid.UUID
    expected_version: int = Field(ge=0)


class ProductOfferVersionView(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    version: int
    status: Literal["active", "superseded"]
    source_agent_run_id: uuid.UUID
    source_strategy_version: int
    context_id: str
    portfolio: dict[str, object]
    evidence_refs: dict[str, object]
    approved_by_owner_id: uuid.UUID
    approved_at: datetime
    superseded_at: datetime | None


class ProductOfferCandidateView(BaseModel):
    run_id: uuid.UUID
    context_id: str
    portfolio_name: str
    source_strategy_version: int
    completed_at: datetime


class ProductOfferDashboardView(BaseModel):
    business_id: uuid.UUID
    current_version: int
    current: ProductOfferVersionView | None
    versions: list[ProductOfferVersionView]
    candidate_runs: list[ProductOfferCandidateView]


def _version_view(value: ProductOfferVersion) -> ProductOfferVersionView:
    return ProductOfferVersionView.model_validate(value, from_attributes=True)


def _candidate_view(value: AgentRun) -> ProductOfferCandidateView:
    output = value.structured_output or {}
    evidence = value.structured_input.get("offer_evidence")
    return ProductOfferCandidateView(
        run_id=value.id,
        context_id=str(value.structured_input.get("context_id", "")),
        portfolio_name=str(output.get("portfolio_name", "Untitled portfolio")),
        source_strategy_version=(
            int(evidence.get("strategy_version", 0)) if isinstance(evidence, dict) else 0
        ),
        completed_at=value.completed_at or value.created_at,
    )


@router.get("", response_model=ProductOfferDashboardView)
async def product_offer_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> ProductOfferDashboardView:
    dashboard = await ProductOfferService().dashboard(context)
    response.headers["Cache-Control"] = "no-store"
    return ProductOfferDashboardView(
        business_id=dashboard.business_id,
        current_version=dashboard.current.version if dashboard.current is not None else 0,
        current=_version_view(dashboard.current) if dashboard.current is not None else None,
        versions=[_version_view(item) for item in dashboard.versions],
        candidate_runs=[_candidate_view(run) for run in dashboard.candidate_runs],
    )


@router.post("/approve", response_model=ProductOfferVersionView)
async def approve_product_offer(
    payload: ApproveProductOfferRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> ProductOfferVersionView:
    try:
        approved = await ProductOfferService().approve(
            context, run_id=payload.run_id, expected_version=payload.expected_version
        )
    except ProductOfferRunNotFound as error:
        raise HTTPException(status_code=404, detail="Run not found") from error
    except ProductOfferApprovalConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Portfolio version changed or this run is already current",
        ) from error
    except ProductOfferRunInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Only a completed Product & Offer proposal tied to the current approved "
                "strategy can be approved"
            ),
        ) from error
    return _version_view(approved)
