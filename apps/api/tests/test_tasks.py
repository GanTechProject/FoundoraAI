from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from foundora.api.auth import require_auth, require_csrf
from foundora.api.tasks import CreateTaskRequest, TaskRetryRequest
from foundora.auth.service import AuthContext
from foundora.main import app
from foundora.models import Owner, OwnerSession, Task, TaskEvent
from foundora.tasks.service import (
    DependencyViolation,
    InvalidTaskTransition,
    TaskDashboard,
    TaskRecord,
    ensure_transition,
)

ORIGIN = "http://localhost:3000"


def records() -> tuple[AuthContext, TaskRecord]:
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
    business_id = uuid.uuid4()
    context = AuthContext(
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
    task = Task(
        id=uuid.uuid4(),
        business_id=business_id,
        goal_id=None,
        title="Prepare launch brief",
        description=None,
        priority=2,
        owner_type="founder",
        owner_agent_id=None,
        owner_agent_version_id=None,
        status="draft",
        due_at=None,
        max_retries=2,
        retry_count=0,
        last_error=None,
        created_by_owner_id=owner.id,
        created_at=now,
        updated_at=now,
    )
    event = TaskEvent(
        id=uuid.uuid4(),
        task_id=task.id,
        event_type="created",
        from_status=None,
        to_status="draft",
        actor_owner_id=owner.id,
        idempotency_key=None,
        details={"priority": 2},
        created_at=now,
    )
    return context, TaskRecord(task=task, dependencies=[], events=[event])


def test_transition_graph_rejects_skips_and_terminal_mutation() -> None:
    ensure_transition("draft", "planned")
    ensure_transition("running", "completed")
    with pytest.raises(InvalidTaskTransition):
        ensure_transition("draft", "running")
    with pytest.raises(InvalidTaskTransition):
        ensure_transition("completed", "queued")


def test_task_request_requires_timezone_and_exact_agent_owner() -> None:
    with pytest.raises(ValueError):
        CreateTaskRequest(title="Task", due_at=datetime(2026, 9, 1))
    with pytest.raises(ValueError):
        CreateTaskRequest(title="Task", owner_type="agent")
    request = CreateTaskRequest(
        title="  Prepare   launch  ",
        owner_type="agent",
        owner_agent_id="runtime-verification-agent",
        due_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert request.title == "Prepare launch"


def test_retry_request_requires_reusable_bounded_key() -> None:
    assert TaskRetryRequest(idempotency_key="retry:task:01").idempotency_key == "retry:task:01"
    with pytest.raises(ValueError):
        TaskRetryRequest(idempotency_key="short")


def test_create_task_returns_durable_event_shape() -> None:
    context, record = records()
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with (
            patch(
                "foundora.api.tasks.TaskService.create",
                new=AsyncMock(return_value=record),
            ) as create,
            TestClient(app) as client,
        ):
            response = client.post(
                "/tasks",
                headers={"Origin": ORIGIN},
                json={
                    "title": "Prepare launch brief",
                    "priority": 2,
                    "owner_type": "founder",
                    "max_retries": 2,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["events"][0]["event_type"] == "created"
    assert payload["blocked_by"] == []
    create.assert_awaited_once()


def test_dependency_conflict_exposes_blockers_without_cross_business_data() -> None:
    context, record = records()
    blocker_id = uuid.uuid4()
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with (
            patch(
                "foundora.api.tasks.TaskService.transition",
                new=AsyncMock(
                    side_effect=DependencyViolation("Dependencies incomplete", [blocker_id])
                ),
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                f"/tasks/{record.task.id}/status",
                headers={"Origin": ORIGIN},
                json={"status": "queued"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": "Dependencies incomplete",
        "blockers": [str(blocker_id)],
    }


def test_task_read_requires_authentication() -> None:
    context, _ = records()
    app.dependency_overrides[require_auth] = lambda: context
    try:
        with TestClient(app) as client:
            response = client.get("/tasks/not-a-uuid")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422


def test_task_dashboard_forwards_bounded_pagination() -> None:
    context, record = records()
    dashboard = TaskDashboard(
        business_id=record.task.business_id,
        goals=[],
        agent_owners=[],
        tasks=[record],
        total_tasks=250,
        limit=25,
        offset=50,
    )
    app.dependency_overrides[require_auth] = lambda: context
    try:
        with (
            patch(
                "foundora.api.tasks.TaskService.dashboard",
                new=AsyncMock(return_value=dashboard),
            ) as load,
            TestClient(app) as client,
        ):
            response = client.get("/tasks?limit=25&offset=50")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["total_tasks"] == 250
    load.assert_awaited_once_with(context, limit=25, offset=50)
