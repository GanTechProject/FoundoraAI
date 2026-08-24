from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from foundora.api.auth import require_csrf
from foundora.api.workflows import ResumeWorkflowRequest
from foundora.auth.service import AuthContext
from foundora.main import app
from foundora.models import (
    Owner,
    OwnerSession,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStepRun,
    WorkflowVersion,
)
from foundora.workflows.definition import (
    WorkflowDefinitionError,
    condition_matches,
    execute_internal_tool,
    parse_definition,
)
from foundora.workflows.service import WorkflowRunRecord

ORIGIN = "http://localhost:3000"


def records() -> tuple[AuthContext, WorkflowRunRecord]:
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
    version_id = uuid.uuid4()
    run = WorkflowRun(
        id=uuid.uuid4(),
        business_id=business_id,
        workflow_id="durable-checkpoint-workflow",
        workflow_version_id=version_id,
        task_id=None,
        status="queued",
        structured_input={"message": "test", "include_branch": True},
        structured_output=None,
        current_step_key=None,
        error_type=None,
        error_message=None,
        worker_recovery_count=0,
        created_by_owner_id=owner.id,
        created_at=now,
        queued_at=now,
        started_at=None,
        completed_at=None,
        cancelled_at=None,
    )
    version = WorkflowVersion(
        id=version_id,
        workflow_id=run.workflow_id,
        version=1,
        description="test",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        definition={"steps": []},
        created_at=now,
    )
    step = WorkflowStepRun(
        id=uuid.uuid4(),
        workflow_run_id=run.id,
        step_key="capture",
        sequence=1,
        step_type="tool",
        status="pending",
        attempt_count=0,
        max_retries=1,
        agent_run_id=None,
        governance_action_id=None,
        structured_input=None,
        structured_output=None,
        error_type=None,
        error_message=None,
        started_at=None,
        completed_at=None,
    )
    event = WorkflowEvent(
        id=uuid.uuid4(),
        workflow_run_id=run.id,
        sequence=1,
        event_type="run_created",
        step_key=None,
        actor_owner_id=owner.id,
        idempotency_key=None,
        details={"workflow_version": 1},
        created_at=now,
    )
    return context, WorkflowRunRecord(run=run, version=version, steps=[step], events=[event])


def test_definition_accepts_dag_and_rejects_cycle_or_external_tool() -> None:
    steps = parse_definition(
        {
            "steps": [
                {
                    "key": "first",
                    "type": "tool",
                    "tool": "foundora.internal.echo",
                    "depends_on": [],
                },
                {
                    "key": "second",
                    "type": "wait",
                    "depends_on": ["first"],
                },
            ]
        }
    )
    assert [step.key for step in steps] == ["first", "second"]
    with pytest.raises(WorkflowDefinitionError, match="cycle"):
        parse_definition(
            {
                "steps": [
                    {"key": "a", "type": "wait", "depends_on": ["b"]},
                    {"key": "b", "type": "wait", "depends_on": ["a"]},
                ]
            }
        )
    with pytest.raises(WorkflowDefinitionError, match="allowlist"):
        parse_definition(
            {
                "steps": [
                    {
                        "key": "publish",
                        "type": "tool",
                        "tool": "provider.publish",
                        "depends_on": [],
                    }
                ]
            }
        )
    with pytest.raises(WorkflowDefinitionError, match="immutable agent_version_id"):
        parse_definition(
            {
                "steps": [
                    {
                        "key": "analyze",
                        "type": "agent",
                        "agent_id": "runtime-verification-agent",
                        "depends_on": [],
                    }
                ]
            }
        )


def test_condition_and_internal_tools_are_deterministic() -> None:
    assert condition_matches(
        {"source": "input", "path": "continue", "equals": True},
        {"continue": True},
        {},
    )
    assert not condition_matches(
        {"source": "steps", "path": "missing.value", "equals": True},
        {},
        {},
    )
    assert execute_internal_tool("foundora.internal.echo", {"value": 1}) == {"value": 1}
    with pytest.raises(RuntimeError, match="deterministic"):
        execute_internal_tool("foundora.internal.fail", {})


def test_resume_request_requires_bounded_idempotency_key() -> None:
    request = ResumeWorkflowRequest(idempotency_key="resume:test:01", decision="approved")
    assert request.decision == "approved"
    with pytest.raises(ValueError):
        ResumeWorkflowRequest(idempotency_key="short")


def test_start_workflow_returns_pinned_durable_shape() -> None:
    context, record = records()
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with (
            patch(
                "foundora.api.workflows.WorkflowService.start",
                new=AsyncMock(return_value=record),
            ) as start,
            TestClient(app) as client,
        ):
            response = client.post(
                "/workflows/durable-checkpoint-workflow/runs",
                headers={"Origin": ORIGIN},
                json={"input": {"message": "test", "include_branch": True}},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 202
    payload = response.json()
    assert payload["workflow_version"] == 1
    assert payload["steps"][0]["status"] == "pending"
    assert payload["events"][0]["event_type"] == "run_created"
    start.assert_awaited_once()
