"""Add evidence-linked founder-approved website specifications.

Revision ID: 20260825_20
Revises: 20260825_19
Create Date: 2026-08-25
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_20"
down_revision: str | None = "20260825_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_ID = "website-specification"
VERSION_ID = UUID("00000000-0000-0000-0000-000000002001")


def _strings(maximum: int, *, minimum: int = 0, length: int = 512) -> dict[str, object]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1, "maxLength": length},
    }


def _evidence_properties() -> dict[str, object]:
    return {
        "strategy_item_refs": _strings(12, minimum=1),
        "product_offer_refs": _strings(12, minimum=1),
        "brand_item_refs": _strings(12, minimum=1),
    }


def _input_schema() -> dict[str, object]:
    evidence_required = [
        "strategy_version",
        "strategy_source_agent_run_id",
        "strategy_context_id",
        "strategy_item_refs",
        "approved_strategy",
        "product_offer_id",
        "product_offer_version",
        "product_offer_source_agent_run_id",
        "product_offer_context_id",
        "product_offer_refs",
        "approved_product_offer",
        "brand_system_id",
        "brand_version",
        "brand_source_agent_run_id",
        "brand_context_id",
        "brand_item_refs",
        "approved_brand_system",
    ]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "objective",
            "business_context",
            "context_id",
            "context_sha256",
            "website_specification_evidence",
        ],
        "properties": {
            "objective": {"type": "string", "minLength": 1, "maxLength": 500},
            "business_context": {"type": "object"},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "context_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "website_specification_evidence": {
                "type": "object",
                "additionalProperties": False,
                "required": evidence_required,
                "properties": {
                    "strategy_version": {"type": "integer", "minimum": 1},
                    "strategy_source_agent_run_id": {"type": "string", "format": "uuid"},
                    "strategy_context_id": {"type": "string", "minLength": 64, "maxLength": 64},
                    "strategy_item_refs": _strings(144, minimum=1),
                    "approved_strategy": {"type": "object"},
                    "product_offer_id": {"type": "string", "format": "uuid"},
                    "product_offer_version": {"type": "integer", "minimum": 1},
                    "product_offer_source_agent_run_id": {
                        "type": "string",
                        "format": "uuid",
                    },
                    "product_offer_context_id": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64,
                    },
                    "product_offer_refs": _strings(128, minimum=1),
                    "approved_product_offer": {"type": "object"},
                    "brand_system_id": {"type": "string", "format": "uuid"},
                    "brand_version": {"type": "integer", "minimum": 1},
                    "brand_source_agent_run_id": {"type": "string", "format": "uuid"},
                    "brand_context_id": {"type": "string", "minLength": 64, "maxLength": 64},
                    "brand_item_refs": _strings(208, minimum=1),
                    "approved_brand_system": {"type": "object"},
                },
            },
        },
    }


def _common_artifact_properties(*, include_item_id: bool = True) -> dict[str, object]:
    properties: dict[str, object] = {
        "statement": {"type": "string", "minLength": 1, "maxLength": 2500},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 1500},
        **_evidence_properties(),
    }
    if include_item_id:
        properties["item_id"] = {"type": "string", "minLength": 1, "maxLength": 64}
    return properties


def _site_objective_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "item_id",
            "statement",
            "rationale",
            "strategy_item_refs",
            "product_offer_refs",
            "brand_item_refs",
        ],
        "properties": _common_artifact_properties(),
    }


def _sitemap_schema() -> dict[str, object]:
    properties = _common_artifact_properties(include_item_id=False)
    properties.update(
        {
            "page_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "path": {"type": "string", "pattern": "^/", "maxLength": 240},
            "label": {"type": "string", "minLength": 1, "maxLength": 160},
            "parent_page_id": {
                "type": ["string", "null"],
                "minLength": 1,
                "maxLength": 64,
            },
            "order": {"type": "integer", "minimum": 0, "maximum": 1000},
        }
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "page_id",
            "path",
            "label",
            "parent_page_id",
            "order",
            "statement",
            "rationale",
            "strategy_item_refs",
            "product_offer_refs",
            "brand_item_refs",
        ],
        "properties": properties,
    }


def _page_spec_schema() -> dict[str, object]:
    properties = _evidence_properties()
    properties.update(
        {
            "page_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "page_name": {"type": "string", "minLength": 1, "maxLength": 160},
            "path": {"type": "string", "pattern": "^/", "maxLength": 240},
            "purpose": {"type": "string", "minLength": 1, "maxLength": 2000},
            "primary_audience": {"type": "string", "minLength": 1, "maxLength": 1000},
            "sections": {
                "type": "array",
                "minItems": 1,
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "section_id",
                        "name",
                        "objective",
                        "content_requirements",
                        "conversion_goal_refs",
                    ],
                    "properties": {
                        "section_id": {"type": "string", "minLength": 1, "maxLength": 64},
                        "name": {"type": "string", "minLength": 1, "maxLength": 160},
                        "objective": {"type": "string", "minLength": 1, "maxLength": 1500},
                        "content_requirements": _strings(20, minimum=1, length=1000),
                        "conversion_goal_refs": _strings(12, length=64),
                    },
                },
            },
        }
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "page_id",
            "page_name",
            "path",
            "purpose",
            "primary_audience",
            "sections",
            "strategy_item_refs",
            "product_offer_refs",
            "brand_item_refs",
        ],
        "properties": properties,
    }


def _conversion_schema() -> dict[str, object]:
    properties = _common_artifact_properties(include_item_id=False)
    properties.update(
        {
            "goal_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "success_signal": {"type": "string", "minLength": 1, "maxLength": 1000},
            "target_page_ids": _strings(30, minimum=1, length=64),
        }
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "goal_id",
            "statement",
            "rationale",
            "success_signal",
            "target_page_ids",
            "strategy_item_refs",
            "product_offer_refs",
            "brand_item_refs",
        ],
        "properties": properties,
    }


def _requirement_schema(section: str) -> dict[str, object]:
    properties = _common_artifact_properties()
    properties["target_page_ids"] = _strings(30, minimum=1, length=64)
    additions: dict[str, dict[str, object]] = {
        "seo_requirements": {
            "category": {"enum": ["technical", "on_page", "metadata", "structured_data", "crawl"]},
            "acceptance_criteria": _strings(12, minimum=1, length=1000),
        },
        "content_requirements": {
            "content_type": {
                "enum": ["headline", "body", "proof", "offer", "cta", "legal", "media_brief"]
            },
            "owner": {"enum": ["founder", "future_content_agent", "shared"]},
        },
        "brand_constraints": {
            "constraint_type": {
                "enum": ["voice", "messaging", "visual", "naming", "accessibility", "asset"]
            }
        },
        "technical_requirements": {
            "category": {
                "enum": [
                    "architecture",
                    "accessibility",
                    "performance",
                    "security",
                    "compatibility",
                    "analytics",
                    "integration",
                ]
            },
            "acceptance_criteria": _strings(12, minimum=1, length=1000),
        },
    }
    required = [
        "item_id",
        "statement",
        "rationale",
        "target_page_ids",
        "strategy_item_refs",
        "product_offer_refs",
        "brand_item_refs",
    ]
    for name, schema in additions[section].items():
        properties[name] = schema
        required.append(name)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _output_schema() -> dict[str, object]:
    properties: dict[str, object] = {
        "specification_status": {"const": "proposed"},
        "code_generation_status": {"const": "not_started"},
        "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
        "project_title": {"type": "string", "minLength": 1, "maxLength": 240},
        "site_objective": _site_objective_schema(),
        "sitemap": {
            "type": "array",
            "minItems": 1,
            "maxItems": 30,
            "items": _sitemap_schema(),
        },
        "page_specs": {
            "type": "array",
            "minItems": 1,
            "maxItems": 30,
            "items": _page_spec_schema(),
        },
        "conversion_goals": {
            "type": "array",
            "minItems": 1,
            "maxItems": 30,
            "items": _conversion_schema(),
        },
        "founder_decisions_required": _strings(30, length=1000),
        "overall_limitations": _strings(30, length=1000),
    }
    for section in (
        "seo_requirements",
        "content_requirements",
        "brand_constraints",
        "technical_requirements",
    ):
        properties[section] = {
            "type": "array",
            "minItems": 1,
            "maxItems": 60,
            "items": _requirement_schema(section),
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def upgrade() -> None:
    op.create_table(
        "website_specification_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "source_agent_run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_strategy_version", sa.Integer(), nullable=False),
        sa.Column(
            "source_product_offer_id",
            sa.Uuid(),
            sa.ForeignKey("product_offer_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_product_offer_version", sa.Integer(), nullable=False),
        sa.Column(
            "source_brand_system_id",
            sa.Uuid(),
            sa.ForeignKey("brand_system_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_brand_version", sa.Integer(), nullable=False),
        sa.Column("context_id", sa.String(length=64), nullable=False),
        sa.Column("specification", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column(
            "approved_by_owner_id",
            sa.Uuid(),
            sa.ForeignKey("owners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_website_specification_versions_version"),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')",
            name="ck_website_specification_versions_status",
        ),
        sa.UniqueConstraint(
            "business_id", "version", name="uq_website_specification_versions_business_version"
        ),
        sa.UniqueConstraint(
            "source_agent_run_id", name="uq_website_specification_versions_source_run"
        ),
    )
    op.create_index(
        "ix_website_specification_versions_business_id",
        "website_specification_versions",
        ["business_id"],
    )
    op.create_index(
        "ix_website_specification_versions_status",
        "website_specification_versions",
        ["status"],
    )
    op.create_index(
        "uq_website_specification_versions_active_business",
        "website_specification_versions",
        ["business_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    now = datetime(2026, 8, 25, tzinfo=UTC)
    agents = sa.table(
        "agents",
        sa.column("id", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("current_version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        agents,
        [
            {
                "id": AGENT_ID,
                "display_name": "Website Specification Agent",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    versions = sa.table(
        "agent_versions",
        *[
            sa.column(name, column_type)
            for name, column_type in (
                ("id", sa.Uuid()),
                ("agent_id", sa.String()),
                ("version", sa.Integer()),
                ("role", sa.String()),
                ("purpose", sa.Text()),
                ("responsibilities", sa.JSON()),
                ("non_responsibilities", sa.JSON()),
                ("allowed_task_types", sa.JSON()),
                ("allowed_skills", sa.JSON()),
                ("allowed_tools", sa.JSON()),
                ("forbidden_actions", sa.JSON()),
                ("model_policy", sa.JSON()),
                ("data_access_scope", sa.JSON()),
                ("risk_level", sa.String()),
                ("maximum_autonomy", sa.String()),
                ("input_schema", sa.JSON()),
                ("output_schema", sa.JSON()),
                ("evaluation_criteria", sa.JSON()),
                ("escalation_criteria", sa.JSON()),
                ("created_at", sa.DateTime(timezone=True)),
            )
        ],
    )
    op.bulk_insert(
        versions,
        [
            {
                "id": VERSION_ID,
                "agent_id": AGENT_ID,
                "version": 1,
                "role": "Evidence-bound website specification architect",
                "purpose": (
                    "Propose a complete founder-reviewable website specification before "
                    "any code generation or source modification can begin."
                ),
                "responsibilities": [
                    "Define the site objective, sitemap, and one specification per page",
                    "Define conversion, SEO, content, brand, and technical requirements",
                    "Preserve exact approved strategy, offer, and brand traceability",
                    "Expose decisions and limitations for explicit founder review",
                ],
                "non_responsibilities": [
                    "Generating or editing source code, files, or dependencies",
                    "Running builds, tests, accessibility tools, or performance tools",
                    "Selecting hosting, deployment, domain, CMS, analytics, or framework providers",
                    "Publishing, deploying, or claiming implementation has begun",
                ],
                "allowed_task_types": ["website.specification.propose"],
                "allowed_skills": [],
                "allowed_tools": [],
                "forbidden_actions": [
                    "Inventing or citing unpinned strategy, offer, or brand items",
                    "Self-approval or claiming founder approval",
                    "Source code generation, repository access, or filesystem modification",
                    "Build, test, deployment, publication, domain, or hosting operations",
                    "Provider selection, credential access, tool invocation, or side effects",
                    "Creating tasks, workflows, policy, memory, knowledge, content, or campaigns",
                ],
                "model_policy": {
                    "task_type": "website.specification.propose",
                    "sensitivity": "sensitive",
                    "allow_fallback": False,
                    "max_output_tokens": 12000,
                    "token_budget": 70000,
                    "cost_budget_microusd": 180000,
                    "context_token_budget": 14000,
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
                    ],
                    "drafts": "forbidden",
                    "approved_strategy": "required_exact_current_version",
                    "approved_product_offer": "required_exact_active_version",
                    "approved_brand": "required_exact_active_version",
                    "approved_website_specification": "write_only_after_founder_approval",
                    "repository": "forbidden",
                    "filesystem": "forbidden",
                    "external_providers": "not_configured",
                },
                "risk_level": "R0",
                "maximum_autonomy": "manual_advisory_only",
                "input_schema": _input_schema(),
                "output_schema": _output_schema(),
                "evaluation_criteria": [
                    "Every Phase 20 artifact is complete and structured",
                    "The sitemap is rooted and every page has exactly one specification",
                    "All targets and conversion references resolve",
                    "Every artifact cites exact approved strategy, offer, and brand evidence",
                    "Code generation remains explicitly not started until a later phase",
                ],
                "escalation_criteria": [
                    "No aligned current strategy, offer, and brand approvals exist",
                    "A required website decision conflicts with approved business evidence",
                    (
                        "A request requires provider, framework, repository, filesystem, "
                        "or deployment access"
                    ),
                    "The request crosses into Phase 21 website or coding-agent implementation",
                ],
                "created_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("website_specification_versions")
    op.execute(
        sa.text(
            "DELETE FROM agent_messages WHERE run_id IN "
            "(SELECT id FROM agent_runs WHERE agent_version_id = :version_id)"
        ).bindparams(version_id=VERSION_ID)
    )
    op.execute(
        sa.text("DELETE FROM agent_runs WHERE agent_version_id = :version_id").bindparams(
            version_id=VERSION_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM agent_versions WHERE id = :version_id").bindparams(
            version_id=VERSION_ID
        )
    )
    op.execute(sa.text("DELETE FROM agents WHERE id = :agent_id").bindparams(agent_id=AGENT_ID))
