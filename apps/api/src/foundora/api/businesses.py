from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.business.service import (
    BusinessNameConflict,
    BusinessNotFound,
    BusinessService,
    GoalNotFound,
    NoSelectedBusiness,
    Workspace,
)
from foundora.models import Business, BusinessGoal, BusinessPreference

router = APIRouter(tags=["business workspace"])
locale_pattern = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")

BusinessStatus = Literal["planning", "active", "paused"]
GoalStatus = Literal["active", "completed", "cancelled"]


def _clean(value: str) -> str:
    return " ".join(value.strip().split())


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class BusinessProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("business name cannot be blank")
        return cleaned

    @field_validator("summary")
    @classmethod
    def clean_summary(cls, value: str | None) -> str | None:
        return _optional_text(value)


class SelectBusinessRequest(BaseModel):
    business_id: UUID


class BusinessStatusRequest(BaseModel):
    status: BusinessStatus


class BusinessPreferencesRequest(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
    currency: str = Field(min_length=3, max_length=3)
    locale: str = Field(min_length=2, max_length=35)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        cleaned = value.strip()
        try:
            ZoneInfo(cleaned)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be a valid IANA identifier") from error
        return cleaned

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isascii() or not normalized.isalpha():
            raise ValueError("currency must be a three-letter ISO 4217 code")
        return normalized

    @field_validator("locale")
    @classmethod
    def valid_locale(cls, value: str) -> str:
        cleaned = value.strip()
        if locale_pattern.fullmatch(cleaned) is None:
            raise ValueError("locale must be a BCP 47 language tag")
        return cleaned


class GoalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    details: str | None = Field(default=None, max_length=2000)
    target_date: date | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("goal title cannot be blank")
        return cleaned

    @field_validator("details")
    @classmethod
    def clean_details(cls, value: str | None) -> str | None:
        return _optional_text(value)


class GoalStatusRequest(BaseModel):
    status: GoalStatus


class BusinessView(BaseModel):
    id: UUID
    name: str
    summary: str | None
    status: BusinessStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    selected: bool


class BusinessCollectionView(BaseModel):
    businesses: list[BusinessView]
    selected_business_id: UUID | None


class PreferenceView(BaseModel):
    timezone: str
    currency: str
    locale: str
    updated_at: datetime


class GoalView(BaseModel):
    id: UUID
    title: str
    details: str | None
    target_date: date | None
    status: GoalStatus
    created_at: datetime
    updated_at: datetime


class WorkspaceView(BaseModel):
    business: BusinessView
    preferences: PreferenceView
    goals: list[GoalView]


def _business_view(business: Business, selected_business_id: UUID | None = None) -> BusinessView:
    return BusinessView(
        id=business.id,
        name=business.name,
        summary=business.summary,
        status=business.status,  # type: ignore[arg-type]
        created_at=business.created_at,
        updated_at=business.updated_at,
        archived_at=business.archived_at,
        selected=business.id == selected_business_id,
    )


def _preference_view(preference: BusinessPreference) -> PreferenceView:
    return PreferenceView(
        timezone=preference.timezone,
        currency=preference.currency,
        locale=preference.locale,
        updated_at=preference.updated_at,
    )


def _goal_view(goal: BusinessGoal) -> GoalView:
    return GoalView(
        id=goal.id,
        title=goal.title,
        details=goal.details,
        target_date=goal.target_date,
        status=goal.status,  # type: ignore[arg-type]
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


def _workspace_view(workspace: Workspace) -> WorkspaceView:
    return WorkspaceView(
        business=_business_view(workspace.business, workspace.business.id),
        preferences=_preference_view(workspace.preferences),
        goals=[_goal_view(goal) for goal in workspace.goals],
    )


def _no_selected(error: NoSelectedBusiness) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="No active business is selected",
    )


@router.get("/businesses", response_model=BusinessCollectionView)
async def businesses(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> BusinessCollectionView:
    records = await BusinessService().list_businesses(context)
    selected_id = context.session.selected_business_id
    response.headers["Cache-Control"] = "no-store"
    return BusinessCollectionView(
        businesses=[_business_view(record, selected_id) for record in records],
        selected_business_id=selected_id,
    )


@router.post("/businesses", response_model=BusinessView, status_code=status.HTTP_201_CREATED)
async def create_business(
    payload: BusinessProfileRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> BusinessView:
    try:
        business = await BusinessService().create_business(
            context, name=payload.name, summary=payload.summary
        )
    except BusinessNameConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A business with this name already exists",
        ) from error
    selected_id = (
        business.id
        if context.session.selected_business_id is None
        else context.session.selected_business_id
    )
    return _business_view(business, selected_id)


@router.post("/businesses/select", response_model=BusinessView)
async def select_business(
    payload: SelectBusinessRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> BusinessView:
    try:
        business = await BusinessService().select_business(context, payload.business_id)
    except BusinessNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active business not found",
        ) from error
    return _business_view(business, business.id)


@router.get("/workspace", response_model=WorkspaceView)
async def workspace(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> WorkspaceView:
    try:
        record = await BusinessService().get_workspace(context)
    except NoSelectedBusiness as error:
        raise _no_selected(error) from error
    response.headers["Cache-Control"] = "no-store"
    return _workspace_view(record)


@router.post("/workspace/profile", response_model=BusinessView)
async def update_profile(
    payload: BusinessProfileRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> BusinessView:
    try:
        business = await BusinessService().update_profile(
            context, name=payload.name, summary=payload.summary
        )
    except NoSelectedBusiness as error:
        raise _no_selected(error) from error
    except BusinessNameConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A business with this name already exists",
        ) from error
    return _business_view(business, business.id)


@router.post("/workspace/status", response_model=BusinessView)
async def update_status(
    payload: BusinessStatusRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> BusinessView:
    try:
        business = await BusinessService().update_status(context, payload.status)
    except NoSelectedBusiness as error:
        raise _no_selected(error) from error
    return _business_view(business, business.id)


@router.post("/workspace/preferences", response_model=PreferenceView)
async def update_preferences(
    payload: BusinessPreferencesRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> PreferenceView:
    try:
        preference = await BusinessService().update_preferences(
            context,
            timezone=payload.timezone,
            currency=payload.currency,
            locale=payload.locale,
        )
    except NoSelectedBusiness as error:
        raise _no_selected(error) from error
    return _preference_view(preference)


@router.post("/workspace/goals", response_model=GoalView, status_code=status.HTTP_201_CREATED)
async def add_goal(
    payload: GoalRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> GoalView:
    try:
        goal = await BusinessService().add_goal(
            context,
            title=payload.title,
            details=payload.details,
            target_date=payload.target_date,
        )
    except NoSelectedBusiness as error:
        raise _no_selected(error) from error
    return _goal_view(goal)


@router.post("/workspace/goals/{goal_id}/status", response_model=GoalView)
async def update_goal_status(
    goal_id: UUID,
    payload: GoalStatusRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> GoalView:
    try:
        goal = await BusinessService().update_goal_status(context, goal_id, payload.status)
    except NoSelectedBusiness as error:
        raise _no_selected(error) from error
    except GoalNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found"
        ) from error
    return _goal_view(goal)


@router.post("/workspace/archive", response_model=BusinessView)
async def archive_business(
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> BusinessView:
    try:
        business = await BusinessService().archive_selected(context)
    except NoSelectedBusiness as error:
        raise _no_selected(error) from error
    return _business_view(business)
