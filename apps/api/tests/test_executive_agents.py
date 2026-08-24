from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from foundora.agents.executive import (
    CEO_AGENT_ID,
    PLANNING_AGENT_ID,
    executive_prompt_constraints,
    validate_executive_output,
)
from foundora.agents.runtime import AgentRuntime, ExecutionClaim
from foundora.agents.schema import AgentSchemaError
from foundora.agents.service import AgentRunRecord
from foundora.api.agents import _run_view
from foundora.model_gateway.service import GatewayResult
from foundora.models import AgentRun, AgentVersion

CONTEXT_ID = "a" * 64
CONTEXT_SHA256 = "b" * 64
SOURCE_REFERENCE = "businesses/00000000-0000-0000-0000-000000000015"


def _structured_input() -> dict[str, object]:
    return {
        "objective": "Prioritize launch readiness",
        "context_id": CONTEXT_ID,
        "context_sha256": CONTEXT_SHA256,
        "business_context": {
            "schema": "foundora.business_context.v1",
            "business_id": "00000000-0000-0000-0000-000000000015",
            "purpose": "agent_runtime",
            "sources": [
                {
                    "source_reference": SOURCE_REFERENCE,
                    "source_type": "business_profile",
                    "source_version": "v1",
                    "authority": "founder_workspace",
                    "content": {"name": "Foundora"},
                }
            ],
        },
    }


def _ceo_output() -> dict[str, object]:
    return {
        "plan_status": "proposed",
        "context_id": CONTEXT_ID,
        "plan_title": "Launch readiness priorities",
        "objective_interpretation": "Prepare the business for a grounded launch decision.",
        "business_state_summary": "The selected workspace exists and needs launch planning.",
        "priorities": [
            {
                "priority_id": "P1",
                "title": "Build the launch plan",
                "rationale": "The founder objective requires an ordered plan.",
                "evidence_refs": [SOURCE_REFERENCE],
                "delegation_target": PLANNING_AGENT_ID,
                "requested_work": "Propose a dependency-aware launch plan.",
                "risk_level": "R0",
                "approval_required": False,
            }
        ],
        "assumptions": [],
        "limitations": ["No market research evidence is present."],
        "founder_decisions_required": [],
    }


def _planning_output() -> dict[str, object]:
    return {
        "plan_status": "proposed",
        "context_id": CONTEXT_ID,
        "plan_title": "Proposed launch work",
        "objective": "Prepare launch readiness",
        "tasks": [
            {
                "task_id": "T1",
                "title": "Confirm launch criteria",
                "description": "Draft measurable founder review criteria.",
                "priority": "high",
                "depends_on": [],
                "candidate_agent": "founder",
                "requested_specialist_work": "Founder decision only; no execution requested.",
                "evidence_refs": [SOURCE_REFERENCE],
                "completion_criteria": ["Founder confirms the criteria"],
            },
            {
                "task_id": "T2",
                "title": "Prepare the launch outline",
                "description": "Propose an outline after criteria are confirmed.",
                "priority": "normal",
                "depends_on": ["T1"],
                "candidate_agent": "future-specialist",
                "requested_specialist_work": "Request a future strategy specialist.",
                "evidence_refs": [SOURCE_REFERENCE],
                "completion_criteria": ["Outline maps to confirmed criteria"],
            },
        ],
        "progress_review": [],
        "assumptions": [],
        "limitations": ["The specialist is not implemented."],
        "founder_decisions_required": ["Confirm launch criteria"],
    }


def _claim(agent_id: str) -> ExecutionClaim:
    return ExecutionClaim(
        run_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        agent_id=agent_id,
        version=1,
        role="Executive advisor",
        purpose="Produce a proposed plan",
        structured_input=_structured_input(),
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        model_policy={
            "task_type": "executive.plan",
            "sensitivity": "sensitive",
            "allow_fallback": False,
            "max_output_tokens": 1000,
            "token_budget": 10000,
            "cost_budget_microusd": 10000,
        },
        forbidden_actions=["Tool invocation", "External side effects"],
        skill_id=None,
        skill_version=None,
        skill_description=None,
        skill_input_schema=None,
        skill_workflow=[],
        skill_permissions=[],
        skill_tool_requirements=[],
        skill_evaluation_rubric=[],
    )


class _Repository:
    def __init__(self, claim: ExecutionClaim) -> None:
        self.claim_value = claim
        self.completed: dict[str, object] | None = None
        self.failure: tuple[str, str] | None = None

    async def claim(self, _: uuid.UUID, __: uuid.UUID) -> ExecutionClaim | None:
        return self.claim_value

    async def complete(self, _: uuid.UUID, output: dict[str, object]) -> bool:
        self.completed = output
        return True

    async def fail(self, _: uuid.UUID, error_type: str, message: str) -> bool:
        self.failure = (error_type, message)
        return True


class _Gateway:
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.called = False
        self.system_prompt = ""

    async def generate(
        self,
        _: uuid.UUID,
        request: object,
        *,
        operation_id: uuid.UUID | None = None,
        agent_run_id: uuid.UUID | None = None,
    ) -> GatewayResult:
        self.called = True
        self.system_prompt = str(getattr(request, "system_prompt", ""))
        return GatewayResult(
            operation_id=operation_id or uuid.uuid4(),
            text=json.dumps(self.output),
            provider="gemini",
            model="test-model",
            input_tokens=10,
            output_tokens=10,
            total_tokens=20,
            estimated_cost_microusd=1,
            latency_ms=1,
            attempts=1,
            fallback_used=False,
            structured=True,
        )


@pytest.mark.asyncio
async def test_ceo_produces_traceable_proposed_plan_without_tools() -> None:
    claim = _claim(CEO_AGENT_ID)
    repository = _Repository(claim)
    gateway = _Gateway(_ceo_output())

    await AgentRuntime(repository=repository, gateway=gateway).execute(claim.run_id)

    assert gateway.called is True
    assert repository.completed == _ceo_output()
    assert repository.failure is None
    assert "advisory executive planning only" in gateway.system_prompt
    assert SOURCE_REFERENCE in gateway.system_prompt


def test_ceo_rejects_unknown_evidence_and_unsafe_risk_approval() -> None:
    unknown = _ceo_output()
    priorities = unknown["priorities"]
    assert isinstance(priorities, list) and isinstance(priorities[0], dict)
    priorities[0]["evidence_refs"] = ["invented/source"]
    with pytest.raises(AgentSchemaError, match="unknown sources"):
        validate_executive_output(CEO_AGENT_ID, _structured_input(), unknown)

    unsafe = _ceo_output()
    unsafe_priorities = unsafe["priorities"]
    assert isinstance(unsafe_priorities, list) and isinstance(unsafe_priorities[0], dict)
    unsafe_priorities[0]["risk_level"] = "R3"
    with pytest.raises(AgentSchemaError, match="cannot waive approval"):
        validate_executive_output(CEO_AGENT_ID, _structured_input(), unsafe)


def test_executive_output_must_bind_to_context_and_remain_proposed() -> None:
    output = _ceo_output()
    output["context_id"] = "c" * 64
    with pytest.raises(AgentSchemaError, match="does not match"):
        validate_executive_output(CEO_AGENT_ID, _structured_input(), output)

    output = _ceo_output()
    output["plan_status"] = "executed"
    with pytest.raises(AgentSchemaError, match="must remain proposed"):
        validate_executive_output(CEO_AGENT_ID, _structured_input(), output)


def test_planning_agent_accepts_acyclic_graph_and_rejects_cycle() -> None:
    output = _planning_output()
    validate_executive_output(PLANNING_AGENT_ID, _structured_input(), output)

    tasks = output["tasks"]
    assert isinstance(tasks, list) and isinstance(tasks[0], dict)
    tasks[0]["depends_on"] = ["T2"]
    with pytest.raises(AgentSchemaError, match="dependency cycle"):
        validate_executive_output(PLANNING_AGENT_ID, _structured_input(), output)


def test_planning_progress_must_cite_an_included_current_task() -> None:
    structured_input = _structured_input()
    context = structured_input["business_context"]
    assert isinstance(context, dict) and isinstance(context["sources"], list)
    task_reference = "tasks/00000000-0000-0000-0000-000000000115"
    context["sources"].append(
        {
            "source_reference": task_reference,
            "source_type": "current_tasks",
            "source_version": "v1",
            "authority": "task_engine",
            "content": {"status": "planned"},
        }
    )
    output = _planning_output()
    output["progress_review"] = [
        {
            "task_reference": task_reference,
            "status_summary": "The existing task remains planned.",
            "evidence_refs": [task_reference],
        }
    ]
    validate_executive_output(PLANNING_AGENT_ID, structured_input, output)

    progress = output["progress_review"]
    assert isinstance(progress, list) and isinstance(progress[0], dict)
    progress[0]["task_reference"] = SOURCE_REFERENCE
    with pytest.raises(AgentSchemaError, match="not a current task source"):
        validate_executive_output(PLANNING_AGENT_ID, structured_input, output)


@pytest.mark.asyncio
async def test_runtime_persists_invalid_executive_output_honestly() -> None:
    claim = _claim(PLANNING_AGENT_ID)
    repository = _Repository(claim)
    output = _planning_output()
    tasks = output["tasks"]
    assert isinstance(tasks, list) and isinstance(tasks[1], dict)
    tasks[1]["evidence_refs"] = ["invented/source"]

    await AgentRuntime(repository=repository, gateway=_Gateway(output)).execute(claim.run_id)

    assert repository.completed is None
    assert repository.failure is not None
    assert repository.failure[0] == "agent_schema_invalid"
    assert "unknown sources" in repository.failure[1]


def test_run_view_exposes_executive_plan_trace() -> None:
    now = datetime.now(UTC)
    claim = _claim(CEO_AGENT_ID)
    run = AgentRun(
        id=claim.run_id,
        business_id=claim.business_id,
        agent_id=claim.agent_id,
        agent_version_id=uuid.uuid4(),
        skill_version_id=None,
        status="completed",
        structured_input=claim.structured_input,
        structured_output=_ceo_output(),
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
        id=run.agent_version_id,
        agent_id=run.agent_id,
        version=1,
        role="Executive advisor",
        purpose="Plan",
        responsibilities=[],
        non_responsibilities=[],
        allowed_task_types=[],
        allowed_skills=[],
        allowed_tools=[],
        forbidden_actions=[],
        model_policy={},
        data_access_scope={},
        risk_level="R0",
        maximum_autonomy="manual_advisory_only",
        input_schema={},
        output_schema={},
        evaluation_criteria=[],
        escalation_criteria=[],
        created_at=now,
    )

    view = _run_view(
        AgentRunRecord(
            run=run,
            version=version,
            skill_version=None,
            messages=[],
            gateway_calls=[],
        )
    )

    assert view.executive_plan_trace is not None
    assert view.executive_plan_trace.context_id == CONTEXT_ID
    assert view.executive_plan_trace.source_references == [SOURCE_REFERENCE]
    assert view.executive_plan_trace.output_context_matches is True
    assert view.executive_plan_trace.advisory_only is True


def test_non_executive_agent_has_no_plan_trace() -> None:
    claim = replace(_claim(CEO_AGENT_ID), agent_id="runtime-verification-agent")
    assert executive_prompt_constraints(claim.agent_id, claim.structured_input) == ""
