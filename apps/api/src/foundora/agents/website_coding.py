from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

from foundora.agents.schema import AgentSchemaError

WEBSITE_CODING_AGENT_ID = "website-coding"
WEBSITE_BUILD_SKILL_ID = "website-build"
WEBSITE_TOOL_IDS = (
    "foundora.repository.website",
    "foundora.filesystem.website",
    "foundora.dependencies.website",
    "foundora.checks.website",
)
ALLOWED_SOURCE_SUFFIXES = frozenset({".html", ".css", ".js", ".json", ".txt"})
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _items(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def validate_project_path(value: object, path: str = "$.changes[].path") -> str:
    if not isinstance(value, str) or not value or len(value) > 180:
        raise AgentSchemaError(f"{path} must be a bounded relative path")
    if "\\" in value or value.startswith(("/", ".")):
        raise AgentSchemaError(f"{path} must use a non-hidden POSIX relative path")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or not all(_SEGMENT.fullmatch(part) for part in candidate.parts)
        or candidate.suffix.lower() not in ALLOWED_SOURCE_SUFFIXES
    ):
        raise AgentSchemaError(f"{path} is outside the controlled website source tree")
    return candidate.as_posix()


def specification_item_references(
    specification: dict[str, object], specification_id: str, version: int
) -> set[str]:
    prefix = f"website_specification_versions/{specification_id}/v{version}"
    references: set[str] = set()
    objective = specification.get("site_objective")
    if isinstance(objective, dict) and isinstance(objective.get("item_id"), str):
        references.add(f"{prefix}/site_objective/{objective['item_id']}")
    for page in _items(specification.get("sitemap")):
        if isinstance(page, dict) and isinstance(page.get("page_id"), str):
            references.add(f"{prefix}/sitemap/{page['page_id']}")
    for page in _items(specification.get("page_specs")):
        if not isinstance(page, dict) or not isinstance(page.get("page_id"), str):
            continue
        page_prefix = f"{prefix}/page_specs/{page['page_id']}"
        references.add(page_prefix)
        for section in _items(page.get("sections")):
            if isinstance(section, dict) and isinstance(section.get("section_id"), str):
                references.add(f"{page_prefix}/sections/{section['section_id']}")
    for goal in _items(specification.get("conversion_goals")):
        if isinstance(goal, dict) and isinstance(goal.get("goal_id"), str):
            references.add(f"{prefix}/conversion_goals/{goal['goal_id']}")
    for collection in (
        "seo_requirements",
        "content_requirements",
        "brand_constraints",
        "technical_requirements",
    ):
        for item in _items(specification.get(collection)):
            if isinstance(item, dict) and isinstance(item.get("item_id"), str):
                references.add(f"{prefix}/{collection}/{item['item_id']}")
    return references


def website_coding_evidence(
    structured_input: dict[str, object],
) -> tuple[dict[str, object], set[str], set[str]]:
    evidence = structured_input.get("website_coding_evidence")
    if not isinstance(evidence, dict):
        raise AgentSchemaError("Website coding evidence is missing")
    specification = evidence.get("approved_website_specification")
    specification_id = evidence.get("website_specification_id")
    specification_version = evidence.get("website_specification_version")
    supplied_refs = evidence.get("specification_item_refs")
    if (
        not isinstance(specification, dict)
        or not isinstance(specification_id, str)
        or not isinstance(specification_version, int)
        or isinstance(specification_version, bool)
        or not isinstance(supplied_refs, list)
        or not all(isinstance(item, str) for item in supplied_refs)
    ):
        raise AgentSchemaError("Website coding evidence is incomplete")
    expected_refs = specification_item_references(
        specification, specification_id, specification_version
    )
    if (
        not expected_refs
        or set(supplied_refs) != expected_refs
        or len(supplied_refs) != len(expected_refs)
    ):
        raise AgentSchemaError(
            "Website coding evidence does not contain the complete specification"
        )
    base = evidence.get("base_project")
    base_paths: set[str] = set()
    if base is not None:
        if not isinstance(base, dict):
            raise AgentSchemaError("Base website project evidence is malformed")
        base_files = base.get("source_files")
        if not isinstance(base_files, list):
            raise AgentSchemaError("Base website project evidence is malformed")
        for index, item in enumerate(base_files):
            if not isinstance(item, dict):
                raise AgentSchemaError("Base website project contains an invalid file")
            base_paths.add(validate_project_path(item.get("path"), f"$.base_project[{index}].path"))
    return evidence, expected_refs, base_paths


def _page_paths(specification: dict[str, object]) -> set[str]:
    return {
        path
        for page in _items(specification.get("sitemap"))
        if isinstance(page, dict) and isinstance((path := page.get("path")), str)
    }


def validate_website_coding_output(
    agent_id: str, structured_input: dict[str, object], output: dict[str, object]
) -> None:
    if agent_id != WEBSITE_CODING_AGENT_ID:
        return
    evidence, expected_refs, base_paths = website_coding_evidence(structured_input)
    skill = structured_input.get("skill")
    if not isinstance(skill, dict) or skill.get("skill_id") != WEBSITE_BUILD_SKILL_ID:
        raise AgentSchemaError("Website Coding Agent requires its pinned build skill")
    skill_input = skill.get("input")
    requested_operation = skill_input.get("operation") if isinstance(skill_input, dict) else None
    operation = output.get("project_operation")
    if operation not in {"generate", "modify"} or operation != requested_operation:
        raise AgentSchemaError("Project operation does not match the founder request")
    if output.get("context_id") != structured_input.get("context_id"):
        raise AgentSchemaError("Website project context_id does not match the run snapshot")
    if output.get("website_specification_id") != evidence.get(
        "website_specification_id"
    ) or output.get("website_specification_version") != evidence.get(
        "website_specification_version"
    ):
        raise AgentSchemaError("Website project does not cite the pinned specification")
    if operation == "generate" and base_paths:
        raise AgentSchemaError("Generation cannot silently overwrite a current aligned project")
    if operation == "modify" and not base_paths:
        raise AgentSchemaError("Modification requires an exact current base project")

    manifest = output.get("dependency_manifest")
    if (
        not isinstance(manifest, dict)
        or manifest.get("manager") != "none"
        or manifest.get("dependencies") != []
    ):
        raise AgentSchemaError("Phase 21 permits only the reviewed dependency-free build profile")

    changes = output.get("changes")
    if not isinstance(changes, list) or not changes:
        raise AgentSchemaError("Website project must contain at least one controlled source change")
    changed_paths: set[str] = set()
    resulting_paths = set(base_paths)
    for index, change in enumerate(changes):
        if not isinstance(change, dict):
            raise AgentSchemaError(f"$.changes[{index}] must be an object")
        path = validate_project_path(change.get("path"), f"$.changes[{index}].path")
        if path in changed_paths:
            raise AgentSchemaError("A source path can be changed only once per run")
        changed_paths.add(path)
        action = change.get("operation")
        content = change.get("content")
        if action not in {"add", "update", "delete"}:
            raise AgentSchemaError("Source change operation is invalid")
        if operation == "generate" and action != "add":
            raise AgentSchemaError("Project generation may only add files to an empty tree")
        if action == "add":
            if path in resulting_paths or not isinstance(content, str) or not content:
                raise AgentSchemaError("Add operations require a new path and non-empty content")
            resulting_paths.add(path)
        elif action == "update":
            if path not in resulting_paths or not isinstance(content, str) or not content:
                raise AgentSchemaError("Update operations require an existing path and content")
        else:
            if path not in resulting_paths or content is not None:
                raise AgentSchemaError(
                    "Delete operations require an existing path and null content"
                )
            resulting_paths.remove(path)

    traces = output.get("implementation_trace")
    if not isinstance(traces, list) or not traces:
        raise AgentSchemaError("Implementation trace is missing")
    traced_refs: set[str] = set()
    for index, trace in enumerate(traces):
        if not isinstance(trace, dict) or not isinstance(trace.get("specification_ref"), str):
            raise AgentSchemaError(f"$.implementation_trace[{index}] is invalid")
        reference = trace["specification_ref"]
        if reference not in expected_refs or reference in traced_refs:
            raise AgentSchemaError(
                "Implementation trace contains an unknown or duplicate reference"
            )
        traced_refs.add(reference)
        file_paths = trace.get("file_paths")
        if not isinstance(file_paths, list) or not file_paths:
            raise AgentSchemaError("Every specification trace must cite an implemented file")
        for file_index, file_path in enumerate(file_paths):
            normalized = validate_project_path(
                file_path, f"$.implementation_trace[{index}].file_paths[{file_index}]"
            )
            if normalized not in resulting_paths:
                raise AgentSchemaError("Implementation trace cites a file absent from the result")
    if traced_refs != expected_refs:
        raise AgentSchemaError("Every approved website specification item must be implemented")

    specification = evidence["approved_website_specification"]
    assert isinstance(specification, dict)
    expected_page_paths = _page_paths(specification)
    test_cases = output.get("test_cases")
    if not isinstance(test_cases, list):
        raise AgentSchemaError("Website project tests are missing")
    tested_page_paths = {case.get("page_path") for case in test_cases if isinstance(case, dict)}
    if tested_page_paths != expected_page_paths:
        raise AgentSchemaError("Every sitemap page requires an explicit generated test case")


def website_coding_prompt_constraints(agent_id: str, structured_input: dict[str, object]) -> str:
    if agent_id != WEBSITE_CODING_AGENT_ID:
        return ""
    evidence, references, base_paths = website_coding_evidence(structured_input)
    identity = {
        key: evidence.get(key)
        for key in (
            "website_specification_id",
            "website_specification_version",
            "requested_operation",
        )
    }
    return (
        " Website Coding Agent constraints: produce only a declarative, complete source-change "
        "set for the controlled Website Build Skill. The runtime—not you—will apply files and "
        "compute build, test, lint, accessibility, SEO, and performance results. Never claim a "
        "build or check passed. Use only POSIX relative .html, .css, .js, .json, or .txt paths; "
        "never request host paths, hidden files, credentials, commands, processes, network access, "
        "package installation, deployment, publication, domains, or provider configuration. The "
        "dependency manifest must use manager 'none' with an empty dependency list. Implement "
        "every pinned specification reference exactly once in implementation_trace and provide "
        "one test case for every sitemap path. The pinned references are: "
        f"{json.dumps(sorted(references), ensure_ascii=False)}. Base source paths are: "
        f"{json.dumps(sorted(base_paths), ensure_ascii=False)}. Pinned evidence identity: "
        f"{json.dumps(identity, ensure_ascii=False)}."
    )
