from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator

from foundora.agents.service import (
    AgentQueueUnavailable,
    AgentRunRecord,
    AgentService,
    SkillNotAssigned,
    WebsiteCodingEvidenceInvalid,
)
from foundora.agents.website_coding import WEBSITE_BUILD_SKILL_ID, WEBSITE_CODING_AGENT_ID
from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.models import AgentRun, WebsiteProjectVersion, WebsiteSpecificationVersion
from foundora.website_projects.service import WebsiteProjectDashboard, WebsiteProjectService

router = APIRouter(prefix="/website-projects", tags=["website projects"])


class WebsiteProjectRunRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=500)
    operation: Literal["generate", "modify"]
    base_project_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_base(self) -> WebsiteProjectRunRequest:
        if self.operation == "modify" and self.base_project_version is None:
            raise ValueError("Modification requires a base project version")
        if self.operation == "generate" and self.base_project_version is not None:
            raise ValueError("Generation cannot include a base project version")
        self.objective = " ".join(self.objective.strip().split())
        if not self.objective:
            raise ValueError("Objective cannot be blank")
        return self


class WebsiteSpecificationReferenceView(BaseModel):
    id: uuid.UUID
    version: int
    approved_at: datetime


class WebsiteProjectView(BaseModel):
    id: uuid.UUID
    version: int
    status: Literal["active", "superseded"]
    operation: Literal["generate", "modify"]
    source_agent_run_id: uuid.UUID
    source_website_specification_id: uuid.UUID
    source_website_specification_version: int
    base_project_id: uuid.UUID | None
    base_project_version: int | None
    context_id: str
    source_files: list[dict[str, object]]
    dependency_manifest: dict[str, object]
    source_digest: str
    build_digest: str
    build_manifest: list[dict[str, object]]
    build_report: dict[str, object]
    check_report: dict[str, object]
    tool_audit: list[dict[str, object]]
    source_is_current: bool
    created_at: datetime
    superseded_at: datetime | None


class WebsiteCodingRunView(BaseModel):
    id: uuid.UUID
    status: str
    error_type: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class WebsiteProjectDashboardView(BaseModel):
    business_id: uuid.UUID
    current_specification: WebsiteSpecificationReferenceView | None
    current_project: WebsiteProjectView | None
    history: list[WebsiteProjectView]
    recent_runs: list[WebsiteCodingRunView]
    next_operation: Literal["generate", "modify"] | None
    blocker: str | None


def _specification_view(
    value: WebsiteSpecificationVersion | None,
) -> WebsiteSpecificationReferenceView | None:
    if value is None:
        return None
    return WebsiteSpecificationReferenceView(
        id=value.id, version=value.version, approved_at=value.approved_at
    )


def _project_view(
    value: WebsiteProjectVersion, specification: WebsiteSpecificationVersion | None
) -> WebsiteProjectView:
    return WebsiteProjectView(
        id=value.id,
        version=value.version,
        status=value.status,  # type: ignore[arg-type]
        operation=value.operation,  # type: ignore[arg-type]
        source_agent_run_id=value.source_agent_run_id,
        source_website_specification_id=value.source_website_specification_id,
        source_website_specification_version=value.source_website_specification_version,
        base_project_id=value.base_project_id,
        base_project_version=value.base_project_version,
        context_id=value.context_id,
        source_files=value.source_files,
        dependency_manifest=value.dependency_manifest,
        source_digest=value.source_digest,
        build_digest=value.build_digest,
        build_manifest=value.build_manifest,
        build_report=value.build_report,
        check_report=value.check_report,
        tool_audit=value.tool_audit,
        source_is_current=(
            specification is not None
            and value.source_website_specification_id == specification.id
            and value.source_website_specification_version == specification.version
        ),
        created_at=value.created_at,
        superseded_at=value.superseded_at,
    )


def _run_view(value: AgentRun) -> WebsiteCodingRunView:
    return WebsiteCodingRunView(
        id=value.id,
        status=value.status,
        error_type=value.error_type,
        error_message=value.error_message,
        created_at=value.created_at,
        completed_at=value.completed_at,
    )


def _dashboard_view(value: WebsiteProjectDashboard) -> WebsiteProjectDashboardView:
    specification = value.current_specification
    return WebsiteProjectDashboardView(
        business_id=value.business_id,
        current_specification=_specification_view(specification),
        current_project=(
            _project_view(value.current_project, specification)
            if value.current_project is not None
            else None
        ),
        history=[_project_view(item, specification) for item in value.history],
        recent_runs=[_run_view(item) for item in value.recent_runs],
        next_operation=value.next_operation,  # type: ignore[arg-type]
        blocker=value.blocker,
    )


@router.get("", response_model=WebsiteProjectDashboardView)
async def website_project_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)],
    response: Response,
) -> WebsiteProjectDashboardView:
    response.headers["Cache-Control"] = "no-store"
    return _dashboard_view(await WebsiteProjectService().dashboard(context))


@router.post(
    "/runs",
    response_model=WebsiteCodingRunView,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_csrf)],
)
async def start_website_project_run(
    payload: WebsiteProjectRunRequest,
    context: Annotated[AuthContext, Depends(require_auth)],
) -> WebsiteCodingRunView:
    skill_input: dict[str, object] = {"operation": payload.operation}
    if payload.base_project_version is not None:
        skill_input["base_project_version"] = payload.base_project_version
    try:
        record: AgentRunRecord = await AgentService().create_run(
            context,
            WEBSITE_CODING_AGENT_ID,
            payload.objective,
            skill_id=WEBSITE_BUILD_SKILL_ID,
            skill_input=skill_input,
        )
    except (SkillNotAssigned, WebsiteCodingEvidenceInvalid) as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The approved specification or exact modification base is unavailable",
        ) from error
    except AgentQueueUnavailable as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "queue_unavailable", "run_id": str(error.run_id)},
        ) from error
    return _run_view(record.run)
