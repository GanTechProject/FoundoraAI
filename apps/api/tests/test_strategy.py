from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundora.agents.schema import AgentSchemaError
from foundora.agents.service import AgentRunRecord
from foundora.agents.strategy import (
    BUSINESS_STRATEGIST_AGENT_ID,
    STRATEGY_SECTIONS,
    strategy_prompt_constraints,
    validate_strategy_output,
)
from foundora.api.agents import _run_view
from foundora.auth.service import AuthContext
from foundora.business_brain.service import ContextService
from foundora.events.contracts import AUDIT_CONSUMER, consumers_for, validate_event
from foundora.models import (
    AgentRun,
    AgentVersion,
    ApprovedBusinessStrategy,
    Business,
    Owner,
    OwnerSession,
)
from foundora.strategy.service import StrategyService

CONTEXT_ID = "a" * 64
FACT_REF = "approved_business_profiles/00000000-0000-0000-0000-000000001700"
FINDING_REF = "agent_runs/00000000-0000-0000-0000-000000001601/findings/F1"


def _structured_input() -> dict[str, object]:
    return {
        "objective": "Propose an evidence-backed business strategy",
        "business_context": {"sources": []},
        "context_id": CONTEXT_ID,
        "context_sha256": "b" * 64,
        "strategy_evidence": {
            "approved_fact_refs": [FACT_REF],
            "research_runs": [
                {
                    "run_id": "00000000-0000-0000-0000-000000001601",
                    "agent_id": "market-research",
                    "agent_version_id": "00000000-0000-0000-0000-000000001601",
                    "agent_version": 1,
                    "context_id": CONTEXT_ID,
                    "research_query": "query",
                    "supported_finding_refs": [FINDING_REF],
                    "output": {},
                }
            ],
        },
    }


def _output() -> dict[str, object]:
    output: dict[str, object] = {
        "strategy_status": "proposed",
        "context_id": CONTEXT_ID,
        "strategy_title": "Evidence-backed launch strategy",
        "founder_decisions_required": ["Approve or revise this proposal."],
        "overall_limitations": ["Evidence is limited to registered sources."],
    }
    for index, section in enumerate(STRATEGY_SECTIONS, start=1):
        item: dict[str, object] = {
            "item_id": f"S{index}",
            "statement": f"Proposed {section.replace('_', ' ')}.",
            "approved_fact_refs": [FACT_REF],
            "research_finding_refs": [FINDING_REF],
            "confidence": "medium",
            "limitations": ["Requires founder review."],
        }
        if section == "pricing_hypotheses":
            item["validation_status"] = "requires_validation"
        if section == "assumptions_requiring_validation":
            item["validation_method"] = "Run a bounded founder-approved validation test."
        output[section] = [item]
    return output


def test_strategy_requires_all_artifacts_and_exact_dual_evidence() -> None:
    validate_strategy_output(BUSINESS_STRATEGIST_AGENT_ID, _structured_input(), _output())

    unpinned = _output()
    first = unpinned["opportunity_assessment"]
    assert isinstance(first, list) and isinstance(first[0], dict)
    first[0]["research_finding_refs"] = ["agent_runs/invented/findings/F9"]
    with pytest.raises(AgentSchemaError, match="unpinned research finding"):
        validate_strategy_output(BUSINESS_STRATEGIST_AGENT_ID, _structured_input(), unpinned)

    missing = _output()
    missing["risks"] = []
    with pytest.raises(AgentSchemaError, match="must contain at least one"):
        validate_strategy_output(BUSINESS_STRATEGIST_AGENT_ID, _structured_input(), missing)


def test_strategy_remains_proposed_and_pricing_requires_validation() -> None:
    approved = _output()
    approved["strategy_status"] = "approved"
    with pytest.raises(AgentSchemaError, match="must remain proposed"):
        validate_strategy_output(BUSINESS_STRATEGIST_AGENT_ID, _structured_input(), approved)

    priced = _output()
    items = priced["pricing_hypotheses"]
    assert isinstance(items, list) and isinstance(items[0], dict)
    items[0]["validation_status"] = "validated"
    with pytest.raises(AgentSchemaError, match="Pricing must remain a hypothesis"):
        validate_strategy_output(BUSINESS_STRATEGIST_AGENT_ID, _structured_input(), priced)


def test_strategy_prompt_and_run_view_expose_evidence_boundary() -> None:
    prompt = strategy_prompt_constraints(BUSINESS_STRATEGIST_AGENT_ID, _structured_input())
    assert FACT_REF in prompt
    assert FINDING_REF in prompt
    assert "never an executed or approved strategy" in prompt

    now = datetime.now(UTC)
    version_id = uuid.uuid4()
    run = AgentRun(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        agent_id=BUSINESS_STRATEGIST_AGENT_ID,
        agent_version_id=version_id,
        skill_version_id=None,
        status="completed",
        structured_input=_structured_input(),
        structured_output=_output(),
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
        agent_id=BUSINESS_STRATEGIST_AGENT_ID,
        version=1,
        role="Strategist",
        purpose="Propose strategy",
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
    view = _run_view(AgentRunRecord(run, version, None, [], []))
    assert view.strategy_trace is not None
    assert view.strategy_trace.approved_fact_refs == [FACT_REF]
    assert view.strategy_trace.research_finding_refs == [FINDING_REF]
    assert view.strategy_trace.output_context_matches is True


def test_approved_strategy_is_a_versioned_business_brain_source_and_event() -> None:
    now = datetime.now(UTC)
    business_id = uuid.uuid4()
    strategy = ApprovedBusinessStrategy(
        business_id=business_id,
        version=2,
        source_agent_run_id=uuid.uuid4(),
        context_id=CONTEXT_ID,
        strategy=_output(),
        evidence_refs={
            "approved_fact_refs": [FACT_REF],
            "research_finding_refs": [FINDING_REF],
        },
        approved_by_owner_id=uuid.uuid4(),
        approved_at=now,
    )
    candidate = ContextService._approved_strategy_candidate(strategy)
    assert candidate.source_type == "approved_strategy"
    assert candidate.source_version == "2"
    assert candidate.authority == "founder_approved_strategy"
    assert candidate.content["strategy"] == _output()

    contract = validate_event(
        "strategy.approved",
        1,
        "business_strategy",
        {
            "business_id": str(business_id),
            "strategy_version": 2,
            "source_agent_run_id": str(strategy.source_agent_run_id),
            "context_id": CONTEXT_ID,
        },
    )
    assert contract.event_type == "strategy.approved"
    assert [consumer.name for consumer in consumers_for(contract.event_type)] == [
        AUDIT_CONSUMER.name
    ]


class _AsyncContext:
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.mark.asyncio
async def test_founder_approval_revalidates_and_publishes_transactionally() -> None:
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
        name="Strategy Test",
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
        idle_expires_at=now,
        expires_at=now,
        revoked_at=None,
        user_agent="test",
        selected_business_id=business.id,
    )
    context = AuthContext(owner=owner, session=session)
    version_id = uuid.uuid4()
    run = AgentRun(
        id=uuid.uuid4(),
        business_id=business.id,
        agent_id=BUSINESS_STRATEGIST_AGENT_ID,
        agent_version_id=version_id,
        skill_version_id=None,
        status="completed",
        structured_input=_structured_input(),
        structured_output=_output(),
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
        agent_id=BUSINESS_STRATEGIST_AGENT_ID,
        version=1,
        role="Strategist",
        purpose="Propose strategy",
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
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        evaluation_criteria=[],
        escalation_criteria=[],
        created_at=now,
    )
    database = MagicMock()
    database.begin.return_value = _AsyncContext(None)

    async def get_record(model: object, _: object, **__: object) -> object | None:
        if model is ApprovedBusinessStrategy:
            return None
        if model is AgentVersion:
            return version
        return None

    database.get = AsyncMock(side_effect=get_record)
    database.scalar = AsyncMock(return_value=run)
    database.flush = AsyncMock()
    session_factory = MagicMock(return_value=_AsyncContext(database))

    with (
        patch(
            "foundora.strategy.service.resolve_selected_business",
            new=AsyncMock(return_value=business),
        ),
        patch("foundora.strategy.service.publish_event", new=AsyncMock()) as publish,
    ):
        approved = await StrategyService(session_factory=session_factory).approve(  # type: ignore[arg-type]
            context, run_id=run.id, expected_version=0
        )

    assert approved.version == 1
    assert approved.source_agent_run_id == run.id
    assert approved.strategy == _output()
    assert approved.evidence_refs == {
        "approved_fact_refs": [FACT_REF],
        "research_finding_refs": [FINDING_REF],
    }
    database.add.assert_called_once_with(approved)
    publish.assert_awaited_once()
    event_call = publish.await_args.kwargs
    assert event_call["event_type"] == "strategy.approved"
    assert event_call["business_id"] == business.id
    assert event_call["payload"]["strategy_version"] == 1
