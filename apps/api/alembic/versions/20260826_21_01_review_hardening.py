"""Pin approved-profile versions at the strategy approval boundary.

Revision ID: 20260826_21_01
Revises: 20260825_21
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_21_01"
down_revision: str | None = "20260825_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STRATEGIST_VERSION_ID = "00000000-0000-0000-0000-000000001701"


def upgrade() -> None:
    op.add_column(
        "approved_business_strategies",
        sa.Column("source_profile_version", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE approved_business_strategies AS strategy "
            "SET source_profile_version = COALESCE("
            "  (SELECT CASE WHEN source->>'source_version' ~ '^[1-9][0-9]*$' "
            "          THEN (source->>'source_version')::integer END "
            "   FROM agent_runs AS run "
            "   CROSS JOIN LATERAL json_array_elements("
            "     COALESCE(run.structured_input->'business_context'->'sources', '[]'::json)"
            "   ) AS source "
            "   WHERE run.id = strategy.source_agent_run_id "
            "     AND source->>'authority' = 'founder_approved_onboarding' "
            "   LIMIT 1), "
            "  (SELECT profile.version FROM approved_business_profiles AS profile "
            "   WHERE profile.business_id = strategy.business_id)"
            ")"
        )
    )
    op.alter_column(
        "approved_business_strategies",
        "source_profile_version",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_approved_business_strategies_source_profile_version",
        "approved_business_strategies",
        "source_profile_version > 0",
    )
    op.execute(
        sa.text(
            "UPDATE agent_versions SET input_schema = jsonb_set("
            "  jsonb_set("
            "    input_schema::jsonb, "
            "    '{properties,strategy_evidence,properties,approved_profile_version}', "
            "    jsonb_build_object('type', 'integer', 'minimum', 1), true"
            "  ), "
            "  '{properties,strategy_evidence,required}', "
            "  (input_schema::jsonb #> '{properties,strategy_evidence,required}') "
            "    || '[\"approved_profile_version\"]'::jsonb, true"
            ")::json WHERE id = CAST(:version_id AS uuid)"
        ).bindparams(version_id=STRATEGIST_VERSION_ID)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE agent_versions SET input_schema = jsonb_set("
            "  input_schema::jsonb "
            "    #- '{properties,strategy_evidence,properties,approved_profile_version}', "
            "  '{properties,strategy_evidence,required}', "
            "  COALESCE(("
            "    SELECT jsonb_agg(item) FROM jsonb_array_elements("
            "      input_schema::jsonb #> '{properties,strategy_evidence,required}'"
            "    ) AS item WHERE item <> '\"approved_profile_version\"'::jsonb"
            "  ), '[]'::jsonb), true"
            ")::json WHERE id = CAST(:version_id AS uuid)"
        ).bindparams(version_id=STRATEGIST_VERSION_ID)
    )
    op.drop_constraint(
        "ck_approved_business_strategies_source_profile_version",
        "approved_business_strategies",
        type_="check",
    )
    op.drop_column("approved_business_strategies", "source_profile_version")
