from __future__ import annotations

import asyncio
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
from foundora.config import get_settings
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    AgentRun,
    Task,
    Workflow,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStepRun,
    WorkflowVersion,
)
from foundora.workflows.definition import StepDefinition, parse_definition
from foundora.workflows.runtime import add_event, fail_workflow

logger = logging.getLogger(__name__)
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class WorkflowNotFound(Exception):
    pass


class WorkflowRunNotFound(Exception):
    pass


class WorkflowTaskNotFound(Exception):
    pass


class WorkflowResumeNotAllowed(Exception):
    pass


class WorkflowRunNotCancellable(Exception):
    pass


class WorkflowQueueUnavailable(Exception):
    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        super().__init__("Workflow run could not be queued")


@dataclass(frozen=True)
class WorkflowDefinitionRecord:
    workflow: Workflow
    version: WorkflowVersion
    steps: list[StepDefinition]


@dataclass(frozen=True)
class WorkflowRunRecord:
    run: WorkflowRun
    version: WorkflowVersion
    steps: list[WorkflowStepRun]
    events: list[WorkflowEvent]


@dataclass(frozen=True)
class WorkflowDashboard:
    business_id: uuid.UUID
    definitions: list[WorkflowDefinitionRecord]
    runs: list[WorkflowRunRecord]


def _now() -> datetime:
    return datetime.now(UTC)


def _workflow_job_id(run_id: uuid.UUID, recovery_count: int = 0) -> str:
    base = f"workflow-run-{run_id}"
    return base if recovery_count == 0 else f"{base}-recovery-{recovery_count}"


def _enqueue_sync(run_id: uuid.UUID, recovery_count: int = 0) -> None:
    settings = get_settings()
    connection = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        queue = Queue(settings.worker_queue, connection=connection)
        job_id = _workflow_job_id(run_id, recovery_count)
        existing = queue.fetch_job(job_id)
        if existing is not None:
            if existing.get_status(refresh=True) in {
                JobStatus.QUEUED,
                JobStatus.STARTED,
                JobStatus.DEFERRED,
                JobStatus.SCHEDULED,
            }:
                return
            existing.delete(remove_from_queue=True)
        queue.enqueue(
            "foundora.workflows.jobs.execute_workflow_run",
            str(run_id),
            job_id=job_id,
            job_timeout=300,
            result_ttl=0,
            failure_ttl=86_400,
        )
    finally:
        connection.close()


async def enqueue_workflow_run(run_id: uuid.UUID) -> None:
    await asyncio.to_thread(_enqueue_sync, run_id)


class WorkflowService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        enqueue: Callable[[uuid.UUID], Awaitable[None]] = enqueue_workflow_run,
    ) -> None:
        self._session_factory = session_factory or get_session_factory()
        self._enqueue = enqueue

    async def dashboard(self, context: AuthContext) -> WorkflowDashboard:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            definition_rows = (
                await database.execute(
                    select(Workflow, WorkflowVersion)
                    .join(
                        WorkflowVersion,
                        and_(
                            WorkflowVersion.workflow_id == Workflow.id,
                            WorkflowVersion.version == Workflow.current_version,
                        ),
                    )
                    .order_by(Workflow.id)
                )
            ).all()
            runs = list(
                await database.scalars(
                    select(WorkflowRun)
                    .where(WorkflowRun.business_id == business.id)
                    .order_by(desc(WorkflowRun.created_at))
                    .limit(50)
                )
            )
            records = await self._records(database, runs, include_events=False)
        return WorkflowDashboard(
            business_id=business.id,
            definitions=[
                WorkflowDefinitionRecord(
                    workflow=workflow,
                    version=version,
                    steps=parse_definition(version.definition),
                )
                for workflow, version in definition_rows
            ],
            runs=records,
        )

    async def start(
        self,
        context: AuthContext,
        workflow_id: str,
        structured_input: dict[str, object],
        task_id: uuid.UUID | None = None,
    ) -> WorkflowRunRecord:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                row = (
                    await database.execute(
                        select(Workflow, WorkflowVersion)
                        .join(
                            WorkflowVersion,
                            and_(
                                WorkflowVersion.workflow_id == Workflow.id,
                                WorkflowVersion.version == Workflow.current_version,
                            ),
                        )
                        .where(Workflow.id == workflow_id, Workflow.enabled.is_(True))
                    )
                ).one_or_none()
                if row is None:
                    raise WorkflowNotFound
                workflow, version = row
                definitions = parse_definition(version.definition)
                validate_schema(structured_input, version.input_schema)
                if task_id is not None:
                    task = await database.scalar(
                        select(Task).where(Task.id == task_id, Task.business_id == business.id)
                    )
                    if task is None:
                        raise WorkflowTaskNotFound
                now = _now()
                run = WorkflowRun(
                    id=uuid.uuid4(),
                    business_id=business.id,
                    workflow_id=workflow.id,
                    workflow_version_id=version.id,
                    task_id=task_id,
                    status="queued",
                    structured_input=dict(structured_input),
                    structured_output=None,
                    current_step_key=None,
                    error_type=None,
                    error_message=None,
                    worker_recovery_count=0,
                    created_by_owner_id=context.owner.id,
                    created_at=now,
                    queued_at=now,
                    started_at=None,
                    completed_at=None,
                    cancelled_at=None,
                )
                database.add(run)
                await database.flush()
                for sequence, definition in enumerate(definitions, start=1):
                    database.add(
                        WorkflowStepRun(
                            id=uuid.uuid4(),
                            workflow_run_id=run.id,
                            step_key=definition.key,
                            sequence=sequence,
                            step_type=definition.step_type,
                            status="pending",
                            attempt_count=0,
                            max_retries=definition.max_retries,
                            agent_run_id=None,
                            structured_input=None,
                            structured_output=None,
                            error_type=None,
                            error_message=None,
                            started_at=None,
                            completed_at=None,
                        )
                    )
                await add_event(
                    database,
                    run,
                    "run_created",
                    actor_owner_id=context.owner.id,
                    details={
                        "workflow_id": workflow.id,
                        "workflow_version": version.version,
                        "task_id": str(task_id) if task_id else None,
                    },
                )
        try:
            await self._enqueue(run.id)
        except Exception:
            logger.exception("Workflow run enqueue failed")
            await self._mark_queue_failure(run.id)
            raise WorkflowQueueUnavailable(run.id) from None
        return await self._record_for_business(run.id, business.id)

    async def inspect(self, context: AuthContext, run_id: uuid.UUID) -> WorkflowRunRecord:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
        return await self._record_for_business(run_id, business.id)

    async def resume(
        self,
        context: AuthContext,
        run_id: uuid.UUID,
        *,
        idempotency_key: str,
        decision: str | None,
        structured_input: dict[str, object],
    ) -> WorkflowRunRecord:
        should_enqueue = False
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                run = await database.scalar(
                    select(WorkflowRun)
                    .where(
                        WorkflowRun.id == run_id,
                        WorkflowRun.business_id == business.id,
                    )
                    .with_for_update()
                )
                if run is None:
                    raise WorkflowRunNotFound
                existing = await database.scalar(
                    select(WorkflowEvent).where(
                        WorkflowEvent.workflow_run_id == run.id,
                        WorkflowEvent.event_type == "owner_resumed",
                        WorkflowEvent.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    return await self._record(database, run)
                version = await database.get(WorkflowVersion, run.workflow_version_id)
                if version is None:
                    raise WorkflowResumeNotAllowed("Pinned workflow version is missing")
                definitions = {step.key: step for step in parse_definition(version.definition)}
                steps = list(
                    await database.scalars(
                        select(WorkflowStepRun)
                        .where(WorkflowStepRun.workflow_run_id == run.id)
                        .order_by(WorkflowStepRun.sequence)
                        .with_for_update()
                    )
                )
                step = next((item for item in steps if item.step_key == run.current_step_key), None)
                if step is None:
                    raise WorkflowResumeNotAllowed("Workflow is not at a resumable step")
                if run.status == "waiting_approval":
                    if decision not in {"approved", "rejected"}:
                        raise WorkflowResumeNotAllowed(
                            "Approval checkpoints require approved or rejected"
                        )
                    step.structured_output = {
                        "decision": decision,
                        "input": dict(structured_input),
                    }
                    step.completed_at = _now()
                    if decision == "rejected":
                        step.status = "failed"
                        step.error_type = "checkpoint_rejected"
                        step.error_message = "The owner rejected the workflow checkpoint"
                        await fail_workflow(
                            database,
                            run,
                            definitions,
                            steps,
                            step.error_type,
                            step.error_message,
                            step_key=step.step_key,
                        )
                    else:
                        step.status = "completed"
                        run.status = "queued"
                        run.queued_at = _now()
                        should_enqueue = True
                elif run.status == "waiting":
                    if decision is not None:
                        raise WorkflowResumeNotAllowed("Wait steps do not accept a decision")
                    step.status = "completed"
                    step.structured_output = {"resume_input": dict(structured_input)}
                    step.completed_at = _now()
                    run.status = "queued"
                    run.queued_at = _now()
                    should_enqueue = True
                elif run.status == "waiting_agent":
                    if decision is not None or step.agent_run_id is None:
                        raise WorkflowResumeNotAllowed("Agent steps do not accept a decision")
                    agent_run = await database.get(AgentRun, step.agent_run_id)
                    if agent_run is None or agent_run.status not in {
                        "completed",
                        "failed",
                        "cancelled",
                    }:
                        raise WorkflowResumeNotAllowed("The child agent is not terminal")
                    step.completed_at = _now()
                    if agent_run.status == "completed":
                        step.status = "completed"
                        step.structured_output = agent_run.structured_output or {}
                        run.status = "queued"
                        run.queued_at = _now()
                        should_enqueue = True
                    elif step.attempt_count <= step.max_retries:
                        step.status = "pending"
                        step.agent_run_id = None
                        step.error_type = None
                        step.error_message = None
                        run.status = "queued"
                        run.queued_at = _now()
                        should_enqueue = True
                        await add_event(
                            database,
                            run,
                            "step_retried",
                            step_key=step.step_key,
                            details={"attempt": step.attempt_count},
                        )
                    else:
                        step.status = "failed"
                        step.error_type = "workflow_agent_failed"
                        step.error_message = "The pinned child agent did not complete"
                        await fail_workflow(
                            database,
                            run,
                            definitions,
                            steps,
                            step.error_type,
                            step.error_message,
                            step_key=step.step_key,
                        )
                else:
                    raise WorkflowResumeNotAllowed("Workflow is not waiting")
                await add_event(
                    database,
                    run,
                    "owner_resumed",
                    step_key=step.step_key,
                    actor_owner_id=context.owner.id,
                    idempotency_key=idempotency_key,
                    details={"decision": decision},
                )
        if should_enqueue:
            try:
                await self._enqueue(run.id)
            except Exception:
                logger.exception("Resumed workflow could not be queued")
                await self._mark_queue_failure(run.id)
                raise WorkflowQueueUnavailable(run.id) from None
        return await self._record_for_business(run.id, business.id)

    async def cancel(self, context: AuthContext, run_id: uuid.UUID) -> WorkflowRunRecord:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                run = await database.scalar(
                    select(WorkflowRun)
                    .where(
                        WorkflowRun.id == run_id,
                        WorkflowRun.business_id == business.id,
                    )
                    .with_for_update()
                )
                if run is None:
                    raise WorkflowRunNotFound
                if run.status in TERMINAL_STATUSES:
                    raise WorkflowRunNotCancellable
                run.status = "cancelled"
                run.completed_at = _now()
                run.cancelled_at = run.completed_at
                steps = list(
                    await database.scalars(
                        select(WorkflowStepRun).where(
                            WorkflowStepRun.workflow_run_id == run.id,
                            WorkflowStepRun.status.in_(
                                {
                                    "pending",
                                    "running",
                                    "waiting",
                                    "waiting_approval",
                                    "waiting_agent",
                                }
                            ),
                        )
                    )
                )
                for step in steps:
                    step.status = "cancelled"
                    step.completed_at = run.completed_at
                await add_event(
                    database,
                    run,
                    "run_cancelled",
                    actor_owner_id=context.owner.id,
                )
        return await self._record_for_business(run.id, business.id)

    async def _mark_queue_failure(self, run_id: uuid.UUID) -> None:
        async with self._session_factory() as database:
            run = await database.scalar(
                select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
            )
            if run is None or run.status != "queued":
                return
            run.status = "failed"
            run.error_type = "workflow_queue_unavailable"
            run.error_message = "The background worker queue was unavailable"
            run.completed_at = _now()
            await add_event(
                database,
                run,
                "run_failed",
                details={"error_type": run.error_type},
            )
            await database.commit()

    async def _record_for_business(
        self, run_id: uuid.UUID, business_id: uuid.UUID
    ) -> WorkflowRunRecord:
        async with self._session_factory() as database:
            run = await database.scalar(
                select(WorkflowRun).where(
                    WorkflowRun.id == run_id, WorkflowRun.business_id == business_id
                )
            )
            if run is None:
                raise WorkflowRunNotFound
            return await self._record(database, run)

    async def _records(
        self,
        database: AsyncSession,
        runs: list[WorkflowRun],
        *,
        include_events: bool = True,
    ) -> list[WorkflowRunRecord]:
        if not runs:
            return []
        run_ids = [run.id for run in runs]
        version_ids = {run.workflow_version_id for run in runs}
        versions = list(
            await database.scalars(
                select(WorkflowVersion).where(WorkflowVersion.id.in_(version_ids))
            )
        )
        versions_by_id = {version.id: version for version in versions}
        steps = list(
            await database.scalars(
                select(WorkflowStepRun)
                .where(WorkflowStepRun.workflow_run_id.in_(run_ids))
                .order_by(WorkflowStepRun.workflow_run_id, WorkflowStepRun.sequence)
            )
        )
        steps_by_run: dict[uuid.UUID, list[WorkflowStepRun]] = {run_id: [] for run_id in run_ids}
        for step in steps:
            steps_by_run[step.workflow_run_id].append(step)
        events_by_run: dict[uuid.UUID, list[WorkflowEvent]] = {run_id: [] for run_id in run_ids}
        if include_events:
            events = list(
                await database.scalars(
                    select(WorkflowEvent)
                    .where(WorkflowEvent.workflow_run_id.in_(run_ids))
                    .order_by(WorkflowEvent.workflow_run_id, WorkflowEvent.sequence)
                )
            )
            for event in events:
                events_by_run[event.workflow_run_id].append(event)
        return [
            WorkflowRunRecord(
                run=run,
                version=versions_by_id[run.workflow_version_id],
                steps=steps_by_run[run.id],
                events=events_by_run[run.id],
            )
            for run in runs
        ]

    async def _record(self, database: AsyncSession, run: WorkflowRun) -> WorkflowRunRecord:
        return (await self._records(database, [run]))[0]
