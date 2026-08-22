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
