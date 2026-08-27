from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.main import app
from foundora.models import (
    ApprovalRequest,
    GovernanceAction,
    Owner,
    OwnerSession,
    SandboxExecution,
)
from foundora.sandbox.service import (
    SandboxExecutionPage,
    SandboxExecutionRecord,
    SandboxQueueUnavailable,
)

ORIGIN = "http://localhost:3000"


def _context(*, business_id: uuid.UUID | None = None) -> AuthContext:
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
            selected_business_id=business_id or uuid.uuid4(),
        ),
    )


def _record(context: AuthContext) -> SandboxExecutionRecord:
    now = datetime.now(UTC)
    action_id = uuid.uuid4()
    policy_id = uuid.uuid4()
    execution = SandboxExecution(
        id=uuid.uuid4(),
        business_id=context.session.selected_business_id,
        idempotency_key="ui:sandbox:test",
        website_project_id=uuid.uuid4(),
        website_project_version=3,
        website_specification_id=uuid.uuid4(),
        website_specification_version=2,
        source_digest="1" * 64,
        build_digest="2" * 64,
        source_archive_sha256="3" * 64,
        source_archive_size_bytes=512,
        routes=["/"],
        profile_id="static-website",
        profile_version=1,
        harness_contract_version=1,
        runtime_image_id=None,
        request_digest="4" * 64,
        governance_action_id=action_id,
        policy_version_id=policy_id,
        status="waiting_approval",
        worker_recovery_count=0,
        cleanup_status="pending",
        cleanup_attempts=0,
        route_results=None,
        process_results=None,
        stdout_excerpt="<script>alert('not markup')</script>",
        stderr_excerpt=None,
        created_at=now,
        updated_at=now,
    )
    action = GovernanceAction(
        id=action_id,
        business_id=execution.business_id,
        policy_version_id=policy_id,
        workflow_run_id=None,
        workflow_step_key=None,
        action_type="internal.code.execute",
        actor_type="owner",
        actor_id=str(context.owner.id),
        tool_id="foundora.sandbox.website",
        risk_class="R2",
        execution_mode="manual",
        data_classification="confidential",
        requested_spend_microusd=0,
        frequency_key="sandbox:website",
        target="website-project:test",
        status="approval_required",
        rationale="R2 requires owner approval",
        idempotency_key=f"sandbox:{execution.id}",
        created_by_owner_id=context.owner.id,
        created_at=now,
        updated_at=now,
        authorized_at=None,
    )
    approval = ApprovalRequest(
        id=uuid.uuid4(),
        action_id=action.id,
        business_id=execution.business_id,
        status="pending",
        prompt="Approve isolated execution?",
        decision_reason=None,
        requested_by_owner_id=context.owner.id,
        decided_by_owner_id=None,
        requested_at=now,
        decided_at=None,
    )
    return SandboxExecutionRecord(execution, action, approval)


def test_sandbox_list_and_detail_are_authenticated_scoped_and_not_cacheable() -> None:
    context = _context()
    record = _record(context)
    page = SandboxExecutionPage(context.session.selected_business_id, [record], 1, 25, 0)
    app.dependency_overrides[require_auth] = lambda: context
    try:
        with (
            patch(
                "foundora.api.sandbox.SandboxService.list_executions",
                new=AsyncMock(return_value=page),
            ) as list_executions,
            patch(
                "foundora.api.sandbox.SandboxService.get_execution",
                new=AsyncMock(return_value=record),
            ) as get_execution,
            TestClient(app) as client,
        ):
            listed = client.get("/sandbox/executions")
            detailed = client.get(f"/sandbox/executions/{record.execution.id}")
    finally:
        app.dependency_overrides.clear()

    assert listed.status_code == 200
    assert detailed.status_code == 200
    assert listed.headers["Cache-Control"] == "no-store"
    assert detailed.headers["Cache-Control"] == "no-store"
    assert listed.json()["business_id"] == str(context.session.selected_business_id)
    assert detailed.json()["request_digest"] == record.execution.request_digest
    assert detailed.json()["stdout_excerpt"] == "<script>alert('not markup')</script>"
    assert "source_archive" not in detailed.json()
    list_executions.assert_awaited_once_with(context, limit=25, offset=0)
    get_execution.assert_awaited_once_with(context, record.execution.id)


def test_sandbox_reads_require_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/sandbox/executions")
    assert response.status_code == 401


def test_sandbox_mutations_require_csrf() -> None:
    context = _context()
    app.dependency_overrides[require_auth] = lambda: context
    try:
        with TestClient(app) as client:
            response = client.post(
                "/sandbox/executions",
                headers={"Origin": ORIGIN},
                json={"idempotency_key": "ui:sandbox:test"},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403


def test_owner_can_request_start_and_cancel_through_csrf_boundary() -> None:
    context = _context()
    record = _record(context)
    requested = AsyncMock(return_value=record.execution)
    started = AsyncMock(return_value=record.execution)
    cancelled = AsyncMock(return_value=record.execution)
    detail = AsyncMock(return_value=record)
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with (
            patch(
                "foundora.api.sandbox.SandboxService.request_execution",
                new=requested,
            ),
            patch(
                "foundora.api.sandbox.SandboxService.start_execution",
                new=started,
            ),
            patch(
                "foundora.api.sandbox.SandboxService.cancel_execution",
                new=cancelled,
            ),
            patch(
                "foundora.api.sandbox.SandboxService.get_execution",
                new=detail,
            ),
            TestClient(app) as client,
        ):
            requested_response = client.post(
                "/sandbox/executions",
                headers={"Origin": ORIGIN},
                json={"idempotency_key": "ui:sandbox:request-1"},
            )
            started_response = client.post(
                f"/sandbox/executions/{record.execution.id}/start",
                headers={"Origin": ORIGIN},
            )
            cancelled_response = client.post(
                f"/sandbox/executions/{record.execution.id}/cancel",
                headers={"Origin": ORIGIN},
            )
    finally:
        app.dependency_overrides.clear()

    assert requested_response.status_code == 201
    assert started_response.status_code == 202
    assert cancelled_response.status_code == 202
    requested.assert_awaited_once_with(context, idempotency_key="ui:sandbox:request-1")
    started.assert_awaited_once_with(context, record.execution.id)
    cancelled.assert_awaited_once_with(context, record.execution.id)
    assert all(
        response.headers["Cache-Control"] == "no-store"
        for response in (requested_response, started_response, cancelled_response)
    )


def test_queue_failure_is_reported_without_fake_execution_success() -> None:
    context = _context()
    record = _record(context)
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with (
            patch(
                "foundora.api.sandbox.SandboxService.start_execution",
                new=AsyncMock(side_effect=SandboxQueueUnavailable),
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                f"/sandbox/executions/{record.execution.id}/start",
                headers={"Origin": ORIGIN},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "queue_unavailable"
