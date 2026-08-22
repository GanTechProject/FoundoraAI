from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import cast

from foundora.config import Settings
from foundora.model_gateway.registry import model_spec
from foundora.model_gateway.types import (
    FallbackPolicyViolation,
    ModelProvider,
    ProviderName,
    Sensitivity,
)

_TASK_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")


@dataclass(frozen=True)
class RouteCandidate:
    provider: ModelProvider
    model: str


class ModelRouter:
    def __init__(self, settings: Settings, providers: dict[ProviderName, ModelProvider]) -> None:
        self._settings = settings
        self._providers = providers
        self._task_routes = self._parse_task_routes(settings.model_task_routes)

    @staticmethod
    def _parse_task_routes(value: str) -> dict[str, tuple[ProviderName, str]]:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("FOUNDORA_MODEL_TASK_ROUTES must be valid JSON") from error
        if not isinstance(decoded, dict):
            raise ValueError("FOUNDORA_MODEL_TASK_ROUTES must be a JSON object")
        routes: dict[str, tuple[ProviderName, str]] = {}
        for task_type, route in decoded.items():
            if not isinstance(task_type, str) or _TASK_PATTERN.fullmatch(task_type) is None:
                raise ValueError("Model task route names must use lowercase identifiers")
            if not isinstance(route, dict):
                raise ValueError("Each model task route must be an object")
            provider = route.get("provider")
            model = route.get("model")
            if provider not in {"openai", "gemini", "anthropic"} or not isinstance(model, str):
                raise ValueError("Each task route requires a supported provider and model")
            typed_provider: ProviderName = provider
            model_spec(typed_provider, model)
            routes[task_type] = (typed_provider, model)
        return routes

    @property
    def task_routes(self) -> dict[str, tuple[ProviderName, str]]:
        return dict(self._task_routes)

    def candidates(
        self,
        task_type: str,
        *,
        sensitivity: Sensitivity,
        allow_fallback: bool,
    ) -> list[RouteCandidate]:
        if allow_fallback and sensitivity == "sensitive":
            raise FallbackPolicyViolation("Sensitive content cannot be sent to a fallback provider")
        route = self._task_routes.get(task_type)
        ordered: list[tuple[ProviderName, str]] = []
        if route is not None:
            ordered.append(route)
        else:
            primary = self._settings.model_primary_provider
            ordered.append((primary, self._providers[primary].model))
        if allow_fallback:
            primary = self._settings.model_primary_provider
            ordered.append((primary, self._providers[primary].model))
            for value in self._settings.model_fallback_providers.split(","):
                name = value.strip().lower()
                if name not in {"openai", "gemini", "anthropic"}:
                    raise ValueError("Fallback providers contain an unsupported provider")
                provider_name = cast(ProviderName, name)
                ordered.append((provider_name, self._providers[provider_name].model))
        result: list[RouteCandidate] = []
        seen: set[tuple[ProviderName, str]] = set()
        for provider_name, model in ordered:
            key = (provider_name, model)
            if key not in seen:
                model_spec(provider_name, model)
                result.append(RouteCandidate(provider=self._providers[provider_name], model=model))
                seen.add(key)
        return result
