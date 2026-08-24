"""Add the policy, risk, approval, and governance engine.

Revision ID: 20260824_11
Revises: 20260824_10
Create Date: 2026-08-24
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260824_11"
down_revision: str | None = "20260824_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY_ID = "foundora-default-governance"
POLICY_VERSION_ID = UUID("00000000-0000-0000-0000-000000001101")


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("current_version > 0", name="ck_policies_current_version"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_policy_versions_version"),
        sa.ForeignKeyConstraint(["policy_id"], ["policies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "version", name="uq_policy_versions_policy_version"),
    )
    op.create_index("ix_policy_versions_policy_id", "policy_versions", ["policy_id"])
    op.create_table(
        "global_governance_controls",
        sa.Column("singleton_key", sa.SmallInteger(), nullable=False),
        sa.Column("kill_switch_enabled", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by_owner_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("singleton_key = 1", name="ck_global_governance_singleton"),
        sa.CheckConstraint("revision > 0", name="ck_global_governance_revision"),
        sa.ForeignKeyConstraint(["updated_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("singleton_key"),
    )
    op.create_table(
        "governance_settings",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("autonomy_level", sa.String(length=32), nullable=False),
        sa.Column("daily_spend_limit_microusd", sa.BigInteger(), nullable=False),
        sa.Column("per_action_spend_limit_microusd", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by_owner_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "autonomy_level IN ('OFF', 'RECOMMEND', 'ASSISTED', 'AUTONOMOUS_LOW_RISK')",
            name="ck_governance_settings_autonomy",
        ),
        sa.CheckConstraint(
            "daily_spend_limit_microusd >= 0 AND per_action_spend_limit_microusd >= 0",
            name="ck_governance_settings_spend_limits",
        ),
        sa.CheckConstraint("revision > 0", name="ck_governance_settings_revision"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("business_id"),
    )
    op.create_table(
        "governance_tool_permissions",
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("tool_id", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by_owner_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_tool_permissions_revision"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("business_id", "tool_id"),
    )
    op.create_table(
        "governance_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_step_key", sa.String(length=80), nullable=True),
        sa.Column("action_type", sa.String(length=120), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=160), nullable=True),
        sa.Column("tool_id", sa.String(length=160), nullable=True),
        sa.Column("risk_class", sa.String(length=2), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("data_classification", sa.String(length=16), nullable=False),
        sa.Column("requested_spend_microusd", sa.BigInteger(), nullable=False),
        sa.Column("frequency_key", sa.String(length=160), nullable=True),
        sa.Column("target", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("rationale", sa.String(length=500), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_by_owner_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "actor_type IN ('owner', 'agent', 'workflow', 'system')",
            name="ck_governance_actions_actor_type",
        ),
        sa.CheckConstraint(
            "risk_class IN ('R0', 'R1', 'R2', 'R3', 'R4', 'R5')",
            name="ck_governance_actions_risk_class",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('manual', 'autonomous')",
            name="ck_governance_actions_execution_mode",
        ),
        sa.CheckConstraint(
            "data_classification IN ('public', 'internal', 'confidential', 'restricted')",
            name="ck_governance_actions_data_classification",
        ),
        sa.CheckConstraint(
            "status IN ('approval_required', 'approved', 'rejected', 'authorized', "
            "'denied', 'blocked')",
            name="ck_governance_actions_status",
        ),
        sa.CheckConstraint("requested_spend_microusd >= 0", name="ck_governance_actions_spend"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_version_id"], ["policy_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "idempotency_key", name="uq_governance_actions_idempotency"
        ),
    )
    op.create_index("ix_governance_actions_business_id", "governance_actions", ["business_id"])
    op.create_index(
        "ix_governance_actions_policy_version_id",
        "governance_actions",
        ["policy_version_id"],
    )
    op.create_index(
        "ix_governance_actions_workflow_run_id", "governance_actions", ["workflow_run_id"]
    )
    op.create_index(
        "ix_governance_actions_business_created",
        "governance_actions",
        ["business_id", "created_at"],
    )
    op.create_index(
        "ix_governance_actions_business_status",
        "governance_actions",
        ["business_id", "status"],
    )
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("prompt", sa.String(length=500), nullable=False),
        sa.Column("decision_reason", sa.String(length=500), nullable=True),
        sa.Column("requested_by_owner_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_owner_id", sa.Uuid(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_approval_requests_status",
        ),
        sa.ForeignKeyConstraint(["action_id"], ["governance_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decided_by_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", name="uq_approval_requests_action"),
    )
    op.create_index("ix_approval_requests_action_id", "approval_requests", ["action_id"])
    op.create_index("ix_approval_requests_business_id", "approval_requests", ["business_id"])
    op.create_index(
        "ix_approval_requests_business_status",
        "approval_requests",
        ["business_id", "status"],
    )
    op.create_table(
        "governance_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=True),
        sa.Column("action_id", sa.Uuid(), nullable=True),
        sa.Column("approval_request_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_owner_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["action_id"], ["governance_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["approval_request_id"], ["approval_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["actor_owner_id"], ["owners.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_governance_audit_events_business_id",
        "governance_audit_events",
        ["business_id"],
    )
    op.create_index(
        "ix_governance_audit_events_action_id", "governance_audit_events", ["action_id"]
    )
    op.create_index(
        "ix_governance_audit_events_approval_request_id",
        "governance_audit_events",
        ["approval_request_id"],
    )
    op.create_index(
        "ix_governance_audit_business_created",
        "governance_audit_events",
        ["business_id", "created_at"],
    )
    op.create_index(
        "ix_governance_audit_action_created",
        "governance_audit_events",
        ["action_id", "created_at"],
    )
    op.add_column("workflow_step_runs", sa.Column("governance_action_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_workflow_step_runs_governance_action",
        "workflow_step_runs",
        "governance_actions",
        ["governance_action_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_workflow_step_runs_governance_action_id",
        "workflow_step_runs",
        ["governance_action_id"],
    )

    now = datetime(2026, 8, 24, tzinfo=UTC)
    policies = sa.table(
        "policies",
        sa.column("id", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("current_version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    versions = sa.table(
        "policy_versions",
        sa.column("id", sa.Uuid()),
        sa.column("policy_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("description", sa.Text()),
        sa.column("rules", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    controls = sa.table(
        "global_governance_controls",
        sa.column("singleton_key", sa.SmallInteger()),
        sa.column("kill_switch_enabled", sa.Boolean()),
        sa.column("reason", sa.String()),
        sa.column("revision", sa.Integer()),
        sa.column("updated_by_owner_id", sa.Uuid()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        policies,
        [
            {
                "id": POLICY_ID,
                "display_name": "Foundora default governance",
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
                "id": POLICY_VERSION_ID,
                "policy_id": POLICY_ID,
                "version": 1,
                "description": (
                    "Provider-neutral least-authority policy: R3/R4 always require owner "
                    "approval, R5 is denied, autonomous execution is bounded, and all "
                    "authorization is rechecked against live controls."
                ),
                "rules": {
                    "risk_classes": {
                        "R0": "automatic_when_execution_mode_is_permitted",
                        "R1": "automatic_subject_to_budget_when_execution_mode_is_permitted",
                        "R2": "owner_approval_required",
                        "R3": "owner_approval_required",
                        "R4": "explicit_owner_approval_and_spend_limits_required",
                        "R5": "denied",
                    },
                    "autonomy_levels": [
                        "OFF",
                        "RECOMMEND",
                        "ASSISTED",
                        "AUTONOMOUS_LOW_RISK",
                    ],
                    "kill_switch": "execution_time_enforced",
                    "unknown_tools": "denied",
                },
                "created_at": now,
            }
        ],
    )
    op.bulk_insert(
        controls,
        [
            {
                "singleton_key": 1,
                "kill_switch_enabled": False,
                "reason": None,
                "revision": 1,
                "updated_by_owner_id": None,
                "updated_at": now,
            }
        ],
    )
    op.execute(
        sa.text(
            "INSERT INTO governance_settings "
            "(business_id, autonomy_level, daily_spend_limit_microusd, "
            "per_action_spend_limit_microusd, revision, updated_by_owner_id, updated_at) "
            "SELECT id, 'OFF', 0, 0, 1, owner_id, CURRENT_TIMESTAMP FROM businesses"
        )
    )
    for tool_id in (
        "foundora.internal.discard",
        "foundora.internal.echo",
        "foundora.internal.fail",
    ):
        op.execute(
            sa.text(
                "INSERT INTO governance_tool_permissions "
                "(business_id, tool_id, enabled, revision, updated_by_owner_id, updated_at) "
                "SELECT id, :tool_id, true, 1, owner_id, CURRENT_TIMESTAMP FROM businesses"
            ).bindparams(tool_id=tool_id)
        )


def downgrade() -> None:
    op.drop_index("ix_workflow_step_runs_governance_action_id", table_name="workflow_step_runs")
    op.drop_constraint(
        "fk_workflow_step_runs_governance_action",
        "workflow_step_runs",
        type_="foreignkey",
    )
    op.drop_column("workflow_step_runs", "governance_action_id")
    op.drop_index("ix_governance_audit_action_created", table_name="governance_audit_events")
    op.drop_index("ix_governance_audit_business_created", table_name="governance_audit_events")
    op.drop_index(
        "ix_governance_audit_events_approval_request_id",
        table_name="governance_audit_events",
    )
    op.drop_index("ix_governance_audit_events_action_id", table_name="governance_audit_events")
    op.drop_index("ix_governance_audit_events_business_id", table_name="governance_audit_events")
    op.drop_table("governance_audit_events")
    op.drop_index("ix_approval_requests_business_status", table_name="approval_requests")
    op.drop_index("ix_approval_requests_business_id", table_name="approval_requests")
    op.drop_index("ix_approval_requests_action_id", table_name="approval_requests")
    op.drop_table("approval_requests")
    op.drop_index("ix_governance_actions_business_status", table_name="governance_actions")
    op.drop_index("ix_governance_actions_business_created", table_name="governance_actions")
    op.drop_index("ix_governance_actions_workflow_run_id", table_name="governance_actions")
    op.drop_index("ix_governance_actions_policy_version_id", table_name="governance_actions")
    op.drop_index("ix_governance_actions_business_id", table_name="governance_actions")
    op.drop_table("governance_actions")
    op.drop_table("governance_tool_permissions")
    op.drop_table("governance_settings")
    op.drop_table("global_governance_controls")
    op.drop_index("ix_policy_versions_policy_id", table_name="policy_versions")
    op.drop_table("policy_versions")
    op.drop_table("policies")
