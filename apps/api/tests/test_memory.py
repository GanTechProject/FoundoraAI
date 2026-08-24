from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from foundora.api.auth import require_auth
from foundora.auth.service import AuthContext
from foundora.main import app
from foundora.memory.service import (
    MemoryConflict,
    MemoryDashboard,
    MemoryEntry,
    PolicyState,
    _normalize_expiry,
    _reject_secrets,
    _validate_type,
    canonical_key,
)
from foundora.models import (
    MemoryProposal,
    MemoryProvenance,
    MemoryRecord,
    MemoryRevision,
    Owner,
    OwnerSession,
)


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
            selected_business_id=business_id,
        ),
    )


def test_canonical_duplicates_merge_whitespace_and_case() -> None:
    first = canonical_key("semantic", "fact", "Pricing Model", "Annual subscriptions")
    second = canonical_key("semantic", "fact", " pricing   model ", "annual  SUBSCRIPTIONS")
    assert first == second


@pytest.mark.parametrize(
    ("memory_type", "epistemic_status"),
    [
        ("working", "observation"),
        ("working", "assumption"),
        ("episodic", "observation"),
        ("semantic", "assumption"),
        ("semantic", "fact"),
        ("decision", "decision"),
        ("preference", "preference"),
        ("workflow", "procedure"),
        ("evaluation", "evaluation"),
    ],
)
def test_all_memory_types_have_explicit_epistemic_statuses(
    memory_type: str, epistemic_status: str
) -> None:
    _validate_type(memory_type, epistemic_status)


def test_type_boundary_prevents_assumptions_masquerading_as_other_memory() -> None:
    with pytest.raises(MemoryConflict, match="cannot be stored"):
        _validate_type("decision", "fact")
    with pytest.raises(MemoryConflict, match="cannot be stored"):
        _validate_type("preference", "assumption")


def test_secret_guard_rejects_credential_shaped_content() -> None:
    with pytest.raises(MemoryConflict, match="secrets"):
        _reject_secrets("api_key=sk-abcdefghijklmnopqrstuvwxyz")
    with pytest.raises(MemoryConflict, match="secrets"):
        _reject_secrets("-----BEGIN PRIVATE KEY-----")


def test_working_memory_requires_scope_and_bounded_expiry() -> None:
    now = datetime.now(UTC)
    execution_id = uuid.uuid4()
    assert _normalize_expiry("working", now + timedelta(hours=2), "task", execution_id, now)
    with pytest.raises(MemoryConflict, match="requires"):
        _normalize_expiry("working", None, None, None, now)
    with pytest.raises(MemoryConflict, match="seven days"):
        _normalize_expiry("working", now + timedelta(days=8), "task", execution_id, now)


def test_memory_dashboard_exposes_status_revision_and_provenance() -> None:
    now = datetime.now(UTC)
    business_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    proposal_id = uuid.uuid4()
    memory_id = uuid.uuid4()
    proposal = MemoryProposal(
        id=proposal_id,
        business_id=business_id,
        memory_type="semantic",
        epistemic_status="fact",
        title="Approved pricing",
        content="Annual subscriptions are the approved model.",
        confidence=1.0,
        status="accepted",
        acceptance_route="founder",
        canonical_key="a" * 64,
        execution_type=None,
        execution_id=None,
        expires_at=None,
        source_kind="founder_input",
        source_id=None,
        source_uri="https://example.com/decision",
        source_label="Founder review",
        source_excerpt="Approved in review.",
        source_metadata={},
        requested_by_owner_id=owner_id,
        decided_by_owner_id=owner_id,
        resolution_memory_id=memory_id,
        decision_reason="Confirmed",
        revision=2,
        created_at=now,
        updated_at=now,
        decided_at=now,
    )
    record = MemoryRecord(
        id=memory_id,
        business_id=business_id,
        originating_proposal_id=proposal_id,
        memory_type="semantic",
        epistemic_status="fact",
        title=proposal.title,
        content=proposal.content,
        confidence=1.0,
        status="active",
        accepted_via="founder",
        canonical_key=proposal.canonical_key,
        execution_type=None,
        execution_id=None,
        expires_at=None,
        current_revision=1,
        accepted_by_owner_id=owner_id,
        created_at=now,
        updated_at=now,
        invalidated_at=None,
        invalidation_reason=None,
    )
    revision = MemoryRevision(
        id=uuid.uuid4(),
        memory_id=memory_id,
        business_id=business_id,
        revision=1,
        proposal_id=proposal_id,
        change_type="accepted",
        title=record.title,
        content=record.content,
        confidence=1.0,
        canonical_key=record.canonical_key,
        created_by="founder",
        created_by_owner_id=owner_id,
        created_at=now,
    )
    provenance = MemoryProvenance(
        id=uuid.uuid4(),
        memory_id=memory_id,
        business_id=business_id,
        revision=1,
        source_kind="founder_input",
        source_id=None,
        source_uri=proposal.source_uri,
        source_label=proposal.source_label,
        source_excerpt=proposal.source_excerpt,
        source_metadata={},
        created_at=now,
    )
    dashboard = MemoryDashboard(
        business_id=business_id,
        policy=PolicyState((), 0.9, 0, False),
        proposals=[proposal],
        memories=[MemoryEntry(record, [revision], [provenance])],
    )
    app.dependency_overrides[require_auth] = lambda: auth_context(business_id)
    try:
        with (
            patch(
                "foundora.api.memory.MemoryService.dashboard",
                new=AsyncMock(return_value=dashboard),
            ),
            TestClient(app) as client,
        ):
            response = client.get("/memory")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    item = response.json()["memories"][0]
    assert item["epistemic_status"] == "fact"
    assert item["accepted_via"] == "founder"
    assert item["provenance"][0]["source_uri"] == "https://example.com/decision"


def test_memory_requires_authentication() -> None:
    with TestClient(app) as client:
        assert client.get("/memory").status_code == 401
