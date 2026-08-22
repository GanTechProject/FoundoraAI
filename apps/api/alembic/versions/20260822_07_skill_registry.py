"""Add the immutable skill registry and assignment boundary.

Revision ID: 20260822_07
Revises: 20260822_06
Create Date: 2026-08-22
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_07"
down_revision: str | None = "20260822_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_ID = "runtime-verification-agent"
AGENT_VERSION_2_ID = UUID("00000000-0000-0000-0000-000000000702")
SUMMARY_SKILL_ID = "summarize-business-context"
PLAN_SKILL_ID = "generate-structured-plan"
ANALYSIS_SKILL_ID = "analyze-provided-data"
SUMMARY_VERSION_ID = UUID("00000000-0000-0000-0000-000000000801")
PLAN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000802")
ANALYSIS_VERSION_ID = UUID("00000000-0000-0000-0000-000000000803")


def _summary_output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "observations", "escalation_required"],
        "properties": {
            "summary": {"type": "string", "minLength": 1, "maxLength": 1200},
            "observations": {
                "type": "array",
                "maxItems": 5,
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "escalation_required": {"type": "boolean"},
        },
    }


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("current_version > 0", name="ck_skills_current_version"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("compatible_agents", sa.JSON(), nullable=False),
        sa.Column("prerequisites", sa.JSON(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("tool_requirements", sa.JSON(), nullable=False),
        sa.Column("workflow", sa.JSON(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("risk_class", sa.String(length=2), nullable=False),
        sa.Column("test_fixtures", sa.JSON(), nullable=False),
        sa.Column("evaluation_rubric", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_skill_versions_version"),
        sa.CheckConstraint(
            "risk_class IN ('R0', 'R1', 'R2', 'R3', 'R4', 'R5')",
            name="ck_skill_versions_risk_class",
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
    )
    op.create_index("ix_skill_versions_skill_id", "skill_versions", ["skill_id"])
    op.create_table(
        "agent_skill_assignments",
        sa.Column("agent_version_id", sa.Uuid(), nullable=False),
        sa.Column("skill_version_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_version_id"], ["skill_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("agent_version_id", "skill_version_id"),
    )
    op.add_column("agent_runs", sa.Column("skill_version_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_agent_runs_skill_version_id",
        "agent_runs",
        "skill_versions",
        ["skill_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_agent_runs_skill_version_id", "agent_runs", ["skill_version_id"])

    now = datetime(2026, 8, 22, tzinfo=UTC)
    skills = sa.table(
        "skills",
        sa.column("id", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("current_version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    versions = sa.table(
        "skill_versions",
        sa.column("id", sa.Uuid()),
        sa.column("skill_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("description", sa.Text()),
        sa.column("compatible_agents", sa.JSON()),
        sa.column("prerequisites", sa.JSON()),
        sa.column("input_schema", sa.JSON()),
        sa.column("output_schema", sa.JSON()),
        sa.column("tool_requirements", sa.JSON()),
        sa.column("workflow", sa.JSON()),
        sa.column("permissions", sa.JSON()),
        sa.column("risk_class", sa.String()),
        sa.column("test_fixtures", sa.JSON()),
        sa.column("evaluation_rubric", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        skills,
        [
            {
                "id": SUMMARY_SKILL_ID,
                "display_name": "Summarize Business Context",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": PLAN_SKILL_ID,
                "display_name": "Generate Structured Plan",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": ANALYSIS_SKILL_ID,
                "display_name": "Analyze Provided Data",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )
    op.bulk_insert(
        versions,
        [
            {
                "id": SUMMARY_VERSION_ID,
                "skill_id": SUMMARY_SKILL_ID,
                "version": 1,
                "description": (
                    "Summarize only the supplied approved business context into a "
                    "bounded, grounded observation without taking any action."
                ),
                "compatible_agents": [AGENT_ID],
                "prerequisites": [
                    "A selected business",
                    "A bounded Phase 06 context snapshot",
                ],
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["focus"],
                    "properties": {"focus": {"type": "string", "minLength": 1, "maxLength": 500}},
                },
                "output_schema": _summary_output_schema(),
                "tool_requirements": [],
                "workflow": [
                    "Read the supplied context and provenance",
                    "Select claims supported by included sources",
                    "Return the declared structured summary",
                ],
                "permissions": [
                    "Read only the run's selected-business snapshot",
                    "Call the governed model gateway within the agent budget",
                ],
                "risk_class": "R0",
                "test_fixtures": [
                    {
                        "name": "grounded-summary",
                        "input": {"focus": "Identify one supported business observation"},
                        "expects": ["summary", "observations", "escalation_required"],
                    }
                ],
                "evaluation_rubric": [
                    "Every observation is supported by supplied context",
                    "The output matches the declared schema",
                    "No external action or new approved fact is claimed",
                ],
                "created_at": now,
            },
            {
                "id": PLAN_VERSION_ID,
                "skill_id": PLAN_SKILL_ID,
                "version": 1,
                "description": (
                    "Turn a provided goal and constraints into a small structured plan; "
                    "the plan is advisory and performs no steps."
                ),
                "compatible_agents": [AGENT_ID],
                "prerequisites": ["A founder-provided goal"],
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["goal", "constraints"],
                    "properties": {
                        "goal": {"type": "string", "minLength": 1, "maxLength": 500},
                        "constraints": {
                            "type": "array",
                            "maxItems": 10,
                            "items": {"type": "string", "minLength": 1, "maxLength": 300},
                        },
                    },
                },
                "output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["goal", "steps", "assumptions"],
                    "properties": {
                        "goal": {"type": "string", "minLength": 1, "maxLength": 500},
                        "steps": {
                            "type": "array",
                            "maxItems": 8,
                            "items": {"type": "string", "minLength": 1, "maxLength": 500},
                        },
                        "assumptions": {
                            "type": "array",
                            "maxItems": 8,
                            "items": {"type": "string", "minLength": 1, "maxLength": 500},
                        },
                    },
                },
                "tool_requirements": [],
                "workflow": [
                    "Normalize the supplied goal and constraints",
                    "Draft ordered advisory steps",
                    "Expose assumptions in the declared output",
                ],
                "permissions": ["Use only supplied input", "Return advisory text only"],
                "risk_class": "R0",
                "test_fixtures": [
                    {
                        "name": "bounded-plan",
                        "input": {"goal": "Prepare a launch outline", "constraints": []},
                        "expects": ["goal", "steps", "assumptions"],
                    }
                ],
                "evaluation_rubric": [
                    "Steps address the supplied goal",
                    "Constraints and assumptions remain explicit",
                    "No step is represented as executed",
                ],
                "created_at": now,
            },
            {
                "id": ANALYSIS_VERSION_ID,
                "skill_id": ANALYSIS_SKILL_ID,
                "version": 1,
                "description": (
                    "Analyze only caller-provided structured data and report bounded "
                    "findings and limitations without external enrichment."
                ),
                "compatible_agents": [AGENT_ID],
                "prerequisites": ["Caller-provided JSON data and a question"],
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["question", "data"],
                    "properties": {
                        "question": {"type": "string", "minLength": 1, "maxLength": 500},
                        "data": {"type": "object"},
                    },
                },
                "output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["findings", "limitations"],
                    "properties": {
                        "findings": {
                            "type": "array",
                            "maxItems": 10,
                            "items": {"type": "string", "minLength": 1, "maxLength": 500},
                        },
                        "limitations": {
                            "type": "array",
                            "maxItems": 10,
                            "items": {"type": "string", "minLength": 1, "maxLength": 500},
                        },
                    },
                },
                "tool_requirements": [],
                "workflow": [
                    "Inspect only the provided JSON data",
                    "Answer the stated question with bounded findings",
                    "Report missing fields and analytical limitations",
                ],
                "permissions": ["Read only caller-provided data", "Return analysis only"],
                "risk_class": "R0",
                "test_fixtures": [
                    {
                        "name": "small-dataset",
                        "input": {"question": "What is present?", "data": {"count": 3}},
                        "expects": ["findings", "limitations"],
                    }
                ],
                "evaluation_rubric": [
                    "Findings are traceable to supplied data",
                    "Missing evidence appears under limitations",
                    "No external or inferred dataset is claimed",
                ],
                "created_at": now,
            },
        ],
    )

    agent_versions = sa.table(
        "agent_versions",
        sa.column("id", sa.Uuid()),
        sa.column("agent_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("role", sa.String()),
        sa.column("purpose", sa.Text()),
        sa.column("responsibilities", sa.JSON()),
        sa.column("non_responsibilities", sa.JSON()),
        sa.column("allowed_task_types", sa.JSON()),
        sa.column("allowed_skills", sa.JSON()),
        sa.column("allowed_tools", sa.JSON()),
        sa.column("forbidden_actions", sa.JSON()),
        sa.column("model_policy", sa.JSON()),
        sa.column("data_access_scope", sa.JSON()),
        sa.column("risk_level", sa.String()),
        sa.column("maximum_autonomy", sa.String()),
        sa.column("input_schema", sa.JSON()),
        sa.column("output_schema", sa.JSON()),
        sa.column("evaluation_criteria", sa.JSON()),
        sa.column("escalation_criteria", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        agent_versions,
        [
            {
                "id": AGENT_VERSION_2_ID,
                "agent_id": AGENT_ID,
                "version": 2,
                "role": "Read-only business context observer",
                "purpose": (
                    "Prove governed agent and assigned-skill execution by inspecting "
                    "selected-business context and returning a bounded observation."
                ),
                "responsibilities": [
                    "Inspect only supplied approved and live business context",
                    "Invoke only explicitly assigned immutable skill versions",
                    "Return the required structured observation",
                    "Escalate when context cannot support a claim",
                ],
                "non_responsibilities": [
                    "Taking external actions",
                    "Making founder decisions",
                    "Creating or changing approved business facts",
                ],
                "allowed_task_types": ["agent.runtime.inspect_context"],
                "allowed_skills": [SUMMARY_SKILL_ID],
                "allowed_tools": [],
                "forbidden_actions": [
                    "External side effects",
                    "Unassigned skill invocation",
                    "Tool invocation",
                    "Credential access",
                    "Treating assumptions as approved facts",
                ],
                "model_policy": {
                    "task_type": "agent.runtime.inspect_context",
                    "sensitivity": "standard",
                    "allow_fallback": True,
                    "max_output_tokens": 256,
                    "token_budget": 8192,
                    "cost_budget_microusd": 10000,
                    "context_token_budget": 1024,
                },
                "data_access_scope": {
                    "business_scope": "run.business_id",
                    "sources": [
                        "business_profile",
                        "approved_profile",
                        "approved_goals",
                        "products_services",
                        "brand",
                        "operating_context",
                        "operational_goals",
                    ],
                    "drafts": "forbidden",
                },
                "risk_level": "R0",
                "maximum_autonomy": "manual_run_only",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "objective",
                        "business_context",
                        "context_id",
                        "context_sha256",
                    ],
                    "properties": {
                        "objective": {"type": "string", "minLength": 1, "maxLength": 500},
                        "business_context": {"type": "object"},
                        "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
                        "context_sha256": {
                            "type": "string",
                            "minLength": 64,
                            "maxLength": 64,
                        },
                        "skill": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["skill_id", "version", "input"],
                            "properties": {
                                "skill_id": {"type": "string", "minLength": 1, "maxLength": 80},
                                "version": {"type": "integer"},
                                "input": {"type": "object"},
                            },
                        },
                    },
                },
                "output_schema": _summary_output_schema(),
                "evaluation_criteria": [
                    "Output matches the agent and invoked-skill schemas",
                    "Claims remain grounded in supplied context",
                    "No unassigned skill, tool, or external action is used",
                ],
                "escalation_criteria": [
                    "A requested skill is not assigned",
                    "Required context is unavailable",
                    "The objective requests an external or forbidden action",
                    "The supplied facts do not support a confident observation",
                ],
                "created_at": now,
            }
        ],
    )
    op.execute(
        sa.text(
            "UPDATE agents SET current_version = 2, updated_at = :now WHERE id = :agent_id"
        ).bindparams(now=now, agent_id=AGENT_ID)
    )
    assignments = sa.table(
        "agent_skill_assignments",
        sa.column("agent_version_id", sa.Uuid()),
        sa.column("skill_version_id", sa.Uuid()),
        sa.column("assigned_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        assignments,
        [
            {
                "agent_version_id": AGENT_VERSION_2_ID,
                "skill_version_id": SUMMARY_VERSION_ID,
                "assigned_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM agent_messages WHERE run_id IN "
            "(SELECT id FROM agent_runs WHERE agent_version_id = :version_id)"
        ).bindparams(version_id=AGENT_VERSION_2_ID)
    )
    op.execute(
        sa.text("DELETE FROM agent_runs WHERE agent_version_id = :version_id").bindparams(
            version_id=AGENT_VERSION_2_ID
        )
    )
    op.drop_index("ix_agent_runs_skill_version_id", table_name="agent_runs")
    op.drop_constraint("fk_agent_runs_skill_version_id", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "skill_version_id")
    op.drop_table("agent_skill_assignments")
    op.execute(
        sa.text("UPDATE agents SET current_version = 1 WHERE id = :agent_id").bindparams(
            agent_id=AGENT_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM agent_versions WHERE id = :version_id").bindparams(
            version_id=AGENT_VERSION_2_ID
        )
    )
    op.drop_index("ix_skill_versions_skill_id", table_name="skill_versions")
    op.drop_table("skill_versions")
    op.drop_table("skills")
