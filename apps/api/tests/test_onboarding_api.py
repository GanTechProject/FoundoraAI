from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from foundora.api.auth import require_auth, require_csrf
from foundora.api.onboarding import ExecutionRequest
from foundora.auth.service import AuthContext
from foundora.main import app
from foundora.models import (
    ApprovedBusinessProfile,
    Business,
    BusinessOnboardingDraft,
    Owner,
    OwnerSession,
)
from foundora.onboarding.service import (
    OnboardingIncomplete,
    OnboardingRevisionConflict,
    OnboardingState,
    missing_required_fields,
)

ORIGIN = "http://localhost:3000"


def onboarding_records() -> tuple[
    AuthContext, Business, BusinessOnboardingDraft, ApprovedBusinessProfile
]:
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
    business = Business(
        id=uuid.uuid4(),
        owner_id=owner.id,
        name="Selected Business",
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
        selected_business_id=business.id,
    )
    draft = BusinessOnboardingDraft(
        business_id=business.id,
        status="review",
        current_step=5,
        revision=5,
        business_type="idea",
        business_name="Selected Business",
        industry="Software",
        geography="India",
        problem="Manual work",
        target_audience="Small teams",
        offer="Automation software",
        goals=["Launch"],
        existing_assets=[],
        constraints=["Small team"],
        budget="INR 100,000",
        brand_preferences="Clear and direct",
        connected_services=["GitHub"],
        created_at=now,
        updated_at=now,
        submitted_at=now,
    )
    profile = ApprovedBusinessProfile(
        business_id=business.id,
        version=1,
        business_type="idea",
        business_name="Selected Business",
        industry="Software",
        geography="India",
        problem="Manual work",
        target_audience="Small teams",
        offer="Automation software",
        goals=["Launch"],
        existing_assets=[],
        constraints=["Small team"],
        budget="INR 100,000",
        brand_preferences="Clear and direct",
        connected_services=["GitHub"],
        approved_by_owner_id=owner.id,
        approved_at=now,
    )
    return AuthContext(owner=owner, session=session), business, draft, profile


def test_new_onboarding_is_a_resumable_unapproved_draft() -> None:
    context, business, _, _ = onboarding_records()
    app.dependency_overrides[require_auth] = lambda: context
    try:
        with (
            patch(
                "foundora.api.onboarding.OnboardingService.get_state",
                new=AsyncMock(
                    return_value=OnboardingState(
                        business=business,
                        draft=None,
                        approved_profile=None,
                    )
                ),
            ),
            TestClient(app) as client,
        ):
            response = client.get("/onboarding")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["draft"] == {
        "status": "draft",
        "current_step": 1,
        "revision": 0,
        "business_type": None,
        "business_name": "Selected Business",
        "industry": None,
        "geography": None,
        "problem": None,
        "target_audience": None,
        "offer": None,
        "goals": [],
        "existing_assets": [],
        "constraints": [],
        "budget": None,
        "brand_preferences": None,
        "connected_services": [],
        "updated_at": None,
        "submitted_at": None,
    }
    assert response.json()["approved_profile"] is None


def test_stale_revision_is_rejected() -> None:
    context, _, _, _ = onboarding_records()
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with (
            patch(
                "foundora.api.onboarding.OnboardingService.save_market",
                new=AsyncMock(side_effect=OnboardingRevisionConflict),
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/onboarding/steps/market",
                headers={"Origin": ORIGIN},
                json={
                    "revision": 1,
                    "problem": "Problem",
                    "target_audience": "Audience",
                    "offer": "Offer",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "reload" in response.json()["detail"]


def test_incomplete_draft_cannot_be_submitted() -> None:
    context, _, _, _ = onboarding_records()
    app.dependency_overrides[require_csrf] = lambda: context
    error = OnboardingIncomplete(["offer", "at least one goal"])
    try:
        with (
            patch(
                "foundora.api.onboarding.OnboardingService.submit_for_review",
                new=AsyncMock(side_effect=error),
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/onboarding/submit",
                headers={"Origin": ORIGIN},
                json={"revision": 4},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"]["missing_fields"] == ["offer", "at least one goal"]


def test_approval_returns_separate_founder_approved_profile() -> None:
    context, _, _, profile = onboarding_records()
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with (
            patch(
                "foundora.api.onboarding.OnboardingService.approve",
                new=AsyncMock(return_value=profile),
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/onboarding/approve",
                headers={"Origin": ORIGIN},
                json={"revision": 5},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert response.json()["business_name"] == "Selected Business"


def test_list_fields_are_trimmed_and_deduplicated() -> None:
    payload = ExecutionRequest(
        revision=1,
        goals=[" Launch ", "launch", "Reach ten customers"],
        existing_assets=[],
        constraints=[],
        budget="Founder-funded",
    )
    assert payload.goals == ["Launch", "Reach ten customers"]

    _, _, draft, _ = onboarding_records()
    draft.offer = None
    draft.goals = []
    assert missing_required_fields(draft) == ["offer", "at least one goal"]
