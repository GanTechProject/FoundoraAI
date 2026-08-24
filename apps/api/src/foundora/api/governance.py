from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.governance.registry import (
    ACTION_CATALOG,
    TOOL_CATALOG,
    GovernanceClassificationError,
)
from foundora.governance.service import (
    ActionRecord,
    GovernanceConflict,
    GovernanceDashboard,
    GovernanceDenied,
    GovernanceNotFound,
    GovernanceService,
)
from foundora.models import GlobalGovernanceControl, GovernanceSetting

router = APIRouter(prefix="/governance", tags=["policy, risk, and approvals"])
ActionType = Literal[
    "internal.analysis",
    "internal.content.create",
    "external.reversible",
    "external.communication",
    "external.publication",
    "financial.spend",
    "destructive.delete",
    "privileged.configuration",
    "security.bypass",
]
AutonomyLevel = Literal["OFF", "RECOMMEND", "ASSISTED", "AUTONOMOUS_LOW_RISK"]


class EvaluateActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    tool_id: str | None = Field(default=None, min_length=1, max_length=160)
    execution_mode: Literal["manual", "autonomous"] = "manual"
    data_classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    requested_spend_microusd: int = Field(default=0, ge=0, le=1_000_000_000_000)
    frequency_key: str | None = Field(default=None, min_length=1, max_length=160)
    target: str | None = Field(default=None, min_length=1, max_length=300)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")

    @model_validator(mode="after")
    def validate_tool(self) -> EvaluateActionRequest:
        if self.tool_id is not None and self.tool_id not in TOOL_CATALOG:
            raise ValueError("Tool is not in the code-reviewed catalog")
        return self


class DecideApprovalRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class AuthorizeActionRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class UpdateSettingsRequest(BaseModel):
    autonomy_level: AutonomyLevel
    daily_spend_limit_microusd: int = Field(ge=0, le=1_000_000_000_000)
    per_action_spend_limit_microusd: int = Field(ge=0, le=1_000_000_000_000)
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def action_limit_within_daily_limit(self) -> UpdateSettingsRequest:
        if self.per_action_spend_limit_microusd > self.daily_spend_limit_microusd:
            raise ValueError("Per-action spend limit cannot exceed the daily limit")
        return self


class UpdateToolPermissionRequest(BaseModel):
    enabled: bool
    revision: int = Field(ge=1)


class UpdateKillSwitchRequest(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=500)
    revision: int = Field(ge=1)


class PolicyView(BaseModel):
    policy_id: str
    display_name: str
    version_id: UUID
    version: int
    description: str
    rules: dict[str, object]


class GlobalControlsView(BaseModel):
    kill_switch_enabled: bool
    reason: str | None
    revision: int
    updated_at: datetime


class GovernanceSettingsView(BaseModel):
    autonomy_level: AutonomyLevel
    daily_spend_limit_microusd: int
    per_action_spend_limit_microusd: int
    authorized_spend_today_microusd: int
    revision: int
    updated_at: datetime


class ToolPermissionView(BaseModel):
    tool_id: str
    display_name: str
    risk_class: Literal["R0", "R1", "R2", "R3", "R4", "R5"]
    internal: bool
    enabled: bool
    revision: int
    updated_at: datetime


class ActionCatalogView(BaseModel):
    action_type: str
    display_name: str
    risk_class: Literal["R0", "R1", "R2", "R3", "R4", "R5"]
    description: str


class ApprovalView(BaseModel):
    id: UUID
    status: Literal["pending", "approved", "rejected", "cancelled"]
    prompt: str
    decision_reason: str | None
    requested_at: datetime
    decided_at: datetime | None


class GovernanceActionView(BaseModel):
    id: UUID
    business_id: UUID
    policy_version_id: UUID
    workflow_run_id: UUID | None
    workflow_step_key: str | None
    action_type: str
    actor_type: Literal["owner", "agent", "workflow", "system"]
    actor_id: str | None
    tool_id: str | None
    risk_class: Literal["R0", "R1", "R2", "R3", "R4", "R5"]
    execution_mode: Literal["manual", "autonomous"]
    data_classification: Literal["public", "internal", "confidential", "restricted"]
    requested_spend_microusd: int
    frequency_key: str | None
    target: str | None
    status: Literal["approval_required", "approved", "rejected", "authorized", "denied", "blocked"]
    rationale: str
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    authorized_at: datetime | None
    approval: ApprovalView | None


class AuditEventView(BaseModel):
    id: UUID
    business_id: UUID | None
    action_id: UUID | None
    approval_request_id: UUID | None
    event_type: str
    idempotency_key: str | None
    details: dict[str, object]
    created_at: datetime


class GovernanceDashboardView(BaseModel):
    business_id: UUID
    policy: PolicyView
    controls: GlobalControlsView
    settings: GovernanceSettingsView
    action_catalog: list[ActionCatalogView]
    tool_permissions: list[ToolPermissionView]
    actions: list[GovernanceActionView]
    audit_events: list[AuditEventView]


def _approval_view(record: ActionRecord) -> ApprovalView | None:
    approval = record.approval
    if approval is None:
        return None
    return ApprovalView(
        id=approval.id,
        status=approval.status,  # type: ignore[arg-type]
        prompt=approval.prompt,
        decision_reason=approval.decision_reason,
        requested_at=approval.requested_at,
        decided_at=approval.decided_at,
    )


def _action_view(record: ActionRecord) -> GovernanceActionView:
    action = record.action
    return GovernanceActionView(
        id=action.id,
        business_id=action.business_id,
        policy_version_id=action.policy_version_id,
        workflow_run_id=action.workflow_run_id,
        workflow_step_key=action.workflow_step_key,
        action_type=action.action_type,
        actor_type=action.actor_type,  # type: ignore[arg-type]
        actor_id=action.actor_id,
        tool_id=action.tool_id,
        risk_class=action.risk_class,  # type: ignore[arg-type]
        execution_mode=action.execution_mode,  # type: ignore[arg-type]
        data_classification=action.data_classification,  # type: ignore[arg-type]
        requested_spend_microusd=action.requested_spend_microusd,
        frequency_key=action.frequency_key,
        target=action.target,
        status=action.status,  # type: ignore[arg-type]
        rationale=action.rationale,
        idempotency_key=action.idempotency_key,
        created_at=action.created_at,
        updated_at=action.updated_at,
        authorized_at=action.authorized_at,
        approval=_approval_view(record),
    )


def _controls_view(controls: GlobalGovernanceControl) -> GlobalControlsView:
    return GlobalControlsView(
        kill_switch_enabled=controls.kill_switch_enabled,
        reason=controls.reason,
        revision=controls.revision,
        updated_at=controls.updated_at,
    )


def _settings_view(
    settings: GovernanceSetting, authorized_spend_today_microusd: int
) -> GovernanceSettingsView:
    return GovernanceSettingsView(
        autonomy_level=settings.autonomy_level,  # type: ignore[arg-type]
        daily_spend_limit_microusd=settings.daily_spend_limit_microusd,
        per_action_spend_limit_microusd=settings.per_action_spend_limit_microusd,
        authorized_spend_today_microusd=authorized_spend_today_microusd,
        revision=settings.revision,
        updated_at=settings.updated_at,
    )


def _dashboard_view(dashboard: GovernanceDashboard) -> GovernanceDashboardView:
    return GovernanceDashboardView(
        business_id=dashboard.business_id,
        policy=PolicyView(
            policy_id=dashboard.policy.id,
            display_name=dashboard.policy.display_name,
            version_id=dashboard.policy_version.id,
            version=dashboard.policy_version.version,
            description=dashboard.policy_version.description,
            rules=dashboard.policy_version.rules,
        ),
        controls=_controls_view(dashboard.controls),
        settings=_settings_view(dashboard.settings, dashboard.authorized_spend_today_microusd),
        action_catalog=[
            ActionCatalogView(
                action_type=item.action_type,
                display_name=item.display_name,
                risk_class=item.risk_class,  # type: ignore[arg-type]
                description=item.description,
            )
            for item in ACTION_CATALOG.values()
            if item.action_type != "workflow.checkpoint"
        ],
        tool_permissions=[
            ToolPermissionView(
                tool_id=permission.tool_id,
                display_name=TOOL_CATALOG[permission.tool_id].display_name,
                risk_class=TOOL_CATALOG[permission.tool_id].risk_class,  # type: ignore[arg-type]
                internal=TOOL_CATALOG[permission.tool_id].internal,
                enabled=permission.enabled,
                revision=permission.revision,
                updated_at=permission.updated_at,
            )
            for permission in dashboard.tool_permissions
        ],
        actions=[_action_view(item) for item in dashboard.actions],
        audit_events=[
            AuditEventView(
                id=event.id,
                business_id=event.business_id,
                action_id=event.action_id,
                approval_request_id=event.approval_request_id,
                event_type=event.event_type,
                idempotency_key=event.idempotency_key,
                details=event.details,
                created_at=event.created_at,
            )
            for event in dashboard.audit_events
        ],
    )


def _handle(error: Exception) -> HTTPException:
    if isinstance(error, GovernanceNotFound):
        return HTTPException(status_code=404, detail="Governance record not found")
    if isinstance(error, GovernanceConflict):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, GovernanceDenied):
        return HTTPException(status_code=403, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


@router.get("", response_model=GovernanceDashboardView)
async def governance_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> GovernanceDashboardView:
    response.headers["Cache-Control"] = "no-store"
    return _dashboard_view(await GovernanceService().dashboard(context))


@router.post(
    "/actions/evaluate",
    response_model=GovernanceActionView,
    status_code=status.HTTP_201_CREATED,
)
async def evaluate_action(
    payload: EvaluateActionRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> GovernanceActionView:
    try:
        record = await GovernanceService().evaluate(
            context,
            action_type=payload.action_type,
            actor_type="owner",
            actor_id=None,
            tool_id=payload.tool_id,
            execution_mode=payload.execution_mode,
            data_classification=payload.data_classification,
            requested_spend_microusd=payload.requested_spend_microusd,
            frequency_key=payload.frequency_key,
            target=payload.target,
            idempotency_key=payload.idempotency_key,
        )
    except (GovernanceClassificationError, GovernanceConflict, GovernanceDenied) as error:
        raise _handle(error) from error
    return _action_view(record)


@router.post("/approvals/{approval_id}/decide", response_model=GovernanceActionView)
async def decide_approval(
    approval_id: UUID,
    payload: DecideApprovalRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> GovernanceActionView:
    try:
        record = await GovernanceService().decide(
            context,
            approval_id,
            decision=payload.decision,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
        )
    except (GovernanceNotFound, GovernanceConflict) as error:
        raise _handle(error) from error
    return _action_view(record)


@router.post("/actions/{action_id}/authorize", response_model=GovernanceActionView)
async def authorize_action(
    action_id: UUID,
    payload: AuthorizeActionRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> GovernanceActionView:
    try:
        record = await GovernanceService().authorize(
            context, action_id, idempotency_key=payload.idempotency_key
        )
    except GovernanceNotFound as error:
        raise _handle(error) from error
    if record.action.status != "authorized":
        raise HTTPException(status_code=403, detail=record.action.rationale)
    return _action_view(record)


@router.post("/settings", response_model=GovernanceSettingsView)
async def update_governance_settings(
    payload: UpdateSettingsRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> GovernanceSettingsView:
    try:
        service = GovernanceService()
        await service.update_settings(
            context,
            autonomy_level=payload.autonomy_level,
            daily_spend_limit_microusd=payload.daily_spend_limit_microusd,
            per_action_spend_limit_microusd=payload.per_action_spend_limit_microusd,
            revision=payload.revision,
        )
    except GovernanceConflict as error:
        raise _handle(error) from error
    dashboard = await service.dashboard(context)
    return _settings_view(dashboard.settings, dashboard.authorized_spend_today_microusd)


@router.post("/tools/{tool_id}/permission", response_model=ToolPermissionView)
async def update_tool_permission(
    tool_id: str,
    payload: UpdateToolPermissionRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> ToolPermissionView:
    try:
        permission = await GovernanceService().set_tool_permission(
            context, tool_id, enabled=payload.enabled, revision=payload.revision
        )
    except (GovernanceNotFound, GovernanceConflict) as error:
        raise _handle(error) from error
    descriptor = TOOL_CATALOG[permission.tool_id]
    return ToolPermissionView(
        tool_id=permission.tool_id,
        display_name=descriptor.display_name,
        risk_class=descriptor.risk_class,  # type: ignore[arg-type]
        internal=descriptor.internal,
        enabled=permission.enabled,
        revision=permission.revision,
        updated_at=permission.updated_at,
    )


@router.post("/kill-switch", response_model=GlobalControlsView)
async def update_kill_switch(
    payload: UpdateKillSwitchRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> GlobalControlsView:
    try:
        controls = await GovernanceService().set_kill_switch(
            context,
            enabled=payload.enabled,
            reason=payload.reason,
            revision=payload.revision,
        )
    except (GovernanceNotFound, GovernanceConflict) as error:
        raise _handle(error) from error
    return _controls_view(controls)
