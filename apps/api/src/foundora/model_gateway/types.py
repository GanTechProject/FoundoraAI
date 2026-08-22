from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Literal, Protocol

ProviderName = Literal["openai", "gemini", "anthropic"]
Sensitivity = Literal["standard", "sensitive"]


class GatewayError(Exception):
    code = "gateway_error"


class NoConfiguredProvider(GatewayError):
    code = "no_configured_provider"


class BudgetExceeded(GatewayError):
    code = "budget_exceeded"


class FallbackPolicyViolation(GatewayError):
    code = "fallback_policy_violation"


class ProviderFailure(GatewayError):
    def __init__(
        self,
        provider: ProviderName,
        code: str,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        self.provider = provider
        self.code = code
        self.safe_message = message
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class ModelSpec:
    provider: ProviderName
    model: str
    input_microusd_per_token: Decimal
    output_microusd_per_token: Decimal
    supports_streaming: bool = True
    supports_structured_output: bool = True

    def cost_microusd(self, input_tokens: int, output_tokens: int) -> int:
        cost = (
            Decimal(input_tokens) * self.input_microusd_per_token
            + Decimal(output_tokens) * self.output_microusd_per_token
        )
        return int(cost.quantize(Decimal("1"), rounding=ROUND_CEILING))


@dataclass(frozen=True)
class ProviderRequest:
    prompt: str
    system_prompt: str | None
    max_output_tokens: int
    json_schema: dict[str, object] | None


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ProviderStreamEvent:
    kind: Literal["delta", "done"]
    delta: str = ""
    response: ProviderResponse | None = None


@dataclass(frozen=True)
class ProviderValidationResult:
    valid: bool
    model_available: bool


class ModelProvider(Protocol):
    name: ProviderName
    model: str
    configured: bool

    async def validate_configuration(self) -> ProviderValidationResult: ...

    async def generate(self, request: ProviderRequest) -> ProviderResponse: ...

    def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamEvent]: ...
