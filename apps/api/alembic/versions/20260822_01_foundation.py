"""Establish the Phase 01 migration baseline.

Revision ID: 20260822_01
Revises:
Create Date: 2026-08-22
"""

from collections.abc import Sequence

revision: str = "20260822_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create only Alembic's version table; domain tables belong to later phases."""


def downgrade() -> None:
    """No domain objects were introduced by the baseline revision."""
