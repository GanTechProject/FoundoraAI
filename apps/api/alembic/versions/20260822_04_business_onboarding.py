"""Add resumable onboarding and approved business profiles.

Revision ID: 20260822_04
Revises: 20260822_03
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260822_04"
down_revision: str | None = "20260822_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "business_onboarding_drafts",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_step", sa.SmallInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("business_type", sa.String(length=16), nullable=True),
        sa.Column("business_name", sa.String(length=120), nullable=True),
        sa.Column("industry", sa.String(length=160), nullable=True),
        sa.Column("geography", sa.String(length=240), nullable=True),
        sa.Column("problem", sa.Text(), nullable=True),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("offer", sa.Text(), nullable=True),
        sa.Column("goals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("existing_assets", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("budget", sa.Text(), nullable=True),
        sa.Column("brand_preferences", sa.Text(), nullable=True),
        sa.Column("connected_services", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'review', 'approved')",
            name="ck_business_onboarding_drafts_status",
        ),
        sa.CheckConstraint(
            "current_step BETWEEN 1 AND 5",
            name="ck_business_onboarding_drafts_current_step",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("business_id"),
    )
    op.create_table(
        "approved_business_profiles",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("business_type", sa.String(length=16), nullable=False),
        sa.Column("business_name", sa.String(length=120), nullable=False),
        sa.Column("industry", sa.String(length=160), nullable=False),
        sa.Column("geography", sa.String(length=240), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("target_audience", sa.Text(), nullable=False),
        sa.Column("offer", sa.Text(), nullable=False),
        sa.Column("goals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("existing_assets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("budget", sa.Text(), nullable=False),
        sa.Column("brand_preferences", sa.Text(), nullable=False),
        sa.Column("connected_services", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approved_by_owner_id", sa.Uuid(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "business_type IN ('idea', 'existing')",
            name="ck_approved_business_profiles_business_type",
        ),
        sa.ForeignKeyConstraint(["approved_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("business_id"),
    )


def downgrade() -> None:
    op.drop_table("approved_business_profiles")
    op.drop_table("business_onboarding_drafts")
