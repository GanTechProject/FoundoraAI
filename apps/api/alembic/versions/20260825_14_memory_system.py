"""Add curated, provenance-first business memory.

Revision ID: 20260825_14
Revises: 20260825_13
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_14"
down_revision: str | None = "20260825_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEMORY_TYPES = (
    "'working', 'episodic', 'semantic', 'decision', 'preference', 'workflow', 'evaluation'"
)
EPISTEMIC_STATUSES = (
    "'observation', 'assumption', 'fact', 'decision', 'preference', 'procedure', 'evaluation'"
)


def _typed_constraints(prefix: str) -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint(f"memory_type IN ({MEMORY_TYPES})", name=f"ck_{prefix}_type"),
        sa.CheckConstraint(
            f"epistemic_status IN ({EPISTEMIC_STATUSES})",
            name=f"ck_{prefix}_epistemic_status",
        ),
        sa.CheckConstraint(
            "(memory_type = 'working' AND epistemic_status IN ('observation', 'assumption')) OR "
            "(memory_type = 'episodic' AND epistemic_status = 'observation') OR "
            "(memory_type = 'semantic' AND epistemic_status IN ('fact', 'assumption')) OR "
            "(memory_type = 'decision' AND epistemic_status = 'decision') OR "
            "(memory_type = 'preference' AND epistemic_status = 'preference') OR "
            "(memory_type = 'workflow' AND epistemic_status = 'procedure') OR "
            "(memory_type = 'evaluation' AND epistemic_status = 'evaluation')",
            name=f"ck_{prefix}_type_epistemic",
        ),
        sa.CheckConstraint(
            "(memory_type = 'working' AND execution_type IS NOT NULL AND "
            "execution_id IS NOT NULL AND expires_at IS NOT NULL) OR "
            "(memory_type <> 'working' AND execution_type IS NULL AND execution_id IS NULL)",
            name=f"ck_{prefix}_working_scope",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "memory_policies",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("automatic_accept_types", sa.JSON(), nullable=False),
        sa.Column("minimum_confidence", sa.Float(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by_owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "minimum_confidence >= 0 AND minimum_confidence <= 1",
            name="ck_memory_policies_confidence",
        ),
        sa.CheckConstraint("revision > 0", name="ck_memory_policies_revision"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("business_id"),
    )

    op.create_table(
        "memory_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("memory_type", sa.String(length=24), nullable=False),
        sa.Column("epistemic_status", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("acceptance_route", sa.String(length=16), nullable=False),
        sa.Column("canonical_key", sa.String(length=64), nullable=False),
        sa.Column("execution_type", sa.String(length=32), nullable=True),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=True),
        sa.Column("source_uri", sa.String(length=2048), nullable=True),
        sa.Column("source_label", sa.String(length=200), nullable=False),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("requested_by_owner_id", sa.Uuid(), nullable=False),
        sa.Column("decided_by_owner_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_memory_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.String(length=500), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        *_typed_constraints("memory_proposals"),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'merged')",
            name="ck_memory_proposals_status",
        ),
        sa.CheckConstraint(
            "acceptance_route IN ('founder', 'automatic')",
            name="ck_memory_proposals_acceptance_route",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_memory_proposals_confidence"
        ),
        sa.CheckConstraint("revision > 0", name="ck_memory_proposals_revision"),
        sa.CheckConstraint(
            "source_kind IN ('founder_input', 'knowledge_chunk', 'task', "
            "'agent_run', 'workflow_run')",
            name="ck_memory_proposals_source_kind",
        ),
        sa.CheckConstraint(
            "(source_kind = 'founder_input' AND source_id IS NULL) OR "
            "(source_kind <> 'founder_input' AND source_id IS NOT NULL)",
            name="ck_memory_proposals_source_identity",
        ),
        sa.CheckConstraint(
            "execution_type IS NULL OR execution_type IN ('task', 'agent_run', 'workflow_run')",
            name="ck_memory_proposals_execution_type",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_proposals_business_status",
        "memory_proposals",
        ["business_id", "status", "created_at"],
    )

    op.create_table(
        "memory_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("originating_proposal_id", sa.Uuid(), nullable=False),
        sa.Column("memory_type", sa.String(length=24), nullable=False),
        sa.Column("epistemic_status", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("accepted_via", sa.String(length=16), nullable=False),
        sa.Column("canonical_key", sa.String(length=64), nullable=False),
        sa.Column("execution_type", sa.String(length=32), nullable=True),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("accepted_by_owner_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_reason", sa.String(length=500), nullable=True),
        *_typed_constraints("memory_records"),
        sa.CheckConstraint("status IN ('active', 'invalidated')", name="ck_memory_records_status"),
        sa.CheckConstraint(
            "accepted_via IN ('founder', 'automatic')",
            name="ck_memory_records_accepted_via",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_memory_records_confidence"
        ),
        sa.CheckConstraint("current_revision > 0", name="ck_memory_records_revision"),
        sa.CheckConstraint(
            "epistemic_status <> 'fact' OR accepted_via = 'founder'",
            name="ck_memory_records_fact_founder",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["originating_proposal_id"], ["memory_proposals.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["accepted_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("originating_proposal_id"),
        sa.UniqueConstraint("id", "business_id", name="uq_memory_records_scope"),
    )
    op.create_index(
        "ix_memory_records_business_active",
        "memory_records",
        ["business_id", "status", "memory_type"],
    )
    op.create_index(
        "ix_memory_records_execution",
        "memory_records",
        ["business_id", "execution_type", "execution_id"],
    )
    op.create_foreign_key(
        "fk_memory_proposals_resolution_memory_id_memory_records",
        "memory_proposals",
        "memory_records",
        ["resolution_memory_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "memory_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("change_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("canonical_key", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=16), nullable=False),
        sa.Column("created_by_owner_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_memory_revisions_revision"),
        sa.CheckConstraint(
            "change_type IN ('accepted', 'merged')", name="ck_memory_revisions_change_type"
        ),
        sa.CheckConstraint(
            "created_by IN ('founder', 'automatic')", name="ck_memory_revisions_created_by"
        ),
        sa.ForeignKeyConstraint(
            ["memory_id", "business_id"],
            ["memory_records.id", "memory_records.business_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["memory_proposals.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id"),
        sa.UniqueConstraint("memory_id", "revision", name="uq_memory_revisions_number"),
        sa.UniqueConstraint(
            "memory_id", "business_id", "revision", name="uq_memory_revisions_scope"
        ),
    )
    op.create_index("ix_memory_revisions_memory_id", "memory_revisions", ["memory_id"])

    op.create_table(
        "memory_provenance",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=True),
        sa.Column("source_uri", sa.String(length=2048), nullable=True),
        sa.Column("source_label", sa.String(length=200), nullable=False),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id", "business_id", "revision"],
            [
                "memory_revisions.memory_id",
                "memory_revisions.business_id",
                "memory_revisions.revision",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_provenance_memory_revision",
        "memory_provenance",
        ["memory_id", "revision"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_provenance_memory_revision", table_name="memory_provenance")
    op.drop_table("memory_provenance")
    op.drop_index("ix_memory_revisions_memory_id", table_name="memory_revisions")
    op.drop_table("memory_revisions")
    op.drop_constraint(
        "fk_memory_proposals_resolution_memory_id_memory_records",
        "memory_proposals",
        type_="foreignkey",
    )
    op.drop_index("ix_memory_records_execution", table_name="memory_records")
    op.drop_index("ix_memory_records_business_active", table_name="memory_records")
    op.drop_table("memory_records")
    op.drop_index("ix_memory_proposals_business_status", table_name="memory_proposals")
    op.drop_table("memory_proposals")
    op.drop_table("memory_policies")
