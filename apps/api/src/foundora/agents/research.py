from __future__ import annotations

from foundora.agents.schema import AgentSchemaError

MARKET_RESEARCH_AGENT_ID = "market-research"
COMPETITOR_INTELLIGENCE_AGENT_ID = "competitor-intelligence"
CUSTOMER_RESEARCH_AGENT_ID = "customer-research"
RESEARCH_AGENT_IDS = frozenset(
    {
        MARKET_RESEARCH_AGENT_ID,
        COMPETITOR_INTELLIGENCE_AGENT_ID,
        CUSTOMER_RESEARCH_AGENT_ID,
    }
)

_CATEGORIES = {
    MARKET_RESEARCH_AGENT_ID: frozenset(
        {"trend", "demand_signal", "market_evidence", "market_gap"}
    ),
    COMPETITOR_INTELLIGENCE_AGENT_ID: frozenset(
        {"positioning", "pricing", "feature", "strength", "weakness", "whitespace"}
    ),
    CUSTOMER_RESEARCH_AGENT_ID: frozenset(
        {
            "icp",
            "persona",
            "job_to_be_done",
            "pain_point",
            "buying_trigger",
            "objection",
        }
    ),
}
_CONFIDENCE = frozenset({"high", "medium", "low", "unknown"})


def _research_input(structured_input: dict[str, object]) -> dict[str, object]:
    value = structured_input.get("research")
    if not isinstance(value, dict):
        raise AgentSchemaError("Research input is missing its evidence trace")
    return value


def _evidence_by_id(structured_input: dict[str, object]) -> dict[str, dict[str, object]]:
    evidence = _research_input(structured_input).get("evidence")
    if not isinstance(evidence, list) or not all(isinstance(item, dict) for item in evidence):
        raise AgentSchemaError("Research evidence trace is invalid")
    result: dict[str, dict[str, object]] = {}
    for item in evidence:
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in result:
            raise AgentSchemaError("Research evidence identities are invalid")
        result[evidence_id] = item
    return result


def _object_list(value: object, path: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise AgentSchemaError(f"{path} must contain objects")
    return value


def _string_list(value: object, path: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AgentSchemaError(f"{path} must contain strings")
    if required and not value:
        raise AgentSchemaError(f"{path} must contain at least one item")
    return value


def _validate_source(
    source: dict[str, object], evidence: dict[str, dict[str, object]], path: str
) -> dict[str, object]:
    evidence_id = source.get("evidence_id")
    if not isinstance(evidence_id, str) or evidence_id not in evidence:
        raise AgentSchemaError(f"{path}.evidence_id is not in the pinned search evidence")
    pinned = evidence[evidence_id]
    for key in ("source", "retrieval_date"):
        if source.get(key) != pinned.get(key):
            raise AgentSchemaError(f"{path}.{key} does not match pinned search evidence")
    return pinned


def _validate_competitor_subject(
    subject: object, cited_evidence: list[dict[str, object]], path: str
) -> None:
    if not isinstance(subject, str) or not subject.strip():
        raise AgentSchemaError(f"{path}.subject is invalid")
    normalized = " ".join(subject.casefold().split())
    if not any(
        normalized
        in " ".join(f"{item.get('source_title', '')} {item.get('excerpt', '')}".casefold().split())
        for item in cited_evidence
    ):
        raise AgentSchemaError(
            f"{path}.subject is not named in its cited evidence; competitor data cannot be invented"
        )


def _validate_extractive_claim(
    claim: object, cited_evidence: list[dict[str, object]], path: str
) -> None:
    if not isinstance(claim, str) or not claim.strip():
        raise AgentSchemaError(f"{path}.claim is invalid")
    normalized = " ".join(claim.casefold().split())
    if not any(
        normalized in " ".join(str(item.get("excerpt", "")).casefold().split())
        for item in cited_evidence
    ):
        raise AgentSchemaError(
            f"{path}.claim is not an extractive statement from its cited evidence"
        )


def validate_research_output(
    agent_id: str,
    structured_input: dict[str, object],
    output: dict[str, object],
) -> None:
    if agent_id not in RESEARCH_AGENT_IDS:
        return
    research = _research_input(structured_input)
    evidence = _evidence_by_id(structured_input)
    if output.get("context_id") != structured_input.get("context_id"):
        raise AgentSchemaError("Research output context_id does not match the run snapshot")
    if output.get("research_query") != research.get("query"):
        raise AgentSchemaError("Research output query does not match the pinned search query")
    findings = _object_list(output.get("findings"), "$.findings")
    if not findings:
        raise AgentSchemaError("$.findings must contain at least one supported or flagged claim")
    identifiers: set[str] = set()
    supported_count = 0
    for index, finding in enumerate(findings):
        path = f"$.findings[{index}]"
        finding_id = finding.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id or finding_id in identifiers:
            raise AgentSchemaError(f"{path}.finding_id is invalid or duplicated")
        identifiers.add(finding_id)
        if finding.get("category") not in _CATEGORIES[agent_id]:
            raise AgentSchemaError(f"{path}.category is invalid for this research role")
        if finding.get("confidence") not in _CONFIDENCE:
            raise AgentSchemaError(f"{path}.confidence is invalid")
        limitations = _string_list(finding.get("limitations"), f"{path}.limitations")
        sources = _object_list(finding.get("sources"), f"{path}.sources")
        supported = finding.get("supported")
        if not isinstance(supported, bool):
            raise AgentSchemaError(f"{path}.supported must be a boolean")
        if supported:
            if not sources:
                raise AgentSchemaError(f"{path} is marked supported without a source")
            supported_count += 1
        elif sources:
            raise AgentSchemaError(f"{path} is unsupported but claims a source")
        elif not limitations:
            raise AgentSchemaError(f"{path} is unsupported and must state a limitation")
        cited = [
            _validate_source(source, evidence, f"{path}.sources[{source_index}]")
            for source_index, source in enumerate(sources)
        ]
        if supported:
            _validate_extractive_claim(finding.get("claim"), cited, path)
        if agent_id == COMPETITOR_INTELLIGENCE_AGENT_ID and supported:
            _validate_competitor_subject(finding.get("subject"), cited, path)
        elif agent_id == COMPETITOR_INTELLIGENCE_AGENT_ID and finding.get("subject") != "unknown":
            raise AgentSchemaError(
                f"{path}.subject must be unknown when competitor evidence is unsupported"
            )
    status = output.get("research_status")
    expected_status = "evidence_backed" if supported_count else "insufficient_evidence"
    if status != expected_status:
        raise AgentSchemaError(
            f"Research status must be {expected_status} for the validated findings"
        )
    overall_limitations = _string_list(output.get("overall_limitations"), "$.overall_limitations")
    if not evidence and not overall_limitations:
        raise AgentSchemaError("Research without retrieved evidence must state overall limitations")


def research_prompt_constraints(agent_id: str, structured_input: dict[str, object]) -> str:
    if agent_id not in RESEARCH_AGENT_IDS:
        return ""
    evidence = _evidence_by_id(structured_input)
    citations = [
        {
            "evidence_id": evidence_id,
            "source": item.get("source"),
            "retrieval_date": item.get("retrieval_date"),
        }
        for evidence_id, item in evidence.items()
    ]
    return (
        " This is source-backed research only. Use only the pinned research evidence. "
        "Every supported finding must copy source citation fields exactly from this allowlist: "
        f"{citations}. A supported claim must be an exact extractive statement from a cited "
        "excerpt. Put interpretation only in the summary and keep it limited to validated "
        "findings. Flag unsupported claims with supported=false, no sources, confidence low or "
        "unknown, and explicit limitations. Never invent a competitor, customer fact, market "
        "statistic, price, feature, strength, weakness, or demand signal. Copy context_id and "
        "research_query exactly from the input."
    )
