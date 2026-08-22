from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from redis import Redis
from rq import Queue
from rq.job import JobStatus
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.agents.schema import validate_schema
from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.business_brain.service import (
    SOURCE_TYPES,
    ContextBuildRequest,
    ContextService,
)
from foundora.config import get_settings
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    Agent,
    AgentMessage,
    AgentRun,
    AgentSkillAssignment,
    AgentVersion,
    ModelGatewayCall,
    Skill,
    SkillVersion,
)

logger = logging.getLogger(__name__)
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class AgentNotFound(Exception):
    pass


class AgentRunNotFound(Exception):
    pass


class AgentRunNotCancellable(Exception):
    pass


class SkillNotAssigned(Exception):
    pass


class AgentQueueUnavailable(Exception):
    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        super().__init__("Agent run could not be queued")


@dataclass(frozen=True)
class AgentDefinitionRecord:
    agent: Agent
    version: AgentVersion
    assigned_skills: list[SkillVersion]


@dataclass(frozen=True)
class SkillDefinitionRecord:
    skill: Skill
    version: SkillVersion


@dataclass(frozen=True)
class AgentRunRecord:
    run: AgentRun
    version: AgentVersion
    skill_version: SkillVersion | None
    messages: list[AgentMessage]
    gateway_calls: list[ModelGatewayCall]


@dataclass(frozen=True)
class AgentDashboard:
    business_id: uuid.UUID
    definitions: list[AgentDefinitionRecord]
    skills: list[SkillDefinitionRecord]
    runs: list[AgentRunRecord]


def _now() -> datetime:
    return datetime.now(UTC)


def _agent_job_id(run_id: uuid.UUID, worker_recovery_count: int) -> str:
    base = f"agent-run-{run_id}"
    return base if worker_recovery_count == 0 else f"{base}-recovery-{worker_recovery_count}"


def _enqueue_sync(run_id: uuid.UUID, worker_recovery_count: int = 0) -> None:
    settings = get_settings()
    connection = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        queue = Queue(settings.worker_queue, connection=connection)
        job_id = _agent_job_id(run_id, worker_recovery_count)
        existing = queue.fetch_job(job_id)
        if existing is not None:
            active_statuses = {
                JobStatus.QUEUED,
                JobStatus.STARTED,
                JobStatus.DEFERRED,
                JobStatus.SCHEDULED,
            }
            if existing.get_status(refresh=True) in active_statuses:
                return
            existing.delete(remove_from_queue=True)
        queue.enqueue(
            "foundora.agents.jobs.execute_agent_run",
            str(run_id),
            job_id=job_id,
            job_timeout=300,
            result_ttl=0,
            failure_ttl=86_400,
        )
    finally:
        connection.close()


async def enqueue_agent_run(run_id: uuid.UUID) -> None:
    await asyncio.to_thread(_enqueue_sync, run_id)


class AgentService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        context_service: ContextService | None = None,
        enqueue: Callable[[uuid.UUID], Awaitable[None]] = enqueue_agent_run,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._context_service = context_service or ContextService(self._session_factory)
        self._enqueue = enqueue

    async def dashboard(self, context: AuthContext) -> AgentDashboard:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            definition_rows = (
                await database.execute(
                    select(Agent, AgentVersion)
                    .join(
                        AgentVersion,
                        and_(
                            AgentVersion.agent_id == Agent.id,
                            AgentVersion.version == Agent.current_version,
                        ),
                    )
                    .order_by(Agent.id)
                )
            ).all()
            skill_rows = (
                await database.execute(
                    select(Skill, SkillVersion)
                    .join(
                        SkillVersion,
                        and_(
                            SkillVersion.skill_id == Skill.id,
                            SkillVersion.version == Skill.current_version,
                        ),
                    )
                    .order_by(Skill.id)
                )
            ).all()
            version_ids = [version.id for _, version in definition_rows]
            assigned_by_agent_version: dict[uuid.UUID, list[SkillVersion]] = {
                version_id: [] for version_id in version_ids
            }
            if version_ids:
                assignment_rows = (
                    await database.execute(
                        select(AgentSkillAssignment.agent_version_id, SkillVersion)
                        .join(
                            SkillVersion,
                            SkillVersion.id == AgentSkillAssignment.skill_version_id,
                        )
                        .where(AgentSkillAssignment.agent_version_id.in_(version_ids))
                        .order_by(SkillVersion.skill_id, SkillVersion.version)
                    )
                ).all()
                for agent_version_id, assigned_version in assignment_rows:
                    assigned_by_agent_version[agent_version_id].append(assigned_version)
            run_rows = (
                await database.execute(
                    select(AgentRun, AgentVersion, SkillVersion)
                    .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
                    .outerjoin(SkillVersion, SkillVersion.id == AgentRun.skill_version_id)
                    .where(AgentRun.business_id == business.id)
                    .order_by(desc(AgentRun.created_at))
                    .limit(20)
                )
            ).all()
            run_ids = [run.id for run, _, _ in run_rows]
            calls_by_run: dict[uuid.UUID, list[ModelGatewayCall]] = {
                run_id: [] for run_id in run_ids
            }
            if run_ids:
                calls = list(
                    await database.scalars(
                        select(ModelGatewayCall)
                        .where(ModelGatewayCall.agent_run_id.in_(run_ids))
                        .order_by(
                            ModelGatewayCall.created_at,
                            ModelGatewayCall.attempt_number,
                        )
                    )
                )
                for call in calls:
                    if call.agent_run_id is not None:
                        calls_by_run[call.agent_run_id].append(call)
        return AgentDashboard(
            business_id=business.id,
            definitions=[
                AgentDefinitionRecord(
                    agent=agent,
                    version=version,
                    assigned_skills=assigned_by_agent_version.get(version.id, []),
                )
                for agent, version in definition_rows
            ],
            skills=[
                SkillDefinitionRecord(skill=skill, version=version) for skill, version in skill_rows
            ],
            runs=[
                AgentRunRecord(
                    run=run,
                    version=version,
                    skill_version=skill_version,
                    messages=[],
                    gateway_calls=calls_by_run.get(run.id, []),
                )
                for run, version, skill_version in run_rows
            ],
        )

    async def create_run(
        self,
        context: AuthContext,
        agent_id: str,
        objective: str,
        skill_id: str | None = None,
        skill_input: dict[str, object] | None = None,
    ) -> AgentRunRecord:
        skill_version: SkillVersion | None = None
        normalized_skill_input = skill_input or {}
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            row = (
                await database.execute(
                    select(Agent, AgentVersion)
                    .join(
                        AgentVersion,
                        and_(
                            AgentVersion.agent_id == Agent.id,
                            AgentVersion.version == Agent.current_version,
                        ),
                    )
                    .where(Agent.id == agent_id, Agent.enabled.is_(True))
                )
            ).one_or_none()
            if row is None:
                raise AgentNotFound
            agent, version = row
            if skill_id is not None:
                skill_row = (
                    await database.execute(
                        select(Skill, SkillVersion)
                        .join(
                            SkillVersion,
                            and_(
                                SkillVersion.skill_id == Skill.id,
                                SkillVersion.version == Skill.current_version,
                            ),
                        )
                        .join(
                            AgentSkillAssignment,
                            and_(
                                AgentSkillAssignment.skill_version_id == SkillVersion.id,
                                AgentSkillAssignment.agent_version_id == version.id,
                            ),
                        )
                        .where(Skill.id == skill_id, Skill.enabled.is_(True))
                    )
                ).one_or_none()
                if (
                    skill_row is None
                    or skill_id not in version.allowed_skills
                    or agent.id not in skill_row[1].compatible_agents
                ):
                    raise SkillNotAssigned
                _, skill_version = skill_row
                validate_schema(normalized_skill_input, skill_version.input_schema)
            elif normalized_skill_input:
                raise SkillNotAssigned

        policy = version.model_policy
        context_budget = policy.get("context_token_budget")
        if not isinstance(context_budget, int) or isinstance(context_budget, bool):
            raise AgentNotFound
        allowed_sources = version.data_access_scope.get("sources")
        if not isinstance(allowed_sources, list):
            raise AgentNotFound
        selected_sources = frozenset(source for source in SOURCE_TYPES if source in allowed_sources)
        business_context = await self._context_service.build(
            context,
            ContextBuildRequest(
                purpose="agent_runtime",
                token_budget=context_budget,
                selected_source_types=selected_sources,
            ),
        )
        compiled_context = json.loads(business_context.context)
        if not isinstance(compiled_context, dict):
            raise AgentNotFound
        structured_input: dict[str, object] = {
            "objective": objective,
            "business_context": compiled_context,
            "context_id": business_context.context_id,
            "context_sha256": business_context.context_sha256,
        }
        if skill_version is not None:
            structured_input["skill"] = {
                "skill_id": skill_version.skill_id,
                "version": skill_version.version,
                "input": normalized_skill_input,
            }
        validate_schema(structured_input, version.input_schema)
        now = _now()
        run = AgentRun(
            id=uuid.uuid4(),
            business_id=business.id,
            agent_id=agent.id,
            agent_version_id=version.id,
            skill_version_id=skill_version.id if skill_version is not None else None,
            status="queued",
            structured_input=structured_input,
            structured_output=None,
            model_operation_id=None,
            error_type=None,
            error_message=None,
            worker_recovery_count=0,
            created_at=now,
            queued_at=now,
            started_at=None,
            completed_at=None,
            cancellation_requested_at=None,
            cancelled_at=None,
        )
        message = AgentMessage(
            id=uuid.uuid4(),
            run_id=run.id,
            sequence=1,
            role="user",
            message_type="input",
            content={
                "objective": objective,
                "context_id": business_context.context_id,
                "skill_id": skill_version.skill_id if skill_version is not None else None,
                "skill_input": normalized_skill_input if skill_version is not None else None,
            },
            created_at=now,
        )
        async with self._session_factory() as database:
            database.add(run)
            # AgentRun and AgentMessage deliberately have no ORM relationship.
            # Flush the parent explicitly so PostgreSQL never observes the child
            # insert before its foreign-key target.
            await database.flush()
            database.add(message)
            await database.commit()
        try:
            await self._enqueue(run.id)
        except Exception:
            logger.exception(
                "Agent run enqueue failed",
                extra={"event": "agent.run.enqueue_failed", "agent_run_id": str(run.id)},
            )
            await self._mark_enqueue_failure(run.id)
            raise AgentQueueUnavailable(run.id) from None
        return await self._record_for_business(run.id, business.id)

    async def inspect_run(self, context: AuthContext, run_id: uuid.UUID) -> AgentRunRecord:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
        return await self._record_for_business(run_id, business.id)

    async def cancel_run(self, context: AuthContext, run_id: uuid.UUID) -> AgentRunRecord:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            run = await database.scalar(
                select(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.business_id == business.id)
                .with_for_update()
            )
            if run is None:
                raise AgentRunNotFound
            if run.status in TERMINAL_STATUSES:
                raise AgentRunNotCancellable
            now = _now()
            run.status = "cancelled"
            run.cancellation_requested_at = now
            run.cancelled_at = now
            run.completed_at = now
            database.add(
                AgentMessage(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    sequence=2,
                    role="system",
                    message_type="error",
                    content={"error_type": "owner_cancelled"},
                    created_at=now,
                )
            )
            await database.commit()
        return await self._record_for_business(run_id, business.id)

    async def _mark_enqueue_failure(self, run_id: uuid.UUID) -> None:
        async with self._session_factory() as database:
            run = await database.scalar(
                select(AgentRun).where(AgentRun.id == run_id).with_for_update()
            )
            if run is None or run.status != "queued":
                return
            run.status = "failed"
            run.error_type = "queue_unavailable"
            run.error_message = "The background worker queue was unavailable"
            run.completed_at = _now()
            database.add(
                AgentMessage(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    sequence=2,
                    role="system",
                    message_type="error",
                    content={"error_type": run.error_type, "message": run.error_message},
                    created_at=run.completed_at,
                )
            )
            await database.commit()

    async def _record_for_business(
        self, run_id: uuid.UUID, business_id: uuid.UUID
    ) -> AgentRunRecord:
        async with self._session_factory() as database:
            row = (
                await database.execute(
                    select(AgentRun, AgentVersion, SkillVersion)
                    .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
                    .outerjoin(SkillVersion, SkillVersion.id == AgentRun.skill_version_id)
                    .where(AgentRun.id == run_id, AgentRun.business_id == business_id)
                )
            ).one_or_none()
            if row is None:
                raise AgentRunNotFound
            run, version, skill_version = row
            messages = list(
                await database.scalars(
                    select(AgentMessage)
                    .where(AgentMessage.run_id == run.id)
                    .order_by(AgentMessage.sequence)
                )
            )
            calls = list(
                await database.scalars(
                    select(ModelGatewayCall)
                    .where(ModelGatewayCall.agent_run_id == run.id)
                    .order_by(
                        ModelGatewayCall.created_at,
                        ModelGatewayCall.attempt_number,
                    )
                )
            )
        return AgentRunRecord(
            run=run,
            version=version,
            skill_version=skill_version,
            messages=messages,
            gateway_calls=calls,
        )
