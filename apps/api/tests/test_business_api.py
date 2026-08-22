from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from foundora.api.auth import require_auth, require_csrf
from foundora.api.businesses import BusinessPreferencesRequest
from foundora.auth.service import AuthContext
from foundora.business.service import GoalNotFound, Workspace
from foundora.main import app
from foundora.models import Business, BusinessGoal, BusinessPreference, Owner, OwnerSession

ORIGIN = "http://localhost:3000"


def records() -> tuple[AuthContext, Business, Business, BusinessPreference, BusinessGoal]:
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
    selected = Business(
        id=uuid.uuid4(),
        owner_id=owner.id,
        name="Selected Business",
        summary="Selected summary",
        status="active",
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    other = Business(
        id=uuid.uuid4(),
        owner_id=owner.id,
        name="Other Business",
        summary=None,
        status="planning",
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    session = OwnerSession(
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
        selected_business_id=selected.id,
    )
    preference = BusinessPreference(
        business_id=selected.id,
        timezone="Asia/Kolkata",
        currency="INR",
        locale="en-IN",
        updated_at=now,
    )
    goal = BusinessGoal(
        id=uuid.uuid4(),
        business_id=selected.id,
        title="Launch",
        details="Selected-only goal",
        target_date=date(2026, 12, 31),
        status="active",
        created_at=now,
        updated_at=now,
    )
    return AuthContext(owner=owner, session=session), selected, other, preference, goal


def test_business_list_marks_only_the_session_selection() -> None:
    context, selected, other, _, _ = records()
    app.dependency_overrides[require_auth] = lambda: context
    try:
        with (
            patch(
                "foundora.api.businesses.BusinessService.list_businesses",
                new=AsyncMock(return_value=[selected, other]),
            ),
            TestClient(app) as client,
        ):
            response = client.get("/businesses")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    assert payload["selected_business_id"] == str(selected.id)
    assert [item["selected"] for item in payload["businesses"]] == [True, False]


def test_workspace_returns_only_service_resolved_business_data() -> None:
    context, selected, _, preference, goal = records()
    app.dependency_overrides[require_auth] = lambda: context
    try:
        with (
            patch(
                "foundora.api.businesses.BusinessService.get_workspace",
                new=AsyncMock(
                    return_value=Workspace(
                        business=selected,
                        preferences=preference,
                        goals=[goal],
                    )
                ),
            ),
            TestClient(app) as client,
        ):
            response = client.get("/workspace")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["business"]["id"] == str(selected.id)
    assert payload["preferences"]["currency"] == "INR"
    assert [item["title"] for item in payload["goals"]] == ["Launch"]


def test_goal_from_another_selected_context_is_not_exposed() -> None:
    context, _, _, _, goal = records()
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with (
            patch(
                "foundora.api.businesses.BusinessService.update_goal_status",
                new=AsyncMock(side_effect=GoalNotFound),
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                f"/workspace/goals/{goal.id}/status",
                headers={"Origin": ORIGIN},
                json={"status": "completed"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"detail": "Goal not found"}


def test_preferences_validate_portable_operating_defaults() -> None:
    preferences = BusinessPreferencesRequest(
        timezone="Asia/Kolkata", currency="inr", locale="en-IN"
    )
    assert preferences.currency == "INR"
    assert preferences.timezone == "Asia/Kolkata"
    assert preferences.locale == "en-IN"
