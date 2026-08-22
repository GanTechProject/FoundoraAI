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
    AgentVersion,
    ModelGatewayCall,
)

logger = logging.getLogger(__name__)
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class AgentNotFound(Exception):
    pass


class AgentRunNotFound(Exception):
    pass


class AgentRunNotCancellable(Exception):
    pass


class AgentQueueUnavailable(Exception):
    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        super().__init__("Agent run could not be queued")


@dataclass(frozen=True)
class AgentDefinitionRecord:
    agent: Agent
    version: AgentVersion


@dataclass(frozen=True)
class AgentRunRecord:
    run: AgentRun
    version: AgentVersion
    messages: list[AgentMessage]
    gateway_calls: list[ModelGatewayCall]


@dataclass(frozen=True)
class AgentDashboard:
    business_id: uuid.UUID
    definitions: list[AgentDefinitionRecord]
    runs: list[AgentRunRecord]


def _now() -> datetime:
    return datetime.now(UTC)


def _enqueue_sync(run_id: uuid.UUID) -> None:
    settings = get_settings()
    connection = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        Queue(settings.worker_queue, connection=connection).enqueue(
            "foundora.agents.jobs.execute_agent_run",
            str(run_id),
            job_id=f"agent-run-{run_id}",
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
            run_rows = (
                await database.execute(
                    select(AgentRun, AgentVersion)
                    .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
                    .where(AgentRun.business_id == business.id)
                    .order_by(desc(AgentRun.created_at))
                    .limit(20)
                )
            ).all()
            run_ids = [run.id for run, _ in run_rows]
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
                AgentDefinitionRecord(agent=agent, version=version)
                for agent, version in definition_rows
            ],
            runs=[
                AgentRunRecord(
                    run=run,
                    version=version,
                    messages=[],
                    gateway_calls=calls_by_run.get(run.id, []),
                )
                for run, version in run_rows
            ],
        )

    async def create_run(
        self, context: AuthContext, agent_id: str, objective: str
    ) -> AgentRunRecord:
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
        validate_schema(structured_input, version.input_schema)
        now = _now()
        run = AgentRun(
            id=uuid.uuid4(),
            business_id=business.id,
            agent_id=agent.id,
            agent_version_id=version.id,
            status="queued",
            structured_input=structured_input,
            structured_output=None,
            model_operation_id=None,
            error_type=None,
            error_message=None,
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
            content={"objective": objective, "context_id": business_context.context_id},
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
                    select(AgentRun, AgentVersion)
                    .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
                    .where(AgentRun.id == run_id, AgentRun.business_id == business_id)
                )
            ).one_or_none()
            if row is None:
                raise AgentRunNotFound
            run, version = row
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
            messages=messages,
            gateway_calls=calls,
        )
