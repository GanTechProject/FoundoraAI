"""Add model gateway usage and provider validation records.

Revision ID: 20260822_05
Revises: 20260822_04
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_05"
down_revision: str | None = "20260822_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_gateway_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("sensitivity", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_number", sa.SmallInteger(), nullable=False),
        sa.Column("retry_number", sa.SmallInteger(), nullable=False),
        sa.Column("fallback_from", sa.String(length=32), nullable=True),
        sa.Column("streamed", sa.Boolean(), nullable=False),
        sa.Column("structured", sa.Boolean(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_microusd", sa.BigInteger(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')", name="ck_model_gateway_calls_status"
        ),
        sa.CheckConstraint(
            "sensitivity IN ('standard', 'sensitive')",
            name="ck_model_gateway_calls_sensitivity",
        ),
        sa.CheckConstraint(
            "attempt_number > 0 AND retry_number >= 0",
            name="ck_model_gateway_calls_attempts",
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND "
            "total_tokens = input_tokens + output_tokens",
            name="ck_model_gateway_calls_tokens",
        ),
        sa.CheckConstraint(
            "estimated_cost_microusd >= 0 AND latency_ms >= 0",
            name="ck_model_gateway_calls_measurements",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_gateway_calls_business_created",
        "model_gateway_calls",
        ["business_id", "created_at"],
    )
    op.create_index(
        "ix_model_gateway_calls_operation_attempt",
        "model_gateway_calls",
        ["operation_id", "attempt_number"],
    )
    op.create_index("ix_model_gateway_calls_operation_id", "model_gateway_calls", ["operation_id"])
    op.create_index("ix_model_gateway_calls_business_id", "model_gateway_calls", ["business_id"])
    op.create_table(
        "model_provider_validations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=80), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('valid', 'invalid')", name="ck_model_provider_validations_status"
        ),
        sa.CheckConstraint("latency_ms >= 0", name="ck_model_provider_validations_latency"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_provider_validations_provider_checked",
        "model_provider_validations",
        ["provider", "checked_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_provider_validations_provider_checked",
        table_name="model_provider_validations",
    )
    op.drop_table("model_provider_validations")
    op.drop_index("ix_model_gateway_calls_business_id", table_name="model_gateway_calls")
    op.drop_index("ix_model_gateway_calls_operation_id", table_name="model_gateway_calls")
    op.drop_index("ix_model_gateway_calls_operation_attempt", table_name="model_gateway_calls")
    op.drop_index("ix_model_gateway_calls_business_created", table_name="model_gateway_calls")
    op.drop_table("model_gateway_calls")
