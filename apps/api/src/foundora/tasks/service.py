from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    Agent,
    AgentVersion,
    BusinessGoal,
    Task,
    TaskDependency,
    TaskEvent,
)

TASK_STATUSES = frozenset(
    {
        "draft",
        "planned",
        "queued",
        "running",
        "blocked",
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
    }
)
TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"planned", "cancelled"}),
    "planned": frozenset({"queued", "blocked", "cancelled"}),
    "queued": frozenset({"running", "blocked", "cancelled"}),
    "running": frozenset({"blocked", "waiting_approval", "completed", "failed", "cancelled"}),
    "blocked": frozenset({"planned", "queued", "cancelled"}),
    "waiting_approval": frozenset({"queued", "running", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset({"cancelled"}),
    "cancelled": frozenset(),
}
DEPENDENCY_GATED_STATES = frozenset({"queued", "running"})
DEPENDENCY_MUTABLE_STATES = frozenset({"draft", "planned", "blocked"})


class TaskNotFound(Exception):
    pass


class GoalNotFound(Exception):
    pass


class AgentOwnerNotFound(Exception):
    pass


class InvalidTaskTransition(Exception):
    pass


class DependencyViolation(Exception):
    def __init__(self, message: str, blockers: list[uuid.UUID] | None = None) -> None:
        self.blockers = blockers or []
        super().__init__(message)


class RetryNotAllowed(Exception):
    pass


@dataclass(frozen=True)
class AgentOwner:
    agent: Agent
    version: AgentVersion


@dataclass(frozen=True)
class TaskRecord:
    task: Task
    dependencies: list[Task]
    events: list[TaskEvent]
    owner_version: AgentVersion | None = None


@dataclass(frozen=True)
class TaskDashboard:
    business_id: uuid.UUID
    goals: list[BusinessGoal]
    agent_owners: list[AgentOwner]
    tasks: list[TaskRecord]
    total_tasks: int
    limit: int
    offset: int


def _now() -> datetime:
    return datetime.now(UTC)


def ensure_transition(current: str, requested: str) -> None:
    if requested not in TASK_STATUSES or requested not in TRANSITIONS.get(current, frozenset()):
        raise InvalidTaskTransition(f"Task cannot transition from {current} to {requested}")


class TaskService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def dashboard(
        self, context: AuthContext, *, limit: int = 100, offset: int = 0
    ) -> TaskDashboard:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            goals = list(
                await database.scalars(
                    select(BusinessGoal)
                    .where(BusinessGoal.business_id == business.id)
                    .order_by(BusinessGoal.created_at.desc())
                )
            )
            owner_rows = (
                await database.execute(
                    select(Agent, AgentVersion)
                    .join(
                        AgentVersion,
                        and_(
                            AgentVersion.agent_id == Agent.id,
                            AgentVersion.version == Agent.current_version,
                        ),
                    )
                    .where(Agent.enabled.is_(True))
                    .order_by(Agent.display_name)
                )
            ).all()
            tasks = list(
                await database.scalars(
                    select(Task)
                    .where(Task.business_id == business.id)
                    .order_by(Task.priority, Task.due_at.asc().nulls_last(), Task.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            total_tasks = int(
                await database.scalar(
                    select(func.count(Task.id)).where(Task.business_id == business.id)
                )
                or 0
            )
            records = await self._records(database, tasks, include_events=False)
        return TaskDashboard(
            business_id=business.id,
            goals=goals,
            agent_owners=[
                AgentOwner(agent=agent, version=version) for agent, version in owner_rows
            ],
            tasks=records,
            total_tasks=total_tasks,
            limit=limit,
            offset=offset,
        )

    async def inspect(self, context: AuthContext, task_id: uuid.UUID) -> TaskRecord:
        async with self._session_factory() as database:
            business = await resolve_selected_business(database, context)
            task = await database.scalar(
                select(Task).where(Task.id == task_id, Task.business_id == business.id)
            )
            if task is None:
                raise TaskNotFound
            return (await self._records(database, [task]))[0]

    async def create(
        self,
        context: AuthContext,
        *,
        title: str,
        description: str | None,
        goal_id: uuid.UUID | None,
        priority: int,
        owner_type: str,
        owner_agent_id: str | None,
        due_at: datetime | None,
        max_retries: int,
    ) -> TaskRecord:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context)
                if goal_id is not None:
                    goal = await database.scalar(
                        select(BusinessGoal).where(
                            BusinessGoal.id == goal_id,
                            BusinessGoal.business_id == business.id,
                        )
                    )
                    if goal is None:
                        raise GoalNotFound
                owner_version_id: uuid.UUID | None = None
                if owner_type == "agent":
                    owner = await self._agent_owner(database, owner_agent_id)
                    owner_agent_id = owner.agent.id
                    owner_version_id = owner.version.id
                else:
                    owner_agent_id = None
                now = _now()
                task = Task(
                    id=uuid.uuid4(),
                    business_id=business.id,
                    goal_id=goal_id,
                    title=title,
                    description=description,
                    priority=priority,
                    owner_type=owner_type,
                    owner_agent_id=owner_agent_id,
                    owner_agent_version_id=owner_version_id,
                    status="draft",
                    due_at=due_at,
                    max_retries=max_retries,
                    retry_count=0,
                    last_error=None,
                    created_by_owner_id=context.owner.id,
                    created_at=now,
                    updated_at=now,
                )
                database.add(task)
                await database.flush()
                database.add(
                    self._event(
                        task,
                        context,
                        event_type="created",
                        from_status=None,
                        to_status="draft",
                        details={"priority": priority, "owner_type": owner_type},
                    )
                )
            return (await self._records(database, [task]))[0]

    async def add_dependency(
        self, context: AuthContext, task_id: uuid.UUID, depends_on_task_id: uuid.UUID
    ) -> TaskRecord:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                task = await self._task(database, business.id, task_id, lock=True)
                dependency = await self._task(database, business.id, depends_on_task_id, lock=True)
                if task.id == dependency.id:
                    raise DependencyViolation("A task cannot depend on itself")
                if task.status not in DEPENDENCY_MUTABLE_STATES:
                    raise DependencyViolation("Dependencies cannot change after a task is queued")
                existing = await database.get(TaskDependency, (task.id, dependency.id))
                if existing is None:
                    if await self._would_create_cycle(database, task.id, dependency.id):
                        raise DependencyViolation("Dependency would create a cycle")
                    now = _now()
                    database.add(
                        TaskDependency(
                            task_id=task.id,
                            depends_on_task_id=dependency.id,
                            created_at=now,
                        )
                    )
                    database.add(
                        self._event(
                            task,
                            context,
                            event_type="dependency_added",
                            from_status=task.status,
                            to_status=task.status,
                            details={"depends_on_task_id": str(dependency.id)},
                        )
                    )
                    task.updated_at = now
            return (await self._records(database, [task]))[0]

    async def transition(
        self,
        context: AuthContext,
        task_id: uuid.UUID,
        requested_status: str,
        error: str | None = None,
    ) -> TaskRecord:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                task = await self._task(database, business.id, task_id, lock=True)
                ensure_transition(task.status, requested_status)
                if requested_status in DEPENDENCY_GATED_STATES:
                    await self._ensure_dependencies_complete(database, task.id)
                previous = task.status
                now = _now()
                task.status = requested_status
                task.last_error = error if requested_status == "failed" else None
                task.updated_at = now
                database.add(
                    self._event(
                        task,
                        context,
                        event_type="status_changed",
                        from_status=previous,
                        to_status=requested_status,
                        details={"error": error} if error else {},
                    )
                )
            return (await self._records(database, [task]))[0]

    async def retry(
        self, context: AuthContext, task_id: uuid.UUID, idempotency_key: str
    ) -> TaskRecord:
        async with self._session_factory() as database:
            async with database.begin():
                business = await resolve_selected_business(database, context, lock=True)
                task = await self._task(database, business.id, task_id, lock=True)
                prior = await database.scalar(
                    select(TaskEvent).where(
                        TaskEvent.task_id == task.id,
                        TaskEvent.event_type == "retried",
                        TaskEvent.idempotency_key == idempotency_key,
                    )
                )
                if prior is not None:
                    return await self._record(database, task)
                if task.status != "failed":
                    raise RetryNotAllowed("Only failed tasks can be retried")
                if task.retry_count >= task.max_retries:
                    raise RetryNotAllowed("Task retry limit has been reached")
                await self._ensure_dependencies_complete(database, task.id)
                now = _now()
                prior_error = task.last_error
                task.retry_count += 1
                task.status = "queued"
                task.last_error = None
                task.updated_at = now
                database.add(
                    self._event(
                        task,
                        context,
                        event_type="retried",
                        from_status="failed",
                        to_status="queued",
                        details={
                            "retry_count": task.retry_count,
                            "previous_error": prior_error,
                        },
                        idempotency_key=idempotency_key,
                    )
                )
            return (await self._records(database, [task]))[0]

    async def _agent_owner(self, database: AsyncSession, agent_id: str | None) -> AgentOwner:
        if agent_id is None:
            raise AgentOwnerNotFound
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
            raise AgentOwnerNotFound
        return AgentOwner(agent=row[0], version=row[1])

    async def _task(
        self,
        database: AsyncSession,
        business_id: uuid.UUID,
        task_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> Task:
        statement = select(Task).where(Task.id == task_id, Task.business_id == business_id)
        if lock:
            statement = statement.with_for_update()
        task = await database.scalar(statement)
        if task is None:
            raise TaskNotFound
        return task

    async def _ensure_dependencies_complete(
        self, database: AsyncSession, task_id: uuid.UUID
    ) -> None:
        blockers = list(
            await database.scalars(
                select(Task)
                .join(TaskDependency, Task.id == TaskDependency.depends_on_task_id)
                .where(TaskDependency.task_id == task_id, Task.status != "completed")
            )
        )
        if blockers:
            raise DependencyViolation(
                "All dependencies must be completed before the task can be queued or run",
                [blocker.id for blocker in blockers],
            )

    async def _would_create_cycle(
        self, database: AsyncSession, task_id: uuid.UUID, dependency_id: uuid.UUID
    ) -> bool:
        pairs = (
            await database.execute(
                select(TaskDependency.task_id, TaskDependency.depends_on_task_id)
            )
        ).all()
        outgoing: dict[uuid.UUID, list[uuid.UUID]] = {}
        for source, target in pairs:
            outgoing.setdefault(source, []).append(target)
        pending = [dependency_id]
        seen: set[uuid.UUID] = set()
        while pending:
            current = pending.pop()
            if current == task_id:
                return True
            if current not in seen:
                seen.add(current)
                pending.extend(outgoing.get(current, []))
        return False

    async def _records(
        self,
        database: AsyncSession,
        tasks: list[Task],
        *,
        include_events: bool = True,
    ) -> list[TaskRecord]:
        if not tasks:
            return []
        task_ids = [task.id for task in tasks]
        owner_version_ids = {
            task.owner_agent_version_id for task in tasks if task.owner_agent_version_id is not None
        }
        owner_versions = (
            list(
                await database.scalars(
                    select(AgentVersion).where(AgentVersion.id.in_(owner_version_ids))
                )
            )
            if owner_version_ids
            else []
        )
        owners_by_id = {version.id: version for version in owner_versions}
        dependency_rows = (
            await database.execute(
                select(TaskDependency.task_id, Task)
                .join(Task, Task.id == TaskDependency.depends_on_task_id)
                .where(TaskDependency.task_id.in_(task_ids))
                .order_by(TaskDependency.task_id, Task.priority, Task.created_at)
            )
        ).all()
        dependencies_by_task: dict[uuid.UUID, list[Task]] = {task_id: [] for task_id in task_ids}
        for task_id, dependency in dependency_rows:
            dependencies_by_task[task_id].append(dependency)
        events_by_task: dict[uuid.UUID, list[TaskEvent]] = {task_id: [] for task_id in task_ids}
        if include_events:
            events = list(
                await database.scalars(
                    select(TaskEvent)
                    .where(TaskEvent.task_id.in_(task_ids))
                    .order_by(TaskEvent.task_id, TaskEvent.created_at, TaskEvent.id)
                )
            )
            for event in events:
                events_by_task[event.task_id].append(event)
        return [
            TaskRecord(
                task=task,
                dependencies=dependencies_by_task[task.id],
                events=events_by_task[task.id],
                owner_version=(
                    owners_by_id.get(task.owner_agent_version_id)
                    if task.owner_agent_version_id is not None
                    else None
                ),
            )
            for task in tasks
        ]

    async def _record(self, database: AsyncSession, task: Task) -> TaskRecord:
        return (await self._records(database, [task]))[0]

    @staticmethod
    def _event(
        task: Task,
        context: AuthContext,
        *,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        details: dict[str, object],
        idempotency_key: str | None = None,
    ) -> TaskEvent:
        return TaskEvent(
            id=uuid.uuid4(),
            task_id=task.id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_owner_id=context.owner.id,
            idempotency_key=idempotency_key,
            details=details,
            created_at=_now(),
        )
