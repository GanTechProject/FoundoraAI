"""Add bounded worker-interruption recovery state.

Revision ID: 20260823_09
Revises: 20260822_08
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260823_09"
down_revision: str | None = "20260822_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "worker_recovery_count",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_agent_runs_worker_recovery_count",
        "agent_runs",
        "worker_recovery_count BETWEEN 0 AND 3",
    )
    op.alter_column("agent_runs", "worker_recovery_count", server_default=None)
    op.create_unique_constraint(
        "uq_model_gateway_calls_operation_attempt",
        "model_gateway_calls",
        ["operation_id", "attempt_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_model_gateway_calls_operation_attempt",
        "model_gateway_calls",
        type_="unique",
    )
    op.drop_constraint(
        "ck_agent_runs_worker_recovery_count",
        "agent_runs",
        type_="check",
    )
    op.drop_column("agent_runs", "worker_recovery_count")
