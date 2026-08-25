"""Add controlled website project generation and the coding agent.

Revision ID: 20260825_21
Revises: 20260825_20
Create Date: 2026-08-25
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_21"
down_revision: str | None = "20260825_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_ID = "website-coding"
AGENT_VERSION_ID = UUID("00000000-0000-0000-0000-000000002101")
SKILL_ID = "website-build"
SKILL_VERSION_ID = UUID("00000000-0000-0000-0000-000000002111")
TOOLS = [
    "foundora.repository.website",
    "foundora.filesystem.website",
    "foundora.dependencies.website",
    "foundora.checks.website",
]


def _strings(maximum: int, *, minimum: int = 0, length: int = 500) -> dict[str, object]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "items": {"type": "string", "minLength": 1, "maxLength": length},
    }


def _source_file_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "media_type", "content", "size_bytes", "sha256"],
        "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 180},
            "media_type": {"type": "string", "minLength": 1, "maxLength": 80},
            "content": {"type": "string", "minLength": 1, "maxLength": 96000},
            "size_bytes": {"type": "integer", "minimum": 1, "maximum": 96000},
            "sha256": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    }


def _base_project_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "project_id",
            "project_version",
            "source_website_specification_id",
            "source_website_specification_version",
            "source_digest",
            "build_digest",
            "dependency_manifest",
            "source_files",
        ],
        "properties": {
            "project_id": {"type": "string", "format": "uuid"},
            "project_version": {"type": "integer", "minimum": 1},
            "source_website_specification_id": {"type": "string", "format": "uuid"},
            "source_website_specification_version": {"type": "integer", "minimum": 1},
            "source_digest": {"type": "string", "minLength": 64, "maxLength": 64},
            "build_digest": {"type": "string", "minLength": 64, "maxLength": 64},
            "dependency_manifest": {"type": "object"},
            "source_files": {
                "type": "array",
                "maxItems": 48,
                "items": _source_file_schema(),
            },
        },
    }


def _skill_input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["operation"],
        "properties": {
            "operation": {"type": "string", "enum": ["generate", "modify"]},
            "base_project_version": {"type": "integer", "minimum": 1},
        },
    }


def _input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "objective",
            "business_context",
            "context_id",
            "context_sha256",
            "website_coding_evidence",
            "skill",
        ],
        "properties": {
            "objective": {"type": "string", "minLength": 1, "maxLength": 500},
            "business_context": {"type": "object"},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "context_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "website_coding_evidence": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "website_specification_id",
                    "website_specification_version",
                    "website_specification_source_agent_run_id",
                    "website_specification_context_id",
                    "specification_item_refs",
                    "approved_website_specification",
                    "requested_operation",
                ],
                "properties": {
                    "website_specification_id": {"type": "string", "format": "uuid"},
                    "website_specification_version": {"type": "integer", "minimum": 1},
                    "website_specification_source_agent_run_id": {
                        "type": "string",
                        "format": "uuid",
                    },
                    "website_specification_context_id": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64,
                    },
                    "specification_item_refs": _strings(256, minimum=1),
                    "approved_website_specification": {"type": "object"},
                    "requested_operation": {
                        "type": "string",
                        "enum": ["generate", "modify"],
                    },
                    "base_project": _base_project_schema(),
                },
            },
            "skill": {
                "type": "object",
                "additionalProperties": False,
                "required": ["skill_id", "version", "input"],
                "properties": {
                    "skill_id": {"type": "string", "const": SKILL_ID},
                    "version": {"type": "integer", "const": 1},
                    "input": _skill_input_schema(),
                },
            },
        },
    }


def _output_schema() -> dict[str, object]:
    change = {
        "type": "object",
        "additionalProperties": False,
        "required": ["operation", "path", "rationale"],
        "properties": {
            "operation": {"type": "string", "enum": ["add", "update", "delete"]},
            "path": {"type": "string", "minLength": 1, "maxLength": 180},
            "media_type": {
                "type": "string",
                "enum": [
                    "text/html",
                    "text/css",
                    "text/javascript",
                    "application/json",
                    "text/plain",
                ],
            },
            "content": {"type": "string", "minLength": 1, "maxLength": 96000},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 500},
        },
    }
    trace = {
        "type": "object",
        "additionalProperties": False,
        "required": ["specification_ref", "file_paths", "implementation_note"],
        "properties": {
            "specification_ref": {"type": "string", "minLength": 1, "maxLength": 500},
            "file_paths": _strings(12, minimum=1, length=180),
            "implementation_note": {"type": "string", "minLength": 1, "maxLength": 700},
        },
    }
    assertion = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "value"],
        "properties": {
            "kind": {
                "type": "string",
                "enum": [
                    "contains_text",
                    "element_id",
                    "link_target",
                    "meta_description",
                ],
            },
            "value": {"type": "string", "minLength": 1, "maxLength": 300},
        },
    }
    test_case = {
        "type": "object",
        "additionalProperties": False,
        "required": ["test_id", "page_path", "assertions"],
        "properties": {
            "test_id": {"type": "string", "minLength": 1, "maxLength": 80},
            "page_path": {"type": "string", "minLength": 1, "maxLength": 240},
            "assertions": {"type": "array", "minItems": 1, "maxItems": 12, "items": assertion},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "project_operation",
            "context_id",
            "website_specification_id",
            "website_specification_version",
            "project_title",
            "implementation_summary",
            "dependency_manifest",
            "changes",
            "implementation_trace",
            "test_cases",
            "limitations",
        ],
        "properties": {
            "project_operation": {"type": "string", "enum": ["generate", "modify"]},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "website_specification_id": {"type": "string", "format": "uuid"},
            "website_specification_version": {"type": "integer", "minimum": 1},
            "project_title": {"type": "string", "minLength": 1, "maxLength": 180},
            "implementation_summary": {"type": "string", "minLength": 1, "maxLength": 2000},
            "dependency_manifest": {
                "type": "object",
                "additionalProperties": False,
                "required": ["manager", "dependencies", "rationale"],
                "properties": {
                    "manager": {"type": "string", "const": "none"},
                    "dependencies": {"type": "array", "maxItems": 0, "items": {"type": "object"}},
                    "rationale": {"type": "string", "minLength": 1, "maxLength": 500},
                },
            },
            "changes": {"type": "array", "minItems": 1, "maxItems": 48, "items": change},
            "implementation_trace": {
                "type": "array",
                "minItems": 1,
                "maxItems": 256,
                "items": trace,
            },
            "test_cases": {"type": "array", "minItems": 1, "maxItems": 48, "items": test_case},
            "limitations": _strings(20, length=700),
        },
    }


def upgrade() -> None:
    op.create_table(
        "website_project_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("source_agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_website_specification_id", sa.Uuid(), nullable=False),
        sa.Column("source_website_specification_version", sa.Integer(), nullable=False),
        sa.Column("base_project_id", sa.Uuid(), nullable=True),
        sa.Column("base_project_version", sa.Integer(), nullable=True),
        sa.Column("context_id", sa.String(length=64), nullable=False),
        sa.Column("source_files", sa.JSON(), nullable=False),
        sa.Column("dependency_manifest", sa.JSON(), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("build_digest", sa.String(length=64), nullable=False),
        sa.Column("build_manifest", sa.JSON(), nullable=False),
        sa.Column("build_report", sa.JSON(), nullable=False),
        sa.Column("check_report", sa.JSON(), nullable=False),
        sa.Column("tool_audit", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_website_project_versions_version"),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')", name="ck_website_project_versions_status"
        ),
        sa.CheckConstraint(
            "operation IN ('generate', 'modify')", name="ck_website_project_versions_operation"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_agent_run_id"], ["agent_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_website_specification_id"],
            ["website_specification_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_project_id"], ["website_project_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "version", name="uq_website_project_versions_business_version"
        ),
        sa.UniqueConstraint("source_agent_run_id", name="uq_website_project_versions_source_run"),
    )
    op.create_index(
        "ix_website_project_versions_business_id",
        "website_project_versions",
        ["business_id"],
    )
    op.create_index("ix_website_project_versions_status", "website_project_versions", ["status"])
    op.create_index(
        "uq_website_project_versions_active_business",
        "website_project_versions",
        ["business_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    now = datetime.now(UTC)
    op.bulk_insert(
        sa.table(
            "agents",
            sa.column("id", sa.String()),
            sa.column("display_name", sa.String()),
            sa.column("enabled", sa.Boolean()),
            sa.column("current_version", sa.Integer()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": AGENT_ID,
                "display_name": "Website / Coding Agent",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "skills",
            sa.column("id", sa.String()),
            sa.column("display_name", sa.String()),
            sa.column("enabled", sa.Boolean()),
            sa.column("current_version", sa.Integer()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": SKILL_ID,
                "display_name": "Controlled Website Build",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "skill_versions",
            sa.column("id", sa.Uuid()),
            sa.column("skill_id", sa.String()),
            sa.column("version", sa.Integer()),
            sa.column("description", sa.Text()),
            sa.column("compatible_agents", sa.JSON()),
            sa.column("prerequisites", sa.JSON()),
            sa.column("input_schema", sa.JSON()),
            sa.column("output_schema", sa.JSON()),
            sa.column("tool_requirements", sa.JSON()),
            sa.column("workflow", sa.JSON()),
            sa.column("permissions", sa.JSON()),
            sa.column("risk_class", sa.String()),
            sa.column("test_fixtures", sa.JSON()),
            sa.column("evaluation_rubric", sa.JSON()),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": SKILL_VERSION_ID,
                "skill_id": SKILL_ID,
                "version": 1,
                "description": (
                    "Apply a complete declarative source change set to a bounded static website "
                    "tree and compute build and quality evidence without executing generated code."
                ),
                "compatible_agents": [AGENT_ID],
                "prerequisites": [
                    "A selected business",
                    "An exact current founder-approved website specification",
                    "A current exact base project for modification operations",
                ],
                "input_schema": _skill_input_schema(),
                "output_schema": _output_schema(),
                "tool_requirements": TOOLS,
                "workflow": [
                    "Pin the exact approved specification and optional current base tree",
                    "Generate a complete declarative file change set and specification trace",
                    "Apply changes through the bounded repository and filesystem tools",
                    "Resolve the reviewed dependency-free manifest",
                    "Materialize the build tree without executing generated code",
                    "Compute tests, lint, accessibility, technical SEO, and performance evidence",
                    "Persist an immutable project version only when every check passes",
                ],
                "permissions": TOOLS,
                "risk_class": "R1",
                "test_fixtures": [],
                "evaluation_rubric": [
                    "Every approved specification item maps to a resulting source file",
                    "All sitemap pages build into concrete HTML documents",
                    "Build and check statuses are computed only by controlled tools",
                    (
                        "Paths, sizes, dependencies, network access, and secret material "
                        "remain bounded"
                    ),
                    (
                        "No deployment, publication, provider selection, or generated "
                        "process execution occurs"
                    ),
                ],
                "created_at": now,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "agent_versions",
            sa.column("id", sa.Uuid()),
            sa.column("agent_id", sa.String()),
            sa.column("version", sa.Integer()),
            sa.column("role", sa.String()),
            sa.column("purpose", sa.Text()),
            sa.column("responsibilities", sa.JSON()),
            sa.column("non_responsibilities", sa.JSON()),
            sa.column("allowed_task_types", sa.JSON()),
            sa.column("allowed_skills", sa.JSON()),
            sa.column("allowed_tools", sa.JSON()),
            sa.column("forbidden_actions", sa.JSON()),
            sa.column("model_policy", sa.JSON()),
            sa.column("data_access_scope", sa.JSON()),
            sa.column("risk_level", sa.String()),
            sa.column("maximum_autonomy", sa.String()),
            sa.column("input_schema", sa.JSON()),
            sa.column("output_schema", sa.JSON()),
            sa.column("evaluation_criteria", sa.JSON()),
            sa.column("escalation_criteria", sa.JSON()),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": AGENT_VERSION_ID,
                "agent_id": AGENT_ID,
                "version": 1,
                "role": "Controlled website implementation specialist",
                "purpose": (
                    "Generate or modify a provider-neutral static website only from the exact "
                    "current approved specification, then delegate all source mutation and "
                    "verification to reviewed internal tools."
                ),
                "responsibilities": [
                    "Generate projects and complete source-change sets",
                    "Maintain a reviewed dependency manifest",
                    "Trace every implementation choice to the approved website specification",
                    "Provide page tests for controlled verification",
                ],
                "non_responsibilities": [
                    "Executing generated code or package lifecycle scripts",
                    "Sandbox controls, visual QA, deployment, domains, or publication",
                    "Selecting hosting, framework, CMS, analytics, or deployment providers",
                    "Claiming tool-computed build or quality results",
                ],
                "allowed_task_types": ["website.project.generate", "website.project.modify"],
                "allowed_skills": [SKILL_ID],
                "allowed_tools": TOOLS,
                "forbidden_actions": [
                    "Raw host repository or filesystem access",
                    "Absolute, hidden, traversal, symlink, executable, or credential file changes",
                    (
                        "Commands, subprocesses, package installation, network access, or "
                        "generated code execution"
                    ),
                    "Fabricated build, test, lint, accessibility, SEO, or performance success",
                    (
                        "Deployment, publication, domains, production credentials, or "
                        "provider configuration"
                    ),
                    "Implementing from a vague prompt without the exact approved specification",
                ],
                "model_policy": {
                    "task_type": "website.project.generate",
                    "sensitivity": "sensitive",
                    "allow_fallback": False,
                    "max_output_tokens": 24000,
                    "token_budget": 120000,
                    "cost_budget_microusd": 300000,
                    "context_token_budget": 18000,
                },
                "data_access_scope": {
                    "business_scope": "run.business_id",
                    "sources": [
                        "business_profile",
                        "approved_profile",
                        "approved_goals",
                        "products_services",
                        "brand",
                        "operating_context",
                        "relevant_memories",
                        "approved_strategy",
                        "website_specification",
                    ],
                    "approved_website_specification": "required_exact_current_version",
                    "base_project": "required_exact_current_version_for_modification",
                    "repository": "controlled_tool_only",
                    "filesystem": "controlled_temporary_tree_only",
                    "dependencies": "reviewed_empty_allowlist",
                    "generated_process_execution": "forbidden_until_phase_22",
                    "external_providers": "not_configured",
                },
                "risk_level": "R1",
                "maximum_autonomy": "manual_internal_execution",
                "input_schema": _input_schema(),
                "output_schema": _output_schema(),
                "evaluation_criteria": [
                    "The resulting project covers every approved specification item",
                    "The controlled build materializes every source file and sitemap page",
                    "Tests, lint, accessibility, technical SEO, and performance checks pass",
                    "Build success comes from computed artifact hashes and check evidence",
                    (
                        "No provider, deployment, network, secret, or generated execution "
                        "boundary is crossed"
                    ),
                ],
                "escalation_criteria": [
                    "No exact current approved website specification exists",
                    "A modification base is absent, stale, or changed",
                    "The requested implementation needs a dependency or external network resource",
                    "A controlled build or quality check fails",
                    (
                        "The request requires sandbox execution, deployment, domain, provider, "
                        "or production access"
                    ),
                ],
                "created_at": now,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "agent_skill_assignments",
            sa.column("agent_version_id", sa.Uuid()),
            sa.column("skill_version_id", sa.Uuid()),
            sa.column("assigned_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "agent_version_id": AGENT_VERSION_ID,
                "skill_version_id": SKILL_VERSION_ID,
                "assigned_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("website_project_versions")
    op.execute(
        sa.text(
            "DELETE FROM agent_messages WHERE run_id IN "
            "(SELECT id FROM agent_runs WHERE agent_version_id = :version_id)"
        ).bindparams(version_id=AGENT_VERSION_ID)
    )
    op.execute(
        sa.text("DELETE FROM agent_runs WHERE agent_version_id = :version_id").bindparams(
            version_id=AGENT_VERSION_ID
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM agent_skill_assignments WHERE agent_version_id = :version_id"
        ).bindparams(version_id=AGENT_VERSION_ID)
    )
    op.execute(
        sa.text("DELETE FROM agent_versions WHERE id = :version_id").bindparams(
            version_id=AGENT_VERSION_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM skill_versions WHERE id = :version_id").bindparams(
            version_id=SKILL_VERSION_ID
        )
    )
    op.execute(sa.text("DELETE FROM skills WHERE id = :skill_id").bindparams(skill_id=SKILL_ID))
    op.execute(sa.text("DELETE FROM agents WHERE id = :agent_id").bindparams(agent_id=AGENT_ID))
