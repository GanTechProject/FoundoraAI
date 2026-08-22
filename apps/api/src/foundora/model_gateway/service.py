from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from foundora.config import Settings, get_settings
from foundora.infrastructure.database import get_session_factory
from foundora.logging import correlation_id
from foundora.model_gateway.registry import MODEL_REGISTRY, build_providers, model_spec
from foundora.model_gateway.routing import ModelRouter, RouteCandidate
from foundora.model_gateway.types import (
    BudgetExceeded,
    FallbackPolicyViolation,
    ModelProvider,
    ModelSpec,
    NoConfiguredProvider,
    ProviderFailure,
    ProviderName,
    ProviderRequest,
    ProviderResponse,
    ProviderValidationResult,
    Sensitivity,
)
from foundora.models import ModelGatewayCall, ModelProviderValidation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GatewayRequest:
    task_type: str
    prompt: str
    system_prompt: str | None
    sensitivity: Sensitivity
    allow_fallback: bool
    max_output_tokens: int
    token_budget: int
    cost_budget_microusd: int
    json_schema: dict[str, object] | None


@dataclass(frozen=True)
class GatewayResult:
    operation_id: uuid.UUID
    text: str
    provider: ProviderName
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_microusd: int
    latency_ms: int
    attempts: int
    fallback_used: bool
    structured: bool


@dataclass(frozen=True)
class GatewayStreamEvent:
    kind: Literal["start", "delta", "done", "error"]
    data: dict[str, object]


@dataclass(frozen=True)
class ProviderStatus:
    name: ProviderName
    configured: bool
    model: str
    latest_validation: ModelProviderValidation | None


@dataclass(frozen=True)
class UsageSummary:
    calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_microusd: int


@dataclass(frozen=True)
class GatewayDashboard:
    providers: list[ProviderStatus]
    task_routes: dict[str, tuple[ProviderName, str]]
    calls: list[ModelGatewayCall]
    usage: UsageSummary


def _now() -> datetime:
    return datetime.now(UTC)


def _prompt_token_upper_bound(request: GatewayRequest) -> int:
    values = [request.prompt, request.system_prompt or ""]
    if request.json_schema is not None:
        values.append(json.dumps(request.json_schema, separators=(",", ":"), sort_keys=True))
    return sum(len(value.encode("utf-8")) for value in values) + 256


class ModelGateway:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        providers: dict[ProviderName, ModelProvider] | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_factory = session_factory or get_session_factory()
        self._providers = providers or build_providers(self._settings)
        self._router = ModelRouter(self._settings, self._providers)
        self._sleeper = sleeper

    @property
    def providers(self) -> dict[ProviderName, ModelProvider]:
        return dict(self._providers)

    @property
    def models(self) -> tuple[ModelSpec, ...]:
        return MODEL_REGISTRY

    async def dashboard(self, business_id: uuid.UUID) -> GatewayDashboard:
        async with self._session_factory() as database:
            calls = list(
                await database.scalars(
                    select(ModelGatewayCall)
                    .where(ModelGatewayCall.business_id == business_id)
                    .order_by(desc(ModelGatewayCall.created_at))
                    .limit(20)
                )
            )
            validations = list(
                await database.scalars(
                    select(ModelProviderValidation).order_by(
                        desc(ModelProviderValidation.checked_at)
                    )
                )
            )
            summary = (
                await database.execute(
                    select(
                        func.count(ModelGatewayCall.id).filter(
                            ModelGatewayCall.status == "succeeded"
                        ),
                        func.coalesce(func.sum(ModelGatewayCall.input_tokens), 0),
                        func.coalesce(func.sum(ModelGatewayCall.output_tokens), 0),
                        func.coalesce(func.sum(ModelGatewayCall.estimated_cost_microusd), 0),
                    ).where(ModelGatewayCall.business_id == business_id)
                )
            ).one()
        latest: dict[str, ModelProviderValidation] = {}
        for validation in validations:
            latest.setdefault(validation.provider, validation)
        return GatewayDashboard(
            providers=[
                ProviderStatus(
                    name=name,
                    configured=provider.configured,
                    model=provider.model,
                    latest_validation=latest.get(name),
                )
                for name, provider in self._providers.items()
            ],
            task_routes=self._router.task_routes,
            calls=calls,
            usage=UsageSummary(
                calls=int(summary[0]),
                input_tokens=int(summary[1]),
                output_tokens=int(summary[2]),
                estimated_cost_microusd=int(summary[3]),
            ),
        )

    async def validate_provider(self, name: ProviderName) -> ProviderValidationResult:
        provider = self._providers[name]
        started = time.perf_counter()
        error_type: str | None = None
        try:
            result = await provider.validate_configuration()
            valid = result.valid and result.model_available
            if result.valid and not result.model_available:
                error_type = "model_unavailable"
        except ProviderFailure as error:
            valid = False
            error_type = error.code
            result = ProviderValidationResult(valid=False, model_available=False)
        latency_ms = round((time.perf_counter() - started) * 1000)
        async with self._session_factory() as database:
            database.add(
                ModelProviderValidation(
                    id=uuid.uuid4(),
                    provider=name,
                    model=provider.model,
                    status="valid" if valid else "invalid",
                    latency_ms=latency_ms,
                    error_type=error_type,
                    checked_at=_now(),
                )
            )
            await database.commit()
        return result

    def _preflight(
        self,
        request: GatewayRequest,
        candidate: RouteCandidate,
        *,
        spent_tokens: int = 0,
        spent_cost: int = 0,
    ) -> None:
        if request.max_output_tokens > self._settings.model_hard_max_output_tokens:
            raise BudgetExceeded("Output token limit exceeds the gateway hard limit")
        input_upper = _prompt_token_upper_bound(request)
        if spent_tokens + input_upper + request.max_output_tokens > request.token_budget:
            raise BudgetExceeded("Request exceeds its token budget before provider execution")
        spec = model_spec(candidate.provider.name, candidate.model)
        worst_cost = spec.cost_microusd(input_upper, request.max_output_tokens)
        if spent_cost + worst_cost > request.cost_budget_microusd:
            raise BudgetExceeded("Request exceeds its cost budget before provider execution")

    @staticmethod
    def _actual_budget_exceeded(
        request: GatewayRequest,
        response: ProviderResponse,
        cost: int,
        *,
        spent_tokens: int,
        spent_cost: int,
    ) -> bool:
        return (
            spent_tokens + response.input_tokens + response.output_tokens > request.token_budget
            or spent_cost + cost > request.cost_budget_microusd
        )

    async def generate(
        self,
        business_id: uuid.UUID,
        request: GatewayRequest,
        *,
        operation_id: uuid.UUID | None = None,
        agent_run_id: uuid.UUID | None = None,
    ) -> GatewayResult:
        candidates = self._router.candidates(
            request.task_type,
            sensitivity=request.sensitivity,
            allow_fallback=request.allow_fallback,
        )
        configured = [candidate for candidate in candidates if candidate.provider.configured]
        if not configured:
            raise NoConfiguredProvider("No routed model provider is configured")
        operation_id = operation_id or uuid.uuid4()
        attempt_number = 0
        previous_provider: ProviderName | None = None
        last_error: ProviderFailure | None = None
        spent_tokens = 0
        spent_cost = 0
        for candidate_index, candidate in enumerate(configured):
            for retry_number in range(self._settings.model_max_retries + 1):
                self._preflight(
                    request,
                    candidate,
                    spent_tokens=spent_tokens,
                    spent_cost=spent_cost,
                )
                attempt_number += 1
                started_at = _now()
                started = time.perf_counter()
                response: ProviderResponse | None = None
                try:
                    response = await candidate.provider.generate(
                        ProviderRequest(
                            prompt=request.prompt,
                            system_prompt=request.system_prompt,
                            max_output_tokens=request.max_output_tokens,
                            json_schema=request.json_schema,
                        )
                    )
                    if request.json_schema is not None:
                        try:
                            json.loads(response.text)
                        except json.JSONDecodeError as error:
                            raise ProviderFailure(
                                candidate.provider.name,
                                "structured_output_invalid",
                                "Provider returned invalid structured output",
                                retryable=True,
                            ) from error
                    latency_ms = round((time.perf_counter() - started) * 1000)
                    cost = model_spec(candidate.provider.name, candidate.model).cost_microusd(
                        response.input_tokens, response.output_tokens
                    )
                    if self._actual_budget_exceeded(
                        request,
                        response,
                        cost,
                        spent_tokens=spent_tokens,
                        spent_cost=spent_cost,
                    ):
                        raise BudgetExceeded("Provider usage exceeded the operation budget")
                    await self._record_call(
                        operation_id=operation_id,
                        business_id=business_id,
                        request=request,
                        candidate=candidate,
                        status="succeeded",
                        attempt_number=attempt_number,
                        retry_number=retry_number,
                        fallback_from=previous_provider,
                        streamed=False,
                        response=response,
                        cost=cost,
                        latency_ms=latency_ms,
                        error=None,
                        started_at=started_at,
                        agent_run_id=agent_run_id,
                    )
                    return GatewayResult(
                        operation_id=operation_id,
                        text=response.text,
                        provider=candidate.provider.name,
                        model=response.model,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        total_tokens=response.input_tokens + response.output_tokens,
                        estimated_cost_microusd=cost,
                        latency_ms=latency_ms,
                        attempts=attempt_number,
                        fallback_used=candidate_index > 0,
                        structured=request.json_schema is not None,
                    )
                except (ProviderFailure, BudgetExceeded) as raw_error:
                    failure = (
                        raw_error
                        if isinstance(raw_error, ProviderFailure)
                        else ProviderFailure(
                            candidate.provider.name,
                            raw_error.code,
                            str(raw_error),
                            retryable=False,
                        )
                    )
                    last_error = failure
                    latency_ms = round((time.perf_counter() - started) * 1000)
                    cost = (
                        model_spec(candidate.provider.name, candidate.model).cost_microusd(
                            response.input_tokens, response.output_tokens
                        )
                        if response is not None
                        else 0
                    )
                    await self._record_call(
                        operation_id=operation_id,
                        business_id=business_id,
                        request=request,
                        candidate=candidate,
                        status="failed",
                        attempt_number=attempt_number,
                        retry_number=retry_number,
                        fallback_from=previous_provider,
                        streamed=False,
                        response=response,
                        cost=cost,
                        latency_ms=latency_ms,
                        error=failure,
                        started_at=started_at,
                        agent_run_id=agent_run_id,
                    )
                    if response is not None:
                        spent_tokens += response.input_tokens + response.output_tokens
                        spent_cost += cost
                    logger.warning(
                        "Model provider attempt failed",
                        extra={
                            "event": "model_gateway.attempt.failed",
                            "provider": candidate.provider.name,
                            "model": candidate.model,
                            "error_type": failure.code,
                            "operation_id": str(operation_id),
                        },
                    )
                    if isinstance(raw_error, BudgetExceeded):
                        raise raw_error
                    if not failure.retryable or retry_number >= self._settings.model_max_retries:
                        break
                    await self._sleeper(min(0.25 * (2**retry_number), 1.0))
            previous_provider = candidate.provider.name
        if last_error is not None:
            raise last_error
        raise NoConfiguredProvider("No routed model provider is configured")

    async def stream(
        self, business_id: uuid.UUID, request: GatewayRequest
    ) -> AsyncIterator[GatewayStreamEvent]:
        try:
            candidates = self._router.candidates(
                request.task_type,
                sensitivity=request.sensitivity,
                allow_fallback=request.allow_fallback,
            )
        except (FallbackPolicyViolation, ValueError):
            yield GatewayStreamEvent(kind="error", data={"code": "fallback_policy_violation"})
            return
        configured = [candidate for candidate in candidates if candidate.provider.configured]
        if not configured:
            yield GatewayStreamEvent(kind="error", data={"code": "no_configured_provider"})
            return
        operation_id = uuid.uuid4()
        attempt_number = 0
        previous_provider: ProviderName | None = None
        spent_tokens = 0
        spent_cost = 0
        yield GatewayStreamEvent(kind="start", data={"operation_id": str(operation_id)})
        for candidate_index, candidate in enumerate(configured):
            for retry_number in range(self._settings.model_max_retries + 1):
                try:
                    self._preflight(
                        request,
                        candidate,
                        spent_tokens=spent_tokens,
                        spent_cost=spent_cost,
                    )
                except BudgetExceeded:
                    yield GatewayStreamEvent(kind="error", data={"code": "budget_exceeded"})
                    return
                attempt_number += 1
                started_at = _now()
                started = time.perf_counter()
                emitted = False
                completed: ProviderResponse | None = None
                try:
                    async for event in candidate.provider.stream(
                        ProviderRequest(
                            prompt=request.prompt,
                            system_prompt=request.system_prompt,
                            max_output_tokens=request.max_output_tokens,
                            json_schema=request.json_schema,
                        )
                    ):
                        if event.kind == "delta":
                            emitted = True
                            yield GatewayStreamEvent(kind="delta", data={"text": event.delta})
                        elif event.response is not None:
                            completed = event.response
                    if completed is None:
                        raise ProviderFailure(
                            candidate.provider.name,
                            "provider_protocol",
                            "Provider stream ended without usage metadata",
                            retryable=False,
                        )
                    if request.json_schema is not None:
                        json.loads(completed.text)
                    latency_ms = round((time.perf_counter() - started) * 1000)
                    cost = model_spec(candidate.provider.name, candidate.model).cost_microusd(
                        completed.input_tokens, completed.output_tokens
                    )
                    if self._actual_budget_exceeded(
                        request,
                        completed,
                        cost,
                        spent_tokens=spent_tokens,
                        spent_cost=spent_cost,
                    ):
                        raise BudgetExceeded("Provider usage exceeded the operation budget")
                    await self._record_call(
                        operation_id=operation_id,
                        business_id=business_id,
                        request=request,
                        candidate=candidate,
                        status="succeeded",
                        attempt_number=attempt_number,
                        retry_number=retry_number,
                        fallback_from=previous_provider,
                        streamed=True,
                        response=completed,
                        cost=cost,
                        latency_ms=latency_ms,
                        error=None,
                        started_at=started_at,
                    )
                    yield GatewayStreamEvent(
                        kind="done",
                        data={
                            "provider": candidate.provider.name,
                            "model": completed.model,
                            "input_tokens": completed.input_tokens,
                            "output_tokens": completed.output_tokens,
                            "estimated_cost_microusd": cost,
                            "attempts": attempt_number,
                            "fallback_used": candidate_index > 0,
                        },
                    )
                    return
                except (ProviderFailure, BudgetExceeded, json.JSONDecodeError) as raw_error:
                    failure = (
                        raw_error
                        if isinstance(raw_error, ProviderFailure)
                        else ProviderFailure(
                            candidate.provider.name,
                            (
                                raw_error.code
                                if isinstance(raw_error, BudgetExceeded)
                                else "structured_output_invalid"
                            ),
                            (
                                str(raw_error)
                                if isinstance(raw_error, BudgetExceeded)
                                else "Provider returned invalid structured output"
                            ),
                            retryable=False,
                        )
                    )
                    latency_ms = round((time.perf_counter() - started) * 1000)
                    cost = (
                        model_spec(candidate.provider.name, candidate.model).cost_microusd(
                            completed.input_tokens, completed.output_tokens
                        )
                        if completed is not None
                        else 0
                    )
                    await self._record_call(
                        operation_id=operation_id,
                        business_id=business_id,
                        request=request,
                        candidate=candidate,
                        status="failed",
                        attempt_number=attempt_number,
                        retry_number=retry_number,
                        fallback_from=previous_provider,
                        streamed=True,
                        response=completed,
                        cost=cost,
                        latency_ms=latency_ms,
                        error=failure,
                        started_at=started_at,
                    )
                    if completed is not None:
                        spent_tokens += completed.input_tokens + completed.output_tokens
                        spent_cost += cost
                    if isinstance(raw_error, BudgetExceeded):
                        yield GatewayStreamEvent(kind="error", data={"code": raw_error.code})
                        return
                    if emitted:
                        yield GatewayStreamEvent(kind="error", data={"code": failure.code})
                        return
                    if failure.retryable and retry_number < self._settings.model_max_retries:
                        await self._sleeper(min(0.25 * (2**retry_number), 1.0))
                        continue
                    break
            previous_provider = candidate.provider.name
        yield GatewayStreamEvent(kind="error", data={"code": "providers_exhausted"})

    async def _record_call(
        self,
        *,
        operation_id: uuid.UUID,
        business_id: uuid.UUID,
        request: GatewayRequest,
        candidate: RouteCandidate,
        status: Literal["succeeded", "failed"],
        attempt_number: int,
        retry_number: int,
        fallback_from: ProviderName | None,
        streamed: bool,
        response: ProviderResponse | None,
        cost: int,
        latency_ms: int,
        error: ProviderFailure | None,
        started_at: datetime,
        agent_run_id: uuid.UUID | None = None,
    ) -> None:
        input_tokens = response.input_tokens if response is not None else 0
        output_tokens = response.output_tokens if response is not None else 0
        async with self._session_factory() as database:
            database.add(
                ModelGatewayCall(
                    id=uuid.uuid4(),
                    operation_id=operation_id,
                    business_id=business_id,
                    agent_run_id=agent_run_id,
                    request_id=correlation_id.get() or str(uuid.uuid4()),
                    task_type=request.task_type,
                    sensitivity=request.sensitivity,
                    provider=candidate.provider.name,
                    model=response.model if response is not None else candidate.model,
                    status=status,
                    attempt_number=attempt_number,
                    retry_number=retry_number,
                    fallback_from=fallback_from,
                    streamed=streamed,
                    structured=request.json_schema is not None,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    estimated_cost_microusd=cost,
                    latency_ms=latency_ms,
                    error_type=error.code if error is not None else None,
                    error_message=error.safe_message[:500] if error is not None else None,
                    created_at=started_at,
                    completed_at=_now(),
                )
            )
            await database.commit()
