from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime

import pytest

from foundora.agents.schema import AgentSchemaError
from foundora.agents.website_coding import (
    WEBSITE_BUILD_SKILL_ID,
    WEBSITE_CODING_AGENT_ID,
    WEBSITE_TOOL_IDS,
    specification_item_references,
    validate_website_coding_output,
    website_coding_prompt_constraints,
)
from foundora.business_brain.service import ContextService
from foundora.events.contracts import AUDIT_CONSUMER, consumers_for, validate_event
from foundora.models import WebsiteProjectVersion
from foundora.website_projects.tools import ControlledWebsiteBuilder, ControlledWebsiteToolError

SPECIFICATION_ID = "00000000-0000-0000-0000-000000002000"
CONTEXT_ID = "a" * 64


def _specification() -> dict[str, object]:
    requirement = {
        "statement": "Implement the approved requirement.",
        "target_page_ids": ["HOME"],
    }
    return {
        "site_objective": {"item_id": "OBJ1"},
        "sitemap": [{"page_id": "HOME", "path": "/"}],
        "page_specs": [
            {
                "page_id": "HOME",
                "path": "/",
                "sections": [{"section_id": "HERO"}],
            }
        ],
        "conversion_goals": [{"goal_id": "CONTACT"}],
        "seo_requirements": [{"item_id": "SEO1", **requirement}],
        "content_requirements": [{"item_id": "CONTENT1", **requirement}],
        "brand_constraints": [{"item_id": "BRAND1", **requirement}],
        "technical_requirements": [{"item_id": "TECH1", **requirement}],
    }


def _structured_input() -> dict[str, object]:
    specification = _specification()
    references = specification_item_references(specification, SPECIFICATION_ID, 1)
    return {
        "objective": "Generate the approved website",
        "business_context": {"sources": []},
        "context_id": CONTEXT_ID,
        "context_sha256": "b" * 64,
        "website_coding_evidence": {
            "website_specification_id": SPECIFICATION_ID,
            "website_specification_version": 1,
            "website_specification_source_agent_run_id": str(uuid.uuid4()),
            "website_specification_context_id": "c" * 64,
            "specification_item_refs": sorted(references),
            "approved_website_specification": specification,
            "requested_operation": "generate",
        },
        "skill": {
            "skill_id": WEBSITE_BUILD_SKILL_ID,
            "version": 1,
            "input": {"operation": "generate"},
        },
    }


def _html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Launch with confidence</title>
    <meta name="description" content="A clear path to a confident launch.">
    <link rel="stylesheet" href="/styles.css">
  </head>
  <body>
    <header><nav aria-label="Primary"><a href="/">Home</a></nav></header>
    <main><h1 id="hero">Launch with confidence</h1><p>Request a consultation.</p></main>
  </body>
</html>"""


def _output() -> dict[str, object]:
    references = sorted(specification_item_references(_specification(), SPECIFICATION_ID, 1))
    return {
        "project_operation": "generate",
        "context_id": CONTEXT_ID,
        "website_specification_id": SPECIFICATION_ID,
        "website_specification_version": 1,
        "project_title": "Launch website",
        "implementation_summary": "A complete dependency-free static website.",
        "dependency_manifest": {
            "manager": "none",
            "dependencies": [],
            "rationale": "No package is needed for this bounded build.",
        },
        "changes": [
            {
                "operation": "add",
                "path": "index.html",
                "media_type": "text/html",
                "content": _html(),
                "rationale": "Implements the approved home page.",
            },
            {
                "operation": "add",
                "path": "styles.css",
                "media_type": "text/css",
                "content": "body { color: #172033; background: #ffffff; }",
                "rationale": "Provides the approved visual foundation.",
            },
        ],
        "implementation_trace": [
            {
                "specification_ref": reference,
                "file_paths": [
                    "styles.css" if "/brand_constraints/" in reference else "index.html"
                ],
                "implementation_note": "Implemented directly in the controlled source tree.",
            }
            for reference in references
        ],
        "test_cases": [
            {
                "test_id": "HOME_TEXT",
                "page_path": "/",
                "assertions": [
                    {"kind": "contains_text", "value": "Launch with confidence"},
                    {"kind": "element_id", "value": "hero"},
                    {"kind": "link_target", "value": "/"},
                ],
            }
        ],
        "limitations": ["Deployment has not started."],
    }


def test_coding_output_requires_exact_specification_trace_and_safe_changes() -> None:
    validate_website_coding_output(WEBSITE_CODING_AGENT_ID, _structured_input(), _output())

    incomplete = _output()
    traces = incomplete["implementation_trace"]
    assert isinstance(traces, list)
    traces.pop()
    with pytest.raises(AgentSchemaError, match="Every approved website specification"):
        validate_website_coding_output(WEBSITE_CODING_AGENT_ID, _structured_input(), incomplete)

    traversal = _output()
    changes = traversal["changes"]
    assert isinstance(changes, list) and isinstance(changes[0], dict)
    changes[0]["path"] = "../index.html"
    with pytest.raises(AgentSchemaError, match="POSIX relative path"):
        validate_website_coding_output(WEBSITE_CODING_AGENT_ID, _structured_input(), traversal)


def test_controlled_builder_computes_real_build_and_quality_evidence() -> None:
    artifact = ControlledWebsiteBuilder().build(_structured_input(), _output())

    assert artifact.build_report["status"] == "passed"
    assert artifact.check_report["status"] == "passed"
    assert artifact.source_digest == artifact.build_digest
    assert {item["path"] for item in artifact.build_manifest} == {
        "index.html",
        "styles.css",
    }
    assert [item["tool_id"] for item in artifact.tool_audit] == [
        WEBSITE_TOOL_IDS[0],
        WEBSITE_TOOL_IDS[1],
        WEBSITE_TOOL_IDS[2],
        WEBSITE_TOOL_IDS[0],
        WEBSITE_TOOL_IDS[3],
    ]


def test_controlled_builder_rejects_external_and_failed_accessibility_source() -> None:
    external = _output()
    changes = external["changes"]
    assert isinstance(changes, list) and isinstance(changes[0], dict)
    changes[0]["content"] = _html().replace(
        "</head>", '<script src="https://example.com/site.js"></script></head>'
    )
    with pytest.raises(ControlledWebsiteToolError, match="external network reference"):
        ControlledWebsiteBuilder().build(_structured_input(), external)

    inaccessible = _output()
    inaccessible_changes = inaccessible["changes"]
    assert isinstance(inaccessible_changes, list) and isinstance(inaccessible_changes[0], dict)
    inaccessible_changes[0]["content"] = _html().replace(' lang="en"', "")
    with pytest.raises(ControlledWebsiteToolError, match="html lang is missing"):
        ControlledWebsiteBuilder().build(_structured_input(), inaccessible)

    prompt = website_coding_prompt_constraints(WEBSITE_CODING_AGENT_ID, _structured_input())
    assert "runtime—not you" in prompt
    assert "Never claim a build" in prompt
    assert "network access" in prompt


def test_verified_project_is_current_brain_metadata_and_transactional_event() -> None:
    now = datetime.now(UTC)
    project = WebsiteProjectVersion(
        id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        version=2,
        status="active",
        operation="modify",
        source_agent_run_id=uuid.uuid4(),
        source_website_specification_id=uuid.UUID(SPECIFICATION_ID),
        source_website_specification_version=1,
        base_project_id=uuid.uuid4(),
        base_project_version=1,
        context_id=CONTEXT_ID,
        source_files=[],
        dependency_manifest={"manager": "none", "dependencies": []},
        source_digest="d" * 64,
        build_digest="e" * 64,
        build_manifest=[],
        build_report={"status": "passed"},
        check_report={"status": "passed"},
        tool_audit=[],
        created_at=now,
        superseded_at=None,
    )
    candidate = ContextService._website_project_candidate(project)
    assert candidate.source_type == "website_project"
    assert candidate.authority == "controlled_verified_website_build"
    assert candidate.content["deployment_status"] == "not_started"
    stale = ContextService._website_project_candidate(project, validity="stale")
    assert stale.validity == "stale"

    contract = validate_event(
        "website_project.built",
        1,
        "website_project",
        {
            "business_id": str(project.business_id),
            "website_project_id": str(project.id),
            "website_project_version": project.version,
            "operation": project.operation,
            "source_agent_run_id": str(project.source_agent_run_id),
            "source_website_specification_id": str(project.source_website_specification_id),
            "source_website_specification_version": (project.source_website_specification_version),
            "source_digest": project.source_digest,
            "build_digest": project.build_digest,
            "build_status": "passed",
            "check_status": "passed",
        },
    )
    assert [consumer.name for consumer in consumers_for(contract.event_type)] == [
        AUDIT_CONSUMER.name
    ]


def test_modification_requires_exact_base_and_applies_update() -> None:
    initial_artifact = ControlledWebsiteBuilder().build(_structured_input(), _output())
    structured_input = copy.deepcopy(_structured_input())
    evidence = structured_input["website_coding_evidence"]
    skill = structured_input["skill"]
    assert isinstance(evidence, dict) and isinstance(skill, dict)
    evidence["requested_operation"] = "modify"
    evidence["base_project"] = {
        "project_id": str(uuid.uuid4()),
        "project_version": 1,
        "source_website_specification_id": SPECIFICATION_ID,
        "source_website_specification_version": 1,
        "source_digest": initial_artifact.source_digest,
        "build_digest": initial_artifact.build_digest,
        "dependency_manifest": initial_artifact.dependency_manifest,
        "source_files": initial_artifact.source_files,
    }
    skill["input"] = {"operation": "modify", "base_project_version": 1}
    output = _output()
    output["project_operation"] = "modify"
    output["changes"] = [
        {
            "operation": "update",
            "path": "index.html",
            "media_type": "text/html",
            "content": _html().replace("Request a consultation.", "Book a consultation."),
            "rationale": "Improve the approved conversion wording.",
        }
    ]
    validate_website_coding_output(WEBSITE_CODING_AGENT_ID, structured_input, output)
    artifact = ControlledWebsiteBuilder().build(structured_input, output)
    assert artifact.source_digest != initial_artifact.source_digest
    assert artifact.build_report["status"] == "passed"
