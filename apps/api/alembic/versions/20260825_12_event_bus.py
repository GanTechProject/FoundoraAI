"""Add the durable internal domain event bus.

Revision ID: 20260825_12
Revises: 20260824_11
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_12"
down_revision: str | None = "20260824_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "domain_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.SmallInteger(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("causation_event_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("schema_version > 0", name="ck_domain_events_schema_version"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["causation_event_id"], ["domain_events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id",
            "event_type",
            "idempotency_key",
            name="uq_domain_events_idempotency",
        ),
    )
    op.create_index("ix_domain_events_business_id", "domain_events", ["business_id"])
    op.create_index("ix_domain_events_causation_event_id", "domain_events", ["causation_event_id"])
    op.create_index(
        "ix_domain_events_business_occurred",
        "domain_events",
        ["business_id", "occurred_at"],
    )
    op.create_index(
        "ix_domain_events_type_occurred", "domain_events", ["event_type", "occurred_at"]
    )

    op.create_table(
        "event_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("consumer_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt_count", sa.SmallInteger(), nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), nullable=False),
        sa.Column("redrive_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_type", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column("handler_result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'retry_wait', 'processing', 'completed', 'dead_letter')",
            name="ck_event_deliveries_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10 "
            "AND attempt_count <= max_attempts",
            name="ck_event_deliveries_attempts",
        ),
        sa.CheckConstraint("redrive_count >= 0", name="ck_event_deliveries_redrives"),
        sa.ForeignKeyConstraint(["event_id"], ["domain_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "consumer_name", name="uq_event_deliveries_consumer"),
    )
    op.create_index("ix_event_deliveries_event_id", "event_deliveries", ["event_id"])
    op.create_index(
        "ix_event_deliveries_status_available",
        "event_deliveries",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_event_deliveries_consumer_status",
        "event_deliveries",
        ["consumer_name", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_deliveries_consumer_status", table_name="event_deliveries")
    op.drop_index("ix_event_deliveries_status_available", table_name="event_deliveries")
    op.drop_index("ix_event_deliveries_event_id", table_name="event_deliveries")
    op.drop_table("event_deliveries")
    op.drop_index("ix_domain_events_type_occurred", table_name="domain_events")
    op.drop_index("ix_domain_events_business_occurred", table_name="domain_events")
    op.drop_index("ix_domain_events_causation_event_id", table_name="domain_events")
    op.drop_index("ix_domain_events_business_id", table_name="domain_events")
    op.drop_table("domain_events")
