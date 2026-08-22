from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from foundora.api.auth import require_auth
from foundora.auth.service import AuthContext
from foundora.business_brain.service import (
    SOURCE_TYPES,
    BusinessContext,
    ContextBuildRequest,
    ContextCandidate,
    ContextSourceDecision,
    select_context,
)
from foundora.main import app
from foundora.models import Owner, OwnerSession


def auth_context(business_id: uuid.UUID) -> AuthContext:
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
        selected_business_id=business_id,
    )
    return AuthContext(owner=owner, session=session)


def candidate(
    reference: str,
    value: str,
    *,
    validity: str = "current",
) -> ContextCandidate:
    return ContextCandidate(
        source_type="operational_goals",
        source_reference=reference,
        source_version="1",
        authority="founder_workspace",
        label=reference,
        updated_at=datetime(2026, 8, 22, tzinfo=UTC),
        validity=validity,  # type: ignore[arg-type]
        content={"value": value},
    )


def test_selector_excludes_stale_invalidated_and_unselected_sources() -> None:
    business_id = uuid.uuid4()
    result = select_context(
        business_id=business_id,
        request=ContextBuildRequest(
            purpose="planning",
            token_budget=4096,
            selected_source_types=frozenset({"operational_goals"}),
        ),
        candidates=[
            candidate("current", "current-only"),
            candidate("stale", "must-not-appear-stale", validity="stale"),
            candidate(
                "invalidated",
                "must-not-appear-invalidated",
                validity="invalidated",
            ),
            ContextCandidate(
                source_type="brand",
                source_reference="brand",
                source_version="1",
                authority="founder_approved_onboarding",
                label="Brand",
                updated_at=datetime(2026, 8, 22, tzinfo=UTC),
                validity="current",
                content={"value": "must-not-appear-unselected"},
            ),
        ],
        unavailable_sources={},
    )

    assert result.business_id == business_id
    assert result.estimated_tokens <= result.token_budget
    assert "current-only" in result.context
    assert "must-not-appear" not in result.context
    assert [item.exclusion_reason for item in result.sources] == [
        None,
        "stale",
        "invalidated",
        "not_selected",
    ]
    assert all(
        item.content is None for item in result.sources if item.selection_status == "excluded"
    )


def test_selector_enforces_budget_and_produces_deterministic_provenance() -> None:
    business_id = uuid.uuid4()
    request = ContextBuildRequest(
        purpose="general",
        token_budget=256,
        selected_source_types=frozenset(SOURCE_TYPES),
    )
    candidates = [
        candidate("first", "small"),
        candidate("second", "x" * 1000),
    ]

    first = select_context(
        business_id=business_id,
        request=request,
        candidates=candidates,
        unavailable_sources={"knowledge": "Unavailable"},
    )
    second = select_context(
        business_id=business_id,
        request=request,
        candidates=candidates,
        unavailable_sources={"knowledge": "Unavailable"},
    )

    assert first.estimated_tokens <= 256
    assert first.sources[-1].exclusion_reason == "token_budget"
    assert first.context_id == second.context_id
    assert first.context_sha256 == second.context_sha256

    different_selection = select_context(
        business_id=business_id,
        request=ContextBuildRequest(
            purpose="general",
            token_budget=256,
            selected_source_types=frozenset(),
        ),
        candidates=[],
        unavailable_sources={"knowledge": "Unavailable"},
    )
    all_selected_without_candidates = select_context(
        business_id=business_id,
        request=request,
        candidates=[],
        unavailable_sources={"knowledge": "Unavailable"},
    )
    assert different_selection.context_id != all_selected_without_candidates.context_id


def test_context_endpoint_exposes_provenance_for_selected_business() -> None:
    business_id = uuid.uuid4()
    context = auth_context(business_id)
    generated_at = datetime(2026, 8, 22, tzinfo=UTC)
    service_result = BusinessContext(
        context_id="a" * 64,
        business_id=business_id,
        purpose="planning",
        generated_at=generated_at,
        token_budget=1024,
        estimated_tokens=200,
        budget_remaining=824,
        selected_source_types=("business_profile",),
        sources=[
            ContextSourceDecision(
                source_type="business_profile",
                source_reference=f"businesses/{business_id}",
                source_version="1",
                authority="founder_workspace",
                label="Business profile",
                updated_at=generated_at,
                validity="current",
                selection_status="included",
                exclusion_reason=None,
                estimated_tokens=100,
                content_sha256="b" * 64,
                content={"name": "Selected only"},
            )
        ],
        unavailable_sources={"knowledge": "Not implemented"},
        context='{"business_id":"selected"}',
        context_sha256="c" * 64,
    )
    app.dependency_overrides[require_auth] = lambda: context
    try:
        with (
            patch(
                "foundora.api.business_brain.ContextService.build",
                new=AsyncMock(return_value=service_result),
            ) as build,
            TestClient(app) as client,
        ):
            response = client.get(
                "/brain/context",
                params={
                    "purpose": "planning",
                    "token_budget": 1024,
                    "sources": "business_profile",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    assert payload["business_id"] == str(business_id)
    assert payload["sources"][0]["source_reference"] == f"businesses/{business_id}"
    build.assert_awaited_once()


def test_context_endpoint_rejects_unknown_source() -> None:
    business_id = uuid.uuid4()
    app.dependency_overrides[require_auth] = lambda: auth_context(business_id)
    try:
        with TestClient(app) as client:
            response = client.get("/brain/context?sources=imaginary_source")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_context_source"
