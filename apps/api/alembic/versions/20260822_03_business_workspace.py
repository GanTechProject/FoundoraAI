"""Add owner business workspaces and session selection.

Revision ID: 20260822_03
Revises: 20260822_02
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_03"
down_revision: str | None = "20260822_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "businesses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('planning', 'active', 'paused')",
            name="ck_businesses_status",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_businesses_owner_id", "businesses", ["owner_id"])
    op.create_index("ix_businesses_owner_archived", "businesses", ["owner_id", "archived_at"])
    op.create_index(
        "uq_businesses_owner_name",
        "businesses",
        ["owner_id", sa.text("lower(name)")],
        unique=True,
    )
    op.create_table(
        "business_preferences",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("locale", sa.String(length=35), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("business_id"),
    )
    op.create_table(
        "business_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')",
            name="ck_business_goals_status",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_business_goals_business_id", "business_goals", ["business_id"])
    op.create_index(
        "ix_business_goals_business_status", "business_goals", ["business_id", "status"]
    )
    op.add_column("owner_sessions", sa.Column("selected_business_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_owner_sessions_selected_business_id_businesses",
        "owner_sessions",
        "businesses",
        ["selected_business_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_owner_sessions_selected_business_id", "owner_sessions", ["selected_business_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_owner_sessions_selected_business_id", table_name="owner_sessions")
    op.drop_constraint(
        "fk_owner_sessions_selected_business_id_businesses",
        "owner_sessions",
        type_="foreignkey",
    )
    op.drop_column("owner_sessions", "selected_business_id")
    op.drop_index("ix_business_goals_business_status", table_name="business_goals")
    op.drop_index("ix_business_goals_business_id", table_name="business_goals")
    op.drop_table("business_goals")
    op.drop_table("business_preferences")
    op.drop_index("uq_businesses_owner_name", table_name="businesses")
    op.drop_index("ix_businesses_owner_archived", table_name="businesses")
    op.drop_index("ix_businesses_owner_id", table_name="businesses")
    op.drop_table("businesses")
