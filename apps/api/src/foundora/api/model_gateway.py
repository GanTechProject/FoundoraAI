from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from jsonschema import SchemaError
from jsonschema.validators import validator_for
from pydantic import BaseModel, Field, field_validator

from foundora.api.auth import require_auth, require_csrf
from foundora.auth.service import AuthContext
from foundora.business.context import resolve_selected_business
from foundora.config import get_settings
from foundora.infrastructure.database import get_session_factory
from foundora.model_gateway.registry import MODEL_REGISTRY
from foundora.model_gateway.service import GatewayRequest, ModelGateway
from foundora.model_gateway.types import (
    BudgetExceeded,
    FallbackPolicyViolation,
    GatewayError,
    NoConfiguredProvider,
    ProviderFailure,
    ProviderName,
)

router = APIRouter(prefix="/ai", tags=["model gateway"])
_TASK_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")


class GenerateRequest(BaseModel):
    task_type: str = "general"
    prompt: str = Field(min_length=1, max_length=20_000)
    system_prompt: str | None = Field(default=None, max_length=8_000)
    sensitivity: Literal["standard", "sensitive"] = "sensitive"
    allow_fallback: bool = False
    max_output_tokens: int | None = Field(default=None, ge=1)
    token_budget: int | None = Field(default=None, ge=1, le=1_000_000)
    cost_budget_microusd: int | None = Field(default=None, ge=1, le=10_000_000)
    json_schema: dict[str, object] | None = None

    @field_validator("task_type")
    @classmethod
    def valid_task_type(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if _TASK_PATTERN.fullmatch(cleaned) is None:
            raise ValueError("task_type must be a lowercase identifier")
        return cleaned

    @field_validator("prompt")
    @classmethod
    def clean_prompt(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("prompt cannot be blank")
        return cleaned

    @field_validator("system_prompt")
    @classmethod
    def clean_system_prompt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("json_schema")
    @classmethod
    def bounded_schema(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        if value is None:
            return None
        encoded = json.dumps(value, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 16_384:
            raise ValueError("json_schema exceeds 16 KiB")
        if value.get("type") not in {"object", "array"}:
            raise ValueError("json_schema root type must be object or array")
        try:
            validator_for(value).check_schema(value)
        except SchemaError as error:
            raise ValueError("json_schema is not a valid JSON Schema") from error
        return value


class ProviderStatusView(BaseModel):
    name: ProviderName
    configured: bool
    model: str
    validation_status: Literal["never", "valid", "invalid"]
    validated_at: datetime | None
    validation_error_type: str | None


class ModelView(BaseModel):
    provider: ProviderName
    model: str
    input_microusd_per_token: str
    output_microusd_per_token: str
    supports_streaming: bool
    supports_structured_output: bool


class UsageSummaryView(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_microusd: int


class GatewayCallView(BaseModel):
    operation_id: str
    task_type: str
    sensitivity: Literal["standard", "sensitive"]
    provider: ProviderName
    model: str
    status: Literal["succeeded", "failed"]
    attempt_number: int
    retry_number: int
    fallback_from: ProviderName | None
    streamed: bool
    structured: bool
    input_tokens: int
    output_tokens: int
    estimated_cost_microusd: int
    latency_ms: int
    error_type: str | None
    created_at: datetime


class GatewayDashboardView(BaseModel):
    business_id: str
    providers: list[ProviderStatusView]
    models: list[ModelView]
    primary_provider: ProviderName
    fallback_providers: list[ProviderName]
    task_routes: dict[str, dict[str, str]]
    default_max_output_tokens: int
    default_token_budget: int
    default_cost_budget_microusd: int
    usage: UsageSummaryView
    recent_calls: list[GatewayCallView]


class ProviderValidationView(BaseModel):
    provider: ProviderName
    configured: bool
    valid: bool
    model: str
    model_available: bool


class GenerationView(BaseModel):
    operation_id: str
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


async def _selected_business_id(context: AuthContext) -> uuid.UUID:
    session_factory = get_session_factory()
    async with session_factory() as database:
        business = await resolve_selected_business(database, context)
        return business.id


def _request(payload: GenerateRequest) -> GatewayRequest:
    settings = get_settings()
    return GatewayRequest(
        task_type=payload.task_type,
        prompt=payload.prompt,
        system_prompt=payload.system_prompt,
        sensitivity=payload.sensitivity,
        allow_fallback=payload.allow_fallback,
        max_output_tokens=payload.max_output_tokens or settings.model_default_max_output_tokens,
        token_budget=payload.token_budget or settings.model_default_token_budget,
        cost_budget_microusd=payload.cost_budget_microusd
        or settings.model_default_cost_budget_microusd,
        json_schema=payload.json_schema,
    )


def _gateway_error(error: GatewayError) -> HTTPException:
    if isinstance(error, (BudgetExceeded, FallbackPolicyViolation)):
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif isinstance(error, NoConfiguredProvider):
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(error, ProviderFailure) and error.code == "provider_timeout":
        code = status.HTTP_504_GATEWAY_TIMEOUT
    else:
        code = status.HTTP_502_BAD_GATEWAY
    return HTTPException(status_code=code, detail={"code": error.code, "message": str(error)})


@router.get("", response_model=GatewayDashboardView)
async def gateway_dashboard(
    context: Annotated[AuthContext, Depends(require_auth)], response: Response
) -> GatewayDashboardView:
    business_id = await _selected_business_id(context)
    gateway = ModelGateway()
    dashboard = await gateway.dashboard(business_id)
    settings = get_settings()
    fallback_names: list[ProviderName] = []
    for value in settings.model_fallback_providers.split(","):
        name = value.strip().lower()
        if name in {"openai", "gemini", "anthropic"}:
            fallback_names.append(name)  # type: ignore[arg-type]
    response.headers["Cache-Control"] = "no-store"
    return GatewayDashboardView(
        business_id=str(business_id),
        providers=[
            ProviderStatusView(
                name=item.name,
                configured=item.configured,
                model=item.model,
                validation_status=cast(
                    Literal["never", "valid", "invalid"],
                    item.latest_validation.status
                    if item.latest_validation is not None
                    else "never",
                ),
                validated_at=(
                    item.latest_validation.checked_at
                    if item.latest_validation is not None
                    else None
                ),
                validation_error_type=(
                    item.latest_validation.error_type
                    if item.latest_validation is not None
                    else None
                ),
            )
            for item in dashboard.providers
        ],
        models=[
            ModelView(
                provider=item.provider,
                model=item.model,
                input_microusd_per_token=str(item.input_microusd_per_token),
                output_microusd_per_token=str(item.output_microusd_per_token),
                supports_streaming=item.supports_streaming,
                supports_structured_output=item.supports_structured_output,
            )
            for item in MODEL_REGISTRY
        ],
        primary_provider=settings.model_primary_provider,
        fallback_providers=fallback_names,
        task_routes={
            task: {"provider": route[0], "model": route[1]}
            for task, route in dashboard.task_routes.items()
        },
        default_max_output_tokens=settings.model_default_max_output_tokens,
        default_token_budget=settings.model_default_token_budget,
        default_cost_budget_microusd=settings.model_default_cost_budget_microusd,
        usage=UsageSummaryView(
            calls=dashboard.usage.calls,
            input_tokens=dashboard.usage.input_tokens,
            output_tokens=dashboard.usage.output_tokens,
            total_tokens=dashboard.usage.input_tokens + dashboard.usage.output_tokens,
            estimated_cost_microusd=dashboard.usage.estimated_cost_microusd,
        ),
        recent_calls=[
            GatewayCallView(
                operation_id=str(item.operation_id),
                task_type=item.task_type,
                sensitivity=item.sensitivity,  # type: ignore[arg-type]
                provider=item.provider,  # type: ignore[arg-type]
                model=item.model,
                status=item.status,  # type: ignore[arg-type]
                attempt_number=item.attempt_number,
                retry_number=item.retry_number,
                fallback_from=item.fallback_from,  # type: ignore[arg-type]
                streamed=item.streamed,
                structured=item.structured,
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                estimated_cost_microusd=item.estimated_cost_microusd,
                latency_ms=item.latency_ms,
                error_type=item.error_type,
                created_at=item.created_at,
            )
            for item in dashboard.calls
        ],
    )


@router.post("/providers/{provider}/validate", response_model=ProviderValidationView)
async def validate_provider(
    provider: ProviderName,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> ProviderValidationView:
    await _selected_business_id(context)
    gateway = ModelGateway()
    result = await gateway.validate_provider(provider)
    configured = gateway.providers[provider].configured
    return ProviderValidationView(
        provider=provider,
        configured=configured,
        valid=result.valid and result.model_available,
        model=gateway.providers[provider].model,
        model_available=result.model_available,
    )


@router.post("/generate", response_model=GenerationView)
async def generate(
    payload: GenerateRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> GenerationView:
    business_id = await _selected_business_id(context)
    try:
        result = await ModelGateway().generate(business_id, _request(payload))
    except GatewayError as error:
        raise _gateway_error(error) from error
    return GenerationView(
        operation_id=str(result.operation_id),
        text=result.text,
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        total_tokens=result.total_tokens,
        estimated_cost_microusd=result.estimated_cost_microusd,
        latency_ms=result.latency_ms,
        attempts=result.attempts,
        fallback_used=result.fallback_used,
        structured=result.structured,
    )


@router.post("/stream")
async def stream(
    payload: GenerateRequest,
    context: Annotated[AuthContext, Depends(require_csrf)],
) -> StreamingResponse:
    business_id = await _selected_business_id(context)

    async def events() -> AsyncIterator[str]:
        async for event in ModelGateway().stream(business_id, _request(payload)):
            yield f"event: {event.kind}\ndata: {json.dumps(event.data, separators=(',', ':'))}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
