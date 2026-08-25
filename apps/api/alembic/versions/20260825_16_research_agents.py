"""Add source-backed research agents.

Revision ID: 20260825_16
Revises: 20260825_15
Create Date: 2026-08-25
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_16"
down_revision: str | None = "20260825_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKET_AGENT_ID = "market-research"
COMPETITOR_AGENT_ID = "competitor-intelligence"
CUSTOMER_AGENT_ID = "customer-research"
MARKET_VERSION_ID = UUID("00000000-0000-0000-0000-000000001601")
COMPETITOR_VERSION_ID = UUID("00000000-0000-0000-0000-000000001602")
CUSTOMER_VERSION_ID = UUID("00000000-0000-0000-0000-000000001603")


def _string_array(*, maximum: int, item_maximum: int = 1000) -> dict[str, object]:
    return {
        "type": "array",
        "maxItems": maximum,
        "items": {"type": "string", "minLength": 1, "maxLength": item_maximum},
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
            "research",
        ],
        "properties": {
            "objective": {"type": "string", "minLength": 1, "maxLength": 500},
            "business_context": {"type": "object"},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "context_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "research": {
                "type": "object",
                "additionalProperties": False,
                "required": ["provider", "query", "evidence"],
                "properties": {
                    "provider": {"type": "string", "minLength": 1, "maxLength": 80},
                    "query": {"type": "string", "minLength": 1, "maxLength": 500},
                    "evidence": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "evidence_id",
                                "source",
                                "source_title",
                                "retrieval_date",
                                "retrieved_at",
                                "excerpt",
                                "content_sha256",
                            ],
                            "properties": {
                                "evidence_id": {
                                    "type": "string",
                                    "minLength": 36,
                                    "maxLength": 36,
                                },
                                "source": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 2048,
                                },
                                "source_title": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 200,
                                },
                                "retrieval_date": {
                                    "type": "string",
                                    "minLength": 10,
                                    "maxLength": 10,
                                },
                                "retrieved_at": {
                                    "type": "string",
                                    "minLength": 20,
                                    "maxLength": 40,
                                },
                                "excerpt": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 12000,
                                },
                                "content_sha256": {
                                    "type": "string",
                                    "minLength": 64,
                                    "maxLength": 64,
                                },
                            },
                        },
                    },
                },
            },
        },
    }


def _output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "research_status",
            "context_id",
            "research_query",
            "summary",
            "findings",
            "overall_limitations",
        ],
        "properties": {
            "research_status": {"type": "string", "minLength": 1, "maxLength": 32},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "research_query": {"type": "string", "minLength": 1, "maxLength": 500},
            "summary": {"type": "string", "minLength": 1, "maxLength": 1600},
            "findings": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "finding_id",
                        "category",
                        "subject",
                        "claim",
                        "supported",
                        "sources",
                        "confidence",
                        "limitations",
                    ],
                    "properties": {
                        "finding_id": {"type": "string", "minLength": 1, "maxLength": 40},
                        "category": {"type": "string", "minLength": 1, "maxLength": 40},
                        "subject": {"type": "string", "minLength": 1, "maxLength": 200},
                        "claim": {"type": "string", "minLength": 1, "maxLength": 1600},
                        "supported": {"type": "boolean"},
                        "sources": {
                            "type": "array",
                            "maxItems": 8,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["evidence_id", "source", "retrieval_date"],
                                "properties": {
                                    "evidence_id": {
                                        "type": "string",
                                        "minLength": 36,
                                        "maxLength": 36,
                                    },
                                    "source": {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": 2048,
                                    },
                                    "retrieval_date": {
                                        "type": "string",
                                        "minLength": 10,
                                        "maxLength": 10,
                                    },
                                },
                            },
                        },
                        "confidence": {"type": "string", "minLength": 3, "maxLength": 7},
                        "limitations": _string_array(maximum=8),
                    },
                },
            },
            "overall_limitations": _string_array(maximum=12),
        },
    }


def upgrade() -> None:
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
                "id": MARKET_AGENT_ID,
                "display_name": "Market Research Agent",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": COMPETITOR_AGENT_ID,
                "display_name": "Competitor Intelligence Agent",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": CUSTOMER_AGENT_ID,
                "display_name": "Customer Research Agent",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    versions = sa.table(
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
    )
    context_sources = [
        "business_profile",
        "approved_profile",
        "approved_goals",
        "products_services",
        "brand",
        "operating_context",
        "operational_goals",
        "relevant_memories",
    ]
    forbidden = [
        "Inventing or presenting unsupported research as fact",
        "Inventing competitor names, pricing, features, positioning, or performance",
        "Using a source outside the pinned search evidence",
        "Tool invocation by the model",
        "External side effects or recurring monitoring",
        "Creating or changing tasks, workflows, approvals, policy, memory, or knowledge",
        "Spending money or contacting people",
        "Credential or secret access",
    ]
    policy: dict[str, object] = {
        "sensitivity": "sensitive",
        "allow_fallback": False,
        "max_output_tokens": 2200,
        "token_budget": 28000,
        "cost_budget_microusd": 60000,
        "context_token_budget": 5000,
    }
    access_scope = {
        "business_scope": "run.business_id",
        "sources": context_sources,
        "drafts": "forbidden",
        "research_evidence": "explicit_search_provider_results_only",
        "external_search": "not_configured",
    }
    output_schema = _output_schema()
    shared_evaluation = [
        "Every supported claim includes an exact pinned source and retrieval date",
        "Every supported claim is an extractive statement from a cited evidence excerpt",
        "Unsupported claims are explicitly flagged with confidence and limitations",
        "The output query and context identity match the immutable run input",
        "No source, statistic, customer fact, competitor fact, or action is invented",
    ]
    op.bulk_insert(
        versions,
        [
            {
                "id": MARKET_VERSION_ID,
                "agent_id": MARKET_AGENT_ID,
                "version": 1,
                "role": "Source-backed market evidence and demand-signal researcher",
                "purpose": (
                    "Analyze explicitly retrieved evidence for market trends, demand signals, "
                    "market evidence, and gaps without presenting assumptions as facts."
                ),
                "responsibilities": [
                    "Identify market trends in retrieved evidence",
                    "Extract demand signals and market evidence",
                    "State confidence and evidence limitations for each claim",
                    "Flag claims that the retrieved sources do not support",
                ],
                "non_responsibilities": [
                    "Estimating market size without cited evidence",
                    "Running external searches or recurring monitoring",
                    "Making strategy decisions or taking external action",
                ],
                "allowed_task_types": ["research.market.analyze"],
                "allowed_skills": [],
                "allowed_tools": [],
                "forbidden_actions": forbidden,
                "model_policy": {**policy, "task_type": "research.market.analyze"},
                "data_access_scope": access_scope,
                "risk_level": "R0",
                "maximum_autonomy": "manual_advisory_only",
                "input_schema": _input_schema(),
                "output_schema": output_schema,
                "evaluation_criteria": [
                    *shared_evaluation,
                    "Trend and demand findings use only the allowed market categories",
                ],
                "escalation_criteria": [
                    "No relevant source evidence was retrieved",
                    "Sources conflict or do not support the requested market claim",
                    "A requested conclusion requires external or paid research",
                ],
                "created_at": now,
            },
            {
                "id": COMPETITOR_VERSION_ID,
                "agent_id": COMPETITOR_AGENT_ID,
                "version": 1,
                "role": "Evidence-bound competitor intelligence researcher",
                "purpose": (
                    "Identify only source-named competitors and compare cited positioning, "
                    "pricing, features, strengths, weaknesses, and whitespace."
                ),
                "responsibilities": [
                    "Identify competitors explicitly named in retrieved evidence",
                    "Compare cited positioning, pricing, and features",
                    "Describe evidenced strengths, weaknesses, and whitespace",
                    "Flag every unsupported competitor claim",
                ],
                "non_responsibilities": [
                    "Inventing a competitor or inferring uncited competitor attributes",
                    "Recurring monitoring or external search execution",
                    "Contacting competitors or changing business strategy",
                ],
                "allowed_task_types": ["research.competitor.analyze"],
                "allowed_skills": [],
                "allowed_tools": [],
                "forbidden_actions": forbidden,
                "model_policy": {**policy, "task_type": "research.competitor.analyze"},
                "data_access_scope": access_scope,
                "risk_level": "R0",
                "maximum_autonomy": "manual_advisory_only",
                "input_schema": _input_schema(),
                "output_schema": output_schema,
                "evaluation_criteria": [
                    *shared_evaluation,
                    "Each supported competitor subject is named verbatim in cited evidence",
                ],
                "escalation_criteria": [
                    "A competitor is not explicitly named in retrieved evidence",
                    "Pricing, feature, strength, or weakness evidence is absent or stale",
                    "The request requires recurring monitoring or an external provider",
                ],
                "created_at": now,
            },
            {
                "id": CUSTOMER_VERSION_ID,
                "agent_id": CUSTOMER_AGENT_ID,
                "version": 1,
                "role": "Source-backed customer and jobs-to-be-done researcher",
                "purpose": (
                    "Analyze cited evidence for ICP, personas, jobs-to-be-done, pain points, "
                    "buying triggers, and objections while exposing evidence gaps."
                ),
                "responsibilities": [
                    "Extract ICP and persona evidence",
                    "Identify cited jobs-to-be-done and pain points",
                    "Identify evidenced buying triggers and objections",
                    "State confidence and limitations for each customer claim",
                ],
                "non_responsibilities": [
                    "Inventing customer interviews, personas, intent, or demographic facts",
                    "Contacting customers or collecting external data",
                    "Changing offers, CRM records, or marketing strategy",
                ],
                "allowed_task_types": ["research.customer.analyze"],
                "allowed_skills": [],
                "allowed_tools": [],
                "forbidden_actions": forbidden,
                "model_policy": {**policy, "task_type": "research.customer.analyze"},
                "data_access_scope": access_scope,
                "risk_level": "R0",
                "maximum_autonomy": "manual_advisory_only",
                "input_schema": _input_schema(),
                "output_schema": output_schema,
                "evaluation_criteria": [
                    *shared_evaluation,
                    "Customer findings use only the allowed research categories",
                ],
                "escalation_criteria": [
                    "No direct or credible customer evidence was retrieved",
                    "A persona or buying claim is inferred beyond the cited source",
                    "The request requires customer contact or external data collection",
                ],
                "created_at": now,
            },
        ],
    )


def downgrade() -> None:
    version_ids = (MARKET_VERSION_ID, COMPETITOR_VERSION_ID, CUSTOMER_VERSION_ID)
    op.execute(
        sa.text(
            "UPDATE tasks SET owner_type = 'unassigned', owner_agent_id = NULL, "
            "owner_agent_version_id = NULL WHERE owner_agent_version_id "
            "IN (:market, :competitor, :customer)"
        ).bindparams(market=version_ids[0], competitor=version_ids[1], customer=version_ids[2])
    )
    op.execute(
        sa.text(
            "DELETE FROM agent_messages WHERE run_id IN "
            "(SELECT id FROM agent_runs WHERE agent_version_id "
            "IN (:market, :competitor, :customer))"
        ).bindparams(market=version_ids[0], competitor=version_ids[1], customer=version_ids[2])
    )
    op.execute(
        sa.text(
            "DELETE FROM agent_runs WHERE agent_version_id IN (:market, :competitor, :customer)"
        ).bindparams(market=version_ids[0], competitor=version_ids[1], customer=version_ids[2])
    )
    op.execute(
        sa.text(
            "DELETE FROM agent_versions WHERE id IN (:market, :competitor, :customer)"
        ).bindparams(market=version_ids[0], competitor=version_ids[1], customer=version_ids[2])
    )
    op.execute(
        sa.text("DELETE FROM agents WHERE id IN (:market, :competitor, :customer)").bindparams(
            market=MARKET_AGENT_ID,
            competitor=COMPETITOR_AGENT_ID,
            customer=CUSTOMER_AGENT_ID,
        )
    )
