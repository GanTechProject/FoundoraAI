"""Add the durable task engine.

Revision ID: 20260822_08
Revises: 20260822_07
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_08"
down_revision: str | None = "20260822_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("owner_type", sa.String(length=16), nullable=False),
        sa.Column("owner_agent_id", sa.String(length=80), nullable=True),
        sa.Column("owner_agent_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_retries", sa.SmallInteger(), nullable=False),
        sa.Column("retry_count", sa.SmallInteger(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_by_owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'planned', 'queued', 'running', 'blocked', "
            "'waiting_approval', 'completed', 'failed', 'cancelled')",
            name="ck_tasks_status",
        ),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name="ck_tasks_priority"),
        sa.CheckConstraint(
            "owner_type IN ('unassigned', 'founder', 'agent')",
            name="ck_tasks_owner_type",
        ),
        sa.CheckConstraint(
            "(owner_type = 'agent' AND owner_agent_id IS NOT NULL AND "
            "owner_agent_version_id IS NOT NULL) OR "
            "(owner_type <> 'agent' AND owner_agent_id IS NULL AND "
            "owner_agent_version_id IS NULL)",
            name="ck_tasks_agent_owner",
        ),
        sa.CheckConstraint(
            "max_retries BETWEEN 0 AND 10 AND retry_count BETWEEN 0 AND max_retries",
            name="ck_tasks_retries",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["business_goals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["owner_agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_business_id", "tasks", ["business_id"])
    op.create_index("ix_tasks_goal_id", "tasks", ["goal_id"])
    op.create_index("ix_tasks_business_status", "tasks", ["business_id", "status"])
    op.create_index(
        "ix_tasks_business_priority_due", "tasks", ["business_id", "priority", "due_at"]
    )

    op.create_table(
        "task_dependencies",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("depends_on_task_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("task_id <> depends_on_task_id", name="ck_task_dependencies_not_self"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["depends_on_task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id", "depends_on_task_id"),
    )

    op.create_table(
        "task_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=True),
        sa.Column("actor_owner_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('created', 'dependency_added', 'status_changed', 'retried')",
            name="ck_task_events_type",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id", "event_type", "idempotency_key", name="uq_task_events_idempotency"
        ),
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])
    op.create_index("ix_task_events_task_created", "task_events", ["task_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_task_events_task_created", table_name="task_events")
    op.drop_index("ix_task_events_task_id", table_name="task_events")
    op.drop_table("task_events")
    op.drop_table("task_dependencies")
    op.drop_index("ix_tasks_business_priority_due", table_name="tasks")
    op.drop_index("ix_tasks_business_status", table_name="tasks")
    op.drop_index("ix_tasks_goal_id", table_name="tasks")
    op.drop_index("ix_tasks_business_id", table_name="tasks")
    op.drop_table("tasks")
