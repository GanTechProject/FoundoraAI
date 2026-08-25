from __future__ import annotations

from foundora.agents.schema import AgentSchemaError

BRAND_STRATEGIST_AGENT_ID = "brand-strategist"
BRAND_SECTIONS = (
    "brand_strategy",
    "positioning",
    "naming_analysis",
    "voice",
    "messaging",
    "visual_direction",
    "brand_rules",
    "asset_references",
)


def product_offer_references(
    portfolio: dict[str, object], portfolio_id: object, version: int
) -> set[str]:
    references: set[str] = set()
    for section in ("target_segments", "products_services", "packages"):
        values = portfolio.get(section)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            identifier_key = {
                "target_segments": "segment_id",
                "products_services": "product_id",
                "packages": "package_id",
            }[section]
            identifier = item.get(identifier_key)
            if isinstance(identifier, str) and identifier:
                references.add(
                    f"product_offer_versions/{portfolio_id}/v{version}/{section}/{identifier}"
                )
            if section == "products_services":
                benefits = item.get("benefits")
                if not isinstance(benefits, list):
                    continue
                for benefit in benefits:
                    benefit_id = benefit.get("benefit_id") if isinstance(benefit, dict) else None
                    if isinstance(benefit_id, str) and benefit_id:
                        references.add(
                            f"product_offer_versions/{portfolio_id}/v{version}/"
                            f"benefits/{benefit_id}"
                        )
    return references


def brand_evidence_allowlists(
    structured_input: dict[str, object],
) -> tuple[set[str], set[str]]:
    evidence = structured_input.get("brand_evidence")
    if not isinstance(evidence, dict):
        raise AgentSchemaError("Brand input is missing approved strategy and offer evidence")
    strategy_refs = evidence.get("strategy_item_refs")
    offer_refs = evidence.get("product_offer_refs")
    if (
        not isinstance(strategy_refs, list)
        or not strategy_refs
        or not all(isinstance(item, str) and item for item in strategy_refs)
    ):
        raise AgentSchemaError("Brand strategy references are invalid")
    if (
        not isinstance(offer_refs, list)
        or not offer_refs
        or not all(isinstance(item, str) and item for item in offer_refs)
    ):
        raise AgentSchemaError("Brand product and offer references are invalid")
    if not isinstance(evidence.get("approved_strategy"), dict) or not isinstance(
        evidence.get("approved_product_offer"), dict
    ):
        raise AgentSchemaError("Brand input is missing its approved evidence payloads")
    return set(strategy_refs), set(offer_refs)


def _validate_refs(
    item: dict[str, object],
    path: str,
    strategy_allowlist: set[str],
    offer_allowlist: set[str],
) -> None:
    strategy_refs = item.get("strategy_item_refs")
    offer_refs = item.get("product_offer_refs")
    if not isinstance(strategy_refs, list) or not strategy_refs:
        raise AgentSchemaError(f"{path} is not tied to the approved strategy")
    if not isinstance(offer_refs, list) or not offer_refs:
        raise AgentSchemaError(f"{path} is not tied to the approved offer")
    if not all(isinstance(ref, str) and ref in strategy_allowlist for ref in strategy_refs):
        raise AgentSchemaError(f"{path} cites an unpinned strategy item")
    if not all(isinstance(ref, str) and ref in offer_allowlist for ref in offer_refs):
        raise AgentSchemaError(f"{path} cites an unpinned product or offer item")


def validate_brand_output(
    agent_id: str,
    structured_input: dict[str, object],
    output: dict[str, object],
) -> None:
    if agent_id != BRAND_STRATEGIST_AGENT_ID:
        return
    if output.get("brand_status") != "proposed":
        raise AgentSchemaError("Brand output must remain proposed")
    if output.get("context_id") != structured_input.get("context_id"):
        raise AgentSchemaError("Brand output context_id does not match the run snapshot")
    strategy_allowlist, offer_allowlist = brand_evidence_allowlists(structured_input)
    identifiers: set[str] = set()
    for section in BRAND_SECTIONS:
        values = output.get(section)
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(item, dict) for item in values)
        ):
            raise AgentSchemaError(f"$.{section} must contain at least one brand item")
        for index, item in enumerate(values):
            path = f"$.{section}[{index}]"
            item_id = item.get("item_id")
            if not isinstance(item_id, str) or not item_id or item_id in identifiers:
                raise AgentSchemaError(f"{path}.item_id is invalid or duplicated")
            identifiers.add(item_id)
            _validate_refs(item, path, strategy_allowlist, offer_allowlist)
            if section == "naming_analysis" and item.get("availability_status") != "not_checked":
                raise AgentSchemaError("Brand names must not claim availability checks")
            if section == "asset_references" and item.get("reference_status") != (
                "proposed_reference"
            ):
                raise AgentSchemaError("Brand assets must remain proposed references")
    tagline = output.get("tagline")
    if not isinstance(tagline, dict):
        raise AgentSchemaError("$.tagline must contain one brand item")
    tagline_id = tagline.get("item_id")
    if not isinstance(tagline_id, str) or not tagline_id or tagline_id in identifiers:
        raise AgentSchemaError("$.tagline.item_id is invalid or duplicated")
    _validate_refs(tagline, "$.tagline", strategy_allowlist, offer_allowlist)


def brand_prompt_constraints(agent_id: str, structured_input: dict[str, object]) -> str:
    if agent_id != BRAND_STRATEGIST_AGENT_ID:
        return ""
    strategy_refs, offer_refs = brand_evidence_allowlists(structured_input)
    return (
        " Propose a brand system; never claim founder approval, publication, asset creation, "
        "trademark/domain availability, or external validation. Populate brand strategy, "
        "positioning, naming analysis, voice, messaging, visual direction, reusable brand "
        "rules, and asset references. Every item must cite at least one exact "
        "strategy_item_ref and product_offer_ref from these allowlists: "
        f"strategy={sorted(strategy_refs)}; product/offer={sorted(offer_refs)}. "
        "Use brand_status=proposed, availability_status=not_checked for naming analysis, "
        "and reference_status=proposed_reference for assets. Copy context_id exactly. "
        "Expose limitations and decisions requiring founder review."
    )
