from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, StringConstraints, field_validator

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.business.context import NoSelectedBusiness
from foundora.business.service import BusinessNameConflict
from foundora.models import ApprovedBusinessProfile, Business, BusinessOnboardingDraft
from foundora.onboarding.service import (
    OnboardingIncomplete,
    OnboardingRevisionConflict,
    OnboardingService,
    OnboardingState,
    OnboardingStateConflict,
)

router = APIRouter(prefix="/onboarding", tags=["business onboarding"])

OnboardingStatus = Literal["draft", "review", "approved"]
BusinessType = Literal["idea", "existing"]
ListItem = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


def _one_line(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise ValueError("value cannot be blank")
    return cleaned


def _text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("value cannot be blank")
    return cleaned


def _deduplicated(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


class RevisionRequest(BaseModel):
    revision: int = Field(ge=0)


class FoundationRequest(RevisionRequest):
    business_type: BusinessType
    business_name: str = Field(min_length=1, max_length=120)
    industry: str = Field(min_length=1, max_length=160)
    geography: str = Field(min_length=1, max_length=240)

    @field_validator("business_name", "industry", "geography")
    @classmethod
    def clean_one_line(cls, value: str) -> str:
        return _one_line(value)


class MarketRequest(RevisionRequest):
    problem: str = Field(min_length=1, max_length=4000)
    target_audience: str = Field(min_length=1, max_length=4000)
    offer: str = Field(min_length=1, max_length=4000)

    @field_validator("problem", "target_audience", "offer")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return _text(value)


class ExecutionRequest(RevisionRequest):
    goals: list[ListItem] = Field(min_length=1, max_length=25)
    existing_assets: list[ListItem] = Field(default_factory=list, max_length=50)
    constraints: list[ListItem] = Field(default_factory=list, max_length=50)
    budget: str = Field(min_length=1, max_length=2000)

    @field_validator("goals", "existing_assets", "constraints")
    @classmethod
    def unique_items(cls, value: list[str]) -> list[str]:
        return _deduplicated(value)

    @field_validator("budget")
    @classmethod
    def clean_budget(cls, value: str) -> str:
        return _text(value)


class BrandServicesRequest(RevisionRequest):
    brand_preferences: str = Field(min_length=1, max_length=4000)
    connected_services: list[ListItem] = Field(default_factory=list, max_length=50)

    @field_validator("brand_preferences")
    @classmethod
    def clean_brand_preferences(cls, value: str) -> str:
        return _text(value)

    @field_validator("connected_services")
    @classmethod
    def unique_services(cls, value: list[str]) -> list[str]:
        return _deduplicated(value)


class OnboardingDraftView(BaseModel):
    status: OnboardingStatus
    current_step: int
    revision: int
    business_type: BusinessType | None
    business_name: str | None
    industry: str | None
    geography: str | None
    problem: str | None
    target_audience: str | None
    offer: str | None
    goals: list[str]
    existing_assets: list[str]
    constraints: list[str]
    budget: str | None
    brand_preferences: str | None
    connected_services: list[str]
    updated_at: datetime | None
    submitted_at: datetime | None


class ApprovedProfileView(BaseModel):
    version: int
    business_type: BusinessType
    business_name: str
    industry: str
    geography: str
    problem: str
    target_audience: str
    offer: str
    goals: list[str]
    existing_assets: list[str]
    constraints: list[str]
    budget: str
    brand_preferences: str
    connected_services: list[str]
    approved_at: datetime


class OnboardingView(BaseModel):
    business_id: str
    draft: OnboardingDraftView
    approved_profile: ApprovedProfileView | None


def _draft_view(draft: BusinessOnboardingDraft | None, business: Business) -> OnboardingDraftView:
    if draft is None:
        return OnboardingDraftView(
            status="draft",
            current_step=1,
            revision=0,
            business_type=None,
            business_name=business.name,
            industry=None,
            geography=None,
            problem=None,
            target_audience=None,
            offer=None,
            goals=[],
            existing_assets=[],
            constraints=[],
            budget=None,
            brand_preferences=None,
            connected_services=[],
            updated_at=None,
            submitted_at=None,
        )
    return _existing_draft_view(draft)


def _existing_draft_view(draft: BusinessOnboardingDraft) -> OnboardingDraftView:
    return OnboardingDraftView(
        status=draft.status,  # type: ignore[arg-type]
        current_step=draft.current_step,
        revision=draft.revision,
        business_type=draft.business_type,  # type: ignore[arg-type]
        business_name=draft.business_name,
        industry=draft.industry,
        geography=draft.geography,
        problem=draft.problem,
        target_audience=draft.target_audience,
        offer=draft.offer,
        goals=list(draft.goals or []),
        existing_assets=list(draft.existing_assets or []),
        constraints=list(draft.constraints or []),
        budget=draft.budget,
        brand_preferences=draft.brand_preferences,
        connected_services=list(draft.connected_services or []),
        updated_at=draft.updated_at,
        submitted_at=draft.submitted_at,
    )


def _profile_view(profile: ApprovedBusinessProfile) -> ApprovedProfileView:
    return ApprovedProfileView(
        version=profile.version,
        business_type=profile.business_type,  # type: ignore[arg-type]
        business_name=profile.business_name,
        industry=profile.industry,
        geography=profile.geography,
        problem=profile.problem,
        target_audience=profile.target_audience,
        offer=profile.offer,
        goals=list(profile.goals),
        existing_assets=list(profile.existing_assets),
        constraints=list(profile.constraints),
        budget=profile.budget,
        brand_preferences=profile.brand_preferences,
        connected_services=list(profile.connected_services),
        approved_at=profile.approved_at,
    )


def _state_view(state: OnboardingState) -> OnboardingView:
    return OnboardingView(
        business_id=str(state.business.id),
        draft=_draft_view(state.draft, state.business),
        approved_profile=(
            _profile_view(state.approved_profile) if state.approved_profile is not None else None
        ),
    )


def _conflict(error: Exception) -> HTTPException:
    if isinstance(error, OnboardingRevisionConflict):
        detail = "The onboarding draft changed in another request; reload before saving"
    else:
        detail = "The onboarding draft is not editable in its current state"
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _incomplete(error: OnboardingIncomplete) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "message": "Onboarding is incomplete",
            "missing_fields": error.missing_fields,
        },
    )


@router.get("", response_model=OnboardingView)
async def onboarding(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> OnboardingView:
    try:
        state = await OnboardingService().get_state(context)
    except NoSelectedBusiness as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active business is selected",
        ) from error
    response.headers["Cache-Control"] = "no-store"
    return _state_view(state)


@router.post("/steps/foundation", response_model=OnboardingDraftView)
async def save_foundation(
    payload: FoundationRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> OnboardingDraftView:
    try:
        draft = await OnboardingService().save_foundation(
            context,
            expected_revision=payload.revision,
            business_type=payload.business_type,
            business_name=payload.business_name,
            industry=payload.industry,
            geography=payload.geography,
        )
    except (OnboardingRevisionConflict, OnboardingStateConflict) as error:
        raise _conflict(error) from error
    return _existing_draft_view(draft)


@router.post("/steps/market", response_model=OnboardingDraftView)
async def save_market(
    payload: MarketRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> OnboardingDraftView:
    try:
        draft = await OnboardingService().save_market(
            context,
            expected_revision=payload.revision,
            problem=payload.problem,
            target_audience=payload.target_audience,
            offer=payload.offer,
        )
    except (OnboardingRevisionConflict, OnboardingStateConflict) as error:
        raise _conflict(error) from error
    return _existing_draft_view(draft)


@router.post("/steps/execution", response_model=OnboardingDraftView)
async def save_execution(
    payload: ExecutionRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> OnboardingDraftView:
    try:
        draft = await OnboardingService().save_execution(
            context,
            expected_revision=payload.revision,
            goals=payload.goals,
            existing_assets=payload.existing_assets,
            constraints=payload.constraints,
            budget=payload.budget,
        )
    except (OnboardingRevisionConflict, OnboardingStateConflict) as error:
        raise _conflict(error) from error
    return _existing_draft_view(draft)


@router.post("/steps/brand-services", response_model=OnboardingDraftView)
async def save_brand_services(
    payload: BrandServicesRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> OnboardingDraftView:
    try:
        draft = await OnboardingService().save_brand_and_services(
            context,
            expected_revision=payload.revision,
            brand_preferences=payload.brand_preferences,
            connected_services=payload.connected_services,
        )
    except (OnboardingRevisionConflict, OnboardingStateConflict) as error:
        raise _conflict(error) from error
    return _existing_draft_view(draft)


@router.post("/submit", response_model=OnboardingDraftView)
async def submit_onboarding(
    payload: RevisionRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> OnboardingDraftView:
    try:
        draft = await OnboardingService().submit_for_review(
            context, expected_revision=payload.revision
        )
    except OnboardingIncomplete as error:
        raise _incomplete(error) from error
    except (OnboardingRevisionConflict, OnboardingStateConflict) as error:
        raise _conflict(error) from error
    return _existing_draft_view(draft)


@router.post("/approve", response_model=ApprovedProfileView)
async def approve_onboarding(
    payload: RevisionRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> ApprovedProfileView:
    try:
        profile = await OnboardingService().approve(context, expected_revision=payload.revision)
    except OnboardingIncomplete as error:
        raise _incomplete(error) from error
    except (OnboardingRevisionConflict, OnboardingStateConflict) as error:
        raise _conflict(error) from error
    except BusinessNameConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another business already uses this name",
        ) from error
    return _profile_view(profile)


@router.post("/reopen", response_model=OnboardingDraftView)
async def reopen_onboarding(
    payload: RevisionRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> OnboardingDraftView:
    try:
        draft = await OnboardingService().reopen(context, expected_revision=payload.revision)
    except (OnboardingRevisionConflict, OnboardingStateConflict) as error:
        raise _conflict(error) from error
    return _existing_draft_view(draft)
