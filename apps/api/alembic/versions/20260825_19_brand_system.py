"""Add evidence-linked founder-approved brand system versions.

Revision ID: 20260825_19
Revises: 20260825_18
Create Date: 2026-08-25
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_19"
down_revision: str | None = "20260825_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_ID = "brand-strategist"
VERSION_ID = UUID("00000000-0000-0000-0000-000000001901")


def _strings(maximum: int, *, minimum: int = 0) -> dict[str, object]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1, "maxLength": 512},
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
            "brand_evidence",
        ],
        "properties": {
            "objective": {"type": "string", "minLength": 1, "maxLength": 500},
            "business_context": {"type": "object"},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "context_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "brand_evidence": {
                "type": "object",
                "additionalProperties": False,
                "required": [
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
                ],
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
                },
            },
        },
    }


def _item_schema(section: str) -> dict[str, object]:
    required = [
        "item_id",
        "statement",
        "rationale",
        "strategy_item_refs",
        "product_offer_refs",
    ]
    properties: dict[str, object] = {
        "item_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "statement": {"type": "string", "minLength": 1, "maxLength": 2000},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 1500},
        "strategy_item_refs": _strings(12, minimum=1),
        "product_offer_refs": _strings(12, minimum=1),
    }
    additions: dict[str, dict[str, object]] = {
        "naming_analysis": {
            "candidate_name": {"type": "string", "minLength": 1, "maxLength": 160},
            "availability_status": {"const": "not_checked"},
        },
        "voice": {"usage_context": {"type": "string", "minLength": 1, "maxLength": 500}},
        "messaging": {
            "audience": {"type": "string", "minLength": 1, "maxLength": 500},
            "use_case": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "visual_direction": {
            "element": {
                "enum": [
                    "color",
                    "typography",
                    "imagery",
                    "layout",
                    "iconography",
                    "motion",
                    "accessibility",
                ]
            }
        },
        "brand_rules": {
            "category": {
                "enum": [
                    "strategy",
                    "positioning",
                    "naming",
                    "voice",
                    "messaging",
                    "visual",
                    "accessibility",
                ]
            }
        },
        "asset_references": {
            "asset_type": {"enum": ["logo", "color_palette", "font", "imagery", "icon", "other"]},
            "reference": {"type": "string", "minLength": 1, "maxLength": 1000},
            "reference_status": {"const": "proposed_reference"},
        },
    }
    for name, schema in additions.get(section, {}).items():
        properties[name] = schema
        required.append(name)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _output_schema() -> dict[str, object]:
    sections = [
        "brand_strategy",
        "positioning",
        "naming_analysis",
        "voice",
        "messaging",
        "visual_direction",
        "brand_rules",
        "asset_references",
    ]
    properties: dict[str, object] = {
        "brand_status": {"const": "proposed"},
        "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
        "brand_title": {"type": "string", "minLength": 1, "maxLength": 240},
        "tagline": _item_schema("tagline"),
        "founder_decisions_required": _strings(24),
        "overall_limitations": _strings(24),
    }
    for section in sections:
        properties[section] = {
            "type": "array",
            "minItems": 1,
            "maxItems": 24,
            "items": _item_schema(section),
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "brand_status",
            "context_id",
            "brand_title",
            *sections,
            "tagline",
            "founder_decisions_required",
            "overall_limitations",
        ],
        "properties": properties,
    }


def upgrade() -> None:
    op.create_table(
        "brand_system_versions",
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
        sa.Column("context_id", sa.String(length=64), nullable=False),
        sa.Column("brand_system", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column(
            "approved_by_owner_id",
            sa.Uuid(),
            sa.ForeignKey("owners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_brand_system_versions_version"),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')", name="ck_brand_system_versions_status"
        ),
        sa.UniqueConstraint(
            "business_id", "version", name="uq_brand_system_versions_business_version"
        ),
        sa.UniqueConstraint("source_agent_run_id", name="uq_brand_system_versions_source_run"),
    )
    op.create_index(
        "ix_brand_system_versions_business_id", "brand_system_versions", ["business_id"]
    )
    op.create_index("ix_brand_system_versions_status", "brand_system_versions", ["status"])
    op.create_index(
        "uq_brand_system_versions_active_business",
        "brand_system_versions",
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
                "display_name": "Brand Strategist Agent",
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
                "role": "Evidence-bound brand strategist",
                "purpose": (
                    "Propose a founder-reviewable brand system grounded in the current "
                    "approved strategy and product and offer portfolio."
                ),
                "responsibilities": [
                    "Define brand strategy, positioning, voice, and messaging",
                    "Analyze naming and propose a tagline without availability claims",
                    "Define visual direction, reusable brand rules, and asset references",
                    "Preserve exact approved-strategy and approved-offer traceability",
                ],
                "non_responsibilities": [
                    "Approving, publishing, or externally validating a brand",
                    "Checking trademarks, domains, or legal availability",
                    "Generating creative assets, websites, content, or campaigns",
                ],
                "allowed_task_types": ["brand.system.propose"],
                "allowed_skills": [],
                "allowed_tools": [],
                "forbidden_actions": [
                    "Inventing or citing unpinned strategy or offer items",
                    "Self-approval or claiming founder approval",
                    "Claiming trademark, domain, audience, or market validation",
                    "Claiming proposed assets were created or published",
                    "Tool invocation, credential access, provider selection, or side effects",
                    "Creating websites, content, campaigns, tasks, workflows, or policy",
                ],
                "model_policy": {
                    "task_type": "brand.system.propose",
                    "sensitivity": "sensitive",
                    "allow_fallback": False,
                    "max_output_tokens": 6000,
                    "token_budget": 45000,
                    "cost_budget_microusd": 120000,
                    "context_token_budget": 10000,
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
                    "approved_brand": "write_only_after_founder_approval",
                    "external_providers": "not_configured",
                },
                "risk_level": "R0",
                "maximum_autonomy": "manual_advisory_only",
                "input_schema": _input_schema(),
                "output_schema": _output_schema(),
                "evaluation_criteria": [
                    "All Phase 19 brand artifacts are complete and structured",
                    "Every item cites the exact current approved strategy and offer",
                    "Rules are directly retrievable and usable by future content agents",
                    "Names and assets make no unsupported availability or creation claims",
                    "The output remains proposed until separate founder approval",
                ],
                "escalation_criteria": [
                    "No aligned current approved strategy and active offer exist",
                    "Brand direction conflicts with approved business evidence",
                    "Naming or asset availability requires an external check",
                    "The request crosses into Phase 20 website specification implementation",
                ],
                "created_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("brand_system_versions")
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
