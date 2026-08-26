from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundora.agents.schema import AgentSchemaError
from foundora.agents.website_specification import (
    WEBSITE_SPECIFICATION_AGENT_ID,
    validate_website_specification_output,
    website_specification_prompt_constraints,
)
from foundora.auth.service import AuthContext
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
    WebsiteSpecificationVersion,
)
from foundora.website_specification.service import WebsiteSpecificationService

CONTEXT_ID = "a" * 64
BUSINESS_ID = uuid.UUID("00000000-0000-0000-0000-000000002000")
STRATEGY_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000001701")
OFFER_ID = uuid.UUID("00000000-0000-0000-0000-000000001800")
OFFER_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000001801")
BRAND_ID = uuid.UUID("00000000-0000-0000-0000-000000001900")
BRAND_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000001901")
STRATEGY_REF = f"approved_business_strategies/{BUSINESS_ID}/v1/positioning/POS1"
OFFER_REF = f"product_offer_versions/{OFFER_ID}/v1/packages/PKG1"
BRAND_REF = f"brand_system_versions/{BRAND_ID}/v1/brand_rules/BR1"
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
BRAND_SYSTEM = {
    "brand_status": "proposed",
    "brand_rules": [{"item_id": "BR1", "statement": "Use plain, confident language."}],
}


def _structured_input() -> dict[str, object]:
    return {
        "objective": "Create a complete website specification for founder review",
        "business_context": {"sources": []},
        "context_id": CONTEXT_ID,
        "context_sha256": "b" * 64,
        "website_specification_evidence": {
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
            "brand_system_id": str(BRAND_ID),
            "brand_version": 1,
            "brand_source_agent_run_id": str(BRAND_RUN_ID),
            "brand_context_id": "e" * 64,
            "brand_item_refs": [BRAND_REF],
            "approved_brand_system": BRAND_SYSTEM,
        },
    }


def _evidence() -> dict[str, object]:
    return {
        "strategy_item_refs": [STRATEGY_REF],
        "product_offer_refs": [OFFER_REF],
        "brand_item_refs": [BRAND_REF],
    }


def _requirement(item_id: str, statement: str) -> dict[str, object]:
    return {
        "item_id": item_id,
        "statement": statement,
        "rationale": "Required by the approved business direction.",
        "target_page_ids": ["HOME"],
        **_evidence(),
    }


def _output() -> dict[str, object]:
    site_objective = {
        "item_id": "OBJ1",
        "statement": "Convert qualified founders into launch consultations.",
        "rationale": "The approved offer is consultation-led.",
        **_evidence(),
    }
    sitemap = [
        {
            "page_id": "HOME",
            "path": "/",
            "label": "Home",
            "parent_page_id": None,
            "order": 0,
            "statement": "Primary conversion page.",
            "rationale": "Provides the shortest path to the approved offer.",
            **_evidence(),
        }
    ]
    page_specs = [
        {
            "page_id": "HOME",
            "page_name": "Home",
            "path": "/",
            "purpose": "Explain the offer and earn a consultation request.",
            "primary_audience": "Early-stage founders preparing to launch.",
            "sections": [
                {
                    "section_id": "HERO",
                    "name": "Hero",
                    "objective": "Communicate the outcome and next step.",
                    "content_requirements": ["One evidence-aligned headline and CTA."],
                    "conversion_goal_refs": ["CONSULT"],
                }
            ],
            **_evidence(),
        }
    ]
    conversion_goals = [
        {
            "goal_id": "CONSULT",
            "statement": "Request a launch consultation.",
            "rationale": "Matches the active package.",
            "success_signal": "A valid consultation form submission.",
            "target_page_ids": ["HOME"],
            **_evidence(),
        }
    ]
    seo = _requirement("SEO1", "Provide unique title and description metadata.")
    seo.update(category="metadata", acceptance_criteria=["Metadata is present and unique."])
    content = _requirement("CONTENT1", "Use the approved value proposition in the hero.")
    content.update(content_type="headline", owner="future_content_agent")
    brand = _requirement("BRAND1", "Apply the approved plain and confident voice rule.")
    brand["constraint_type"] = "voice"
    technical = _requirement("TECH1", "Meet WCAG 2.2 AA interaction requirements.")
    technical.update(
        category="accessibility",
        acceptance_criteria=["Automated and manual checks report no blocking issue."],
    )
    return {
        "specification_status": "proposed",
        "code_generation_status": "not_started",
        "context_id": CONTEXT_ID,
        "project_title": "Trusted launch website",
        "site_objective": site_objective,
        "sitemap": sitemap,
        "page_specs": page_specs,
        "conversion_goals": conversion_goals,
        "seo_requirements": [seo],
        "content_requirements": [content],
        "brand_constraints": [brand],
        "technical_requirements": [technical],
        "founder_decisions_required": ["Confirm consultation form ownership."],
        "overall_limitations": ["No code, build, or deployment has begun."],
    }


def test_specification_requires_complete_resolved_triple_evidence() -> None:
    validate_website_specification_output(
        WEBSITE_SPECIFICATION_AGENT_ID, _structured_input(), _output()
    )

    missing_page = _output()
    missing_page["page_specs"] = []
    with pytest.raises(AgentSchemaError, match="specify every sitemap page"):
        validate_website_specification_output(
            WEBSITE_SPECIFICATION_AGENT_ID, _structured_input(), missing_page
        )

    invented = _output()
    requirements = invented["technical_requirements"]
    assert isinstance(requirements, list) and isinstance(requirements[0], dict)
    requirements[0]["brand_item_refs"] = ["brand_system_versions/invented"]
    with pytest.raises(AgentSchemaError, match="unpinned brand item"):
        validate_website_specification_output(
            WEBSITE_SPECIFICATION_AGENT_ID, _structured_input(), invented
        )


def test_specification_cannot_claim_code_generation_or_invalid_sitemap() -> None:
    generated = _output()
    generated["code_generation_status"] = "completed"
    with pytest.raises(AgentSchemaError, match="cannot claim code generation"):
        validate_website_specification_output(
            WEBSITE_SPECIFICATION_AGENT_ID, _structured_input(), generated
        )

    cyclic = _output()
    sitemap = cyclic["sitemap"]
    assert isinstance(sitemap, list) and isinstance(sitemap[0], dict)
    sitemap[0]["parent_page_id"] = "HOME"
    with pytest.raises(AgentSchemaError, match="exactly one root page"):
        validate_website_specification_output(
            WEBSITE_SPECIFICATION_AGENT_ID, _structured_input(), cyclic
        )

    prompt = website_specification_prompt_constraints(
        WEBSITE_SPECIFICATION_AGENT_ID, _structured_input()
    )
    assert STRATEGY_REF in prompt and OFFER_REF in prompt and BRAND_REF in prompt
    assert "never source code" in prompt


def test_approved_specification_is_business_brain_data_and_event() -> None:
    now = datetime.now(UTC)
    specification = WebsiteSpecificationVersion(
        id=uuid.uuid4(),
        business_id=BUSINESS_ID,
        version=2,
        status="active",
        source_agent_run_id=uuid.uuid4(),
        source_strategy_version=1,
        source_product_offer_id=OFFER_ID,
        source_product_offer_version=1,
        source_brand_system_id=BRAND_ID,
        source_brand_version=1,
        context_id=CONTEXT_ID,
        specification=_output(),
        evidence_refs={
            "strategy_item_refs": [STRATEGY_REF],
            "product_offer_refs": [OFFER_REF],
            "brand_item_refs": [BRAND_REF],
        },
        approved_by_owner_id=uuid.uuid4(),
        approved_at=now,
        superseded_at=None,
    )
    candidate = ContextService._approved_website_specification_candidate(specification)
    assert candidate.source_type == "website_specification"
    assert candidate.authority == "founder_approved_website_specification"
    assert candidate.content["specification"] == _output()
    assert candidate.content["code_generation_status"] == "not_started"
    stale = ContextService._approved_website_specification_candidate(
        specification, validity="stale"
    )
    assert stale.validity == "stale"

    contract = validate_event(
        "website_specification.approved",
        1,
        "website_specification",
        {
            "business_id": str(BUSINESS_ID),
            "website_specification_id": str(specification.id),
            "website_specification_version": 2,
            "source_agent_run_id": str(specification.source_agent_run_id),
            "source_strategy_version": 1,
            "source_product_offer_id": str(OFFER_ID),
            "source_product_offer_version": 1,
            "source_brand_system_id": str(BRAND_ID),
            "source_brand_version": 1,
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
async def test_founder_approval_creates_immutable_active_specification() -> None:
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
        name="Website Specification Test",
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
        agent_id=WEBSITE_SPECIFICATION_AGENT_ID,
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
        agent_id=WEBSITE_SPECIFICATION_AGENT_ID,
        version=1,
        role="Website specification architect",
        purpose="Propose a complete specification",
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
    brand = BrandSystemVersion(
        id=BRAND_ID,
        business_id=business.id,
        version=1,
        status="active",
        source_agent_run_id=BRAND_RUN_ID,
        source_strategy_version=1,
        source_product_offer_id=OFFER_ID,
        source_product_offer_version=1,
        context_id="e" * 64,
        brand_system=BRAND_SYSTEM,
        evidence_refs={},
        approved_by_owner_id=owner.id,
        approved_at=now,
        superseded_at=None,
    )
    database = MagicMock()
    database.begin.return_value = _AsyncContext(None)
    database.scalar = AsyncMock(side_effect=[None, run, product_offer, brand])

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
            "foundora.website_specification.service.resolve_selected_business",
            new=AsyncMock(return_value=business),
        ),
        patch("foundora.website_specification.service.publish_event", new=AsyncMock()) as publish,
    ):
        approved = await WebsiteSpecificationService(  # type: ignore[arg-type]
            session_factory=session_factory
        ).approve(context, run_id=run.id, expected_version=0)

    assert approved.version == 1
    assert approved.status == "active"
    assert approved.source_brand_system_id == BRAND_ID
    assert approved.specification["code_generation_status"] == "not_started"
    database.add.assert_called_once_with(approved)
    event_call = publish.await_args.kwargs
    assert event_call["event_type"] == "website_specification.approved"
    assert event_call["payload"]["website_specification_id"] == str(approved.id)
