from __future__ import annotations

from decimal import Decimal

import httpx

from foundora.config import Settings
from foundora.model_gateway.providers import AnthropicProvider, GeminiProvider, OpenAIProvider
from foundora.model_gateway.types import ModelProvider, ModelSpec, ProviderName

MODEL_REGISTRY: tuple[ModelSpec, ...] = (
    ModelSpec(
        provider="openai",
        model="gpt-4o-mini",
        input_microusd_per_token=Decimal("0.15"),
        output_microusd_per_token=Decimal("0.60"),
    ),
    ModelSpec(
        provider="gemini",
        model="gemini-3.6-flash",
        input_microusd_per_token=Decimal("0.75"),
        output_microusd_per_token=Decimal("3.75"),
    ),
    ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        input_microusd_per_token=Decimal("1"),
        output_microusd_per_token=Decimal("5"),
    ),
)


def model_spec(provider: ProviderName, model: str) -> ModelSpec:
    for item in MODEL_REGISTRY:
        if item.provider == provider and item.model == model:
            return item
    raise ValueError(f"Model is not in the governed registry: {provider}/{model}")


def _secret(value: object) -> str | None:
    getter = getattr(value, "get_secret_value", None)
    if not callable(getter):
        return None
    secret = str(getter()).strip()
    return secret or None


def build_providers(
    settings: Settings,
    *,
    transports: dict[ProviderName, httpx.AsyncBaseTransport] | None = None,
) -> dict[ProviderName, ModelProvider]:
    transports = transports or {}
    providers: dict[ProviderName, ModelProvider] = {
        "openai": OpenAIProvider(
            _secret(settings.openai_api_key),
            settings.openai_model,
            settings.model_timeout_seconds,
            transport=transports.get("openai"),
        ),
        "gemini": GeminiProvider(
            _secret(settings.gemini_api_key),
            settings.gemini_model,
            settings.model_timeout_seconds,
            transport=transports.get("gemini"),
        ),
        "anthropic": AnthropicProvider(
            _secret(settings.anthropic_api_key),
            settings.anthropic_model,
            settings.model_timeout_seconds,
            transport=transports.get("anthropic"),
        ),
    }
    for provider in providers.values():
        model_spec(provider.name, provider.model)
    return providers
