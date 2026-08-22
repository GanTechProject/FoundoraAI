"""Add the versioned agent registry and durable run lifecycle.

Revision ID: 20260822_06
Revises: 20260822_05
Create Date: 2026-08-22
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_06"
down_revision: str | None = "20260822_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_ID = "runtime-verification-agent"
AGENT_VERSION_ID = UUID("00000000-0000-0000-0000-000000000701")


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("current_version > 0", name="ck_agents_current_version"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=160), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("responsibilities", sa.JSON(), nullable=False),
        sa.Column("non_responsibilities", sa.JSON(), nullable=False),
        sa.Column("allowed_task_types", sa.JSON(), nullable=False),
        sa.Column("allowed_skills", sa.JSON(), nullable=False),
        sa.Column("allowed_tools", sa.JSON(), nullable=False),
        sa.Column("forbidden_actions", sa.JSON(), nullable=False),
        sa.Column("model_policy", sa.JSON(), nullable=False),
        sa.Column("data_access_scope", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(length=2), nullable=False),
        sa.Column("maximum_autonomy", sa.String(length=32), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("evaluation_criteria", sa.JSON(), nullable=False),
        sa.Column("escalation_criteria", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_agent_versions_version"),
        sa.CheckConstraint(
            "risk_level IN ('R0', 'R1', 'R2', 'R3', 'R4', 'R5')",
            name="ck_agent_versions_risk_level",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
    )
    op.create_index("ix_agent_versions_agent_id", "agent_versions", ["agent_id"])
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.String(length=80), nullable=False),
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("structured_input", sa.JSON(), nullable=False),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("model_operation_id", sa.Uuid(), nullable=True),
        sa.Column("error_type", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting_tool', 'waiting_approval', "
            "'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_agent_version_id", "agent_runs", ["agent_version_id"])
    op.create_index("ix_agent_runs_business_id", "agent_runs", ["business_id"])
    op.create_index("ix_agent_runs_business_created", "agent_runs", ["business_id", "created_at"])
    op.create_index("ix_agent_runs_business_status", "agent_runs", ["business_id", "status"])
    op.create_index("ix_agent_runs_model_operation_id", "agent_runs", ["model_operation_id"])
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("message_type", sa.String(length=16), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')", name="ck_agent_messages_role"
        ),
        sa.CheckConstraint(
            "message_type IN ('input', 'output', 'error')",
            name="ck_agent_messages_type",
        ),
        sa.CheckConstraint("sequence > 0", name="ck_agent_messages_sequence"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_messages_run_sequence"),
    )
    op.create_index("ix_agent_messages_run_id", "agent_messages", ["run_id"])
    op.add_column("model_gateway_calls", sa.Column("agent_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_model_gateway_calls_agent_run_id",
        "model_gateway_calls",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_model_gateway_calls_agent_run_id", "model_gateway_calls", ["agent_run_id"])

    now = datetime(2026, 8, 22, tzinfo=UTC)
    agents = sa.table(
        "agents",
        sa.column("id", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("current_version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
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
    op.bulk_insert(
        agents,
        [
            {
                "id": AGENT_ID,
                "display_name": "Runtime Verification Agent",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.bulk_insert(
        versions,
        [
            {
                "id": AGENT_VERSION_ID,
                "agent_id": AGENT_ID,
                "version": 1,
                "role": "Read-only business context observer",
                "purpose": (
                    "Prove the governed agent runtime by inspecting selected-business "
                    "context and returning a bounded structured observation."
                ),
                "responsibilities": [
                    "Inspect only the supplied approved and live business context",
                    "Return the required structured observation",
                    "Escalate when the context cannot support a claim",
                ],
                "non_responsibilities": [
                    "Taking external actions",
                    "Making founder decisions",
                    "Creating or changing approved business facts",
                ],
                "allowed_task_types": ["agent.runtime.inspect_context"],
                "allowed_skills": [],
                "allowed_tools": [],
                "forbidden_actions": [
                    "External side effects",
                    "Tool invocation",
                    "Credential access",
                    "Treating assumptions as approved facts",
                ],
                "model_policy": {
                    "task_type": "agent.runtime.inspect_context",
                    "sensitivity": "standard",
                    "allow_fallback": True,
                    "max_output_tokens": 256,
                    "token_budget": 8192,
                    "cost_budget_microusd": 10000,
                    "context_token_budget": 1024,
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
                    ],
                    "drafts": "forbidden",
                },
                "risk_level": "R0",
                "maximum_autonomy": "manual_run_only",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "objective",
                        "business_context",
                        "context_id",
                        "context_sha256",
                    ],
                    "properties": {
                        "objective": {"type": "string", "minLength": 1, "maxLength": 500},
                        "business_context": {"type": "object"},
                        "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
                        "context_sha256": {
                            "type": "string",
                            "minLength": 64,
                            "maxLength": 64,
                        },
                    },
                },
                "output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["summary", "observations", "escalation_required"],
                    "properties": {
                        "summary": {"type": "string", "minLength": 1, "maxLength": 1200},
                        "observations": {
                            "type": "array",
                            "maxItems": 5,
                            "items": {"type": "string", "minLength": 1, "maxLength": 500},
                        },
                        "escalation_required": {"type": "boolean"},
                    },
                },
                "evaluation_criteria": [
                    "Output matches the declared schema",
                    "Claims remain grounded in supplied context",
                    "No external action or fabricated fact is claimed",
                ],
                "escalation_criteria": [
                    "Required context is unavailable",
                    "The objective requests an external or forbidden action",
                    "The supplied facts do not support a confident observation",
                ],
                "created_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_model_gateway_calls_agent_run_id", table_name="model_gateway_calls")
    op.drop_constraint(
        "fk_model_gateway_calls_agent_run_id", "model_gateway_calls", type_="foreignkey"
    )
    op.drop_column("model_gateway_calls", "agent_run_id")
    op.drop_index("ix_agent_messages_run_id", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_runs_model_operation_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_business_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_business_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_business_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_agent_version_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_agent_versions_agent_id", table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_table("agents")
