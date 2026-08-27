# ruff: noqa: E501
"""Add immutable sandbox profiles and durable executions.

Revision ID: 20260827_22
Revises: 20260826_21_01
Create Date: 2026-08-27
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260827_22"
down_revision: str | None = "20260826_21_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILE_CREATED_AT = datetime(2026, 8, 27, tzinfo=UTC)


def upgrade() -> None:
    op.create_table(
        "sandbox_profiles",
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("harness_contract_version", sa.Integer(), nullable=False),
        sa.Column("runtime_image_contract_key", sa.String(length=80), nullable=False),
        sa.Column("runtime_build_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("cpu_nanos", sa.BigInteger(), nullable=False),
        sa.Column("memory_bytes", sa.BigInteger(), nullable=False),
        sa.Column("memory_swap_bytes", sa.BigInteger(), nullable=False),
        sa.Column("pids_limit", sa.Integer(), nullable=False),
        sa.Column("wall_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("termination_grace_seconds", sa.Integer(), nullable=False),
        sa.Column("tmpfs_bytes", sa.BigInteger(), nullable=False),
        sa.Column("dev_shm_bytes", sa.BigInteger(), nullable=False),
        sa.Column("combined_output_bytes", sa.BigInteger(), nullable=False),
        sa.Column("network_mode", sa.String(length=16), nullable=False),
        sa.Column("read_only_root_filesystem", sa.Boolean(), nullable=False),
        sa.Column("source_read_only", sa.Boolean(), nullable=False),
        sa.Column("run_as_non_root", sa.Boolean(), nullable=False),
        sa.Column("drop_all_capabilities", sa.Boolean(), nullable=False),
        sa.Column("add_sys_chroot_capability", sa.Boolean(), nullable=False),
        sa.Column("no_new_privileges", sa.Boolean(), nullable=False),
        sa.Column("no_host_namespaces", sa.Boolean(), nullable=False),
        sa.Column("no_devices", sa.Boolean(), nullable=False),
        sa.Column("allowed_project_kind", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_sandbox_profiles_version"),
        sa.CheckConstraint(
            "harness_contract_version > 0",
            name="ck_sandbox_profiles_harness_contract_version",
        ),
        sa.CheckConstraint(
            "cpu_nanos > 0 AND memory_bytes > 0 AND memory_swap_bytes >= memory_bytes "
            "AND pids_limit > 0 AND wall_timeout_seconds > 0 "
            "AND termination_grace_seconds > 0 AND tmpfs_bytes > 0 "
            "AND dev_shm_bytes > 0 AND combined_output_bytes > 0",
            name="ck_sandbox_profiles_resource_limits",
        ),
        sa.PrimaryKeyConstraint("profile_id", "version"),
    )
    profile = sa.table(
        "sandbox_profiles",
        sa.column("profile_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("harness_contract_version", sa.Integer()),
        sa.column("runtime_image_contract_key", sa.String()),
        sa.column("runtime_build_manifest_sha256", sa.String()),
        sa.column("cpu_nanos", sa.BigInteger()),
        sa.column("memory_bytes", sa.BigInteger()),
        sa.column("memory_swap_bytes", sa.BigInteger()),
        sa.column("pids_limit", sa.Integer()),
        sa.column("wall_timeout_seconds", sa.Integer()),
        sa.column("termination_grace_seconds", sa.Integer()),
        sa.column("tmpfs_bytes", sa.BigInteger()),
        sa.column("dev_shm_bytes", sa.BigInteger()),
        sa.column("combined_output_bytes", sa.BigInteger()),
        sa.column("network_mode", sa.String()),
        sa.column("read_only_root_filesystem", sa.Boolean()),
        sa.column("source_read_only", sa.Boolean()),
        sa.column("run_as_non_root", sa.Boolean()),
        sa.column("drop_all_capabilities", sa.Boolean()),
        sa.column("add_sys_chroot_capability", sa.Boolean()),
        sa.column("no_new_privileges", sa.Boolean()),
        sa.column("no_host_namespaces", sa.Boolean()),
        sa.column("no_devices", sa.Boolean()),
        sa.column("allowed_project_kind", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        profile,
        [
            {
                "profile_id": "static-website",
                "version": 1,
                "harness_contract_version": 1,
                "runtime_image_contract_key": "foundora-static-website-runtime",
                "runtime_build_manifest_sha256": "ab73f13726b30608c83a212d7cf762ee2b74986f535680377560db69286d8601",
                "cpu_nanos": 1_000_000_000,
                "memory_bytes": 536_870_912,
                "memory_swap_bytes": 536_870_912,
                "pids_limit": 128,
                "wall_timeout_seconds": 60,
                "termination_grace_seconds": 3,
                "tmpfs_bytes": 134_217_728,
                "dev_shm_bytes": 134_217_728,
                "combined_output_bytes": 1_048_576,
                "network_mode": "none",
                "read_only_root_filesystem": True,
                "source_read_only": True,
                "run_as_non_root": True,
                "drop_all_capabilities": True,
                "add_sys_chroot_capability": True,
                "no_new_privileges": True,
                "no_host_namespaces": True,
                "no_devices": True,
                "allowed_project_kind": "static-website",
                "created_at": PROFILE_CREATED_AT,
            }
        ],
    )
    op.execute(
        """
        CREATE FUNCTION reject_sandbox_profile_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'sandbox profile rows are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER sandbox_profiles_immutable
        BEFORE UPDATE OR DELETE ON sandbox_profiles
        FOR EACH ROW EXECUTE FUNCTION reject_sandbox_profile_mutation()
        """
    )

    op.create_table(
        "sandbox_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("website_project_id", sa.Uuid(), nullable=False),
        sa.Column("website_project_version", sa.Integer(), nullable=False),
        sa.Column("website_specification_id", sa.Uuid(), nullable=False),
        sa.Column("website_specification_version", sa.Integer(), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("build_digest", sa.String(length=64), nullable=False),
        sa.Column("source_archive_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_archive_size_bytes", sa.Integer(), nullable=False),
        sa.Column("routes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("profile_id", sa.String(length=64), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("harness_contract_version", sa.Integer(), nullable=False),
        sa.Column("runtime_image_id", sa.String(length=71), nullable=True),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("governance_action_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("worker_recovery_count", sa.Integer(), nullable=False),
        sa.Column("attempt_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_limits", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("effective_limits_digest", sa.String(length=64), nullable=True),
        sa.Column("termination_reason", sa.String(length=120), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("route_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("process_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stdout_excerpt", sa.Text(), nullable=True),
        sa.Column("stderr_excerpt", sa.Text(), nullable=True),
        sa.Column("stdout_sha256", sa.String(length=64), nullable=True),
        sa.Column("stderr_sha256", sa.String(length=64), nullable=True),
        sa.Column("cleanup_status", sa.String(length=16), nullable=False),
        sa.Column("cleanup_attempts", sa.Integer(), nullable=False),
        sa.Column("cleanup_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleanup_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_labeled_resource_count", sa.Integer(), nullable=True),
        sa.Column("cleanup_receipt_digest", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "website_project_version > 0", name="ck_sandbox_executions_project_version"
        ),
        sa.CheckConstraint(
            "website_specification_version > 0", name="ck_sandbox_executions_specification_version"
        ),
        sa.CheckConstraint("profile_version > 0", name="ck_sandbox_executions_profile_version"),
        sa.CheckConstraint(
            "harness_contract_version > 0", name="ck_sandbox_executions_harness_contract_version"
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'waiting_approval', 'queued', 'authorizing', 'running', "
            "'cleaning', 'rejected', 'succeeded', 'failed', 'cancelled', 'timed_out', "
            "'resource_exhausted', 'infrastructure_failed', 'cleanup_failed')",
            name="ck_sandbox_executions_status",
        ),
        sa.CheckConstraint(
            "worker_recovery_count BETWEEN 0 AND 3 AND cleanup_attempts BETWEEN 0 AND 10 "
            "AND (final_labeled_resource_count IS NULL OR final_labeled_resource_count >= 0)",
            name="ck_sandbox_executions_counts",
        ),
        sa.CheckConstraint(
            "cleanup_status IN ('pending', 'verified', 'failed')",
            name="ck_sandbox_executions_cleanup_status",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR (cleanup_status = 'verified' AND final_labeled_resource_count = 0)",
            name="ck_sandbox_executions_truthful_success",
        ),
        sa.CheckConstraint(
            "status <> 'cleanup_failed' OR cleanup_status = 'failed'",
            name="ck_sandbox_executions_cleanup_failure",
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["website_project_id"], ["website_project_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["website_specification_id"], ["website_specification_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "profile_version"],
            ["sandbox_profiles.profile_id", "sandbox_profiles.version"],
            name="fk_sandbox_executions_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["governance_action_id"], ["governance_actions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["policy_version_id"], ["policy_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_id", "idempotency_key", name="uq_sandbox_executions_idempotency"
        ),
        sa.UniqueConstraint("governance_action_id", name="uq_sandbox_executions_governance_action"),
    )
    op.create_index("ix_sandbox_executions_business_id", "sandbox_executions", ["business_id"])
    op.create_index(
        "ix_sandbox_executions_business_created",
        "sandbox_executions",
        ["business_id", "created_at"],
    )
    op.create_index(
        "ix_sandbox_executions_business_status", "sandbox_executions", ["business_id", "status"]
    )
    op.create_index(
        "ix_sandbox_executions_governance_action_id", "sandbox_executions", ["governance_action_id"]
    )
    op.create_index(
        "ix_sandbox_executions_policy_version_id", "sandbox_executions", ["policy_version_id"]
    )
    op.create_index(
        "ix_sandbox_executions_website_project_id", "sandbox_executions", ["website_project_id"]
    )
    op.create_index(
        "ix_sandbox_executions_website_specification_id",
        "sandbox_executions",
        ["website_specification_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sandbox_executions_website_specification_id", table_name="sandbox_executions")
    op.drop_index("ix_sandbox_executions_website_project_id", table_name="sandbox_executions")
    op.drop_index("ix_sandbox_executions_policy_version_id", table_name="sandbox_executions")
    op.drop_index("ix_sandbox_executions_governance_action_id", table_name="sandbox_executions")
    op.drop_index("ix_sandbox_executions_business_status", table_name="sandbox_executions")
    op.drop_index("ix_sandbox_executions_business_created", table_name="sandbox_executions")
    op.drop_index("ix_sandbox_executions_business_id", table_name="sandbox_executions")
    op.drop_table("sandbox_executions")
    op.drop_table("sandbox_profiles")
    op.execute("DROP FUNCTION IF EXISTS reject_sandbox_profile_mutation()")
