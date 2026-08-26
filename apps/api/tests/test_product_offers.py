from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundora.agents.product_offer import (
    PRODUCT_OFFER_AGENT_ID,
    product_offer_prompt_constraints,
    validate_product_offer_output,
)
from foundora.agents.schema import AgentSchemaError
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
    ProductOfferVersion,
)
from foundora.product_offers.service import ProductOfferService

CONTEXT_ID = "a" * 64
BUSINESS_ID = uuid.UUID("00000000-0000-0000-0000-000000001800")
STRATEGY_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000001701")
STRATEGY_REF = f"approved_business_strategies/{BUSINESS_ID}/v1/value_proposition/VP1"
STRATEGY = {
    "strategy_status": "proposed",
    "value_proposition": [{"item_id": "VP1", "statement": "Reduce launch friction."}],
}


def _structured_input() -> dict[str, object]:
    return {
        "objective": "Propose a product and offer portfolio",
        "business_context": {"sources": []},
        "context_id": CONTEXT_ID,
        "context_sha256": "b" * 64,
        "offer_evidence": {
            "strategy_version": 1,
            "strategy_source_agent_run_id": str(STRATEGY_RUN_ID),
            "strategy_context_id": "c" * 64,
            "strategy_item_refs": [STRATEGY_REF],
            "approved_strategy": STRATEGY,
        },
    }


def _output() -> dict[str, object]:
    return {
        "portfolio_status": "proposed",
        "context_id": CONTEXT_ID,
        "portfolio_name": "Founder launch portfolio",
        "target_segments": [
            {
                "segment_id": "SEG1",
                "name": "Early founders",
                "description": "Founders preparing a first launch.",
                "strategy_item_refs": [STRATEGY_REF],
            }
        ],
        "products_services": [
            {
                "product_id": "PROD1",
                "kind": "service",
                "name": "Launch planning",
                "description": "A bounded launch planning service.",
                "delivery_model": "Founder-reviewed advisory deliverable.",
                "target_segment_refs": ["SEG1"],
                "benefits": [
                    {
                        "benefit_id": "BEN1",
                        "statement": "A clear launch sequence.",
                        "strategy_item_refs": [STRATEGY_REF],
                    }
                ],
                "status": "proposed",
                "strategy_item_refs": [STRATEGY_REF],
            }
        ],
        "packages": [
            {
                "package_id": "PKG1",
                "name": "Launch foundation",
                "description": "The initial planning package.",
                "product_refs": ["PROD1"],
                "target_segment_refs": ["SEG1"],
                "included_benefit_refs": ["BEN1"],
                "pricing": {
                    "amount_minor": 25000,
                    "currency": "USD",
                    "billing_period": "one_time",
                    "validation_status": "requires_validation",
                },
                "status": "proposed",
                "strategy_item_refs": [STRATEGY_REF],
            }
        ],
        "founder_decisions_required": ["Approve or revise the package."],
        "overall_limitations": ["Pricing has not been market validated."],
    }


def test_product_offer_requires_resolved_evidence_linked_portfolio() -> None:
    validate_product_offer_output(PRODUCT_OFFER_AGENT_ID, _structured_input(), _output())

    invented = _output()
    packages = invented["packages"]
    assert isinstance(packages, list) and isinstance(packages[0], dict)
    packages[0]["strategy_item_refs"] = ["approved_business_strategies/invented"]
    with pytest.raises(AgentSchemaError, match="unpinned strategy item"):
        validate_product_offer_output(PRODUCT_OFFER_AGENT_ID, _structured_input(), invented)

    unresolved = _output()
    packages = unresolved["packages"]
    assert isinstance(packages, list) and isinstance(packages[0], dict)
    packages[0]["product_refs"] = ["MISSING"]
    with pytest.raises(AgentSchemaError, match="defined product or service"):
        validate_product_offer_output(PRODUCT_OFFER_AGENT_ID, _structured_input(), unresolved)


def test_product_offer_remains_proposed_and_pricing_requires_validation() -> None:
    approved = _output()
    approved["portfolio_status"] = "active"
    with pytest.raises(AgentSchemaError, match="must remain proposed"):
        validate_product_offer_output(PRODUCT_OFFER_AGENT_ID, _structured_input(), approved)

    validated_price = _output()
    packages = validated_price["packages"]
    assert isinstance(packages, list) and isinstance(packages[0], dict)
    pricing = packages[0]["pricing"]
    assert isinstance(pricing, dict)
    pricing["validation_status"] = "validated"
    with pytest.raises(AgentSchemaError, match="explicitly unvalidated"):
        validate_product_offer_output(PRODUCT_OFFER_AGENT_ID, _structured_input(), validated_price)

    prompt = product_offer_prompt_constraints(PRODUCT_OFFER_AGENT_ID, _structured_input())
    assert STRATEGY_REF in prompt
    assert "never claim it is approved" in prompt


def test_approved_portfolio_is_business_brain_data_and_transactional_event() -> None:
    now = datetime.now(UTC)
    portfolio = ProductOfferVersion(
        id=uuid.uuid4(),
        business_id=BUSINESS_ID,
        version=2,
        status="active",
        source_agent_run_id=uuid.uuid4(),
        source_strategy_version=1,
        context_id=CONTEXT_ID,
        portfolio=_output(),
        evidence_refs={"strategy_item_refs": [STRATEGY_REF]},
        approved_by_owner_id=uuid.uuid4(),
        approved_at=now,
        superseded_at=None,
    )
    candidate = ContextService._approved_product_offer_candidate(portfolio)
    assert candidate.source_type == "products_services"
    assert candidate.source_version == "2"
    assert candidate.authority == "founder_approved_product_offer"
    assert candidate.content["portfolio"] == _output()

    contract = validate_event(
        "product_offer.approved",
        1,
        "product_offer_portfolio",
        {
            "business_id": str(BUSINESS_ID),
            "portfolio_id": str(portfolio.id),
            "portfolio_version": 2,
            "source_agent_run_id": str(portfolio.source_agent_run_id),
            "source_strategy_version": 1,
            "context_id": CONTEXT_ID,
        },
    )
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
async def test_founder_approval_creates_immutable_active_version() -> None:
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
        id=BUSINESS_ID,
        owner_id=owner.id,
        name="Offer Test",
        summary=None,
        status="planning",
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    owner_session = OwnerSession(
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
    context = AuthContext(owner=owner, session=owner_session)
    version_id = uuid.uuid4()
    run = AgentRun(
        id=uuid.uuid4(),
        business_id=business.id,
        agent_id=PRODUCT_OFFER_AGENT_ID,
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
        agent_id=PRODUCT_OFFER_AGENT_ID,
        version=1,
        role="Offer architect",
        purpose="Propose offers",
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
    strategy = ApprovedBusinessStrategy(
        business_id=business.id,
        version=1,
        source_agent_run_id=STRATEGY_RUN_ID,
        source_profile_version=1,
        context_id="c" * 64,
        strategy=STRATEGY,
        evidence_refs={},
        approved_by_owner_id=owner.id,
        approved_at=now,
    )
    database = MagicMock()
    database.begin.return_value = _AsyncContext(None)
    database.scalar = AsyncMock(side_effect=[None, run])

    async def get_record(model: object, _: object, **__: object) -> object | None:
        if model is AgentVersion:
            return version
        if model is ApprovedBusinessStrategy:
            return strategy
        return None

    database.get = AsyncMock(side_effect=get_record)
    database.flush = AsyncMock()
    session_factory = MagicMock(return_value=_AsyncContext(database))

    with (
        patch(
            "foundora.product_offers.service.resolve_selected_business",
            new=AsyncMock(return_value=business),
        ),
        patch("foundora.product_offers.service.publish_event", new=AsyncMock()) as publish,
    ):
        approved = await ProductOfferService(  # type: ignore[arg-type]
            session_factory=session_factory
        ).approve(context, run_id=run.id, expected_version=0)

    assert approved.version == 1
    assert approved.status == "active"
    assert approved.source_strategy_version == 1
    assert approved.portfolio == _output()
    database.add.assert_called_once_with(approved)
    event_call = publish.await_args.kwargs
    assert event_call["event_type"] == "product_offer.approved"
    assert event_call["payload"]["portfolio_id"] == str(approved.id)
