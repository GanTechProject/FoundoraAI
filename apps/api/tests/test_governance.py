from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from foundora.api.auth import require_csrf
from foundora.api.governance import EvaluateActionRequest
from foundora.auth.service import AuthContext
from foundora.governance.registry import classify_action
from foundora.governance.service import ActionRecord, GovernanceService
from foundora.main import app
from foundora.models import (
    ApprovalRequest,
    GlobalGovernanceControl,
    GovernanceAction,
    GovernanceSetting,
    GovernanceToolPermission,
    Owner,
    OwnerSession,
    PolicyVersion,
)

ORIGIN = "http://localhost:3000"


def context() -> AuthContext:
    now = datetime.now(UTC)
    owner = Owner(
        id=uuid.uuid4(),
        singleton_key=1,
        email="owner@example.com",
        password_hash="hash",
        created_at=now,
        updated_at=now,
        password_changed_at=now,
    )
    return AuthContext(
        owner=owner,
        session=OwnerSession(
            id=uuid.uuid4(),
            owner_id=owner.id,
            token_hash="a" * 64,
            csrf_hash="b" * 64,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            expires_at=now + timedelta(hours=8),
            revoked_at=None,
            user_agent="test",
            selected_business_id=uuid.uuid4(),
        ),
    )


def controls(*, killed: bool = False) -> GlobalGovernanceControl:
    return GlobalGovernanceControl(
        singleton_key=1,
        kill_switch_enabled=killed,
        reason="Safety stop" if killed else None,
        revision=1,
        updated_by_owner_id=None,
        updated_at=datetime.now(UTC),
    )


def settings(*, autonomy: str = "OFF", daily: int = 0, action: int = 0) -> GovernanceSetting:
    return GovernanceSetting(
        business_id=uuid.uuid4(),
        autonomy_level=autonomy,
        daily_spend_limit_microusd=daily,
        per_action_spend_limit_microusd=action,
        revision=1,
        updated_by_owner_id=None,
        updated_at=datetime.now(UTC),
    )


def permission(*, enabled: bool = True) -> GovernanceToolPermission:
    return GovernanceToolPermission(
        business_id=uuid.uuid4(),
        tool_id="foundora.internal.echo",
        enabled=enabled,
        revision=1,
        updated_by_owner_id=None,
        updated_at=datetime.now(UTC),
    )


def test_risk_classification_is_code_derived_and_spend_escalates() -> None:
    assert classify_action("external.publication", tool_id=None, requested_spend_microusd=0) == "R3"
    assert (
        classify_action("internal.content.create", tool_id=None, requested_spend_microusd=1) == "R4"
    )
    assert (
        classify_action(
            "internal.analysis",
            tool_id="foundora.internal.echo",
            requested_spend_microusd=0,
        )
        == "R0"
    )


def test_r3_r4_require_approval_and_r5_is_denied() -> None:
    common = {
        "controls": controls(),
        "settings": settings(daily=10_000, action=5_000),
        "permission": None,
        "tool_id": None,
        "execution_mode": "manual",
        "data_classification": "internal",
        "authorized_spend_today_microusd": 0,
        "force_approval": False,
    }
    assert (
        GovernanceService._initial_decision(**common, risk_class="R3", requested_spend_microusd=0)[
            0
        ]
        == "approval_required"
    )
    assert (
        GovernanceService._initial_decision(
            **common, risk_class="R4", requested_spend_microusd=1_000
        )[0]
        == "approval_required"
    )
    assert (
        GovernanceService._initial_decision(**common, risk_class="R5", requested_spend_microusd=0)[
            0
        ]
        == "denied"
    )


def test_live_controls_block_killed_disabled_or_over_budget_actions() -> None:
    base = {
        "risk_class": "R0",
        "execution_mode": "manual",
        "data_classification": "internal",
        "authorized_spend_today_microusd": 0,
        "force_approval": False,
    }
    assert (
        GovernanceService._initial_decision(
            **base,
            controls=controls(killed=True),
            settings=settings(),
            permission=permission(),
            tool_id="foundora.internal.echo",
            requested_spend_microusd=0,
        )[0]
        == "blocked"
    )
    assert (
        GovernanceService._initial_decision(
            **base,
            controls=controls(),
            settings=settings(),
            permission=permission(enabled=False),
            tool_id="foundora.internal.echo",
            requested_spend_microusd=0,
        )[0]
        == "denied"
    )
    assert (
        GovernanceService._initial_decision(
            **base,
            controls=controls(),
            settings=settings(daily=1_000, action=100),
            permission=None,
            tool_id=None,
            requested_spend_microusd=101,
        )[0]
        == "denied"
    )


@pytest.mark.asyncio
async def test_force_recheck_blocks_previously_authorized_action_after_kill_switch() -> None:
    now = datetime.now(UTC)
    business_id = uuid.uuid4()
    policy_version = PolicyVersion(
        id=uuid.uuid4(),
        policy_id="foundora-default-governance",
        version=1,
        description="test",
        rules={},
        created_at=now,
    )
    action = GovernanceAction(
        id=uuid.uuid4(),
        business_id=business_id,
        policy_version_id=policy_version.id,
        workflow_run_id=None,
        workflow_step_key=None,
        action_type="internal.code.execute",
        actor_type="owner",
        actor_id=None,
        tool_id="foundora.sandbox.website",
        risk_class="R2",
        execution_mode="manual",
        data_classification="internal",
        requested_spend_microusd=0,
        frequency_key="sandbox",
        target="sandbox:test",
        status="authorized",
        rationale="Previously authorized",
        idempotency_key="sandbox:test",
        created_by_owner_id=None,
        created_at=now,
        updated_at=now,
        authorized_at=now,
    )
    database = AsyncMock()
    database.scalar.side_effect = [action, None]
    service = GovernanceService(session_factory=MagicMock())

    with (
        patch.object(
            service,
            "_policy",
            new=AsyncMock(return_value=(MagicMock(), policy_version)),
        ),
        patch.object(
            service,
            "_defaults",
            new=AsyncMock(return_value=(controls(killed=True), settings(), [permission()])),
        ),
        patch.object(
            service,
            "_authorized_spend_today",
            new=AsyncMock(return_value=0),
        ),
        patch("foundora.governance.service._add_audit", new=AsyncMock()) as add_audit,
    ):
        result = await service.authorize_in_session(
            database,
            business_id=business_id,
            action_id=action.id,
            idempotency_key="sandbox:test:runtime-recheck",
            owner_id=None,
            force_recheck=True,
        )

    assert result.action.status == "blocked"
    assert result.action.authorized_at is None
    assert result.action.rationale == "The global kill switch is engaged"
    add_audit.assert_awaited_once()


def test_autonomous_execution_defaults_off() -> None:
    decision = GovernanceService._initial_decision(
        controls=controls(),
        settings=settings(autonomy="OFF"),
        permission=None,
        risk_class="R0",
        tool_id=None,
        execution_mode="autonomous",
        data_classification="internal",
        requested_spend_microusd=0,
        authorized_spend_today_microusd=0,
        force_approval=False,
    )
    assert decision[0] == "denied"


@pytest.mark.parametrize("autonomy", ["RECOMMEND", "ASSISTED"])
def test_recommend_and_assisted_autonomy_require_approval(autonomy: str) -> None:
    decision = GovernanceService._initial_decision(
        controls=controls(),
        settings=settings(autonomy=autonomy),
        permission=None,
        risk_class="R0",
        tool_id=None,
        execution_mode="autonomous",
        data_classification="internal",
        requested_spend_microusd=0,
        authorized_spend_today_microusd=0,
        force_approval=False,
    )
    assert decision[0] == "approval_required"


def test_low_risk_autonomy_permits_only_low_risk_without_approval() -> None:
    permitted = GovernanceService._initial_decision(
        controls=controls(),
        settings=settings(autonomy="AUTONOMOUS_LOW_RISK"),
        permission=None,
        risk_class="R1",
        tool_id=None,
        execution_mode="autonomous",
        data_classification="internal",
        requested_spend_microusd=0,
        authorized_spend_today_microusd=0,
        force_approval=False,
    )
    guarded = GovernanceService._initial_decision(
        controls=controls(),
        settings=settings(autonomy="AUTONOMOUS_LOW_RISK"),
        permission=None,
        risk_class="R3",
        tool_id=None,
        execution_mode="autonomous",
        data_classification="internal",
        requested_spend_microusd=0,
        authorized_spend_today_microusd=0,
        force_approval=False,
    )
    assert permitted[0] == "authorized"
    assert guarded[0] == "approval_required"


def test_public_evaluation_cannot_impersonate_an_internal_actor() -> None:
    with pytest.raises(ValidationError):
        EvaluateActionRequest.model_validate(
            {
                "action_type": "internal.analysis",
                "actor_type": "agent",
                "actor_id": "unverified-agent",
                "idempotency_key": "test:actor:01",
            }
        )


def test_evaluate_api_returns_durable_classification_and_approval() -> None:
    auth = context()
    now = datetime.now(UTC)
    action = GovernanceAction(
        id=uuid.uuid4(),
        business_id=auth.session.selected_business_id,
        policy_version_id=uuid.uuid4(),
        workflow_run_id=None,
        workflow_step_key=None,
        action_type="external.publication",
        actor_type="owner",
        actor_id=None,
        tool_id=None,
        risk_class="R3",
        execution_mode="manual",
        data_classification="internal",
        requested_spend_microusd=0,
        frequency_key="test",
        target="example.invalid",
        status="approval_required",
        rationale="R3 requires owner approval",
        idempotency_key="test:evaluate:01",
        created_by_owner_id=auth.owner.id,
        created_at=now,
        updated_at=now,
        authorized_at=None,
    )
    approval = ApprovalRequest(
        id=uuid.uuid4(),
        action_id=action.id,
        business_id=action.business_id,
        status="pending",
        prompt="Approve publication",
        decision_reason=None,
        requested_by_owner_id=auth.owner.id,
        decided_by_owner_id=None,
        requested_at=now,
        decided_at=None,
    )
    app.dependency_overrides[require_csrf] = lambda: auth
    try:
        with (
            patch(
                "foundora.api.governance.GovernanceService.evaluate",
                new=AsyncMock(return_value=ActionRecord(action, approval)),
            ) as evaluate,
            TestClient(app) as client,
        ):
            response = client.post(
                "/governance/actions/evaluate",
                headers={"Origin": ORIGIN},
                json={
                    "action_type": "external.publication",
                    "execution_mode": "manual",
                    "data_classification": "internal",
                    "requested_spend_microusd": 0,
                    "target": "example.invalid",
                    "idempotency_key": "test:evaluate:01",
                },
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["risk_class"] == "R3"
    assert response.json()["approval"]["status"] == "pending"
    evaluate.assert_awaited_once()
