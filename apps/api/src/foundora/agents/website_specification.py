from __future__ import annotations

from foundora.agents.schema import AgentSchemaError

WEBSITE_SPECIFICATION_AGENT_ID = "website-specification"
REQUIREMENT_SECTIONS = (
    "seo_requirements",
    "content_requirements",
    "brand_constraints",
    "technical_requirements",
)


def brand_system_references(
    brand_system: dict[str, object], brand_system_id: object, version: int
) -> set[str]:
    references: set[str] = set()
    for section in (
        "brand_strategy",
        "positioning",
        "naming_analysis",
        "voice",
        "messaging",
        "visual_direction",
        "brand_rules",
        "asset_references",
    ):
        values = brand_system.get(section)
        if not isinstance(values, list):
            continue
        for item in values:
            identifier = item.get("item_id") if isinstance(item, dict) else None
            if isinstance(identifier, str) and identifier:
                references.add(
                    f"brand_system_versions/{brand_system_id}/v{version}/{section}/{identifier}"
                )
    tagline = brand_system.get("tagline")
    tagline_id = tagline.get("item_id") if isinstance(tagline, dict) else None
    if isinstance(tagline_id, str) and tagline_id:
        references.add(f"brand_system_versions/{brand_system_id}/v{version}/tagline/{tagline_id}")
    return references


def website_specification_evidence_allowlists(
    structured_input: dict[str, object],
) -> tuple[set[str], set[str], set[str]]:
    evidence = structured_input.get("website_specification_evidence")
    if not isinstance(evidence, dict):
        raise AgentSchemaError(
            "Website specification input is missing approved strategy, offer, and brand evidence"
        )
    allowlists: list[set[str]] = []
    for key, label in (
        ("strategy_item_refs", "strategy"),
        ("product_offer_refs", "product and offer"),
        ("brand_item_refs", "brand"),
    ):
        values = evidence.get(key)
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(item, str) and item for item in values)
        ):
            raise AgentSchemaError(f"Website specification {label} references are invalid")
        allowlists.append(set(values))
    if (
        not isinstance(evidence.get("approved_strategy"), dict)
        or not isinstance(evidence.get("approved_product_offer"), dict)
        or not isinstance(evidence.get("approved_brand_system"), dict)
    ):
        raise AgentSchemaError("Website specification evidence payloads are incomplete")
    return allowlists[0], allowlists[1], allowlists[2]


def _validate_evidence_refs(
    item: dict[str, object],
    path: str,
    strategy_allowlist: set[str],
    offer_allowlist: set[str],
    brand_allowlist: set[str],
) -> None:
    for key, label, allowlist in (
        ("strategy_item_refs", "strategy", strategy_allowlist),
        ("product_offer_refs", "product or offer", offer_allowlist),
        ("brand_item_refs", "brand", brand_allowlist),
    ):
        values = item.get(key)
        if not isinstance(values, list) or not values:
            raise AgentSchemaError(f"{path} is not tied to approved {label} evidence")
        if not all(isinstance(ref, str) and ref in allowlist for ref in values):
            raise AgentSchemaError(f"{path} cites an unpinned {label} item")


def _validate_page_targets(item: dict[str, object], path: str, page_ids: set[str]) -> None:
    targets = item.get("target_page_ids")
    if not isinstance(targets, list) or not targets:
        raise AgentSchemaError(f"{path} must target at least one specified page")
    if not all(isinstance(page_id, str) and page_id in page_ids for page_id in targets):
        raise AgentSchemaError(f"{path} targets an unknown page")


def _validate_sitemap_tree(sitemap: list[dict[str, object]]) -> tuple[set[str], dict[str, str]]:
    page_ids: set[str] = set()
    paths: dict[str, str] = {}
    roots: list[str] = []
    parents: dict[str, str | None] = {}
    for index, page in enumerate(sitemap):
        path = f"$.sitemap[{index}]"
        page_id = page.get("page_id")
        route = page.get("path")
        parent = page.get("parent_page_id")
        if not isinstance(page_id, str) or not page_id or page_id in page_ids:
            raise AgentSchemaError(f"{path}.page_id is invalid or duplicated")
        if not isinstance(route, str) or not route.startswith("/") or route in paths:
            raise AgentSchemaError(f"{path}.path is invalid or duplicated")
        if parent is not None and not isinstance(parent, str):
            raise AgentSchemaError(f"{path}.parent_page_id is invalid")
        page_ids.add(page_id)
        paths[route] = page_id
        parents[page_id] = parent
        if route == "/" and parent is None:
            roots.append(page_id)
    if len(roots) != 1:
        raise AgentSchemaError("$.sitemap must contain exactly one root page at /")
    for page_id, parent in parents.items():
        if parent is not None and (parent not in page_ids or parent == page_id):
            raise AgentSchemaError("$.sitemap contains an invalid parent page")
        seen = {page_id}
        cursor = parent
        while cursor is not None:
            if cursor in seen:
                raise AgentSchemaError("$.sitemap contains a parent cycle")
            seen.add(cursor)
            cursor = parents.get(cursor)
    return page_ids, paths


def validate_website_specification_output(
    agent_id: str,
    structured_input: dict[str, object],
    output: dict[str, object],
) -> None:
    if agent_id != WEBSITE_SPECIFICATION_AGENT_ID:
        return
    if output.get("specification_status") != "proposed":
        raise AgentSchemaError("Website specification must remain proposed")
    if output.get("code_generation_status") != "not_started":
        raise AgentSchemaError("Website specification cannot claim code generation")
    if output.get("context_id") != structured_input.get("context_id"):
        raise AgentSchemaError("Website specification context_id does not match the run snapshot")
    strategy_refs, offer_refs, brand_refs = website_specification_evidence_allowlists(
        structured_input
    )
    site_objective = output.get("site_objective")
    if not isinstance(site_objective, dict):
        raise AgentSchemaError("$.site_objective is incomplete")
    objective_id = site_objective.get("item_id")
    if not isinstance(objective_id, str) or not objective_id.strip():
        raise AgentSchemaError("$.site_objective.item_id must be a non-empty string")
    _validate_evidence_refs(
        site_objective, "$.site_objective", strategy_refs, offer_refs, brand_refs
    )

    sitemap_value = output.get("sitemap")
    if (
        not isinstance(sitemap_value, list)
        or not sitemap_value
        or not all(isinstance(page, dict) for page in sitemap_value)
    ):
        raise AgentSchemaError("$.sitemap must contain at least one page")
    sitemap = sitemap_value
    page_ids, paths = _validate_sitemap_tree(sitemap)
    identifiers = {objective_id}
    for index, page in enumerate(sitemap):
        _validate_evidence_refs(page, f"$.sitemap[{index}]", strategy_refs, offer_refs, brand_refs)

    page_specs_value = output.get("page_specs")
    if (
        not isinstance(page_specs_value, list)
        or not page_specs_value
        or not all(isinstance(page, dict) for page in page_specs_value)
    ):
        raise AgentSchemaError("$.page_specs must specify every sitemap page")
    specified_pages: set[str] = set()
    section_ids: set[str] = set()
    deferred_section_goals: list[tuple[str, list[object]]] = []
    for index, page in enumerate(page_specs_value):
        path = f"$.page_specs[{index}]"
        page_id = page.get("page_id")
        route = page.get("path")
        if (
            not isinstance(page_id, str)
            or page_id not in page_ids
            or page_id in specified_pages
            or paths.get(str(route)) != page_id
        ):
            raise AgentSchemaError(f"{path} does not exactly match one sitemap page")
        specified_pages.add(page_id)
        _validate_evidence_refs(page, path, strategy_refs, offer_refs, brand_refs)
        sections = page.get("sections")
        if not isinstance(sections, list) or not sections:
            raise AgentSchemaError(f"{path}.sections must not be empty")
        for section_index, section in enumerate(sections):
            section_path = f"{path}.sections[{section_index}]"
            if not isinstance(section, dict):
                raise AgentSchemaError(f"{section_path} is invalid")
            section_id = section.get("section_id")
            if not isinstance(section_id, str) or not section_id or section_id in section_ids:
                raise AgentSchemaError(f"{section_path}.section_id is invalid or duplicated")
            section_ids.add(section_id)
            goal_refs = section.get("conversion_goal_refs")
            if not isinstance(goal_refs, list):
                raise AgentSchemaError(f"{section_path}.conversion_goal_refs is invalid")
            deferred_section_goals.append((section_path, goal_refs))
    if specified_pages != page_ids:
        raise AgentSchemaError("$.page_specs must cover every sitemap page exactly once")

    conversions = output.get("conversion_goals")
    if (
        not isinstance(conversions, list)
        or not conversions
        or not all(isinstance(item, dict) for item in conversions)
    ):
        raise AgentSchemaError("$.conversion_goals must contain at least one goal")
    conversion_ids: set[str] = set()
    for index, item in enumerate(conversions):
        path = f"$.conversion_goals[{index}]"
        identifier = item.get("goal_id")
        if not isinstance(identifier, str) or not identifier or identifier in conversion_ids:
            raise AgentSchemaError(f"{path}.goal_id is invalid or duplicated")
        conversion_ids.add(identifier)
        _validate_page_targets(item, path, page_ids)
        _validate_evidence_refs(item, path, strategy_refs, offer_refs, brand_refs)
    for path, goal_refs in deferred_section_goals:
        if not all(isinstance(ref, str) and ref in conversion_ids for ref in goal_refs):
            raise AgentSchemaError(f"{path} cites an unknown conversion goal")

    for section_name in REQUIREMENT_SECTIONS:
        values = output.get(section_name)
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(item, dict) for item in values)
        ):
            raise AgentSchemaError(f"$.{section_name} must contain at least one requirement")
        for index, item in enumerate(values):
            path = f"$.{section_name}[{index}]"
            item_id = item.get("item_id")
            if not isinstance(item_id, str) or not item_id or item_id in identifiers:
                raise AgentSchemaError(f"{path}.item_id is invalid or duplicated")
            identifiers.add(item_id)
            _validate_page_targets(item, path, page_ids)
            _validate_evidence_refs(item, path, strategy_refs, offer_refs, brand_refs)


def website_specification_prompt_constraints(
    agent_id: str, structured_input: dict[str, object]
) -> str:
    if agent_id != WEBSITE_SPECIFICATION_AGENT_ID:
        return ""
    strategy_refs, offer_refs, brand_refs = website_specification_evidence_allowlists(
        structured_input
    )
    return (
        " Produce a complete founder-reviewable website specification, never source code, "
        "file edits, dependency choices, builds, deployments, publication, or claims that "
        "implementation began. Include the site objective, a rooted acyclic sitemap, one "
        "page specification per sitemap page, conversion goals, SEO requirements, content "
        "requirements, brand constraints, and provider-neutral technical requirements. "
        "Every top-level artifact must cite exact approved strategy, product/offer, and "
        f"brand references from these allowlists: strategy={sorted(strategy_refs)}; "
        f"product/offer={sorted(offer_refs)}; brand={sorted(brand_refs)}. Use "
        "specification_status=proposed and code_generation_status=not_started, copy "
        "context_id exactly, and expose founder decisions and limitations."
    )
