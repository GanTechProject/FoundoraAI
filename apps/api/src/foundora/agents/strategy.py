from __future__ import annotations

from foundora.agents.schema import AgentSchemaError

BUSINESS_STRATEGIST_AGENT_ID = "business-strategist"
STRATEGY_SECTIONS = (
    "opportunity_assessment",
    "value_proposition",
    "business_model",
    "pricing_hypotheses",
    "positioning",
    "go_to_market",
    "launch_roadmap",
    "risks",
    "assumptions_requiring_validation",
)
_CONFIDENCE = frozenset({"high", "medium", "low", "unknown"})


def _strategy_evidence(structured_input: dict[str, object]) -> dict[str, object]:
    evidence = structured_input.get("strategy_evidence")
    if not isinstance(evidence, dict):
        raise AgentSchemaError("Strategy input is missing its evidence trace")
    return evidence


def evidence_allowlists(
    structured_input: dict[str, object],
) -> tuple[set[str], set[str]]:
    evidence = _strategy_evidence(structured_input)
    fact_refs = evidence.get("approved_fact_refs")
    research_runs = evidence.get("research_runs")
    if not isinstance(fact_refs, list) or not all(isinstance(item, str) for item in fact_refs):
        raise AgentSchemaError("Strategy approved-fact references are invalid")
    if not fact_refs:
        raise AgentSchemaError("Strategy requires at least one approved business fact")
    if not isinstance(research_runs, list) or not all(
        isinstance(item, dict) for item in research_runs
    ):
        raise AgentSchemaError("Strategy research-run evidence is invalid")
    finding_refs: set[str] = set()
    for research_run in research_runs:
        references = research_run.get("supported_finding_refs")
        if not isinstance(references, list) or not all(
            isinstance(item, str) for item in references
        ):
            raise AgentSchemaError("Strategy research finding references are invalid")
        finding_refs.update(references)
    if not finding_refs:
        raise AgentSchemaError("Strategy requires at least one supported research finding")
    return set(fact_refs), finding_refs


def validate_strategy_output(
    agent_id: str,
    structured_input: dict[str, object],
    output: dict[str, object],
) -> None:
    if agent_id != BUSINESS_STRATEGIST_AGENT_ID:
        return
    if output.get("strategy_status") != "proposed":
        raise AgentSchemaError("Business Strategist output must remain proposed")
    if output.get("context_id") != structured_input.get("context_id"):
        raise AgentSchemaError("Strategy output context_id does not match the run snapshot")
    approved_allowlist, research_allowlist = evidence_allowlists(structured_input)
    identifiers: set[str] = set()
    for section in STRATEGY_SECTIONS:
        items = output.get(section)
        if (
            not isinstance(items, list)
            or not items
            or not all(isinstance(item, dict) for item in items)
        ):
            raise AgentSchemaError(f"$.{section} must contain at least one strategy item")
        for index, item in enumerate(items):
            path = f"$.{section}[{index}]"
            item_id = item.get("item_id")
            if not isinstance(item_id, str) or not item_id or item_id in identifiers:
                raise AgentSchemaError(f"{path}.item_id is invalid or duplicated")
            identifiers.add(item_id)
            if item.get("confidence") not in _CONFIDENCE:
                raise AgentSchemaError(f"{path}.confidence is invalid")
            fact_refs = item.get("approved_fact_refs")
            research_refs = item.get("research_finding_refs")
            if not isinstance(fact_refs, list) or not fact_refs:
                raise AgentSchemaError(f"{path} is not tied to an approved business fact")
            if not isinstance(research_refs, list) or not research_refs:
                raise AgentSchemaError(f"{path} is not tied to research evidence")
            if not all(isinstance(ref, str) and ref in approved_allowlist for ref in fact_refs):
                raise AgentSchemaError(f"{path} cites an unpinned approved business fact")
            if not all(isinstance(ref, str) and ref in research_allowlist for ref in research_refs):
                raise AgentSchemaError(f"{path} cites an unpinned research finding")
            limitations = item.get("limitations")
            if not isinstance(limitations, list) or not all(
                isinstance(value, str) for value in limitations
            ):
                raise AgentSchemaError(f"{path}.limitations must contain strings")
            if section == "pricing_hypotheses" and item.get("validation_status") != (
                "requires_validation"
            ):
                raise AgentSchemaError("Pricing must remain a hypothesis requiring validation")
            if section == "assumptions_requiring_validation" and not item.get("validation_method"):
                raise AgentSchemaError(f"{path} must state a validation method")


def strategy_prompt_constraints(agent_id: str, structured_input: dict[str, object]) -> str:
    if agent_id != BUSINESS_STRATEGIST_AGENT_ID:
        return ""
    approved_refs, research_refs = evidence_allowlists(structured_input)
    return (
        " Produce a proposed business strategy, never an executed or approved strategy. "
        "Populate all nine strategy sections. Every item must cite at least one exact "
        "approved_fact_ref and one exact research_finding_ref from these allowlists: "
        f"approved facts={sorted(approved_refs)}; research findings={sorted(research_refs)}. "
        "Do not cite unsupported research findings. Pricing is a hypothesis and every pricing "
        "item must use validation_status=requires_validation. Every assumption must include a "
        "validation_method. Copy context_id exactly. Expose limitations and founder decisions; "
        "do not claim launch, approval, spending, delegation, contact, or external action."
    )
