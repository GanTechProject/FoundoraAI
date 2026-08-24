"""Add advisory Founder/CEO and Chief-of-Staff agents.

Revision ID: 20260825_15
Revises: 20260825_14
Create Date: 2026-08-25
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "20260825_15"
down_revision: str | None = "20260825_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CEO_AGENT_ID = "founder-ceo"
PLANNING_AGENT_ID = "chief-of-staff-planning"
CEO_VERSION_ID = UUID("00000000-0000-0000-0000-000000001501")
PLANNING_VERSION_ID = UUID("00000000-0000-0000-0000-000000001502")


def _string_array(*, maximum: int, item_maximum: int = 500) -> dict[str, object]:
    return {
        "type": "array",
        "maxItems": maximum,
        "items": {"type": "string", "minLength": 1, "maxLength": item_maximum},
    }


def _input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["objective", "business_context", "context_id", "context_sha256"],
        "properties": {
            "objective": {"type": "string", "minLength": 1, "maxLength": 500},
            "business_context": {"type": "object"},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "context_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    }


def _ceo_output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "plan_status",
            "context_id",
            "plan_title",
            "objective_interpretation",
            "business_state_summary",
            "priorities",
            "assumptions",
            "limitations",
            "founder_decisions_required",
        ],
        "properties": {
            "plan_status": {"type": "string", "minLength": 1, "maxLength": 20},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "plan_title": {"type": "string", "minLength": 1, "maxLength": 160},
            "objective_interpretation": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1000,
            },
            "business_state_summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1500,
            },
            "priorities": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "priority_id",
                        "title",
                        "rationale",
                        "evidence_refs",
                        "delegation_target",
                        "requested_work",
                        "risk_level",
                        "approval_required",
                    ],
                    "properties": {
                        "priority_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 40,
                        },
                        "title": {"type": "string", "minLength": 1, "maxLength": 200},
                        "rationale": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 800,
                        },
                        "evidence_refs": _string_array(maximum=8, item_maximum=500),
                        "delegation_target": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 80,
                        },
                        "requested_work": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 800,
                        },
                        "risk_level": {"type": "string", "minLength": 2, "maxLength": 2},
                        "approval_required": {"type": "boolean"},
                    },
                },
            },
            "assumptions": _string_array(maximum=10),
            "limitations": _string_array(maximum=10),
            "founder_decisions_required": _string_array(maximum=10),
        },
    }


def _planning_output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "plan_status",
            "context_id",
            "plan_title",
            "objective",
            "tasks",
            "progress_review",
            "assumptions",
            "limitations",
            "founder_decisions_required",
        ],
        "properties": {
            "plan_status": {"type": "string", "minLength": 1, "maxLength": 20},
            "context_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "plan_title": {"type": "string", "minLength": 1, "maxLength": 160},
            "objective": {"type": "string", "minLength": 1, "maxLength": 1000},
            "tasks": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "task_id",
                        "title",
                        "description",
                        "priority",
                        "depends_on",
                        "candidate_agent",
                        "requested_specialist_work",
                        "evidence_refs",
                        "completion_criteria",
                    ],
                    "properties": {
                        "task_id": {"type": "string", "minLength": 1, "maxLength": 40},
                        "title": {"type": "string", "minLength": 1, "maxLength": 200},
                        "description": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1000,
                        },
                        "priority": {"type": "string", "minLength": 1, "maxLength": 20},
                        "depends_on": _string_array(maximum=10, item_maximum=40),
                        "candidate_agent": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 80,
                        },
                        "requested_specialist_work": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 800,
                        },
                        "evidence_refs": _string_array(maximum=8, item_maximum=500),
                        "completion_criteria": _string_array(maximum=8),
                    },
                },
            },
            "progress_review": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["task_reference", "status_summary", "evidence_refs"],
                    "properties": {
                        "task_reference": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 500,
                        },
                        "status_summary": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 800,
                        },
                        "evidence_refs": _string_array(maximum=4, item_maximum=500),
                    },
                },
            },
            "assumptions": _string_array(maximum=10),
            "limitations": _string_array(maximum=10),
            "founder_decisions_required": _string_array(maximum=10),
        },
    }


def upgrade() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    agents = sa.table(
        "agents",
        sa.column("id", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("current_version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        agents,
        [
            {
                "id": CEO_AGENT_ID,
                "display_name": "Founder / CEO Agent",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": PLANNING_AGENT_ID,
                "display_name": "Chief-of-Staff / Planning Agent",
                "enabled": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    versions = sa.table(
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
    common_sources = [
        "business_profile",
        "approved_profile",
        "approved_goals",
        "products_services",
        "brand",
        "operating_context",
        "operational_goals",
        "current_tasks",
        "relevant_memories",
    ]
    common_forbidden = [
        "Tool invocation",
        "External side effects",
        "Creating, updating, queueing, or completing tasks or workflows",
        "Granting approvals or changing policy",
        "Spending money or contacting people",
        "Claiming a proposed delegation was executed",
        "Credential or secret access",
        "Treating assumptions as approved facts",
    ]
    common_policy: dict[str, object] = {
        "sensitivity": "sensitive",
        "allow_fallback": False,
        "max_output_tokens": 1800,
        "token_budget": 24000,
        "cost_budget_microusd": 50000,
        "context_token_budget": 6000,
    }
    op.bulk_insert(
        versions,
        [
            {
                "id": CEO_VERSION_ID,
                "agent_id": CEO_AGENT_ID,
                "version": 1,
                "role": "Founder-aligned executive planning and prioritization advisor",
                "purpose": (
                    "Interpret a founder objective against the selected business state, "
                    "prioritize grounded next work, and propose traceable delegations without "
                    "executing them."
                ),
                "responsibilities": [
                    "Interpret the founder's stated objective",
                    "Review the supplied selected-business context snapshot",
                    "Prioritize evidence-backed next work",
                    "Propose delegation to the planning agent, founder, or a future specialist",
                    "Expose assumptions, limitations, risk, and founder decisions",
                ],
                "non_responsibilities": [
                    "Executing tasks, workflows, tools, spend, or external communication",
                    "Approving its own plan or changing founder-owned facts",
                    "Inventing specialist availability or claiming delegation occurred",
                ],
                "allowed_task_types": ["executive.ceo.plan"],
                "allowed_skills": [],
                "allowed_tools": [],
                "forbidden_actions": common_forbidden,
                "model_policy": {**common_policy, "task_type": "executive.ceo.plan"},
                "data_access_scope": {
                    "business_scope": "run.business_id",
                    "sources": common_sources,
                    "drafts": "forbidden",
                    "knowledge_without_explicit_retrieval": "forbidden",
                },
                "risk_level": "R0",
                "maximum_autonomy": "manual_advisory_only",
                "input_schema": _input_schema(),
                "output_schema": _ceo_output_schema(),
                "evaluation_criteria": [
                    "The objective interpretation and priorities are grounded in supplied context",
                    "Every priority cites an exact source reference from the pinned snapshot",
                    "Delegations remain proposed and distinguish future specialists",
                    "Assumptions, limitations, risk, and approval needs remain explicit",
                    "No tool, task, workflow, approval, spend, or external action is claimed",
                ],
                "escalation_criteria": [
                    "The founder objective conflicts with policy or approved business state",
                    "Required evidence is absent or contradictory",
                    "A priority is R3 or higher or needs founder authority",
                    "Requested specialist capability is not implemented",
                ],
                "created_at": now,
            },
            {
                "id": PLANNING_VERSION_ID,
                "agent_id": PLANNING_AGENT_ID,
                "version": 1,
                "role": "Chief-of-Staff advisory plan decomposition and coordination",
                "purpose": (
                    "Convert a founder objective into an evidence-backed proposed task graph with "
                    "dependencies, candidate ownership, and completion criteria."
                ),
                "responsibilities": [
                    "Turn the objective into an ordered proposed plan",
                    "Identify task dependencies and completion criteria",
                    "Propose candidate agents or future specialist work honestly",
                    "Review progress of existing tasks from current-task evidence",
                    "Expose assumptions, limitations, and founder decisions",
                    "Keep every task traceable to the supplied context snapshot",
                ],
                "non_responsibilities": [
                    "Creating or changing durable tasks or workflow runs",
                    "Executing a delegation or contacting a specialist",
                    "Granting approvals, spending, or taking external action",
                ],
                "allowed_task_types": ["executive.planning.decompose"],
                "allowed_skills": [],
                "allowed_tools": [],
                "forbidden_actions": common_forbidden,
                "model_policy": {
                    **common_policy,
                    "task_type": "executive.planning.decompose",
                },
                "data_access_scope": {
                    "business_scope": "run.business_id",
                    "sources": common_sources,
                    "drafts": "forbidden",
                    "knowledge_without_explicit_retrieval": "forbidden",
                },
                "risk_level": "R0",
                "maximum_autonomy": "manual_advisory_only",
                "input_schema": _input_schema(),
                "output_schema": _planning_output_schema(),
                "evaluation_criteria": [
                    "The proposed task graph addresses the founder objective",
                    "Every task cites an exact source reference from the pinned snapshot",
                    "Dependencies refer to unique tasks and remain acyclic",
                    "Progress statements cite exact current-task references",
                    "Candidate ownership never implies the work was assigned or executed",
                    (
                        "No durable task, workflow, tool, approval, spend, or external "
                        "action is claimed"
                    ),
                ],
                "escalation_criteria": [
                    "Required evidence or completion criteria are unavailable",
                    "The plan requires an unimplemented specialist",
                    "The objective requires approval, spend, or external execution",
                    "Dependencies cannot be resolved from current business state",
                ],
                "created_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tasks SET owner_type = 'unassigned', owner_agent_id = NULL, "
            "owner_agent_version_id = NULL WHERE owner_agent_version_id IN (:ceo, :planning)"
        ).bindparams(ceo=CEO_VERSION_ID, planning=PLANNING_VERSION_ID)
    )
    op.execute(
        sa.text(
            "DELETE FROM agent_messages WHERE run_id IN "
            "(SELECT id FROM agent_runs WHERE agent_version_id IN (:ceo, :planning))"
        ).bindparams(ceo=CEO_VERSION_ID, planning=PLANNING_VERSION_ID)
    )
    op.execute(
        sa.text("DELETE FROM agent_runs WHERE agent_version_id IN (:ceo, :planning)").bindparams(
            ceo=CEO_VERSION_ID, planning=PLANNING_VERSION_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM agent_versions WHERE id IN (:ceo, :planning)").bindparams(
            ceo=CEO_VERSION_ID, planning=PLANNING_VERSION_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM agents WHERE id IN (:ceo, :planning)").bindparams(
            ceo=CEO_AGENT_ID, planning=PLANNING_AGENT_ID
        )
    )
