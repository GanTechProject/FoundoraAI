"""Add evidence-linked business strategy and founder approval.

Revision ID: 20260825_17
Revises: 20260825_16
Create Date: 2026-08-25
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_17"
down_revision: str | None = "20260825_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_ID = "business-strategist"
VERSION_ID = UUID("00000000-0000-0000-0000-000000001701")


def _string_array(maximum: int, *, minimum: int = 0) -> dict[str, object]:
    return {
        "type": "array",
        "minItems": minimum,
        "maxItems": maximum,
        "items": {"type": "string", "minLength": 1, "maxLength": 2048},
    }


def _item_schema(*, pricing: bool = False, assumption: bool = False) -> dict[str, object]:
    required = [
        "item_id",
        "statement",
        "approved_fact_refs",
        "research_finding_refs",
        "confidence",
        "limitations",
    ]
    properties: dict[str, object] = {
        "item_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "statement": {"type": "string", "minLength": 1, "maxLength": 2000},
        "approved_fact_refs": _string_array(8, minimum=1),
        "research_finding_refs": _string_array(12, minimum=1),
        "confidence": {"enum": ["high", "medium", "low", "unknown"]},
        "limitations": _string_array(8),
    }
    if pricing:
        properties["validation_status"] = {"const": "requires_validation"}
        required.append("validation_status")
    if assumption:
        properties["validation_method"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 1000,
        }
        required.append("validation_method")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
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
            "strategy_evidence",
        ],
        "properties": {
            "objective": {"type": "string", "minLength": 1, "maxLength": 500},
            "business_context": {"type": "object"},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "context_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "strategy_evidence": {
                "type": "object",
                "additionalProperties": False,
                "required": ["approved_fact_refs", "research_runs"],
                "properties": {
                    "approved_fact_refs": _string_array(16, minimum=1),
                    "research_runs": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "run_id",
                                "agent_id",
                                "agent_version_id",
                                "agent_version",
                                "context_id",
                                "research_query",
                                "supported_finding_refs",
                                "output",
                            ],
                            "properties": {
                                "run_id": {"type": "string", "format": "uuid"},
                                "agent_id": {"type": "string", "minLength": 1, "maxLength": 80},
                                "agent_version_id": {"type": "string", "format": "uuid"},
                                "agent_version": {"type": "integer", "minimum": 1},
                                "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
                                "research_query": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 500,
                                },
                                "supported_finding_refs": _string_array(16, minimum=1),
                                "output": {"type": "object"},
                            },
                        },
                    },
                },
            },
        },
    }


def _output_schema() -> dict[str, object]:
    sections = [
        "opportunity_assessment",
        "value_proposition",
        "business_model",
        "pricing_hypotheses",
        "positioning",
        "go_to_market",
        "launch_roadmap",
        "risks",
        "assumptions_requiring_validation",
    ]
    properties: dict[str, object] = {
        "strategy_status": {"const": "proposed"},
        "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
        "strategy_title": {"type": "string", "minLength": 1, "maxLength": 240},
        "founder_decisions_required": _string_array(16),
        "overall_limitations": _string_array(16),
    }
    for section in sections:
        properties[section] = {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": _item_schema(
                pricing=section == "pricing_hypotheses",
                assumption=section == "assumptions_requiring_validation",
            ),
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "strategy_status",
            "context_id",
            "strategy_title",
            *sections,
            "founder_decisions_required",
            "overall_limitations",
        ],
        "properties": properties,
    }


def upgrade() -> None:
    op.create_table(
        "approved_business_strategies",
        sa.Column(
            "business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "source_agent_run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("context_id", sa.String(length=64), nullable=False),
        sa.Column("strategy", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column(
            "approved_by_owner_id",
            sa.Uuid(),
            sa.ForeignKey("owners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_approved_business_strategies_version"),
        sa.UniqueConstraint(
            "source_agent_run_id", name="uq_approved_business_strategies_source_run"
        ),
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
                "display_name": "Business Strategist Agent",
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
                "role": "Evidence-bound business strategy advisor",
                "purpose": (
                    "Propose a complete, founder-reviewable business strategy tied to "
                    "approved business facts and validated research findings."
                ),
                "responsibilities": [
                    "Assess opportunity and articulate value proposition and positioning",
                    "Propose business model, pricing hypotheses, and go-to-market",
                    "Propose a launch roadmap, risks, and assumptions requiring validation",
                    "Preserve exact approved-fact and research-finding traceability",
                ],
                "non_responsibilities": [
                    "Approving its own strategy or treating hypotheses as facts",
                    "Building products, offers, brands, websites, campaigns, or sales systems",
                    "Executing a launch, spending, contacting people, or using external tools",
                ],
                "allowed_task_types": ["strategy.business.propose"],
                "allowed_skills": [],
                "allowed_tools": [],
                "forbidden_actions": [
                    "Inventing business facts or research findings",
                    "Citing unsupported or unpinned evidence",
                    "Presenting pricing hypotheses as validated prices",
                    "Self-approval or claiming founder approval",
                    "Tool invocation or external side effects",
                    "Creating or changing products, tasks, workflows, policy, memory, or knowledge",
                    "Spending money, contacting people, credential access, or provider selection",
                ],
                "model_policy": {
                    "task_type": "strategy.business.propose",
                    "sensitivity": "sensitive",
                    "allow_fallback": False,
                    "max_output_tokens": 5000,
                    "token_budget": 40000,
                    "cost_budget_microusd": 100000,
                    "context_token_budget": 7000,
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
                        "operational_goals",
                        "relevant_memories",
                    ],
                    "drafts": "forbidden",
                    "research_evidence": "explicit_completed_phase_16_runs_only",
                    "external_search": "not_configured",
                    "approved_strategy": "write_only_after_founder_approval",
                },
                "risk_level": "R0",
                "maximum_autonomy": "manual_advisory_only",
                "input_schema": _input_schema(),
                "output_schema": _output_schema(),
                "evaluation_criteria": [
                    "All nine required strategy artifacts are present",
                    "Every strategy item cites an approved business fact and a supported "
                    "research finding",
                    "All citations exactly match immutable run evidence",
                    "Pricing and assumptions remain explicitly unvalidated",
                    "The output remains proposed until separate founder approval",
                ],
                "escalation_criteria": [
                    "Any Phase 16 specialist lacks a completed supported research run",
                    "No founder-approved business facts are available",
                    "Evidence conflicts or does not support a strategy artifact",
                    "The request crosses into Phase 18 product or offer implementation",
                ],
                "created_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("approved_business_strategies")
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
