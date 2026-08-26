from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundora.agents.brand import (
    BRAND_SECTIONS,
    BRAND_STRATEGIST_AGENT_ID,
    brand_prompt_constraints,
    validate_brand_output,
)
from foundora.agents.schema import AgentSchemaError
from foundora.auth.service import AuthContext
from foundora.brand.service import BrandService
from foundora.business_brain.service import ContextService
from foundora.events.contracts import AUDIT_CONSUMER, consumers_for, validate_event
from foundora.models import (
    AgentRun,
    AgentVersion,
    ApprovedBusinessStrategy,
    BrandSystemVersion,
    Business,
    Owner,
    OwnerSession,
    ProductOfferVersion,
)

CONTEXT_ID = "a" * 64
BUSINESS_ID = uuid.UUID("00000000-0000-0000-0000-000000001900")
STRATEGY_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000001701")
OFFER_ID = uuid.UUID("00000000-0000-0000-0000-000000001800")
OFFER_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000001801")
STRATEGY_REF = f"approved_business_strategies/{BUSINESS_ID}/v1/positioning/POS1"
OFFER_REF = f"product_offer_versions/{OFFER_ID}/v1/packages/PKG1"
STRATEGY = {
    "strategy_status": "proposed",
    "positioning": [{"item_id": "POS1", "statement": "Trusted launch partner."}],
}
PORTFOLIO = {
    "portfolio_status": "proposed",
    "target_segments": [],
    "products_services": [],
    "packages": [{"package_id": "PKG1", "name": "Launch foundation"}],
}


def _structured_input() -> dict[str, object]:
    return {
        "objective": "Propose an evidence-linked brand system",
        "business_context": {"sources": []},
        "context_id": CONTEXT_ID,
        "context_sha256": "b" * 64,
        "brand_evidence": {
            "strategy_version": 1,
            "strategy_source_agent_run_id": str(STRATEGY_RUN_ID),
            "strategy_context_id": "c" * 64,
            "strategy_item_refs": [STRATEGY_REF],
            "approved_strategy": STRATEGY,
            "product_offer_id": str(OFFER_ID),
            "product_offer_version": 1,
            "product_offer_source_agent_run_id": str(OFFER_RUN_ID),
            "product_offer_context_id": "d" * 64,
            "product_offer_refs": [OFFER_REF],
            "approved_product_offer": PORTFOLIO,
        },
    }


def _item(item_id: str) -> dict[str, object]:
    return {
        "item_id": item_id,
        "statement": f"Brand direction {item_id}",
        "rationale": "Aligns the approved strategy and offer.",
        "strategy_item_refs": [STRATEGY_REF],
        "product_offer_refs": [OFFER_REF],
    }


def _output() -> dict[str, object]:
    output: dict[str, object] = {
        "brand_status": "proposed",
        "context_id": CONTEXT_ID,
        "brand_title": "Trusted launch brand",
        "tagline": _item("TAG1"),
        "founder_decisions_required": ["Approve or revise the brand system."],
        "overall_limitations": ["Name and assets have not been externally checked."],
    }
    for index, section in enumerate(BRAND_SECTIONS, start=1):
        item = _item(f"B{index}")
        if section == "naming_analysis":
            item.update(candidate_name="Foundora Launch", availability_status="not_checked")
        elif section == "voice":
            item["usage_context"] = "Founder-facing product communication"
        elif section == "messaging":
            item.update(audience="Early founders", use_case="Offer landing page")
        elif section == "visual_direction":
            item["element"] = "color"
        elif section == "brand_rules":
            item["category"] = "voice"
        elif section == "asset_references":
            item.update(
                asset_type="logo",
                reference="Proposed accessible primary logo specification",
                reference_status="proposed_reference",
            )
        output[section] = [item]
    return output


def test_brand_requires_all_artifacts_and_exact_dual_evidence() -> None:
    validate_brand_output(BRAND_STRATEGIST_AGENT_ID, _structured_input(), _output())

    invented = _output()
    rules = invented["brand_rules"]
    assert isinstance(rules, list) and isinstance(rules[0], dict)
    rules[0]["product_offer_refs"] = ["product_offer_versions/invented"]
    with pytest.raises(AgentSchemaError, match="unpinned product or offer item"):
        validate_brand_output(BRAND_STRATEGIST_AGENT_ID, _structured_input(), invented)

    missing = _output()
    missing["voice"] = []
    with pytest.raises(AgentSchemaError, match="must contain at least one"):
        validate_brand_output(BRAND_STRATEGIST_AGENT_ID, _structured_input(), missing)


def test_brand_remains_proposed_without_availability_or_asset_claims() -> None:
    approved = _output()
    approved["brand_status"] = "approved"
    with pytest.raises(AgentSchemaError, match="must remain proposed"):
        validate_brand_output(BRAND_STRATEGIST_AGENT_ID, _structured_input(), approved)

    available = _output()
    naming = available["naming_analysis"]
    assert isinstance(naming, list) and isinstance(naming[0], dict)
    naming[0]["availability_status"] = "available"
    with pytest.raises(AgentSchemaError, match="must not claim availability"):
        validate_brand_output(BRAND_STRATEGIST_AGENT_ID, _structured_input(), available)

    created = _output()
    assets = created["asset_references"]
    assert isinstance(assets, list) and isinstance(assets[0], dict)
    assets[0]["reference_status"] = "created"
    with pytest.raises(AgentSchemaError, match="must remain proposed references"):
        validate_brand_output(BRAND_STRATEGIST_AGENT_ID, _structured_input(), created)

    prompt = brand_prompt_constraints(BRAND_STRATEGIST_AGENT_ID, _structured_input())
    assert STRATEGY_REF in prompt and OFFER_REF in prompt
    assert "never claim founder approval" in prompt


def test_approved_brand_rules_are_business_brain_data_and_event() -> None:
    now = datetime.now(UTC)
    brand = BrandSystemVersion(
        id=uuid.uuid4(),
        business_id=BUSINESS_ID,
        version=2,
        status="active",
        source_agent_run_id=uuid.uuid4(),
        source_strategy_version=1,
        source_product_offer_id=OFFER_ID,
        source_product_offer_version=1,
        context_id=CONTEXT_ID,
        brand_system=_output(),
        evidence_refs={
            "strategy_item_refs": [STRATEGY_REF],
            "product_offer_refs": [OFFER_REF],
        },
        approved_by_owner_id=uuid.uuid4(),
        approved_at=now,
        superseded_at=None,
    )
    candidate = ContextService._approved_brand_candidate(brand)
    assert candidate.source_type == "brand"
    assert candidate.source_version == "2"
    assert candidate.authority == "founder_approved_brand_system"
    assert candidate.content["brand_rules"] == _output()["brand_rules"]

    contract = validate_event(
        "brand.approved",
        1,
        "brand_system",
        {
            "business_id": str(BUSINESS_ID),
            "brand_system_id": str(brand.id),
            "brand_version": 2,
            "source_agent_run_id": str(brand.source_agent_run_id),
            "source_strategy_version": 1,
            "source_product_offer_id": str(OFFER_ID),
            "source_product_offer_version": 1,
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
async def test_founder_approval_creates_immutable_active_brand_version() -> None:
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
        name="Brand Test",
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
        agent_id=BRAND_STRATEGIST_AGENT_ID,
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
        agent_id=BRAND_STRATEGIST_AGENT_ID,
        version=1,
        role="Brand strategist",
        purpose="Propose brand system",
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
    product_offer = ProductOfferVersion(
        id=OFFER_ID,
        business_id=business.id,
        version=1,
        status="active",
        source_agent_run_id=OFFER_RUN_ID,
        source_strategy_version=1,
        context_id="d" * 64,
        portfolio=PORTFOLIO,
        evidence_refs={},
        approved_by_owner_id=owner.id,
        approved_at=now,
        superseded_at=None,
    )
    database = MagicMock()
    database.begin.return_value = _AsyncContext(None)
    database.scalar = AsyncMock(side_effect=[None, run, product_offer])

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
            "foundora.brand.service.resolve_selected_business",
            new=AsyncMock(return_value=business),
        ),
        patch("foundora.brand.service.publish_event", new=AsyncMock()) as publish,
    ):
        approved = await BrandService(  # type: ignore[arg-type]
            session_factory=session_factory
        ).approve(context, run_id=run.id, expected_version=0)

    assert approved.version == 1
    assert approved.status == "active"
    assert approved.source_product_offer_id == OFFER_ID
    assert approved.brand_system == _output()
    database.add.assert_called_once_with(approved)
    event_call = publish.await_args.kwargs
    assert event_call["event_type"] == "brand.approved"
    assert event_call["payload"]["brand_system_id"] == str(approved.id)
