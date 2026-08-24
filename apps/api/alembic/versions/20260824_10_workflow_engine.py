"""Add the durable versioned workflow engine.

Revision ID: 20260824_10
Revises: 20260823_09
Create Date: 2026-08-24
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260824_10"
down_revision: str | None = "20260823_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKFLOW_ID = "durable-checkpoint-workflow"
WORKFLOW_VERSION_ID = UUID("00000000-0000-0000-0000-000000001001")


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("current_version > 0", name="ck_workflows_current_version"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_workflow_versions_version"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_version"),
    )
    op.create_index("ix_workflow_versions_workflow_id", "workflow_versions", ["workflow_id"])
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.String(length=80), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("structured_input", sa.JSON(), nullable=False),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("current_step_key", sa.String(length=80), nullable=True),
        sa.Column("error_type", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("worker_recovery_count", sa.SmallInteger(), nullable=False),
        sa.Column("created_by_owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting', 'waiting_approval', "
            "'waiting_agent', 'completed', 'failed', 'cancelled')",
            name="ck_workflow_runs_status",
        ),
        sa.CheckConstraint(
            "worker_recovery_count BETWEEN 0 AND 3",
            name="ck_workflow_runs_worker_recovery_count",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workflow_version_id"], ["workflow_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_runs_business_id", "workflow_runs", ["business_id"])
    op.create_index(
        "ix_workflow_runs_workflow_version_id",
        "workflow_runs",
        ["workflow_version_id"],
    )
    op.create_index("ix_workflow_runs_task_id", "workflow_runs", ["task_id"])
    op.create_index(
        "ix_workflow_runs_business_created", "workflow_runs", ["business_id", "created_at"]
    )
    op.create_index("ix_workflow_runs_business_status", "workflow_runs", ["business_id", "status"])
    op.create_table(
        "workflow_step_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(length=80), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt_count", sa.SmallInteger(), nullable=False),
        sa.Column("max_retries", sa.SmallInteger(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("structured_input", sa.JSON(), nullable=True),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("error_type", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "step_type IN ('tool', 'agent', 'approval', 'wait')",
            name="ck_workflow_step_runs_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'waiting', 'waiting_approval', "
            "'waiting_agent', 'completed', 'skipped', 'failed', 'cancelled', 'compensated')",
            name="ck_workflow_step_runs_status",
        ),
        sa.CheckConstraint(
            "max_retries BETWEEN 0 AND 10 AND attempt_count BETWEEN 0 AND max_retries + 1",
            name="ck_workflow_step_runs_attempts",
        ),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", "step_key", name="uq_workflow_step_runs_key"),
    )
    op.create_index(
        "ix_workflow_step_runs_workflow_run_id",
        "workflow_step_runs",
        ["workflow_run_id"],
    )
    op.create_index("ix_workflow_step_runs_agent_run_id", "workflow_step_runs", ["agent_run_id"])
    op.create_index(
        "ix_workflow_step_runs_run_sequence", "workflow_step_runs", ["workflow_run_id", "sequence"]
    )
    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("step_key", sa.String(length=80), nullable=True),
        sa.Column("actor_owner_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence > 0", name="ck_workflow_events_sequence"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", "sequence", name="uq_workflow_events_sequence"),
        sa.UniqueConstraint(
            "workflow_run_id", "event_type", "idempotency_key", name="uq_workflow_events_key"
        ),
    )
    op.create_index("ix_workflow_events_workflow_run_id", "workflow_events", ["workflow_run_id"])
    op.create_index(
        "ix_workflow_events_run_created", "workflow_events", ["workflow_run_id", "created_at"]
    )

    now = datetime(2026, 8, 24, tzinfo=UTC)
    workflows = sa.table(
        "workflows",
        sa.column("id", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("current_version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    versions = sa.table(
        "workflow_versions",
        sa.column("id", sa.Uuid()),
        sa.column("workflow_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("description", sa.Text()),
        sa.column("input_schema", sa.JSON()),
        sa.column("output_schema", sa.JSON()),
        sa.column("definition", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    input_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["message", "include_branch"],
        "properties": {
            "message": {"type": "string", "minLength": 1, "maxLength": 200},
            "include_branch": {"type": "boolean"},
        },
    }
    op.bulk_insert(
        workflows,
        [
            {
                "id": WORKFLOW_ID,
                "display_name": "Durable checkpoint verification",
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
                "id": WORKFLOW_VERSION_ID,
                "workflow_id": WORKFLOW_ID,
                "version": 1,
                "description": (
                    "Provider-neutral R0 workflow proving dependencies, a conditional branch, "
                    "manual approval and wait checkpoints, retries, and deterministic output."
                ),
                "input_schema": input_schema,
                "output_schema": {"type": "object"},
                "definition": {
                    "steps": [
                        {
                            "key": "capture",
                            "type": "tool",
                            "depends_on": [],
                            "max_retries": 1,
                            "tool": "foundora.internal.echo",
                            "input": {"stage": "captured"},
                            "compensation": "foundora.internal.discard",
                        },
                        {
                            "key": "optional_branch",
                            "type": "tool",
                            "depends_on": ["capture"],
                            "max_retries": 0,
                            "tool": "foundora.internal.echo",
                            "input": {"branch": "included"},
                            "condition": {
                                "source": "input",
                                "path": "include_branch",
                                "equals": True,
                            },
                        },
                        {
                            "key": "owner_checkpoint",
                            "type": "approval",
                            "depends_on": ["capture", "optional_branch"],
                            "max_retries": 0,
                            "prompt": "Approve continuation of this R0 verification run.",
                        },
                        {
                            "key": "durable_wait",
                            "type": "wait",
                            "depends_on": ["owner_checkpoint"],
                            "max_retries": 0,
                            "prompt": "Resume when the verification wait is complete.",
                        },
                        {
                            "key": "finish",
                            "type": "tool",
                            "depends_on": ["durable_wait"],
                            "max_retries": 1,
                            "tool": "foundora.internal.echo",
                            "input": {"result": "workflow_complete"},
                        },
                    ]
                },
                "created_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_events_run_created", table_name="workflow_events")
    op.drop_index("ix_workflow_events_workflow_run_id", table_name="workflow_events")
    op.drop_table("workflow_events")
    op.drop_index("ix_workflow_step_runs_run_sequence", table_name="workflow_step_runs")
    op.drop_index("ix_workflow_step_runs_agent_run_id", table_name="workflow_step_runs")
    op.drop_index("ix_workflow_step_runs_workflow_run_id", table_name="workflow_step_runs")
    op.drop_table("workflow_step_runs")
    op.drop_index("ix_workflow_runs_business_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_business_created", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_task_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workflow_version_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_business_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_workflow_versions_workflow_id", table_name="workflow_versions")
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
