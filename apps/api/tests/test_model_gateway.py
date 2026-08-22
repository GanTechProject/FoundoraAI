from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import cast

import httpx
import pytest

from foundora.config import Settings
from foundora.model_gateway.providers import AnthropicProvider, GeminiProvider, OpenAIProvider
from foundora.model_gateway.registry import build_providers
from foundora.model_gateway.service import GatewayRequest, ModelGateway
from foundora.model_gateway.types import (
    BudgetExceeded,
    FallbackPolicyViolation,
    ModelProvider,
    ProviderFailure,
    ProviderName,
    ProviderRequest,
    ProviderResponse,
    ProviderStreamEvent,
    ProviderValidationResult,
)


class FakeProvider:
    def __init__(
        self,
        name: ProviderName,
        model: str,
        outcomes: list[ProviderResponse | ProviderFailure],
        *,
        configured: bool = True,
    ) -> None:
        self.name = name
        self.model = model
        self.configured = configured
        self.outcomes = outcomes
        self.requests: list[ProviderRequest] = []

    async def validate_configuration(self) -> ProviderValidationResult:
        return ProviderValidationResult(valid=self.configured, model_available=self.configured)

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, ProviderFailure):
            raise outcome
        return outcome

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamEvent]:
        response = await self.generate(request)
        yield ProviderStreamEvent(kind="delta", delta=response.text)
        yield ProviderStreamEvent(kind="done", response=response)


class RecordingGateway(ModelGateway):
    def __init__(self, settings: Settings, providers: dict[ProviderName, ModelProvider]) -> None:
        super().__init__(
            settings=settings,
            providers=providers,
            sleeper=self._no_sleep,
        )
        self.records: list[dict[str, object]] = []

    @staticmethod
    async def _no_sleep(_: float) -> None:
        return None

    async def _record_call(self, **values: object) -> None:  # type: ignore[override]
        self.records.append(values)


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)


def request(**values: object) -> GatewayRequest:
    defaults: dict[str, object] = {
        "task_type": "general",
        "prompt": "Return a short answer.",
        "system_prompt": None,
        "sensitivity": "standard",
        "allow_fallback": True,
        "max_output_tokens": 32,
        "token_budget": 2048,
        "cost_budget_microusd": 5000,
        "json_schema": None,
    }
    defaults.update(values)
    return GatewayRequest(**defaults)  # type: ignore[arg-type]


def providers(
    openai: FakeProvider, gemini: FakeProvider, anthropic: FakeProvider
) -> dict[ProviderName, ModelProvider]:
    return {
        "openai": cast(ModelProvider, openai),
        "gemini": cast(ModelProvider, gemini),
        "anthropic": cast(ModelProvider, anthropic),
    }


def response(text: str, model: str) -> ProviderResponse:
    return ProviderResponse(
        text=text,
        model=model,
        input_tokens=12,
        output_tokens=4,
    )


def test_missing_keys_disable_every_provider_without_placeholder_output() -> None:
    configured = build_providers(settings())
    assert {name: provider.configured for name, provider in configured.items()} == {
        "openai": False,
        "gemini": False,
        "anthropic": False,
    }


@pytest.mark.asyncio
async def test_gateway_falls_back_and_persists_each_attempt() -> None:
    openai = FakeProvider(
        "openai",
        "gpt-4o-mini",
        [
            ProviderFailure(
                "openai",
                "provider_http_503",
                "Provider returned HTTP 503",
                retryable=False,
            )
        ],
    )
    gemini = FakeProvider(
        "gemini",
        "gemini-3.6-flash",
        [response("fallback result", "gemini-3.6-flash")],
    )
    anthropic = FakeProvider("anthropic", "claude-haiku-4-5-20251001", [], configured=False)
    gateway = RecordingGateway(settings(model_max_retries=1), providers(openai, gemini, anthropic))

    result = await gateway.generate(uuid.uuid4(), request())

    assert result.provider == "gemini"
    assert result.fallback_used is True
    assert result.attempts == 2
    assert [record["status"] for record in gateway.records] == ["failed", "succeeded"]
    assert gateway.records[1]["fallback_from"] == "openai"


@pytest.mark.asyncio
async def test_sensitive_request_cannot_enable_cross_provider_fallback() -> None:
    openai = FakeProvider("openai", "gpt-4o-mini", [])
    gemini = FakeProvider("gemini", "gemini-3.6-flash", [])
    anthropic = FakeProvider("anthropic", "claude-haiku-4-5-20251001", [])
    gateway = RecordingGateway(settings(), providers(openai, gemini, anthropic))

    with pytest.raises(FallbackPolicyViolation):
        await gateway.generate(uuid.uuid4(), request(sensitivity="sensitive", allow_fallback=True))
    assert not openai.requests
    assert not gateway.records


@pytest.mark.asyncio
async def test_task_route_does_not_cross_provider_without_fallback_permission() -> None:
    openai = FakeProvider("openai", "gpt-4o-mini", [response("must not run", "gpt-4o-mini")])
    gemini = FakeProvider(
        "gemini",
        "gemini-3.6-flash",
        [
            ProviderFailure(
                "gemini",
                "provider_http_503",
                "Provider returned HTTP 503",
                retryable=False,
            )
        ],
    )
    anthropic = FakeProvider("anthropic", "claude-haiku-4-5-20251001", [], configured=False)
    gateway = RecordingGateway(
        settings(
            model_max_retries=0,
            model_task_routes=('{"routed":{"provider":"gemini","model":"gemini-3.6-flash"}}'),
        ),
        providers(openai, gemini, anthropic),
    )

    with pytest.raises(ProviderFailure):
        await gateway.generate(
            uuid.uuid4(),
            request(task_type="routed", allow_fallback=False),
        )

    assert len(gemini.requests) == 1
    assert not openai.requests


@pytest.mark.asyncio
async def test_budget_is_rejected_before_provider_execution() -> None:
    openai = FakeProvider("openai", "gpt-4o-mini", [])
    gemini = FakeProvider("gemini", "gemini-3.6-flash", [], configured=False)
    anthropic = FakeProvider("anthropic", "claude-haiku-4-5-20251001", [], configured=False)
    gateway = RecordingGateway(settings(), providers(openai, gemini, anthropic))

    with pytest.raises(BudgetExceeded):
        await gateway.generate(uuid.uuid4(), request(allow_fallback=False, token_budget=10))
    assert not openai.requests
    assert not gateway.records


@pytest.mark.asyncio
async def test_streaming_records_final_usage() -> None:
    openai = FakeProvider(
        "openai",
        "gpt-4o-mini",
        [response("streamed result", "gpt-4o-mini")],
    )
    gemini = FakeProvider("gemini", "gemini-3.6-flash", [], configured=False)
    anthropic = FakeProvider("anthropic", "claude-haiku-4-5-20251001", [], configured=False)
    gateway = RecordingGateway(settings(), providers(openai, gemini, anthropic))

    events = [event async for event in gateway.stream(uuid.uuid4(), request())]

    assert [event.kind for event in events] == ["start", "delta", "done"]
    assert events[-1].data["output_tokens"] == 4
    assert gateway.records[0]["status"] == "succeeded"
    assert gateway.records[0]["streamed"] is True
    assert gateway.records[0]["response"] == response("streamed result", "gpt-4o-mini")


@pytest.mark.asyncio
async def test_invalid_structured_output_keeps_billed_usage() -> None:
    openai = FakeProvider(
        "openai",
        "gpt-4o-mini",
        [response("not-json", "gpt-4o-mini")],
    )
    gemini = FakeProvider("gemini", "gemini-3.6-flash", [], configured=False)
    anthropic = FakeProvider("anthropic", "claude-haiku-4-5-20251001", [], configured=False)
    gateway = RecordingGateway(settings(model_max_retries=0), providers(openai, gemini, anthropic))

    with pytest.raises(ProviderFailure, match="invalid structured output"):
        await gateway.generate(
            uuid.uuid4(),
            request(allow_fallback=False, json_schema={"type": "object"}),
        )

    assert gateway.records[0]["status"] == "failed"
    assert gateway.records[0]["response"] == response("not-json", "gpt-4o-mini")
    assert cast(int, gateway.records[0]["cost"]) > 0


@pytest.mark.asyncio
async def test_valid_json_that_violates_schema_is_rejected() -> None:
    openai = FakeProvider(
        "openai",
        "gpt-4o-mini",
        [response("{}", "gpt-4o-mini")],
    )
    gemini = FakeProvider("gemini", "gemini-3.6-flash", [], configured=False)
    anthropic = FakeProvider("anthropic", "claude-haiku-4-5-20251001", [], configured=False)
    gateway = RecordingGateway(settings(model_max_retries=0), providers(openai, gemini, anthropic))

    with pytest.raises(ProviderFailure, match="invalid structured output"):
        await gateway.generate(
            uuid.uuid4(),
            request(
                allow_fallback=False,
                json_schema={
                    "type": "object",
                    "required": ["answer"],
                    "properties": {"answer": {"type": "string"}},
                },
            ),
        )

    assert gateway.records[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_unresolvable_structured_output_reference_is_safely_rejected() -> None:
    openai = FakeProvider(
        "openai",
        "gpt-4o-mini",
        [response('{"answer":"okay"}', "gpt-4o-mini")],
    )
    gemini = FakeProvider("gemini", "gemini-3.6-flash", [], configured=False)
    anthropic = FakeProvider("anthropic", "claude-haiku-4-5-20251001", [], configured=False)
    gateway = RecordingGateway(settings(model_max_retries=0), providers(openai, gemini, anthropic))

    with pytest.raises(ProviderFailure, match="invalid structured output"):
        await gateway.generate(
            uuid.uuid4(),
            request(
                allow_fallback=False,
                json_schema={
                    "type": "object",
                    "properties": {"answer": {"$ref": "https://invalid.example/schema"}},
                },
            ),
        )

    assert gateway.records[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_cancelled_stream_persists_failed_attempt() -> None:
    release = asyncio.Event()

    class BlockingProvider(FakeProvider):
        async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamEvent]:
            self.requests.append(request)
            yield ProviderStreamEvent(kind="delta", delta="partial")
            await release.wait()

    openai = BlockingProvider("openai", "gpt-4o-mini", [])
    gemini = FakeProvider("gemini", "gemini-3.6-flash", [], configured=False)
    anthropic = FakeProvider("anthropic", "claude-haiku-4-5-20251001", [], configured=False)
    gateway = RecordingGateway(settings(model_max_retries=0), providers(openai, gemini, anthropic))
    stream = gateway.stream(uuid.uuid4(), request(allow_fallback=False))

    assert (await anext(stream)).kind == "start"
    assert (await anext(stream)).kind == "delta"
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert gateway.records[0]["status"] == "failed"
    error = cast(ProviderFailure, gateway.records[0]["error"])
    assert error.code == "client_stream_cancelled"


@pytest.mark.asyncio
async def test_retry_rechecks_shared_budget_after_billed_failure() -> None:
    openai = FakeProvider(
        "openai",
        "gpt-4o-mini",
        [
            response("not-json", "gpt-4o-mini"),
            response('{"ok":true}', "gpt-4o-mini"),
        ],
    )
    gemini = FakeProvider("gemini", "gemini-3.6-flash", [], configured=False)
    anthropic = FakeProvider("anthropic", "claude-haiku-4-5-20251001", [], configured=False)
    gateway = RecordingGateway(settings(model_max_retries=1), providers(openai, gemini, anthropic))

    with pytest.raises(BudgetExceeded):
        await gateway.generate(
            uuid.uuid4(),
            request(
                allow_fallback=False,
                json_schema={"type": "object"},
                token_budget=340,
            ),
        )

    assert len(openai.requests) == 1
    assert len(gateway.records) == 1


@pytest.mark.asyncio
async def test_openai_adapter_uses_responses_api_and_parses_usage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["store"] is False
        assert payload["text"]["format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "output": [{"content": [{"type": "output_text", "text": '{"ok":true}'}]}],
                "usage": {"input_tokens": 11, "output_tokens": 5},
            },
        )

    provider = OpenAIProvider(
        "test-key",
        "gpt-4o-mini",
        5,
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate(
        ProviderRequest(
            prompt="status",
            system_prompt=None,
            max_output_tokens=32,
            json_schema={"type": "object", "additionalProperties": False},
        )
    )
    assert result.text == '{"ok":true}'
    assert (result.input_tokens, result.output_tokens) == (11, 5)


@pytest.mark.asyncio
async def test_gemini_adapter_uses_native_schema_and_usage_metadata() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models/gemini-3.6-flash:generateContent")
        assert request.headers["x-goog-api-key"] == "test-key"
        payload = json.loads(request.content)
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert payload["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "MINIMAL"
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}],
                "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 3},
            },
        )

    provider = GeminiProvider(
        "test-key",
        "gemini-3.6-flash",
        5,
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate(
        ProviderRequest(
            prompt="status",
            system_prompt="Return JSON.",
            max_output_tokens=32,
            json_schema={"type": "object"},
        )
    )
    assert result.text == '{"ok":true}'
    assert (result.input_tokens, result.output_tokens) == (9, 3)


@pytest.mark.asyncio
async def test_anthropic_adapter_uses_output_config_and_parses_usage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "test-key"
        payload = json.loads(request.content)
        assert payload["output_config"]["format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "model": "claude-haiku-4-5-20251001",
                "content": [{"type": "text", "text": '{"ok":true}'}],
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
        )

    provider = AnthropicProvider(
        "test-key",
        "claude-haiku-4-5-20251001",
        5,
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate(
        ProviderRequest(
            prompt="status",
            system_prompt=None,
            max_output_tokens=32,
            json_schema={"type": "object"},
        )
    )
    assert result.text == '{"ok":true}'
    assert (result.input_tokens, result.output_tokens) == (10, 4)


@pytest.mark.asyncio
async def test_openai_streaming_emits_delta_and_final_usage() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        body = "\n".join(
            [
                'data: {"type":"response.output_text.delta","delta":"hello"}',
                'data: {"type":"response.completed","response":'
                '{"model":"gpt-4o-mini","output":[{"content":'
                '[{"type":"output_text","text":"hello"}]}],'
                '"usage":{"input_tokens":7,"output_tokens":2}}}',
                "data: [DONE]",
            ]
        )
        return httpx.Response(200, text=body)

    provider = OpenAIProvider(
        "test-key",
        "gpt-4o-mini",
        5,
        transport=httpx.MockTransport(handler),
    )
    events = [
        event
        async for event in provider.stream(
            ProviderRequest(
                prompt="status",
                system_prompt=None,
                max_output_tokens=32,
                json_schema=None,
            )
        )
    ]
    assert [event.kind for event in events] == ["delta", "done"]
    assert events[0].delta == "hello"
    assert events[1].response is not None
    assert events[1].response.output_tokens == 2
