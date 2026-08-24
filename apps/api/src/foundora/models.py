from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owners"
    __table_args__ = (CheckConstraint("singleton_key = 1", name="ck_owners_singleton_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    singleton_key: Mapped[int] = mapped_column(SmallInteger, unique=True, default=1)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OwnerSession(Base):
    __tablename__ = "owner_sessions"
    __table_args__ = (
        Index("ix_owner_sessions_owner_active", "owner_id", "revoked_at"),
        Index("ix_owner_sessions_expiration", "expires_at", "idle_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    selected_business_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True
    )


class Business(Base):
    __tablename__ = "businesses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planning', 'active', 'paused')",
            name="ck_businesses_status",
        ),
        Index("ix_businesses_owner_archived", "owner_id", "archived_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="planning")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BusinessPreference(Base):
    __tablename__ = "business_preferences"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    locale: Mapped[str] = mapped_column(String(35), default="en")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BusinessGoal(Base):
    __tablename__ = "business_goals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')",
            name="ck_business_goals_status",
        ),
        Index("ix_business_goals_business_status", "business_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index("uq_businesses_owner_name", Business.owner_id, func.lower(Business.name), unique=True)


class BusinessOnboardingDraft(Base):
    __tablename__ = "business_onboarding_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'review', 'approved')",
            name="ck_business_onboarding_drafts_status",
        ),
        CheckConstraint(
            "current_step BETWEEN 1 AND 5",
            name="ck_business_onboarding_drafts_current_step",
        ),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), default="draft")
    current_step: Mapped[int] = mapped_column(SmallInteger, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    business_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(160), nullable=True)
    geography: Mapped[str | None] = mapped_column(String(240), nullable=True)
    problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    offer: Mapped[str | None] = mapped_column(Text, nullable=True)
    goals: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    existing_assets: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    constraints: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    budget: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_preferences: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_services: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovedBusinessProfile(Base):
    __tablename__ = "approved_business_profiles"
    __table_args__ = (
        CheckConstraint(
            "business_type IN ('idea', 'existing')",
            name="ck_approved_business_profiles_business_type",
        ),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer)
    business_type: Mapped[str] = mapped_column(String(16))
    business_name: Mapped[str] = mapped_column(String(120))
    industry: Mapped[str] = mapped_column(String(160))
    geography: Mapped[str] = mapped_column(String(240))
    problem: Mapped[str] = mapped_column(Text)
    target_audience: Mapped[str] = mapped_column(Text)
    offer: Mapped[str] = mapped_column(Text)
    goals: Mapped[list[str]] = mapped_column(JSON)
    existing_assets: Mapped[list[str]] = mapped_column(JSON)
    constraints: Mapped[list[str]] = mapped_column(JSON)
    budget: Mapped[str] = mapped_column(Text)
    brand_preferences: Mapped[str] = mapped_column(Text)
    connected_services: Mapped[list[str]] = mapped_column(JSON)
    approved_by_owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (CheckConstraint("current_version > 0", name="ck_agents_current_version"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(default=True)
    current_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_agent_versions_version"),
        CheckConstraint(
            "risk_level IN ('R0', 'R1', 'R2', 'R3', 'R4', 'R5')",
            name="ck_agent_versions_risk_level",
        ),
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str] = mapped_column(Text)
    responsibilities: Mapped[list[str]] = mapped_column(JSON)
    non_responsibilities: Mapped[list[str]] = mapped_column(JSON)
    allowed_task_types: Mapped[list[str]] = mapped_column(JSON)
    allowed_skills: Mapped[list[str]] = mapped_column(JSON)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON)
    forbidden_actions: Mapped[list[str]] = mapped_column(JSON)
    model_policy: Mapped[dict[str, object]] = mapped_column(JSON)
    data_access_scope: Mapped[dict[str, object]] = mapped_column(JSON)
    risk_level: Mapped[str] = mapped_column(String(2))
    maximum_autonomy: Mapped[str] = mapped_column(String(32))
    input_schema: Mapped[dict[str, object]] = mapped_column(JSON)
    output_schema: Mapped[dict[str, object]] = mapped_column(JSON)
    evaluation_criteria: Mapped[list[str]] = mapped_column(JSON)
    escalation_criteria: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (CheckConstraint("current_version > 0", name="ck_skills_current_version"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(default=True)
    current_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_skill_versions_version"),
        CheckConstraint(
            "risk_class IN ('R0', 'R1', 'R2', 'R3', 'R4', 'R5')",
            name="ck_skill_versions_risk_class",
        ),
        UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    compatible_agents: Mapped[list[str]] = mapped_column(JSON)
    prerequisites: Mapped[list[str]] = mapped_column(JSON)
    input_schema: Mapped[dict[str, object]] = mapped_column(JSON)
    output_schema: Mapped[dict[str, object]] = mapped_column(JSON)
    tool_requirements: Mapped[list[str]] = mapped_column(JSON)
    workflow: Mapped[list[str]] = mapped_column(JSON)
    permissions: Mapped[list[str]] = mapped_column(JSON)
    risk_class: Mapped[str] = mapped_column(String(2))
    test_fixtures: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    evaluation_rubric: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentSkillAssignment(Base):
    __tablename__ = "agent_skill_assignments"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="CASCADE"), primary_key=True
    )
    skill_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'waiting_tool', 'waiting_approval', "
            "'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
        Index("ix_agent_runs_business_created", "business_id", "created_at"),
        Index("ix_agent_runs_business_status", "business_id", "status"),
        CheckConstraint(
            "worker_recovery_count BETWEEN 0 AND 3",
            name="ck_agent_runs_worker_recovery_count",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"))
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT"), index=True
    )
    skill_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24))
    structured_input: Mapped[dict[str, object]] = mapped_column(JSON)
    structured_output: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    model_operation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    worker_recovery_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_agent_messages_role",
        ),
        CheckConstraint(
            "message_type IN ('input', 'output', 'error')",
            name="ck_agent_messages_type",
        ),
        CheckConstraint("sequence > 0", name="ck_agent_messages_sequence"),
        UniqueConstraint("run_id", "sequence", name="uq_agent_messages_run_sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    message_type: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'planned', 'queued', 'running', 'blocked', "
            "'waiting_approval', 'completed', 'failed', 'cancelled')",
            name="ck_tasks_status",
        ),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_tasks_priority"),
        CheckConstraint(
            "owner_type IN ('unassigned', 'founder', 'agent')",
            name="ck_tasks_owner_type",
        ),
        CheckConstraint(
            "(owner_type = 'agent' AND owner_agent_id IS NOT NULL AND "
            "owner_agent_version_id IS NOT NULL) OR "
            "(owner_type <> 'agent' AND owner_agent_id IS NULL AND "
            "owner_agent_version_id IS NULL)",
            name="ck_tasks_agent_owner",
        ),
        CheckConstraint(
            "max_retries BETWEEN 0 AND 10 AND retry_count BETWEEN 0 AND max_retries",
            name="ck_tasks_retries",
        ),
        Index("ix_tasks_business_status", "business_id", "status"),
        Index("ix_tasks_business_priority_due", "business_id", "priority", "due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("business_goals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(SmallInteger, default=3)
    owner_type: Mapped[str] = mapped_column(String(16), default="unassigned")
    owner_agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True
    )
    owner_agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default="draft")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_retries: Mapped[int] = mapped_column(SmallInteger, default=0)
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        CheckConstraint("task_id <> depends_on_task_id", name="ck_task_dependencies_not_self"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'dependency_added', 'status_changed', 'retried')",
            name="ck_task_events_type",
        ),
        UniqueConstraint(
            "task_id", "event_type", "idempotency_key", name="uq_task_events_idempotency"
        ),
        Index("ix_task_events_task_created", "task_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    actor_owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (CheckConstraint("current_version > 0", name="ck_workflows_current_version"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(default=True)
    current_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_workflow_versions_version"),
        UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    input_schema: Mapped[dict[str, object]] = mapped_column(JSON)
    output_schema: Mapped[dict[str, object]] = mapped_column(JSON)
    definition: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'waiting', 'waiting_approval', "
            "'waiting_agent', 'completed', 'failed', 'cancelled')",
            name="ck_workflow_runs_status",
        ),
        CheckConstraint(
            "worker_recovery_count BETWEEN 0 AND 3",
            name="ck_workflow_runs_worker_recovery_count",
        ),
        Index("ix_workflow_runs_business_created", "business_id", "created_at"),
        Index("ix_workflow_runs_business_status", "business_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="RESTRICT"))
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="RESTRICT"), index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24))
    structured_input: Mapped[dict[str, object]] = mapped_column(JSON)
    structured_output: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    current_step_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    worker_recovery_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_by_owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowStepRun(Base):
    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        CheckConstraint(
            "step_type IN ('tool', 'agent', 'approval', 'wait')",
            name="ck_workflow_step_runs_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'waiting', 'waiting_approval', "
            "'waiting_agent', 'completed', 'skipped', 'failed', 'cancelled', 'compensated')",
            name="ck_workflow_step_runs_status",
        ),
        CheckConstraint(
            "max_retries BETWEEN 0 AND 10 AND attempt_count BETWEEN 0 AND max_retries + 1",
            name="ck_workflow_step_runs_attempts",
        ),
        UniqueConstraint("workflow_run_id", "step_key", name="uq_workflow_step_runs_key"),
        Index("ix_workflow_step_runs_run_sequence", "workflow_run_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    step_key: Mapped[str] = mapped_column(String(80))
    sequence: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempt_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    max_retries: Mapped[int] = mapped_column(SmallInteger, default=0)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    governance_action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("governance_actions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    structured_input: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    structured_output: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_workflow_events_sequence"),
        UniqueConstraint("workflow_run_id", "sequence", name="uq_workflow_events_sequence"),
        UniqueConstraint(
            "workflow_run_id", "event_type", "idempotency_key", name="uq_workflow_events_key"
        ),
        Index("ix_workflow_events_run_created", "workflow_run_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40))
    step_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (CheckConstraint("current_version > 0", name="ck_policies_current_version"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(default=True)
    current_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_policy_versions_version"),
        UniqueConstraint("policy_id", "version", name="uq_policy_versions_policy_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    rules: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GlobalGovernanceControl(Base):
    __tablename__ = "global_governance_controls"
    __table_args__ = (
        CheckConstraint("singleton_key = 1", name="ck_global_governance_singleton"),
        CheckConstraint("revision > 0", name="ck_global_governance_revision"),
    )

    singleton_key: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    kill_switch_enabled: Mapped[bool] = mapped_column(default=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GovernanceSetting(Base):
    __tablename__ = "governance_settings"
    __table_args__ = (
        CheckConstraint(
            "autonomy_level IN ('OFF', 'RECOMMEND', 'ASSISTED', 'AUTONOMOUS_LOW_RISK')",
            name="ck_governance_settings_autonomy",
        ),
        CheckConstraint(
            "daily_spend_limit_microusd >= 0 AND per_action_spend_limit_microusd >= 0",
            name="ck_governance_settings_spend_limits",
        ),
        CheckConstraint("revision > 0", name="ck_governance_settings_revision"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )
    autonomy_level: Mapped[str] = mapped_column(String(32), default="OFF")
    daily_spend_limit_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    per_action_spend_limit_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GovernanceToolPermission(Base):
    __tablename__ = "governance_tool_permissions"
    __table_args__ = (CheckConstraint("revision > 0", name="ck_tool_permissions_revision"),)

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )
    tool_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GovernanceAction(Base):
    __tablename__ = "governance_actions"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('owner', 'agent', 'workflow', 'system')",
            name="ck_governance_actions_actor_type",
        ),
        CheckConstraint(
            "risk_class IN ('R0', 'R1', 'R2', 'R3', 'R4', 'R5')",
            name="ck_governance_actions_risk_class",
        ),
        CheckConstraint(
            "execution_mode IN ('manual', 'autonomous')",
            name="ck_governance_actions_execution_mode",
        ),
        CheckConstraint(
            "data_classification IN ('public', 'internal', 'confidential', 'restricted')",
            name="ck_governance_actions_data_classification",
        ),
        CheckConstraint(
            "status IN ('approval_required', 'approved', 'rejected', 'authorized', "
            "'denied', 'blocked')",
            name="ck_governance_actions_status",
        ),
        CheckConstraint("requested_spend_microusd >= 0", name="ck_governance_actions_spend"),
        UniqueConstraint(
            "business_id", "idempotency_key", name="uq_governance_actions_idempotency"
        ),
        Index("ix_governance_actions_business_created", "business_id", "created_at"),
        Index("ix_governance_actions_business_status", "business_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("policy_versions.id", ondelete="RESTRICT"), index=True
    )
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workflow_step_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action_type: Mapped[str] = mapped_column(String(120))
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tool_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    risk_class: Mapped[str] = mapped_column(String(2))
    execution_mode: Mapped[str] = mapped_column(String(16))
    data_classification: Mapped[str] = mapped_column(String(16))
    requested_spend_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    frequency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    target: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    rationale: Mapped[str] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_by_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_approval_requests_status",
        ),
        UniqueConstraint("action_id", name="uq_approval_requests_action"),
        Index("ix_approval_requests_business_status", "business_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    action_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("governance_actions.id", ondelete="CASCADE"), index=True
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")
    prompt: Mapped[str] = mapped_column(String(500))
    decision_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requested_by_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), nullable=True
    )
    decided_by_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GovernanceAuditEvent(Base):
    __tablename__ = "governance_audit_events"
    __table_args__ = (
        Index("ix_governance_audit_business_created", "business_id", "created_at"),
        Index("ix_governance_audit_action_created", "action_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=True, index=True
    )
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("governance_actions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64))
    actor_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelGatewayCall(Base):
    __tablename__ = "model_gateway_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_model_gateway_calls_status",
        ),
        CheckConstraint(
            "sensitivity IN ('standard', 'sensitive')",
            name="ck_model_gateway_calls_sensitivity",
        ),
        CheckConstraint(
            "attempt_number > 0 AND retry_number >= 0",
            name="ck_model_gateway_calls_attempts",
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND "
            "total_tokens = input_tokens + output_tokens",
            name="ck_model_gateway_calls_tokens",
        ),
        CheckConstraint(
            "estimated_cost_microusd >= 0 AND latency_ms >= 0",
            name="ck_model_gateway_calls_measurements",
        ),
        Index("ix_model_gateway_calls_business_created", "business_id", "created_at"),
        Index("ix_model_gateway_calls_operation_attempt", "operation_id", "attempt_number"),
        UniqueConstraint(
            "operation_id",
            "attempt_number",
            name="uq_model_gateway_calls_operation_attempt",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    operation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    request_id: Mapped[str] = mapped_column(String(128))
    task_type: Mapped[str] = mapped_column(String(80))
    sensitivity: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16))
    attempt_number: Mapped[int] = mapped_column(SmallInteger)
    retry_number: Mapped[int] = mapped_column(SmallInteger)
    fallback_from: Mapped[str | None] = mapped_column(String(32), nullable=True)
    streamed: Mapped[bool] = mapped_column(default=False)
    structured: Mapped[bool] = mapped_column(default=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelProviderValidation(Base):
    __tablename__ = "model_provider_validations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('valid', 'invalid')",
            name="ck_model_provider_validations_status",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="ck_model_provider_validations_latency",
        ),
        Index("ix_model_provider_validations_provider_checked", "provider", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16))
    latency_ms: Mapped[int] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
