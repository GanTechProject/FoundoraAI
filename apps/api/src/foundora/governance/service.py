from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.governance.registry import (
    ACTION_CATALOG,
    RISK_RANK,
    TOOL_CATALOG,
    GovernanceClassificationError,
    classify_action,
)
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    ApprovalRequest,
    GlobalGovernanceControl,
    GovernanceAction,
    GovernanceAuditEvent,
    GovernanceSetting,
    GovernanceToolPermission,
    Policy,
    PolicyVersion,
)

AutonomyLevel = Literal["OFF", "RECOMMEND", "ASSISTED", "AUTONOMOUS_LOW_RISK"]
Decision = Literal["approved", "rejected"]
POLICY_ID = "foundora-default-governance"


class GovernanceNotFound(Exception):
    pass


class GovernanceConflict(Exception):
    pass


class GovernanceDenied(Exception):
    pass


@dataclass(frozen=True)
class ActionRecord:
    action: GovernanceAction
    approval: ApprovalRequest | None


@dataclass(frozen=True)
class GovernanceDashboard:
    business_id: uuid.UUID
    policy: Policy
    policy_version: PolicyVersion
    controls: GlobalGovernanceControl
    settings: GovernanceSetting
    tool_permissions: list[GovernanceToolPermission]
    actions: list[ActionRecord]
    audit_events: list[GovernanceAuditEvent]
    authorized_spend_today_microusd: int


def _now() -> datetime:
    return datetime.now(UTC)


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def _add_audit(
    database: AsyncSession,
    event_type: str,
    *,
    business_id: uuid.UUID | None,
    action_id: uuid.UUID | None = None,
    approval_request_id: uuid.UUID | None = None,
    actor_owner_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    details: dict[str, object] | None = None,
) -> GovernanceAuditEvent:
    event = GovernanceAuditEvent(
        id=uuid.uuid4(),
        business_id=business_id,
        action_id=action_id,
        approval_request_id=approval_request_id,
        event_type=event_type,
        actor_owner_id=actor_owner_id,
        idempotency_key=idempotency_key,
        details=details or {},
        created_at=_now(),
    )
    database.add(event)
    await database.flush()
    return event


class GovernanceService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def _policy(self, database: AsyncSession) -> tuple[Policy, PolicyVersion]:
        row = (
            await database.execute(
                select(Policy, PolicyVersion)
                .join(
                    PolicyVersion,
                    and_(
                        PolicyVersion.policy_id == Policy.id,
                        PolicyVersion.version == Policy.current_version,
                    ),
                )
                .where(Policy.id == POLICY_ID, Policy.enabled.is_(True))
            )
        ).one_or_none()
        if row is None:
            raise GovernanceDenied("The default governance policy is unavailable")
        return row[0], row[1]

    async def _defaults(
        self,
        database: AsyncSession,
        business_id: uuid.UUID,
        *,
        owner_id: uuid.UUID | None = None,
        lock: bool = False,
    ) -> tuple[GlobalGovernanceControl, GovernanceSetting, list[GovernanceToolPermission]]:
        controls = await database.get(GlobalGovernanceControl, 1, with_for_update=lock)
        if controls is None:
            raise GovernanceDenied("Global governance controls are unavailable")
        settings = await database.get(GovernanceSetting, business_id, with_for_update=lock)
        now = _now()
        if settings is None:
            settings = GovernanceSetting(
                business_id=business_id,
                autonomy_level="OFF",
                daily_spend_limit_microusd=0,
                per_action_spend_limit_microusd=0,
                revision=1,
                updated_by_owner_id=owner_id,
                updated_at=now,
            )
            database.add(settings)
            await database.flush()
        permissions = list(
            await database.scalars(
                select(GovernanceToolPermission)
                .where(GovernanceToolPermission.business_id == business_id)
                .order_by(GovernanceToolPermission.tool_id)
                .with_for_update()
                if lock
                else select(GovernanceToolPermission)
                .where(GovernanceToolPermission.business_id == business_id)
                .order_by(GovernanceToolPermission.tool_id)
            )
        )
        existing = {item.tool_id for item in permissions}
        for tool_id in TOOL_CATALOG:
            if tool_id in existing:
                continue
            permission = GovernanceToolPermission(
                business_id=business_id,
                tool_id=tool_id,
                enabled=True,
                revision=1,
                updated_by_owner_id=owner_id,
                updated_at=now,
            )
            database.add(permission)
            permissions.append(permission)
        await database.flush()
        permissions.sort(key=lambda item: item.tool_id)
        return controls, settings, permissions

    async def _authorized_spend_today(
        self, database: AsyncSession, business_id: uuid.UUID, now: datetime
    ) -> int:
        return int(
            await database.scalar(
                select(func.coalesce(func.sum(GovernanceAction.requested_spend_microusd), 0)).where(
                    GovernanceAction.business_id == business_id,
                    GovernanceAction.status == "authorized",
                    GovernanceAction.authorized_at >= _day_start(now),
                )
            )
            or 0
        )

    async def dashboard(self, context: AuthContext) -> GovernanceDashboard:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context)
                policy, version = await self._policy(database)
                controls, settings, permissions = await self._defaults(
                    database, business.id, owner_id=context.owner.id
                )
                actions = list(
                    await database.scalars(
                        select(GovernanceAction)
                        .where(GovernanceAction.business_id == business.id)
                        .order_by(desc(GovernanceAction.created_at))
                        .limit(100)
                    )
                )
                action_ids = [item.id for item in actions]
                approvals = (
                    list(
                        await database.scalars(
                            select(ApprovalRequest).where(ApprovalRequest.action_id.in_(action_ids))
                        )
                    )
                    if action_ids
                    else []
                )
                approvals_by_action = {item.action_id: item for item in approvals}
                audit = list(
                    await database.scalars(
                        select(GovernanceAuditEvent)
                        .where(
                            or_(
                                GovernanceAuditEvent.business_id == business.id,
                                GovernanceAuditEvent.business_id.is_(None),
                            )
                        )
                        .order_by(desc(GovernanceAuditEvent.created_at))
                        .limit(200)
                    )
                )
                spend = await self._authorized_spend_today(database, business.id, _now())
        return GovernanceDashboard(
            business_id=business.id,
            policy=policy,
            policy_version=version,
            controls=controls,
            settings=settings,
            tool_permissions=permissions,
            actions=[ActionRecord(item, approvals_by_action.get(item.id)) for item in actions],
            audit_events=audit,
            authorized_spend_today_microusd=spend,
        )

    async def evaluate(
        self,
        context: AuthContext,
        *,
        action_type: str,
        actor_type: str,
        actor_id: str | None,
        tool_id: str | None,
        execution_mode: str,
        data_classification: str,
        requested_spend_microusd: int,
        frequency_key: str | None,
        target: str | None,
        idempotency_key: str,
    ) -> ActionRecord:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                return await self.evaluate_in_session(
                    database,
                    business_id=business.id,
                    action_type=action_type,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    tool_id=tool_id,
                    execution_mode=execution_mode,
                    data_classification=data_classification,
                    requested_spend_microusd=requested_spend_microusd,
                    frequency_key=frequency_key,
                    target=target,
                    idempotency_key=idempotency_key,
                    created_by_owner_id=context.owner.id,
                )

    async def evaluate_in_session(
        self,
        database: AsyncSession,
        *,
        business_id: uuid.UUID,
        action_type: str,
        actor_type: str,
        actor_id: str | None,
        tool_id: str | None,
        execution_mode: str,
        data_classification: str,
        requested_spend_microusd: int,
        frequency_key: str | None,
        target: str | None,
        idempotency_key: str,
        created_by_owner_id: uuid.UUID | None,
        workflow_run_id: uuid.UUID | None = None,
        workflow_step_key: str | None = None,
        minimum_risk_class: str | None = None,
        force_approval: bool = False,
        approval_prompt: str | None = None,
    ) -> ActionRecord:
        try:
            risk_class = classify_action(
                action_type,
                tool_id=tool_id,
                requested_spend_microusd=requested_spend_microusd,
                minimum_risk_class=minimum_risk_class,
            )
        except GovernanceClassificationError:
            raise
        _, policy_version = await self._policy(database)
        controls, settings, permissions = await self._defaults(
            database, business_id, owner_id=created_by_owner_id, lock=True
        )
        existing = await database.scalar(
            select(GovernanceAction).where(
                GovernanceAction.business_id == business_id,
                GovernanceAction.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if any(
                (
                    existing.action_type != action_type,
                    existing.actor_type != actor_type,
                    existing.actor_id != actor_id,
                    existing.tool_id != tool_id,
                    existing.execution_mode != execution_mode,
                    existing.data_classification != data_classification,
                    existing.requested_spend_microusd != requested_spend_microusd,
                    existing.frequency_key != frequency_key,
                    existing.target != target,
                    existing.workflow_run_id != workflow_run_id,
                    existing.workflow_step_key != workflow_step_key,
                )
            ):
                raise GovernanceConflict("Idempotency key was already used for another action")
            approval = await database.scalar(
                select(ApprovalRequest).where(ApprovalRequest.action_id == existing.id)
            )
            return ActionRecord(existing, approval)
        permission_by_tool = {item.tool_id: item for item in permissions}
        now = _now()
        spend_today = await self._authorized_spend_today(database, business_id, now)
        status, rationale = self._initial_decision(
            controls=controls,
            settings=settings,
            permission=(permission_by_tool.get(tool_id) if tool_id else None),
            risk_class=risk_class,
            tool_id=tool_id,
            execution_mode=execution_mode,
            data_classification=data_classification,
            requested_spend_microusd=requested_spend_microusd,
            authorized_spend_today_microusd=spend_today,
            force_approval=force_approval,
        )
        action = GovernanceAction(
            id=uuid.uuid4(),
            business_id=business_id,
            policy_version_id=policy_version.id,
            workflow_run_id=workflow_run_id,
            workflow_step_key=workflow_step_key,
            action_type=action_type,
            actor_type=actor_type,
            actor_id=actor_id,
            tool_id=tool_id,
            risk_class=risk_class,
            execution_mode=execution_mode,
            data_classification=data_classification,
            requested_spend_microusd=requested_spend_microusd,
            frequency_key=frequency_key,
            target=target,
            status=status,
            rationale=rationale,
            idempotency_key=idempotency_key,
            created_by_owner_id=created_by_owner_id,
            created_at=now,
            updated_at=now,
            authorized_at=now if status == "authorized" else None,
        )
        database.add(action)
        await database.flush()
        await _add_audit(
            database,
            "action_evaluated",
            business_id=business_id,
            action_id=action.id,
            actor_owner_id=created_by_owner_id,
            idempotency_key=idempotency_key,
            details={
                "action_type": action_type,
                "risk_class": risk_class,
                "status": status,
                "policy_version": policy_version.version,
                "rationale": rationale,
            },
        )
        approval = None
        if status == "approval_required":
            approval = ApprovalRequest(
                id=uuid.uuid4(),
                action_id=action.id,
                business_id=business_id,
                status="pending",
                prompt=(approval_prompt or ACTION_CATALOG[action_type].description)[:500],
                decision_reason=None,
                requested_by_owner_id=created_by_owner_id,
                decided_by_owner_id=None,
                requested_at=now,
                decided_at=None,
            )
            database.add(approval)
            await database.flush()
            await _add_audit(
                database,
                "approval_requested",
                business_id=business_id,
                action_id=action.id,
                approval_request_id=approval.id,
                actor_owner_id=created_by_owner_id,
                details={"risk_class": risk_class, "prompt": approval.prompt},
            )
        elif status == "authorized":
            await _add_audit(
                database,
                "execution_authorized",
                business_id=business_id,
                action_id=action.id,
                actor_owner_id=created_by_owner_id,
                details={"risk_class": risk_class, "automatic": True},
            )
        return ActionRecord(action, approval)

    @staticmethod
    def _initial_decision(
        *,
        controls: GlobalGovernanceControl,
        settings: GovernanceSetting,
        permission: GovernanceToolPermission | None,
        risk_class: str,
        tool_id: str | None,
        execution_mode: str,
        data_classification: str,
        requested_spend_microusd: int,
        authorized_spend_today_microusd: int,
        force_approval: bool,
    ) -> tuple[str, str]:
        if controls.kill_switch_enabled:
            return "blocked", "The global kill switch is engaged"
        if risk_class == "R5":
            return "denied", "R5 actions are prohibited"
        if tool_id is not None and (permission is None or not permission.enabled):
            return "denied", "The selected-business tool permission is disabled"
        if data_classification == "restricted" and RISK_RANK[risk_class] >= RISK_RANK["R2"]:
            return "denied", "Restricted data cannot cross the external-action boundary"
        if requested_spend_microusd > settings.per_action_spend_limit_microusd:
            return "denied", "The requested spend exceeds the per-action limit"
        if (
            authorized_spend_today_microusd + requested_spend_microusd
            > settings.daily_spend_limit_microusd
        ):
            return "denied", "The requested spend exceeds the remaining daily limit"
        if execution_mode == "autonomous":
            if settings.autonomy_level == "OFF":
                return "denied", "Autonomous execution is off"
            if settings.autonomy_level in {"RECOMMEND", "ASSISTED"}:
                return (
                    "approval_required",
                    f"{settings.autonomy_level} mode requires owner approval",
                )
        if force_approval or RISK_RANK[risk_class] >= RISK_RANK["R2"]:
            return "approval_required", f"{risk_class} requires owner approval"
        return "authorized", f"{risk_class} is permitted by the active policy"

    async def decide(
        self,
        context: AuthContext,
        approval_id: uuid.UUID,
        *,
        decision: Decision,
        reason: str | None,
        idempotency_key: str,
    ) -> ActionRecord:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                return await self.decide_in_session(
                    database,
                    business_id=business.id,
                    approval_id=approval_id,
                    decision=decision,
                    reason=reason,
                    idempotency_key=idempotency_key,
                    owner_id=context.owner.id,
                )

    async def decide_in_session(
        self,
        database: AsyncSession,
        *,
        business_id: uuid.UUID,
        approval_id: uuid.UUID,
        decision: Decision,
        reason: str | None,
        idempotency_key: str,
        owner_id: uuid.UUID,
    ) -> ActionRecord:
        approval = await database.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.business_id == business_id,
            )
            .with_for_update()
        )
        if approval is None:
            raise GovernanceNotFound
        action = await database.scalar(
            select(GovernanceAction)
            .where(
                GovernanceAction.id == approval.action_id,
                GovernanceAction.business_id == business_id,
            )
            .with_for_update()
        )
        if action is None:
            raise GovernanceNotFound
        existing_event = await database.scalar(
            select(GovernanceAuditEvent).where(
                GovernanceAuditEvent.approval_request_id == approval.id,
                GovernanceAuditEvent.idempotency_key == idempotency_key,
            )
        )
        if existing_event is not None:
            return ActionRecord(action, approval)
        if approval.status != "pending" or action.status != "approval_required":
            if approval.status == decision and action.status == decision:
                return ActionRecord(action, approval)
            raise GovernanceConflict("Approval has already received a terminal decision")
        now = _now()
        approval.status = decision
        approval.decision_reason = reason
        approval.decided_by_owner_id = owner_id
        approval.decided_at = now
        action.status = decision
        action.rationale = (
            "Owner explicitly approved the action"
            if decision == "approved"
            else "Owner explicitly rejected the action"
        )
        action.updated_at = now
        await _add_audit(
            database,
            f"approval_{decision}",
            business_id=business_id,
            action_id=action.id,
            approval_request_id=approval.id,
            actor_owner_id=owner_id,
            idempotency_key=idempotency_key,
            details={"reason": reason},
        )
        return ActionRecord(action, approval)

    async def authorize(
        self, context: AuthContext, action_id: uuid.UUID, *, idempotency_key: str
    ) -> ActionRecord:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                return await self.authorize_in_session(
                    database,
                    business_id=business.id,
                    action_id=action_id,
                    idempotency_key=idempotency_key,
                    owner_id=context.owner.id,
                )

    async def authorize_in_session(
        self,
        database: AsyncSession,
        *,
        business_id: uuid.UUID,
        action_id: uuid.UUID,
        idempotency_key: str,
        owner_id: uuid.UUID | None,
    ) -> ActionRecord:
        action = await database.scalar(
            select(GovernanceAction)
            .where(
                GovernanceAction.id == action_id,
                GovernanceAction.business_id == business_id,
            )
            .with_for_update()
        )
        if action is None:
            raise GovernanceNotFound
        approval = await database.scalar(
            select(ApprovalRequest).where(ApprovalRequest.action_id == action.id)
        )
        if action.status == "authorized":
            return ActionRecord(action, approval)
        if action.status != "approved":
            await _add_audit(
                database,
                "execution_denied",
                business_id=business_id,
                action_id=action.id,
                approval_request_id=approval.id if approval else None,
                actor_owner_id=owner_id,
                idempotency_key=idempotency_key,
                details={"status": action.status, "rationale": action.rationale},
            )
            return ActionRecord(action, approval)
        _, current_policy_version = await self._policy(database)
        if action.policy_version_id != current_policy_version.id:
            action.rationale = "The active policy version changed; re-evaluation is required"
            action.updated_at = _now()
            await _add_audit(
                database,
                "execution_blocked",
                business_id=business_id,
                action_id=action.id,
                approval_request_id=approval.id if approval else None,
                actor_owner_id=owner_id,
                idempotency_key=idempotency_key,
                details={"rationale": "The active policy version changed"},
            )
            return ActionRecord(action, approval)
        controls, settings, permissions = await self._defaults(
            database, business_id, owner_id=owner_id, lock=True
        )
        permission = next((item for item in permissions if item.tool_id == action.tool_id), None)
        spend_today = await self._authorized_spend_today(database, business_id, _now())
        blocked_status, rationale = self._initial_decision(
            controls=controls,
            settings=settings,
            permission=permission,
            risk_class=action.risk_class,
            tool_id=action.tool_id,
            execution_mode="manual",
            data_classification=action.data_classification,
            requested_spend_microusd=action.requested_spend_microusd,
            authorized_spend_today_microusd=spend_today,
            force_approval=False,
        )
        if blocked_status in {"blocked", "denied"}:
            action.rationale = rationale
            action.updated_at = _now()
            await _add_audit(
                database,
                "execution_blocked",
                business_id=business_id,
                action_id=action.id,
                approval_request_id=approval.id if approval else None,
                actor_owner_id=owner_id,
                idempotency_key=idempotency_key,
                details={"rationale": rationale},
            )
            return ActionRecord(action, approval)
        now = _now()
        action.status = "authorized"
        action.rationale = "Approved action passed execution-time policy recheck"
        action.updated_at = now
        action.authorized_at = now
        await _add_audit(
            database,
            "execution_authorized",
            business_id=business_id,
            action_id=action.id,
            approval_request_id=approval.id if approval else None,
            actor_owner_id=owner_id,
            idempotency_key=idempotency_key,
            details={"risk_class": action.risk_class, "automatic": False},
        )
        return ActionRecord(action, approval)

    async def update_settings(
        self,
        context: AuthContext,
        *,
        autonomy_level: AutonomyLevel,
        daily_spend_limit_microusd: int,
        per_action_spend_limit_microusd: int,
        revision: int,
    ) -> GovernanceSetting:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                _, settings, _ = await self._defaults(
                    database, business.id, owner_id=context.owner.id, lock=True
                )
                if settings.revision != revision:
                    raise GovernanceConflict("Governance settings changed; reload before saving")
                settings.autonomy_level = autonomy_level
                settings.daily_spend_limit_microusd = daily_spend_limit_microusd
                settings.per_action_spend_limit_microusd = per_action_spend_limit_microusd
                settings.revision += 1
                settings.updated_by_owner_id = context.owner.id
                settings.updated_at = _now()
                await _add_audit(
                    database,
                    "business_controls_updated",
                    business_id=business.id,
                    actor_owner_id=context.owner.id,
                    details={
                        "autonomy_level": autonomy_level,
                        "daily_spend_limit_microusd": daily_spend_limit_microusd,
                        "per_action_spend_limit_microusd": per_action_spend_limit_microusd,
                        "revision": settings.revision,
                    },
                )
                return settings

    async def set_tool_permission(
        self,
        context: AuthContext,
        tool_id: str,
        *,
        enabled: bool,
        revision: int,
    ) -> GovernanceToolPermission:
        if tool_id not in TOOL_CATALOG:
            raise GovernanceNotFound
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                _, _, permissions = await self._defaults(
                    database, business.id, owner_id=context.owner.id, lock=True
                )
                permission = next(item for item in permissions if item.tool_id == tool_id)
                if permission.revision != revision:
                    raise GovernanceConflict("Tool permission changed; reload before saving")
                permission.enabled = enabled
                permission.revision += 1
                permission.updated_by_owner_id = context.owner.id
                permission.updated_at = _now()
                await _add_audit(
                    database,
                    "tool_permission_updated",
                    business_id=business.id,
                    actor_owner_id=context.owner.id,
                    details={
                        "tool_id": tool_id,
                        "enabled": enabled,
                        "revision": permission.revision,
                    },
                )
                return permission

    async def set_kill_switch(
        self,
        context: AuthContext,
        *,
        enabled: bool,
        reason: str | None,
        revision: int,
    ) -> GlobalGovernanceControl:
        async with self._session_factory() as database:
            async with database.begin():
                await resolve_selected_business(database, context)
                controls = await database.get(GlobalGovernanceControl, 1, with_for_update=True)
                if controls is None:
                    raise GovernanceNotFound
                if controls.revision != revision:
                    raise GovernanceConflict("Global controls changed; reload before saving")
                if enabled and not reason:
                    raise GovernanceConflict("Engaging the kill switch requires a reason")
                controls.kill_switch_enabled = enabled
                controls.reason = reason if enabled else None
                controls.revision += 1
                controls.updated_by_owner_id = context.owner.id
                controls.updated_at = _now()
                await _add_audit(
                    database,
                    "kill_switch_engaged" if enabled else "kill_switch_released",
                    business_id=None,
                    actor_owner_id=context.owner.id,
                    details={"reason": controls.reason, "revision": controls.revision},
                )
                return controls
