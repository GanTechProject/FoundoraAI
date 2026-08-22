from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.tasks.service import (
    AgentOwnerNotFound,
    DependencyViolation,
    GoalNotFound,
    InvalidTaskTransition,
    RetryNotAllowed,
    TaskDashboard,
    TaskNotFound,
    TaskRecord,
    TaskService,
)

router = APIRouter(prefix="/tasks", tags=["task engine"])
TaskStatus = Literal[
    "draft",
    "planned",
    "queued",
    "running",
    "blocked",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
]
OwnerType = Literal["unassigned", "founder", "agent"]


def _clean(value: str) -> str:
    return " ".join(value.strip().split())


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    goal_id: UUID | None = None
    priority: int = Field(default=3, ge=1, le=5)
    owner_type: OwnerType = "unassigned"
    owner_agent_id: str | None = Field(default=None, max_length=80)
    due_at: datetime | None = None
    max_retries: int = Field(default=0, ge=0, le=10)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("task title cannot be blank")
        return cleaned

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("due_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value

    @model_validator(mode="after")
    def owner_shape(self) -> CreateTaskRequest:
        if self.owner_type == "agent" and not self.owner_agent_id:
            raise ValueError("owner_agent_id is required for agent-owned tasks")
        if self.owner_type != "agent" and self.owner_agent_id:
            raise ValueError("owner_agent_id is valid only for agent-owned tasks")
        return self


class TaskStatusRequest(BaseModel):
    status: TaskStatus
    error: str | None = Field(default=None, max_length=500)


class TaskDependencyRequest(BaseModel):
    depends_on_task_id: UUID


class TaskRetryRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class GoalSummaryView(BaseModel):
    id: UUID
    title: str
    status: Literal["active", "completed", "cancelled"]
    target_date: date | None


class AgentOwnerView(BaseModel):
    agent_id: str
    display_name: str
    version: int


class DependencyView(BaseModel):
    task_id: UUID
    title: str
    status: TaskStatus
    satisfied: bool


class TaskEventView(BaseModel):
    id: UUID
    event_type: Literal["created", "dependency_added", "status_changed", "retried"]
    from_status: TaskStatus | None
    to_status: TaskStatus | None
    idempotency_key: str | None
    details: dict[str, object]
    created_at: datetime


class TaskView(BaseModel):
    id: UUID
    business_id: UUID
    goal_id: UUID | None
    title: str
    description: str | None
    priority: int
    owner_type: OwnerType
    owner_agent_id: str | None
    owner_agent_version_id: UUID | None
    owner_agent_version: int | None
    status: TaskStatus
    due_at: datetime | None
    max_retries: int
    retry_count: int
    last_error: str | None
    dependencies: list[DependencyView]
    blocked_by: list[UUID]
    events: list[TaskEventView]
    created_at: datetime
    updated_at: datetime


class TaskDashboardView(BaseModel):
    business_id: UUID
    goals: list[GoalSummaryView]
    agent_owners: list[AgentOwnerView]
    tasks: list[TaskView]
    total_tasks: int
    limit: int
    offset: int


def _task_view(record: TaskRecord) -> TaskView:
    item = record.task
    dependencies = [
        DependencyView(
            task_id=dependency.id,
            title=dependency.title,
            status=dependency.status,  # type: ignore[arg-type]
            satisfied=dependency.status == "completed",
        )
        for dependency in record.dependencies
    ]
    return TaskView(
        id=item.id,
        business_id=item.business_id,
        goal_id=item.goal_id,
        title=item.title,
        description=item.description,
        priority=item.priority,
        owner_type=item.owner_type,  # type: ignore[arg-type]
        owner_agent_id=item.owner_agent_id,
        owner_agent_version_id=item.owner_agent_version_id,
        owner_agent_version=(record.owner_version.version if record.owner_version else None),
        status=item.status,  # type: ignore[arg-type]
        due_at=item.due_at,
        max_retries=item.max_retries,
        retry_count=item.retry_count,
        last_error=item.last_error,
        dependencies=dependencies,
        blocked_by=[dependency.task_id for dependency in dependencies if not dependency.satisfied],
        events=[
            TaskEventView(
                id=event.id,
                event_type=event.event_type,  # type: ignore[arg-type]
                from_status=event.from_status,  # type: ignore[arg-type]
                to_status=event.to_status,  # type: ignore[arg-type]
                idempotency_key=event.idempotency_key,
                details=event.details,
                created_at=event.created_at,
            )
            for event in record.events
        ],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _dashboard_view(record: TaskDashboard) -> TaskDashboardView:
    return TaskDashboardView(
        business_id=record.business_id,
        goals=[
            GoalSummaryView(
                id=goal.id,
                title=goal.title,
                status=goal.status,  # type: ignore[arg-type]
                target_date=goal.target_date,
            )
            for goal in record.goals
        ],
        agent_owners=[
            AgentOwnerView(
                agent_id=owner.agent.id,
                display_name=owner.agent.display_name,
                version=owner.version.version,
            )
            for owner in record.agent_owners
        ],
        tasks=[_task_view(task) for task in record.tasks],
        total_tasks=record.total_tasks,
        limit=record.limit,
        offset=record.offset,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


def _dependency(error: DependencyViolation) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"message": str(error), "blockers": [str(item) for item in error.blockers]},
    )


@router.get("", response_model=TaskDashboardView)
async def task_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> TaskDashboardView:
    response.headers["Cache-Control"] = "no-store"
    return _dashboard_view(await TaskService().dashboard(context, limit=limit, offset=offset))


@router.get("/{task_id}", response_model=TaskView)
async def inspect_task(
    task_id: UUID, context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> TaskView:
    try:
        record = await TaskService().inspect(context, task_id)
    except TaskNotFound as error:
        raise _not_found() from error
    response.headers["Cache-Control"] = "no-store"
    return _task_view(record)


@router.post("", response_model=TaskView, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: CreateTaskRequest, context: Annotated[AuthContext, Depends(require_csrf)]
) -> TaskView:
    try:
        record = await TaskService().create(context, **payload.model_dump())
    except GoalNotFound as error:
        raise HTTPException(status_code=404, detail="Goal not found") from error
    except AgentOwnerNotFound as error:
        raise HTTPException(status_code=404, detail="Agent owner not found") from error
    return _task_view(record)


@router.post("/{task_id}/dependencies", response_model=TaskView)
async def add_dependency(
    task_id: UUID,
    payload: TaskDependencyRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> TaskView:
    try:
        record = await TaskService().add_dependency(context, task_id, payload.depends_on_task_id)
    except TaskNotFound as error:
        raise _not_found() from error
    except DependencyViolation as error:
        raise _dependency(error) from error
    return _task_view(record)


@router.post("/{task_id}/status", response_model=TaskView)
async def transition_task(
    task_id: UUID,
    payload: TaskStatusRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> TaskView:
    try:
        record = await TaskService().transition(context, task_id, payload.status, payload.error)
    except TaskNotFound as error:
        raise _not_found() from error
    except InvalidTaskTransition as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DependencyViolation as error:
        raise _dependency(error) from error
    return _task_view(record)


@router.post("/{task_id}/retry", response_model=TaskView)
async def retry_task(
    task_id: UUID,
    payload: TaskRetryRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> TaskView:
    try:
        record = await TaskService().retry(context, task_id, payload.idempotency_key)
    except TaskNotFound as error:
        raise _not_found() from error
    except RetryNotAllowed as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DependencyViolation as error:
        raise _dependency(error) from error
    return _task_view(record)
