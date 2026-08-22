from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.agents.schema import AgentSchemaError, validate_schema
from foundora.infrastructure.database import get_session_factory
from foundora.model_gateway.service import GatewayRequest, GatewayResult, ModelGateway
from foundora.model_gateway.types import GatewayError
from foundora.models import Agent, AgentMessage, AgentRun, AgentVersion

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ExecutionClaim:
    run_id: uuid.UUID
    business_id: uuid.UUID
    agent_id: str
    version: int
    role: str
    purpose: str
    structured_input: dict[str, object]
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    model_policy: dict[str, object]
    forbidden_actions: list[str]


class RuntimeRepository(Protocol):
    async def claim(self, run_id: uuid.UUID, operation_id: uuid.UUID) -> ExecutionClaim | None: ...

    async def complete(self, run_id: uuid.UUID, output: dict[str, object]) -> bool: ...

    async def fail(self, run_id: uuid.UUID, error_type: str, message: str) -> bool: ...


class RuntimeGateway(Protocol):
    async def generate(
        self,
        business_id: uuid.UUID,
        request: GatewayRequest,
        *,
        operation_id: uuid.UUID | None = None,
        agent_run_id: uuid.UUID | None = None,
    ) -> GatewayResult: ...


class SqlRuntimeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def claim(self, run_id: uuid.UUID, operation_id: uuid.UUID) -> ExecutionClaim | None:
        async with self._session_factory() as database:
            run = await database.scalar(
                select(AgentRun).where(AgentRun.id == run_id).with_for_update()
            )
            if run is None or run.status != "queued":
                return None
            agent = await database.get(Agent, run.agent_id)
            version = await database.get(AgentVersion, run.agent_version_id)
            if agent is None or version is None or not agent.enabled:
                run.status = "failed"
                run.error_type = "agent_disabled"
                run.error_message = "The pinned agent definition is not executable"
                run.completed_at = _now()
                database.add(
                    AgentMessage(
                        id=uuid.uuid4(),
                        run_id=run.id,
                        sequence=2,
                        role="system",
                        message_type="error",
                        content={"error_type": "agent_disabled"},
                        created_at=run.completed_at,
                    )
                )
                await database.commit()
                return None
            run.status = "running"
            run.started_at = _now()
            run.model_operation_id = operation_id
            await database.commit()
            return ExecutionClaim(
                run_id=run.id,
                business_id=run.business_id,
                agent_id=run.agent_id,
                version=version.version,
                role=version.role,
                purpose=version.purpose,
                structured_input=dict(run.structured_input),
                input_schema=dict(version.input_schema),
                output_schema=dict(version.output_schema),
                model_policy=dict(version.model_policy),
                forbidden_actions=list(version.forbidden_actions),
            )

    async def complete(self, run_id: uuid.UUID, output: dict[str, object]) -> bool:
        async with self._session_factory() as database:
            run = await database.scalar(
                select(AgentRun).where(AgentRun.id == run_id).with_for_update()
            )
            if run is None or run.status == "cancelled":
                return False
            if run.status != "running":
                return False
            run.status = "completed"
            run.structured_output = output
            run.completed_at = _now()
            database.add(
                AgentMessage(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    sequence=2,
                    role="assistant",
                    message_type="output",
                    content=output,
                    created_at=run.completed_at,
                )
            )
            await database.commit()
            return True

    async def fail(self, run_id: uuid.UUID, error_type: str, message: str) -> bool:
        async with self._session_factory() as database:
            run = await database.scalar(
                select(AgentRun).where(AgentRun.id == run_id).with_for_update()
            )
            if run is None or run.status == "cancelled":
                return False
            if run.status not in {"queued", "running", "waiting_tool", "waiting_approval"}:
                return False
            run.status = "failed"
            run.error_type = error_type[:80]
            run.error_message = message[:500]
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
            return True


def _policy_int(policy: dict[str, object], key: str) -> int:
    value = policy.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AgentSchemaError(f"Model policy {key} is invalid")
    return value


def _gateway_request(claim: ExecutionClaim) -> GatewayRequest:
    policy = claim.model_policy
    task_type = policy.get("task_type")
    sensitivity = policy.get("sensitivity")
    allow_fallback = policy.get("allow_fallback")
    if not isinstance(task_type, str) or sensitivity not in {"standard", "sensitive"}:
        raise AgentSchemaError("Model policy routing is invalid")
    if not isinstance(allow_fallback, bool):
        raise AgentSchemaError("Model policy fallback setting is invalid")
    system_prompt = (
        f"You are {claim.agent_id} version {claim.version}. Role: {claim.role}. "
        f"Purpose: {claim.purpose} You are read-only and must not perform or claim "
        "external actions. Use only the supplied business context. Distinguish missing "
        "facts from assumptions. Return only JSON matching the supplied schema. "
        f"Forbidden actions: {json.dumps(claim.forbidden_actions, ensure_ascii=False)}"
    )
    return GatewayRequest(
        task_type=task_type,
        prompt=json.dumps(claim.structured_input, ensure_ascii=False, sort_keys=True),
        system_prompt=system_prompt,
        sensitivity=sensitivity,
        allow_fallback=allow_fallback,
        max_output_tokens=_policy_int(policy, "max_output_tokens"),
        token_budget=_policy_int(policy, "token_budget"),
        cost_budget_microusd=_policy_int(policy, "cost_budget_microusd"),
        json_schema=claim.output_schema,
    )


class AgentRuntime:
    def __init__(
        self,
        repository: RuntimeRepository | None = None,
        gateway: RuntimeGateway | None = None,
    ) -> None:
        self._repository = repository or SqlRuntimeRepository()
        self._gateway = gateway or ModelGateway()

    async def execute(self, run_id: uuid.UUID) -> None:
        operation_id = uuid.uuid4()
        claim = await self._repository.claim(run_id, operation_id)
        if claim is None:
            return
        try:
            validate_schema(claim.structured_input, claim.input_schema)
            result = await self._gateway.generate(
                claim.business_id,
                _gateway_request(claim),
                operation_id=operation_id,
                agent_run_id=claim.run_id,
            )
            try:
                raw_output = json.loads(result.text)
            except json.JSONDecodeError as error:
                raise AgentSchemaError("Agent output is not valid JSON") from error
            if not isinstance(raw_output, dict):
                raise AgentSchemaError("Agent output must be an object")
            output = cast(dict[str, object], raw_output)
            validate_schema(output, claim.output_schema)
            await self._repository.complete(run_id, output)
        except AgentSchemaError as error:
            await self._repository.fail(run_id, "agent_schema_invalid", str(error))
        except GatewayError as error:
            safe_message = getattr(error, "safe_message", str(error))
            await self._repository.fail(run_id, error.code, safe_message)
        except Exception:
            logger.exception(
                "Agent run failed unexpectedly",
                extra={"event": "agent.run.failed", "agent_run_id": str(run_id)},
            )
            await self._repository.fail(
                run_id,
                "agent_runtime_error",
                "The agent runtime failed before producing a valid result",
            )
