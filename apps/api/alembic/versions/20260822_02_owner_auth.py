"""Add the single owner account and revocable sessions.

Revision ID: 20260822_02
Revises: 20260822_01
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_02"
down_revision: str | None = "20260822_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("singleton_key", sa.SmallInteger(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("singleton_key = 1", name="ck_owners_singleton_key"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("singleton_key"),
    )
    op.create_table(
        "owner_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_owner_sessions_expiration",
        "owner_sessions",
        ["expires_at", "idle_expires_at"],
    )
    op.create_index("ix_owner_sessions_owner_id", "owner_sessions", ["owner_id"])
    op.create_index(
        "ix_owner_sessions_owner_active",
        "owner_sessions",
        ["owner_id", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_owner_sessions_owner_active", table_name="owner_sessions")
    op.drop_index("ix_owner_sessions_owner_id", table_name="owner_sessions")
    op.drop_index("ix_owner_sessions_expiration", table_name="owner_sessions")
    op.drop_table("owner_sessions")
    op.drop_table("owners")
