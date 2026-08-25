from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from foundora.agents.research import (
    COMPETITOR_INTELLIGENCE_AGENT_ID,
    CUSTOMER_RESEARCH_AGENT_ID,
    MARKET_RESEARCH_AGENT_ID,
    research_prompt_constraints,
    validate_research_output,
)
from foundora.agents.runtime import AgentRuntime, ExecutionClaim
from foundora.agents.schema import AgentSchemaError
from foundora.agents.service import AgentRunRecord
from foundora.api.agents import _run_view
from foundora.knowledge.service import KnowledgeCitation, KnowledgeSearchHit
from foundora.model_gateway.service import GatewayResult
from foundora.models import AgentRun, AgentVersion
from foundora.search.provider import RegisteredKnowledgeSearchProvider, SearchRequest

CONTEXT_ID = "a" * 64
CONTEXT_SHA256 = "b" * 64
EVIDENCE_ID = "00000000-0000-0000-0000-000000001611"
SOURCE = "https://example.com/acme-research"
RETRIEVAL_DATE = "2026-08-25"
QUERY = "Which cited competitors and positioning are documented?"


def _evidence() -> dict[str, object]:
    return {
        "evidence_id": EVIDENCE_ID,
        "source": SOURCE,
        "source_title": "Founder competitor notes",
        "retrieval_date": RETRIEVAL_DATE,
        "retrieved_at": "2026-08-25T08:00:00Z",
        "excerpt": "Acme positions its annual plan around predictable onboarding.",
        "content_sha256": "c" * 64,
    }


def _structured_input(*, with_evidence: bool = True) -> dict[str, object]:
    return {
        "objective": "Prepare competitor intelligence",
        "context_id": CONTEXT_ID,
        "context_sha256": CONTEXT_SHA256,
        "business_context": {"sources": []},
        "research": {
            "provider": "registered_knowledge",
            "query": QUERY,
            "evidence": [_evidence()] if with_evidence else [],
        },
    }


def _supported_output() -> dict[str, object]:
    return {
        "research_status": "evidence_backed",
        "context_id": CONTEXT_ID,
        "research_query": QUERY,
        "summary": "One source-backed competitor finding is available.",
        "findings": [
            {
                "finding_id": "F1",
                "category": "positioning",
                "subject": "Acme",
                "claim": "Acme positions its annual plan around predictable onboarding.",
                "supported": True,
                "sources": [
                    {
                        "evidence_id": EVIDENCE_ID,
                        "source": SOURCE,
                        "retrieval_date": RETRIEVAL_DATE,
                    }
                ],
                "confidence": "high",
                "limitations": ["Only one founder-registered source was retrieved."],
            }
        ],
        "overall_limitations": ["No public-web search was performed."],
    }


def _unsupported_output(category: str) -> dict[str, object]:
    return {
        "research_status": "insufficient_evidence",
        "context_id": CONTEXT_ID,
        "research_query": QUERY,
        "summary": "The requested claim is not supported by registered evidence.",
        "findings": [
            {
                "finding_id": "F1",
                "category": category,
                "subject": "unknown",
                "claim": "No evidence-backed conclusion is available.",
                "supported": False,
                "sources": [],
                "confidence": "unknown",
                "limitations": ["No matching registered source evidence was retrieved."],
            }
        ],
        "overall_limitations": ["Research evidence is unavailable."],
    }


def _claim(agent_id: str) -> ExecutionClaim:
    return ExecutionClaim(
        run_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        agent_id=agent_id,
        version=1,
        role="Research specialist",
        purpose="Produce source-backed research",
        structured_input=_structured_input(),
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        model_policy={
            "task_type": "research.competitor.analyze",
            "sensitivity": "sensitive",
            "allow_fallback": False,
            "max_output_tokens": 1000,
            "token_budget": 10000,
            "cost_budget_microusd": 10000,
        },
        forbidden_actions=["Inventing competitor data", "External side effects"],
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

    async def claim(self, _: uuid.UUID, __: uuid.UUID) -> ExecutionClaim:
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
        self.system_prompt = ""

    async def generate(
        self,
        _: uuid.UUID,
        request: object,
        *,
        operation_id: uuid.UUID | None = None,
        agent_run_id: uuid.UUID | None = None,
    ) -> GatewayResult:
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


def test_supported_research_requires_exact_source_and_retrieval_date() -> None:
    output = _supported_output()
    validate_research_output(COMPETITOR_INTELLIGENCE_AGENT_ID, _structured_input(), output)

    findings = output["findings"]
    assert isinstance(findings, list) and isinstance(findings[0], dict)
    sources = findings[0]["sources"]
    assert isinstance(sources, list) and isinstance(sources[0], dict)
    sources[0]["retrieval_date"] = "2026-08-24"
    with pytest.raises(AgentSchemaError, match="does not match pinned"):
        validate_research_output(COMPETITOR_INTELLIGENCE_AGENT_ID, _structured_input(), output)

    invented = _supported_output()
    invented_findings = invented["findings"]
    assert isinstance(invented_findings, list) and isinstance(invented_findings[0], dict)
    invented_findings[0]["claim"] = "Acme charges a verified monthly price of $99."
    with pytest.raises(AgentSchemaError, match="not an extractive statement"):
        validate_research_output(COMPETITOR_INTELLIGENCE_AGENT_ID, _structured_input(), invented)


def test_unsupported_claims_are_flagged_and_cannot_claim_sources() -> None:
    output = _unsupported_output("market_gap")
    validate_research_output(
        MARKET_RESEARCH_AGENT_ID, _structured_input(with_evidence=False), output
    )

    findings = output["findings"]
    assert isinstance(findings, list) and isinstance(findings[0], dict)
    findings[0]["limitations"] = []
    with pytest.raises(AgentSchemaError, match="must state a limitation"):
        validate_research_output(
            MARKET_RESEARCH_AGENT_ID, _structured_input(with_evidence=False), output
        )


def test_competitor_names_must_appear_in_cited_evidence() -> None:
    output = _supported_output()
    findings = output["findings"]
    assert isinstance(findings, list) and isinstance(findings[0], dict)
    findings[0]["subject"] = "InventedCo"
    with pytest.raises(AgentSchemaError, match="competitor data cannot be invented"):
        validate_research_output(COMPETITOR_INTELLIGENCE_AGENT_ID, _structured_input(), output)

    unsupported = _unsupported_output("whitespace")
    unsupported_findings = unsupported["findings"]
    assert isinstance(unsupported_findings, list)
    assert isinstance(unsupported_findings[0], dict)
    unsupported_findings[0]["subject"] = "InventedCo"
    with pytest.raises(AgentSchemaError, match="must be unknown"):
        validate_research_output(
            COMPETITOR_INTELLIGENCE_AGENT_ID,
            _structured_input(with_evidence=False),
            unsupported,
        )


def test_each_research_role_enforces_its_own_categories() -> None:
    customer = _unsupported_output("pain_point")
    validate_research_output(
        CUSTOMER_RESEARCH_AGENT_ID, _structured_input(with_evidence=False), customer
    )
    with pytest.raises(AgentSchemaError, match="invalid for this research role"):
        validate_research_output(
            MARKET_RESEARCH_AGENT_ID, _structured_input(with_evidence=False), customer
        )


@pytest.mark.asyncio
async def test_runtime_persists_only_semantically_valid_research() -> None:
    claim = _claim(COMPETITOR_INTELLIGENCE_AGENT_ID)
    repository = _Repository(claim)
    gateway = _Gateway(_supported_output())

    await AgentRuntime(repository=repository, gateway=gateway).execute(claim.run_id)

    assert repository.completed == _supported_output()
    assert repository.failure is None
    assert "source-backed research only" in gateway.system_prompt
    assert EVIDENCE_ID in gateway.system_prompt

    invalid = _supported_output()
    findings = invalid["findings"]
    assert isinstance(findings, list) and isinstance(findings[0], dict)
    findings[0]["subject"] = "InventedCo"
    invalid_repository = _Repository(claim)
    await AgentRuntime(repository=invalid_repository, gateway=_Gateway(invalid)).execute(
        claim.run_id
    )
    assert invalid_repository.completed is None
    assert invalid_repository.failure is not None
    assert invalid_repository.failure[0] == "agent_schema_invalid"


def test_run_view_exposes_source_backed_research_trace() -> None:
    now = datetime.now(UTC)
    claim = _claim(COMPETITOR_INTELLIGENCE_AGENT_ID)
    version_id = uuid.uuid4()
    run = AgentRun(
        id=claim.run_id,
        business_id=claim.business_id,
        agent_id=claim.agent_id,
        agent_version_id=version_id,
        skill_version_id=None,
        status="completed",
        structured_input=claim.structured_input,
        structured_output=_supported_output(),
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
        agent_id=claim.agent_id,
        version=1,
        role="Research specialist",
        purpose="Research",
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

    assert view.research_trace is not None
    assert view.research_trace.provider == "registered_knowledge"
    assert view.research_trace.query == QUERY
    assert view.research_trace.evidence[0].source == SOURCE
    assert view.research_trace.evidence[0].retrieval_date == RETRIEVAL_DATE
    assert view.research_trace.output_validated is True


class _DatabaseContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_: object) -> None:
        return None


class _SessionFactory:
    def __call__(self) -> _DatabaseContext:
        return _DatabaseContext()


@pytest.mark.asyncio
async def test_registered_knowledge_adapter_returns_durable_citations() -> None:
    now = datetime.now(UTC)
    citation = KnowledgeCitation(
        source_id=uuid.uuid4(),
        source_title="Founder competitor notes",
        source_uri=SOURCE,
        document_id=uuid.uuid4(),
        filename="competitors.md",
        document_content_sha256="d" * 64,
        document_created_at=now,
        chunk_id=uuid.UUID(EVIDENCE_ID),
        chunk_ordinal=0,
        start_character=0,
        end_character=68,
        content_sha256="c" * 64,
    )
    with patch(
        "foundora.search.provider.search_knowledge",
        new=AsyncMock(
            return_value=[
                KnowledgeSearchHit(
                    score=0.91,
                    text="Acme positions its annual plan around predictable onboarding.",
                    citation=citation,
                )
            ]
        ),
    ):
        provider = RegisteredKnowledgeSearchProvider(session_factory=_SessionFactory())  # type: ignore[arg-type]
        results = await provider.search(
            SearchRequest(business_id=uuid.uuid4(), query="Acme positioning")
        )

    assert provider.provider_id == "registered_knowledge"
    assert len(results) == 1
    assert results[0].evidence_id == EVIDENCE_ID
    assert results[0].source == SOURCE
    assert results[0].source_title == "Founder competitor notes"
    assert results[0].retrieval_date == datetime.now(UTC).date().isoformat()
    assert results[0].content_sha256 == "c" * 64
    assert research_prompt_constraints("runtime-verification-agent", {}) == ""
