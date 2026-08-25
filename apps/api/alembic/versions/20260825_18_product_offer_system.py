"""Add evidence-linked product and offer portfolio versions.

Revision ID: 20260825_18
Revises: 20260825_17
Create Date: 2026-08-25
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_18"
down_revision: str | None = "20260825_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_ID = "product-offer"
VERSION_ID = UUID("00000000-0000-0000-0000-000000001801")


def _strings(maximum: int, *, minimum: int = 0) -> dict[str, object]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1, "maxLength": 256},
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
            "offer_evidence",
        ],
        "properties": {
            "objective": {"type": "string", "minLength": 1, "maxLength": 500},
            "business_context": {"type": "object"},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "context_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "offer_evidence": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "strategy_version",
                    "strategy_source_agent_run_id",
                    "strategy_context_id",
                    "strategy_item_refs",
                    "approved_strategy",
                ],
                "properties": {
                    "strategy_version": {"type": "integer", "minimum": 1},
                    "strategy_source_agent_run_id": {"type": "string", "format": "uuid"},
                    "strategy_context_id": {
                        "type": "string",
                        "minLength": 64,
                        "maxLength": 64,
                    },
                    "strategy_item_refs": _strings(144, minimum=1),
                    "approved_strategy": {"type": "object"},
                },
            },
        },
    }


def _strategy_refs() -> dict[str, object]:
    return _strings(12, minimum=1)


def _output_schema() -> dict[str, object]:
    segment = {
        "type": "object",
        "additionalProperties": False,
        "required": ["segment_id", "name", "description", "strategy_item_refs"],
        "properties": {
            "segment_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "name": {"type": "string", "minLength": 1, "maxLength": 160},
            "description": {"type": "string", "minLength": 1, "maxLength": 1200},
            "strategy_item_refs": _strategy_refs(),
        },
    }
    benefit = {
        "type": "object",
        "additionalProperties": False,
        "required": ["benefit_id", "statement", "strategy_item_refs"],
        "properties": {
            "benefit_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "statement": {"type": "string", "minLength": 1, "maxLength": 1000},
            "strategy_item_refs": _strategy_refs(),
        },
    }
    product = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "product_id",
            "kind",
            "name",
            "description",
            "delivery_model",
            "target_segment_refs",
            "benefits",
            "status",
            "strategy_item_refs",
        ],
        "properties": {
            "product_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "kind": {"enum": ["product", "service"]},
            "name": {"type": "string", "minLength": 1, "maxLength": 160},
            "description": {"type": "string", "minLength": 1, "maxLength": 1500},
            "delivery_model": {"type": "string", "minLength": 1, "maxLength": 500},
            "target_segment_refs": _strings(16, minimum=1),
            "benefits": {"type": "array", "minItems": 1, "maxItems": 24, "items": benefit},
            "status": {"const": "proposed"},
            "strategy_item_refs": _strategy_refs(),
        },
    }
    package = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "package_id",
            "name",
            "description",
            "product_refs",
            "target_segment_refs",
            "included_benefit_refs",
            "pricing",
            "status",
            "strategy_item_refs",
        ],
        "properties": {
            "package_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "name": {"type": "string", "minLength": 1, "maxLength": 160},
            "description": {"type": "string", "minLength": 1, "maxLength": 1500},
            "product_refs": _strings(16, minimum=1),
            "target_segment_refs": _strings(16, minimum=1),
            "included_benefit_refs": _strings(48, minimum=1),
            "pricing": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "amount_minor",
                    "currency",
                    "billing_period",
                    "validation_status",
                ],
                "properties": {
                    "amount_minor": {"type": "integer", "minimum": 0},
                    "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
                    "billing_period": {
                        "enum": ["one_time", "monthly", "quarterly", "annual", "usage"]
                    },
                    "validation_status": {"const": "requires_validation"},
                },
            },
            "status": {"const": "proposed"},
            "strategy_item_refs": _strategy_refs(),
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "portfolio_status",
            "context_id",
            "portfolio_name",
            "target_segments",
            "products_services",
            "packages",
            "founder_decisions_required",
            "overall_limitations",
        ],
        "properties": {
            "portfolio_status": {"const": "proposed"},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "portfolio_name": {"type": "string", "minLength": 1, "maxLength": 240},
            "target_segments": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": segment,
            },
            "products_services": {
                "type": "array",
                "minItems": 1,
                "maxItems": 24,
                "items": product,
            },
            "packages": {"type": "array", "minItems": 1, "maxItems": 24, "items": package},
            "founder_decisions_required": _strings(24),
            "overall_limitations": _strings(24),
        },
    }


def upgrade() -> None:
    op.create_table(
        "product_offer_versions",
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
        sa.Column("context_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column(
            "approved_by_owner_id",
            sa.Uuid(),
            sa.ForeignKey("owners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_product_offer_versions_version"),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')", name="ck_product_offer_versions_status"
        ),
        sa.UniqueConstraint(
            "business_id", "version", name="uq_product_offer_versions_business_version"
        ),
        sa.UniqueConstraint("source_agent_run_id", name="uq_product_offer_versions_source_run"),
    )
    op.create_index(
        "ix_product_offer_versions_business_id",
        "product_offer_versions",
        ["business_id"],
    )
    op.create_index("ix_product_offer_versions_status", "product_offer_versions", ["status"])
    op.create_index(
        "uq_product_offer_versions_active_business",
        "product_offer_versions",
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
                "display_name": "Product & Offer Agent",
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
                "role": "Evidence-bound product and offer architect",
                "purpose": (
                    "Propose founder-reviewable products, services, benefits, packages, "
                    "segments, and pricing from the approved business strategy."
                ),
                "responsibilities": [
                    "Define target segments and products or services",
                    "Map benefits into coherent packages",
                    "Recommend explicit, validation-marked pricing",
                    "Preserve exact approved-strategy traceability",
                ],
                "non_responsibilities": [
                    "Approving, launching, selling, or delivering an offer",
                    "Treating pricing recommendations as market validation",
                    "Creating brands, websites, campaigns, or external side effects",
                ],
                "allowed_task_types": ["product_offer.portfolio.propose"],
                "allowed_skills": [],
                "allowed_tools": [],
                "forbidden_actions": [
                    "Inventing or citing unpinned strategy items",
                    "Self-approval or claiming founder approval",
                    "Claiming pricing, demand, sales, or delivery validation",
                    "Tool invocation or external side effects",
                    "Creating brands, websites, campaigns, tasks, workflows, or policy",
                    "Spending money, contacting people, credential access, or provider selection",
                ],
                "model_policy": {
                    "task_type": "product_offer.portfolio.propose",
                    "sensitivity": "sensitive",
                    "allow_fallback": False,
                    "max_output_tokens": 5000,
                    "token_budget": 40000,
                    "cost_budget_microusd": 100000,
                    "context_token_budget": 8000,
                },
                "data_access_scope": {
                    "business_scope": "run.business_id",
                    "sources": [
                        "business_profile",
                        "approved_profile",
                        "approved_goals",
                        "operating_context",
                        "relevant_memories",
                        "approved_strategy",
                    ],
                    "drafts": "forbidden",
                    "approved_strategy": "required_exact_current_version",
                    "approved_product_offers": "write_only_after_founder_approval",
                    "external_providers": "not_configured",
                },
                "risk_level": "R0",
                "maximum_autonomy": "manual_advisory_only",
                "input_schema": _input_schema(),
                "output_schema": _output_schema(),
                "evaluation_criteria": [
                    "Products, services, packages, benefits, segments, status, and pricing exist",
                    "All entities resolve internal references and cite approved strategy items",
                    "Pricing remains explicitly marked for validation",
                    "The output remains proposed until separate founder approval",
                ],
                "escalation_criteria": [
                    "No founder-approved business strategy exists",
                    "The approved strategy does not support a complete offer",
                    "A pricing or delivery decision requires founder judgment",
                    "The request crosses into Phase 19 brand implementation",
                ],
                "created_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("product_offer_versions")
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
