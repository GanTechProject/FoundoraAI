from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from foundora.agents.recovery import MAX_WORKER_RECOVERIES, _recover_stale_state
from foundora.agents.runtime import AgentRuntime, ExecutionClaim, SqlRuntimeRepository
from foundora.agents.schema import AgentSchemaError, validate_schema
from foundora.agents.service import (
    AgentDashboard,
    AgentNotFound,
    AgentRunRecord,
    SkillNotAssigned,
    _agent_job_id,
)
from foundora.agents.website_coding import WEBSITE_CODING_AGENT_ID, WEBSITE_TOOL_IDS
from foundora.api.agents import _run_view
from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.governance.service import ActionRecord, GovernanceService
from foundora.main import app
from foundora.model_gateway.service import GatewayResult
from foundora.model_gateway.types import ProviderFailure
from foundora.models import (
    AgentMessage,
    AgentRun,
    AgentVersion,
    ModelGatewayCall,
    Owner,
    OwnerSession,
)


class _AsyncContext:
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *args: object) -> None:
        return None


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


INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["objective"],
    "properties": {"objective": {"type": "string", "minLength": 1, "maxLength": 500}},
}
OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "observations", "escalation_required"],
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "observations": {
            "type": "array",
            "maxItems": 5,
            "items": {"type": "string", "minLength": 1},
        },
        "escalation_required": {"type": "boolean"},
    },
}


def execution_claim() -> ExecutionClaim:
    return ExecutionClaim(
        run_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        agent_id="runtime-verification-agent",
        version=1,
        role="Observer",
        purpose="Verify runtime",
        structured_input={"objective": "Inspect context"},
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        model_policy={
            "task_type": "agent.runtime.inspect_context",
            "sensitivity": "standard",
            "allow_fallback": True,
            "max_output_tokens": 256,
            "token_budget": 4096,
            "cost_budget_microusd": 2000,
        },
        forbidden_actions=["External side effects"],
        skill_id=None,
        skill_version=None,
        skill_description=None,
        skill_input_schema=None,
        skill_workflow=[],
        skill_permissions=[],
        skill_tool_requirements=[],
        skill_evaluation_rubric=[],
    )


class FakeRepository:
    def __init__(self, claim: ExecutionClaim | None) -> None:
        self.claim_value = claim
        self.completed: dict[str, object] | None = None
        self.failure: tuple[str, str] | None = None
        self.operation_id: uuid.UUID | None = None

    async def claim(self, _: uuid.UUID, operation_id: uuid.UUID) -> ExecutionClaim | None:
        self.operation_id = operation_id
        return self.claim_value

    async def complete(self, _: uuid.UUID, output: dict[str, object]) -> bool:
        self.completed = output
        return True

    async def fail(self, _: uuid.UUID, error_type: str, message: str) -> bool:
        self.failure = (error_type, message)
        return True


class FakeGateway:
    def __init__(self, *, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.called = False
        self.operation_id: uuid.UUID | None = None
        self.agent_run_id: uuid.UUID | None = None

    async def generate(
        self,
        _: uuid.UUID,
        __: object,
        *,
        operation_id: uuid.UUID | None = None,
        agent_run_id: uuid.UUID | None = None,
    ) -> GatewayResult:
        self.called = True
        self.operation_id = operation_id
        self.agent_run_id = agent_run_id
        if self.error is not None:
            raise self.error
        return GatewayResult(
            operation_id=operation_id or uuid.uuid4(),
            text=self.text,
            provider="gemini",
            model="gemini-test",
            input_tokens=20,
            output_tokens=10,
            total_tokens=30,
            estimated_cost_microusd=2,
            latency_ms=5,
            attempts=1,
            fallback_used=False,
            structured=True,
        )


@pytest.mark.asyncio
async def test_agent_runtime_completes_structured_run_with_usage_identity() -> None:
    claim = execution_claim()
    repository = FakeRepository(claim)
    gateway = FakeGateway(
        text=('{"summary":"Verified","observations":["Grounded"],"escalation_required":false}')
    )

    await AgentRuntime(repository=repository, gateway=gateway).execute(claim.run_id)

    assert repository.completed == {
        "summary": "Verified",
        "observations": ["Grounded"],
        "escalation_required": False,
    }
    assert repository.failure is None
    assert gateway.operation_id == repository.operation_id
    assert gateway.agent_run_id == claim.run_id


@pytest.mark.asyncio
async def test_agent_runtime_persists_provider_failure_honestly() -> None:
    claim = execution_claim()
    repository = FakeRepository(claim)
    gateway = FakeGateway(
        error=ProviderFailure(
            "gemini",
            "provider_unavailable",
            "Provider unavailable",
            retryable=False,
        )
    )

    await AgentRuntime(repository=repository, gateway=gateway).execute(claim.run_id)

    assert repository.completed is None
    assert repository.failure == ("provider_unavailable", "Provider unavailable")


@pytest.mark.asyncio
async def test_agent_runtime_executes_pinned_skill_contract() -> None:
    base = execution_claim()
    skill_input_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["focus"],
        "properties": {"focus": {"type": "string", "minLength": 1}},
    }
    claim = replace(
        base,
        structured_input={
            "objective": "Inspect context",
            "skill": {
                "skill_id": "summarize-business-context",
                "version": 1,
                "input": {"focus": "supported facts"},
            },
        },
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["objective", "skill"],
            "properties": {
                "objective": {"type": "string", "minLength": 1},
                "skill": {"type": "object"},
            },
        },
        skill_id="summarize-business-context",
        skill_version=1,
        skill_description="Summarize supplied context",
        skill_input_schema=skill_input_schema,
        skill_workflow=["Read supplied context", "Return summary"],
        skill_permissions=["Read run context"],
        skill_evaluation_rubric=["Grounded output"],
    )
    repository = FakeRepository(claim)
    gateway = FakeGateway(
        text=('{"summary":"Verified","observations":[],"escalation_required":false}')
    )

    await AgentRuntime(repository=repository, gateway=gateway).execute(claim.run_id)

    assert gateway.called is True
    assert repository.completed is not None
    assert repository.failure is None


@pytest.mark.asyncio
async def test_agent_runtime_rejects_skill_that_requires_tools() -> None:
    claim = replace(execution_claim(), skill_id="tool-skill", skill_tool_requirements=["web"])
    repository = FakeRepository(claim)
    gateway = FakeGateway(text="{}")

    await AgentRuntime(repository=repository, gateway=gateway).execute(claim.run_id)

    assert gateway.called is False
    assert repository.failure == (
        "agent_schema_invalid",
        "Assigned skill requires unsupported tools",
    )


@pytest.mark.asyncio
async def test_website_tools_are_authorized_by_the_durable_policy_engine() -> None:
    run_id = uuid.uuid4()
    business_id = uuid.uuid4()
    run = AgentRun(
        id=run_id,
        business_id=business_id,
        agent_id=WEBSITE_CODING_AGENT_ID,
        status="running",
    )
    database = MagicMock()
    database.scalar = AsyncMock(return_value=run)
    database.begin.return_value = _AsyncContext(None)
    session_factory = MagicMock(return_value=_AsyncContext(database))
    governance = MagicMock(spec=GovernanceService)
    governance.evaluate_in_session = AsyncMock(
        side_effect=[
            ActionRecord(action=MagicMock(status="authorized"), approval=None)
            for _ in WEBSITE_TOOL_IDS
        ]
    )
    repository = SqlRuntimeRepository(
        session_factory=session_factory,  # type: ignore[arg-type]
        governance=governance,
    )

    assert await repository.authorize_website_build(run_id) is True
    assert governance.evaluate_in_session.await_count == len(WEBSITE_TOOL_IDS)
    for tool_id, call in zip(
        WEBSITE_TOOL_IDS,
        governance.evaluate_in_session.await_args_list,
        strict=True,
    ):
        assert call.kwargs == {
            "business_id": business_id,
            "action_type": "internal.content.create",
            "actor_type": "agent",
            "actor_id": WEBSITE_CODING_AGENT_ID,
            "tool_id": tool_id,
            "execution_mode": "manual",
            "data_classification": "confidential",
            "requested_spend_microusd": 0,
            "frequency_key": f"website-build:{run_id}",
            "target": f"website-project:{business_id}",
            "idempotency_key": f"agent-run:{run_id}:website-tool:{tool_id}",
            "created_by_owner_id": None,
        }


@pytest.mark.asyncio
async def test_cancelled_queued_run_is_not_executed() -> None:
    repository = FakeRepository(None)
    gateway = FakeGateway(text="{}")

    await AgentRuntime(repository=repository, gateway=gateway).execute(uuid.uuid4())

    assert gateway.called is False
    assert repository.completed is None


def test_agent_schema_rejects_extra_and_malformed_output() -> None:
    with pytest.raises(AgentSchemaError, match="unsupported fields"):
        validate_schema(
            {
                "summary": "Okay",
                "observations": [],
                "escalation_required": False,
                "action_taken": "published",
            },
            OUTPUT_SCHEMA,
        )
    with pytest.raises(AgentSchemaError, match="must be a boolean"):
        validate_schema(
            {
                "summary": "Okay",
                "observations": [],
                "escalation_required": "no",
            },
            OUTPUT_SCHEMA,
        )


def test_stale_worker_run_recovery_is_bounded() -> None:
    now = datetime.now(UTC)
    run = AgentRun(
        status="running",
        worker_recovery_count=MAX_WORKER_RECOVERIES - 1,
        queued_at=now - timedelta(minutes=10),
        started_at=now - timedelta(minutes=9),
        model_operation_id=uuid.uuid4(),
    )

    assert _recover_stale_state(run, now) == "requeued"
    assert run.status == "queued"
    assert run.worker_recovery_count == MAX_WORKER_RECOVERIES
    assert run.started_at is None
    assert run.model_operation_id is None

    run.status = "running"
    run.started_at = now - timedelta(minutes=9)
    assert _recover_stale_state(run, now) == "failed"
    assert run.status == "failed"
    assert run.error_type == "worker_recovery_exhausted"


def test_each_worker_recovery_uses_a_distinct_deterministic_job_id() -> None:
    run_id = uuid.uuid4()

    assert _agent_job_id(run_id, 0) == f"agent-run-{run_id}"
    assert _agent_job_id(run_id, 1) == f"agent-run-{run_id}-recovery-1"
    assert _agent_job_id(run_id, 3) == f"agent-run-{run_id}-recovery-3"


def test_agent_api_requires_selected_authenticated_owner() -> None:
    with TestClient(app) as client:
        response = client.get("/agents")
    assert response.status_code == 401


def test_agent_dashboard_is_business_scoped_and_not_cached() -> None:
    business_id = uuid.uuid4()
    app.dependency_overrides[require_auth] = lambda: auth_context(business_id)
    try:
        with (
            patch(
                "foundora.api.agents.AgentService.dashboard",
                new=AsyncMock(
                    return_value=AgentDashboard(
                        business_id=business_id,
                        definitions=[],
                        skills=[],
                        runs=[],
                    )
                ),
            ),
            TestClient(app) as client,
        ):
            response = client.get("/agents")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "business_id": str(business_id),
        "definitions": [],
        "skills": [],
        "runs": [],
    }


def test_agent_create_maps_disabled_definition_without_enqueuing() -> None:
    context = auth_context(uuid.uuid4())
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with (
            patch(
                "foundora.api.agents.AgentService.create_run",
                new=AsyncMock(side_effect=AgentNotFound),
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/agents/disabled/runs",
                json={"objective": "Inspect context"},
                headers={"Origin": "http://localhost:3000"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_agent_create_denies_unassigned_skill() -> None:
    context = auth_context(uuid.uuid4())
    app.dependency_overrides[require_csrf] = lambda: context
    try:
        with (
            patch(
                "foundora.api.agents.AgentService.create_run",
                new=AsyncMock(side_effect=SkillNotAssigned),
            ),
            TestClient(app) as client,
        ):
            response = client.post(
                "/agents/runtime-verification-agent/runs",
                json={
                    "objective": "Create a plan",
                    "skill_id": "generate-structured-plan",
                    "skill_input": {"goal": "Launch", "constraints": []},
                },
                headers={"Origin": "http://localhost:3000"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "skill_not_assigned"


def test_run_view_links_messages_and_gateway_usage() -> None:
    now = datetime.now(UTC)
    run_id = uuid.uuid4()
    version_id = uuid.uuid4()
    business_id = uuid.uuid4()
    run = AgentRun(
        id=run_id,
        business_id=business_id,
        agent_id="runtime-verification-agent",
        agent_version_id=version_id,
        skill_version_id=None,
        status="completed",
        structured_input={"objective": "Inspect"},
        structured_output={"summary": "Done"},
        model_operation_id=uuid.uuid4(),
        error_type=None,
        error_message=None,
        worker_recovery_count=0,
        created_at=now,
        queued_at=now,
        started_at=now,
        completed_at=now,
        cancellation_requested_at=None,
        cancelled_at=None,
    )
    version = AgentVersion(
        id=version_id,
        agent_id=run.agent_id,
        version=1,
        role="Observer",
        purpose="Verify",
        responsibilities=[],
        non_responsibilities=[],
        allowed_task_types=[],
        allowed_skills=[],
        allowed_tools=[],
        forbidden_actions=[],
        model_policy={},
        data_access_scope={},
        risk_level="R0",
        maximum_autonomy="manual_run_only",
        input_schema={},
        output_schema={},
        evaluation_criteria=[],
        escalation_criteria=[],
        created_at=now,
    )
    message = AgentMessage(
        id=uuid.uuid4(),
        run_id=run_id,
        sequence=2,
        role="assistant",
        message_type="output",
        content={"summary": "Done"},
        created_at=now,
    )
    call = ModelGatewayCall(
        id=uuid.uuid4(),
        operation_id=run.model_operation_id,
        business_id=business_id,
        agent_run_id=run_id,
        request_id="test",
        task_type="agent.runtime.inspect_context",
        sensitivity="standard",
        provider="gemini",
        model="gemini-test",
        status="succeeded",
        attempt_number=1,
        retry_number=0,
        fallback_from=None,
        streamed=False,
        structured=True,
        input_tokens=20,
        output_tokens=10,
        total_tokens=30,
        estimated_cost_microusd=2,
        latency_ms=5,
        error_type=None,
        error_message=None,
        created_at=now,
        completed_at=now,
    )

    view = _run_view(
        AgentRunRecord(
            run=run,
            version=version,
            skill_version=None,
            messages=[message],
            gateway_calls=[call],
        )
    )

    assert view.business_id == business_id
    assert view.messages[0].message_type == "output"
    assert view.usage.calls == 1
    assert view.usage.total_tokens == 30
