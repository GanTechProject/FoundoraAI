from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.agents.schema import AgentSchemaError, validate_schema
from foundora.agents.service import enqueue_agent_run
from foundora.governance.service import GovernanceService
from foundora.infrastructure.database import get_session_factory
from foundora.models import (
    Agent,
    AgentMessage,
    AgentRun,
    AgentVersion,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStepRun,
    WorkflowVersion,
)
from foundora.workflows.definition import (
    StepDefinition,
    WorkflowDefinitionError,
    condition_matches,
    execute_internal_tool,
    parse_definition,
)

logger = logging.getLogger(__name__)
SATISFIED_STEP_STATUSES = frozenset({"completed", "skipped", "compensated"})


def _now() -> datetime:
    return datetime.now(UTC)


async def add_event(
    database: AsyncSession,
    run: WorkflowRun,
    event_type: str,
    *,
    step_key: str | None = None,
    actor_owner_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    sequence = (
        int(
            await database.scalar(
                select(func.coalesce(func.max(WorkflowEvent.sequence), 0)).where(
                    WorkflowEvent.workflow_run_id == run.id
                )
            )
            or 0
        )
        + 1
    )
    database.add(
        WorkflowEvent(
            id=uuid.uuid4(),
            workflow_run_id=run.id,
            sequence=sequence,
            event_type=event_type,
            step_key=step_key,
            actor_owner_id=actor_owner_id,
            idempotency_key=idempotency_key,
            details=details or {},
            created_at=_now(),
        )
    )
    await database.flush()


async def compensate_completed_steps(
    database: AsyncSession,
    run: WorkflowRun,
    definitions: dict[str, StepDefinition],
    step_runs: list[WorkflowStepRun],
) -> None:
    for step in reversed(step_runs):
        definition = definitions[step.step_key]
        compensation = definition.config.get("compensation")
        if step.status != "completed" or compensation is None:
            continue
        try:
            authorization = await GovernanceService().evaluate_in_session(
                database,
                business_id=run.business_id,
                action_type="internal.analysis",
                actor_type="workflow",
                actor_id=str(run.workflow_version_id),
                tool_id=str(compensation),
                execution_mode="manual",
                data_classification="internal",
                requested_spend_microusd=0,
                frequency_key=None,
                target=step.step_key,
                idempotency_key=f"workflow:{run.id}:compensate:{step.step_key}",
                created_by_owner_id=run.created_by_owner_id,
                workflow_run_id=run.id,
                workflow_step_key=step.step_key,
            )
            if authorization.action.status != "authorized":
                raise RuntimeError(authorization.action.rationale)
            output = execute_internal_tool(compensation, step.structured_output or {})
        except Exception as error:
            await add_event(
                database,
                run,
                "compensation_failed",
                step_key=step.step_key,
                details={"error_type": type(error).__name__},
            )
            continue
        step.status = "compensated"
        step.structured_output = {
            "original": step.structured_output or {},
            "compensation": output,
        }
        step.completed_at = _now()
        await add_event(database, run, "step_compensated", step_key=step.step_key)


async def fail_workflow(
    database: AsyncSession,
    run: WorkflowRun,
    definitions: dict[str, StepDefinition],
    step_runs: list[WorkflowStepRun],
    error_type: str,
    message: str,
    *,
    step_key: str | None = None,
) -> None:
    run.status = "failed"
    run.error_type = error_type[:80]
    run.error_message = message[:500]
    run.current_step_key = step_key
    run.completed_at = _now()
    await compensate_completed_steps(database, run, definitions, step_runs)
    await add_event(
        database,
        run,
        "run_failed",
        step_key=step_key,
        details={"error_type": run.error_type, "message": run.error_message},
    )


class WorkflowRuntime:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def execute(self, run_id: uuid.UUID) -> None:
        async with self._session_factory() as database:
            run = await database.scalar(
                select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
            )
            if run is None or run.status != "queued":
                return
            version = await database.get(WorkflowVersion, run.workflow_version_id)
            if version is None:
                run.status = "failed"
                run.error_type = "workflow_version_missing"
                run.error_message = "The pinned workflow version is unavailable"
                run.completed_at = _now()
                await database.commit()
                return
            try:
                definitions = {step.key: step for step in parse_definition(version.definition)}
            except WorkflowDefinitionError as error:
                run.status = "failed"
                run.error_type = "workflow_definition_invalid"
                run.error_message = str(error)[:500]
                run.completed_at = _now()
                await database.commit()
                return
            step_runs = list(
                await database.scalars(
                    select(WorkflowStepRun)
                    .where(WorkflowStepRun.workflow_run_id == run.id)
                    .order_by(WorkflowStepRun.sequence)
                )
            )
            run.status = "running"
            run.started_at = _now()
            run.current_step_key = None
            await add_event(database, run, "run_started")
            await database.commit()

            while True:
                run = cast(
                    WorkflowRun,
                    await database.scalar(
                        select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
                    ),
                )
                if run.status != "running":
                    await database.rollback()
                    return
                step_runs = list(
                    await database.scalars(
                        select(WorkflowStepRun)
                        .where(WorkflowStepRun.workflow_run_id == run.id)
                        .order_by(WorkflowStepRun.sequence)
                        .with_for_update()
                    )
                )
                by_key = {step.step_key: step for step in step_runs}
                pending = [step for step in step_runs if step.status == "pending"]
                ready = [
                    step
                    for step in pending
                    if all(
                        by_key[key].status in SATISFIED_STEP_STATUSES
                        for key in definitions[step.step_key].depends_on
                    )
                ]
                if not pending:
                    if all(step.status in SATISFIED_STEP_STATUSES for step in step_runs):
                        output: dict[str, object] = {
                            "input": dict(run.structured_input),
                            "steps": {step.step_key: step.structured_output for step in step_runs},
                        }
                        try:
                            validate_schema(output, version.output_schema)
                        except AgentSchemaError as error:
                            await fail_workflow(
                                database,
                                run,
                                definitions,
                                step_runs,
                                "workflow_output_invalid",
                                str(error),
                            )
                        else:
                            run.status = "completed"
                            run.structured_output = output
                            run.current_step_key = None
                            run.completed_at = _now()
                            await add_event(database, run, "run_completed")
                        await database.commit()
                    else:
                        await fail_workflow(
                            database,
                            run,
                            definitions,
                            step_runs,
                            "workflow_deadlock",
                            "No workflow step can make deterministic progress",
                        )
                        await database.commit()
                    return
                if not ready:
                    await fail_workflow(
                        database,
                        run,
                        definitions,
                        step_runs,
                        "workflow_deadlock",
                        "Pending workflow dependencies cannot be satisfied",
                    )
                    await database.commit()
                    return
                step = ready[0]
                definition = definitions[step.step_key]
                outputs = {item.step_key: item.structured_output for item in step_runs}
                try:
                    matches = condition_matches(
                        definition.config.get("condition"), run.structured_input, outputs
                    )
                except WorkflowDefinitionError as error:
                    await fail_workflow(
                        database,
                        run,
                        definitions,
                        step_runs,
                        "workflow_condition_invalid",
                        str(error),
                        step_key=step.step_key,
                    )
                    await database.commit()
                    return
                if not matches:
                    step.status = "skipped"
                    step.structured_output = {"reason": "condition_false"}
                    step.completed_at = _now()
                    await add_event(database, run, "step_skipped", step_key=step.step_key)
                    await database.commit()
                    continue
                run.current_step_key = step.step_key
                if definition.step_type == "approval":
                    authorization = await GovernanceService().evaluate_in_session(
                        database,
                        business_id=run.business_id,
                        action_type="workflow.checkpoint",
                        actor_type="workflow",
                        actor_id=str(run.workflow_version_id),
                        tool_id=None,
                        execution_mode="manual",
                        data_classification="internal",
                        requested_spend_microusd=0,
                        frequency_key=None,
                        target=step.step_key,
                        idempotency_key=f"workflow:{run.id}:approval:{step.step_key}",
                        created_by_owner_id=run.created_by_owner_id,
                        workflow_run_id=run.id,
                        workflow_step_key=step.step_key,
                        force_approval=True,
                        approval_prompt=str(definition.config.get("prompt", ""))[:500],
                    )
                    step.governance_action_id = authorization.action.id
                    if authorization.action.status != "approval_required":
                        step.status = "failed"
                        step.error_type = "governance_denied"
                        step.error_message = authorization.action.rationale
                        step.completed_at = _now()
                        await fail_workflow(
                            database,
                            run,
                            definitions,
                            step_runs,
                            step.error_type,
                            step.error_message,
                            step_key=step.step_key,
                        )
                        await database.commit()
                        return
                    step.status = "waiting_approval"
                    step.started_at = _now()
                    run.status = "waiting_approval"
                    await add_event(
                        database,
                        run,
                        "approval_checkpoint_waiting",
                        step_key=step.step_key,
                        details={"prompt": str(definition.config.get("prompt", ""))[:500]},
                    )
                    await database.commit()
                    return
                if definition.step_type == "wait":
                    step.status = "waiting"
                    step.started_at = _now()
                    run.status = "waiting"
                    await add_event(database, run, "wait_started", step_key=step.step_key)
                    await database.commit()
                    return
                if definition.step_type == "agent":
                    await self._start_agent_step(
                        database,
                        run,
                        step,
                        definition,
                        definitions,
                        step_runs,
                    )
                    return
                await self._execute_tool_step(
                    database, run, step, definition, definitions, step_runs
                )
                if run.status == "failed":
                    await database.commit()
                    return

    async def _execute_tool_step(
        self,
        database: AsyncSession,
        run: WorkflowRun,
        step: WorkflowStepRun,
        definition: StepDefinition,
        definitions: dict[str, StepDefinition],
        step_runs: list[WorkflowStepRun],
    ) -> None:
        authorization = await GovernanceService().evaluate_in_session(
            database,
            business_id=run.business_id,
            action_type="internal.analysis",
            actor_type="workflow",
            actor_id=str(run.workflow_version_id),
            tool_id=str(definition.config.get("tool")),
            execution_mode="manual",
            data_classification="internal",
            requested_spend_microusd=0,
            frequency_key=None,
            target=step.step_key,
            idempotency_key=(
                f"workflow:{run.id}:tool:{step.step_key}:attempt:{step.attempt_count + 1}"
            ),
            created_by_owner_id=run.created_by_owner_id,
            workflow_run_id=run.id,
            workflow_step_key=step.step_key,
        )
        step.governance_action_id = authorization.action.id
        if authorization.action.status != "authorized":
            step.status = "failed"
            step.error_type = "governance_denied"
            step.error_message = authorization.action.rationale
            step.completed_at = _now()
            await fail_workflow(
                database,
                run,
                definitions,
                step_runs,
                step.error_type,
                step.error_message,
                step_key=step.step_key,
            )
            await database.commit()
            return
        step.status = "running"
        step.attempt_count += 1
        step.started_at = step.started_at or _now()
        step.structured_input = cast(dict[str, object], definition.config.get("input", {}))
        await add_event(
            database,
            run,
            "step_started",
            step_key=step.step_key,
            details={"attempt": step.attempt_count},
        )
        try:
            output = execute_internal_tool(
                definition.config.get("tool"), definition.config.get("input", {})
            )
        except Exception as error:
            step.error_type = "workflow_tool_failed"
            step.error_message = str(error)[:500]
            if step.attempt_count <= step.max_retries:
                step.status = "pending"
                await add_event(
                    database,
                    run,
                    "step_retried",
                    step_key=step.step_key,
                    details={"attempt": step.attempt_count},
                )
            else:
                step.status = "failed"
                step.completed_at = _now()
                await fail_workflow(
                    database,
                    run,
                    definitions,
                    step_runs,
                    step.error_type,
                    step.error_message,
                    step_key=step.step_key,
                )
        else:
            step.status = "completed"
            step.structured_output = output
            step.error_type = None
            step.error_message = None
            step.completed_at = _now()
            await add_event(
                database,
                run,
                "step_completed",
                step_key=step.step_key,
                details={"attempt": step.attempt_count},
            )
        await database.commit()

    async def _start_agent_step(
        self,
        database: AsyncSession,
        run: WorkflowRun,
        step: WorkflowStepRun,
        definition: StepDefinition,
        definitions: dict[str, StepDefinition],
        step_runs: list[WorkflowStepRun],
    ) -> None:
        agent_version_id = uuid.UUID(str(definition.config.get("agent_version_id")))
        row = (
            await database.execute(
                select(Agent, AgentVersion)
                .join(
                    AgentVersion,
                    AgentVersion.agent_id == Agent.id,
                )
                .where(
                    Agent.id == definition.config.get("agent_id"),
                    AgentVersion.id == agent_version_id,
                    Agent.enabled.is_(True),
                )
            )
        ).one_or_none()
        payload = definition.config.get("input", run.structured_input)
        if row is None or not isinstance(payload, dict):
            step.status = "failed"
            step.error_type = "workflow_agent_invalid"
            step.error_message = "Workflow agent step is not executable"
            step.completed_at = _now()
            await fail_workflow(
                database,
                run,
                definitions,
                step_runs,
                step.error_type,
                step.error_message,
                step_key=step.step_key,
            )
            await database.commit()
            return
        agent, version = row
        try:
            validate_schema(payload, version.input_schema)
        except AgentSchemaError as error:
            step.status = "failed"
            step.error_type = "workflow_agent_input_invalid"
            step.error_message = str(error)[:500]
            step.completed_at = _now()
            await fail_workflow(
                database,
                run,
                definitions,
                step_runs,
                step.error_type,
                step.error_message,
                step_key=step.step_key,
            )
            await database.commit()
            return
        now = _now()
        agent_run = AgentRun(
            id=uuid.uuid4(),
            business_id=run.business_id,
            agent_id=agent.id,
            agent_version_id=version.id,
            skill_version_id=None,
            status="queued",
            structured_input=dict(payload),
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
        database.add(agent_run)
        await database.flush()
        database.add(
            AgentMessage(
                id=uuid.uuid4(),
                run_id=agent_run.id,
                sequence=1,
                role="user",
                message_type="input",
                content={"workflow_run_id": str(run.id), "step_key": step.step_key},
                created_at=now,
            )
        )
        step.status = "waiting_agent"
        step.attempt_count += 1
        step.agent_run_id = agent_run.id
        step.structured_input = dict(payload)
        step.started_at = now
        run.status = "waiting_agent"
        await add_event(
            database,
            run,
            "agent_step_queued",
            step_key=step.step_key,
            details={"agent_run_id": str(agent_run.id)},
        )
        await database.commit()
        try:
            await enqueue_agent_run(agent_run.id)
        except Exception:
            logger.exception("Workflow child agent could not be queued")
            async with self._session_factory() as failure_database:
                failed_run = await failure_database.get(AgentRun, agent_run.id)
                workflow_run = await failure_database.get(WorkflowRun, run.id)
                failed_step = await failure_database.get(WorkflowStepRun, step.id)
                if failed_run is not None:
                    failed_run.status = "failed"
                    failed_run.error_type = "queue_unavailable"
                    failed_run.error_message = "The background worker queue was unavailable"
                    failed_run.completed_at = _now()
                if workflow_run is not None and failed_step is not None:
                    failed_step.status = "failed"
                    failed_step.error_type = "workflow_agent_queue_unavailable"
                    failed_step.error_message = "The child agent could not be queued"
                    failed_step.completed_at = _now()
                    failed_version = await failure_database.get(
                        WorkflowVersion, workflow_run.workflow_version_id
                    )
                    failed_steps = list(
                        await failure_database.scalars(
                            select(WorkflowStepRun)
                            .where(WorkflowStepRun.workflow_run_id == workflow_run.id)
                            .order_by(WorkflowStepRun.sequence)
                        )
                    )
                    if failed_version is not None:
                        failed_definitions = {
                            item.key: item for item in parse_definition(failed_version.definition)
                        }
                        await fail_workflow(
                            failure_database,
                            workflow_run,
                            failed_definitions,
                            failed_steps,
                            failed_step.error_type,
                            failed_step.error_message,
                            step_key=failed_step.step_key,
                        )
                    await failure_database.commit()
