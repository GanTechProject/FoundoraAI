from __future__ import annotations

from foundora.agents.schema import AgentSchemaError

PRODUCT_OFFER_AGENT_ID = "product-offer"


def strategy_item_references(
    strategy: dict[str, object], business_id: object, version: int
) -> set[str]:
    references: set[str] = set()
    for section, values in strategy.items():
        if not isinstance(values, list):
            continue
        for item in values:
            item_id = item.get("item_id") if isinstance(item, dict) else None
            if isinstance(item_id, str) and item_id:
                references.add(
                    f"approved_business_strategies/{business_id}/v{version}/{section}/{item_id}"
                )
    return references


def offer_strategy_allowlist(structured_input: dict[str, object]) -> set[str]:
    evidence = structured_input.get("offer_evidence")
    if not isinstance(evidence, dict):
        raise AgentSchemaError("Product and offer input is missing approved strategy evidence")
    references = evidence.get("strategy_item_refs")
    if (
        not isinstance(references, list)
        or not references
        or not all(isinstance(item, str) and item for item in references)
    ):
        raise AgentSchemaError("Product and offer strategy references are invalid")
    strategy = evidence.get("approved_strategy")
    if not isinstance(strategy, dict):
        raise AgentSchemaError("Product and offer input is missing its approved strategy")
    return set(references)


def _refs(item: dict[str, object], path: str, allowlist: set[str]) -> list[str]:
    references = item.get("strategy_item_refs")
    if not isinstance(references, list) or not references:
        raise AgentSchemaError(f"{path} is not tied to the approved strategy")
    if not all(isinstance(ref, str) and ref in allowlist for ref in references):
        raise AgentSchemaError(f"{path} cites an unpinned strategy item")
    return references


def validate_product_offer_output(
    agent_id: str,
    structured_input: dict[str, object],
    output: dict[str, object],
) -> None:
    if agent_id != PRODUCT_OFFER_AGENT_ID:
        return
    if output.get("portfolio_status") != "proposed":
        raise AgentSchemaError("Product and offer output must remain proposed")
    if output.get("context_id") != structured_input.get("context_id"):
        raise AgentSchemaError("Product and offer context_id does not match the run snapshot")
    allowlist = offer_strategy_allowlist(structured_input)

    segments = output.get("target_segments")
    products = output.get("products_services")
    packages = output.get("packages")
    if not isinstance(segments, list) or not segments:
        raise AgentSchemaError("$.target_segments must not be empty")
    if not isinstance(products, list) or not products:
        raise AgentSchemaError("$.products_services must not be empty")
    if not isinstance(packages, list) or not packages:
        raise AgentSchemaError("$.packages must not be empty")

    identifiers: set[str] = set()
    segment_ids: set[str] = set()
    product_ids: set[str] = set()
    benefit_ids: set[str] = set()
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise AgentSchemaError(f"$.target_segments[{index}] is invalid")
        identifier = segment.get("segment_id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise AgentSchemaError("Target segment identifiers must be unique")
        identifiers.add(identifier)
        segment_ids.add(identifier)
        _refs(segment, f"$.target_segments[{index}]", allowlist)

    for index, product in enumerate(products):
        if not isinstance(product, dict):
            raise AgentSchemaError(f"$.products_services[{index}] is invalid")
        identifier = product.get("product_id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise AgentSchemaError("Product and service identifiers must be unique")
        identifiers.add(identifier)
        product_ids.add(identifier)
        _refs(product, f"$.products_services[{index}]", allowlist)
        target_refs = product.get("target_segment_refs")
        if (
            not isinstance(target_refs, list)
            or not target_refs
            or not all(isinstance(ref, str) and ref in segment_ids for ref in target_refs)
        ):
            raise AgentSchemaError("Every product or service must target a defined segment")
        benefits = product.get("benefits")
        if not isinstance(benefits, list) or not benefits:
            raise AgentSchemaError("Every product or service must define benefits")
        for benefit_index, benefit in enumerate(benefits):
            if not isinstance(benefit, dict):
                raise AgentSchemaError("Product benefit is invalid")
            benefit_id = benefit.get("benefit_id")
            if not isinstance(benefit_id, str) or not benefit_id or benefit_id in identifiers:
                raise AgentSchemaError("Benefit identifiers must be unique")
            identifiers.add(benefit_id)
            benefit_ids.add(benefit_id)
            _refs(
                benefit,
                f"$.products_services[{index}].benefits[{benefit_index}]",
                allowlist,
            )

    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            raise AgentSchemaError(f"$.packages[{index}] is invalid")
        identifier = package.get("package_id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise AgentSchemaError("Package identifiers must be unique")
        identifiers.add(identifier)
        _refs(package, f"$.packages[{index}]", allowlist)
        for key, allowed, label in (
            ("product_refs", product_ids, "product or service"),
            ("target_segment_refs", segment_ids, "target segment"),
            ("included_benefit_refs", benefit_ids, "benefit"),
        ):
            values = package.get(key)
            if (
                not isinstance(values, list)
                or not values
                or not all(isinstance(ref, str) and ref in allowed for ref in values)
            ):
                raise AgentSchemaError(f"Every package must reference a defined {label}")
        pricing = package.get("pricing")
        if not isinstance(pricing, dict) or pricing.get("validation_status") != (
            "requires_validation"
        ):
            raise AgentSchemaError("Package pricing must remain explicitly unvalidated")


def product_offer_prompt_constraints(agent_id: str, structured_input: dict[str, object]) -> str:
    if agent_id != PRODUCT_OFFER_AGENT_ID:
        return ""
    references = sorted(offer_strategy_allowlist(structured_input))
    return (
        " Propose a product and offer portfolio; never claim it is approved, launched, "
        "sold, or externally validated. Define target segments, products/services with "
        "benefits, and packages with pricing. Every segment, product/service, benefit, and "
        "package must cite exact strategy_item_refs from this allowlist: "
        f"{references}. Resolve every internal reference to an item in this output. "
        "Use status=proposed throughout and validation_status=requires_validation for every "
        "price. Copy context_id exactly. Expose limitations and founder decisions."
    )
