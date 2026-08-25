from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.models import AgentRun, WebsiteSpecificationVersion
from foundora.website_specification.service import (
    WebsiteSpecificationApprovalConflict,
    WebsiteSpecificationRunInvalid,
    WebsiteSpecificationRunNotFound,
    WebsiteSpecificationService,
)

router = APIRouter(prefix="/website-specifications", tags=["website-specifications"])


class ApproveWebsiteSpecificationRequest(BaseModel):
    run_id: uuid.UUID
    expected_version: int = Field(ge=0)


class WebsiteSpecificationVersionView(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    version: int
    status: Literal["active", "superseded"]
    source_agent_run_id: uuid.UUID
    source_strategy_version: int
    source_product_offer_id: uuid.UUID
    source_product_offer_version: int
    source_brand_system_id: uuid.UUID
    source_brand_version: int
    context_id: str
    specification: dict[str, object]
    evidence_refs: dict[str, object]
    approved_by_owner_id: uuid.UUID
    approved_at: datetime
    superseded_at: datetime | None


class WebsiteSpecificationCandidateView(BaseModel):
    run_id: uuid.UUID
    context_id: str
    project_title: str
    source_strategy_version: int
    source_product_offer_version: int
    source_brand_version: int
    completed_at: datetime


class WebsiteSpecificationDashboardView(BaseModel):
    business_id: uuid.UUID
    current_version: int
    current: WebsiteSpecificationVersionView | None
    versions: list[WebsiteSpecificationVersionView]
    candidate_runs: list[WebsiteSpecificationCandidateView]


def _version_view(value: WebsiteSpecificationVersion) -> WebsiteSpecificationVersionView:
    return WebsiteSpecificationVersionView.model_validate(value, from_attributes=True)


def _candidate_view(value: AgentRun) -> WebsiteSpecificationCandidateView:
    output = value.structured_output or {}
    evidence = value.structured_input.get("website_specification_evidence")
    return WebsiteSpecificationCandidateView(
        run_id=value.id,
        context_id=str(value.structured_input.get("context_id", "")),
        project_title=str(output.get("project_title", "Untitled website specification")),
        source_strategy_version=(
            int(evidence.get("strategy_version", 0)) if isinstance(evidence, dict) else 0
        ),
        source_product_offer_version=(
            int(evidence.get("product_offer_version", 0)) if isinstance(evidence, dict) else 0
        ),
        source_brand_version=(
            int(evidence.get("brand_version", 0)) if isinstance(evidence, dict) else 0
        ),
        completed_at=value.completed_at or value.created_at,
    )


@router.get("", response_model=WebsiteSpecificationDashboardView)
async def website_specification_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> WebsiteSpecificationDashboardView:
    dashboard = await WebsiteSpecificationService().dashboard(context)
    response.headers["Cache-Control"] = "no-store"
    return WebsiteSpecificationDashboardView(
        business_id=dashboard.business_id,
        current_version=dashboard.current.version if dashboard.current is not None else 0,
        current=_version_view(dashboard.current) if dashboard.current is not None else None,
        versions=[_version_view(item) for item in dashboard.versions],
        candidate_runs=[_candidate_view(run) for run in dashboard.candidate_runs],
    )


@router.post("/approve", response_model=WebsiteSpecificationVersionView)
async def approve_website_specification(
    payload: ApproveWebsiteSpecificationRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> WebsiteSpecificationVersionView:
    try:
        approved = await WebsiteSpecificationService().approve(
            context, run_id=payload.run_id, expected_version=payload.expected_version
        )
    except WebsiteSpecificationRunNotFound as error:
        raise HTTPException(status_code=404, detail="Run not found") from error
    except WebsiteSpecificationApprovalConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Website specification changed or this run is already current",
        ) from error
    except WebsiteSpecificationRunInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Only a complete Website Specification proposal tied to the current "
                "approved strategy, offer, and brand can be approved"
            ),
        ) from error
    return _version_view(approved)
