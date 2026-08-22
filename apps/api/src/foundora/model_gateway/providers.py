from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from foundora.model_gateway.types import (
    ModelProvider,
    ProviderFailure,
    ProviderName,
    ProviderRequest,
    ProviderResponse,
    ProviderStreamEvent,
    ProviderValidationResult,
)

_RETRYABLE_STATUS = {408, 409, 425, 429}


def _failure(provider: ProviderName, response: httpx.Response) -> ProviderFailure:
    retryable = response.status_code in _RETRYABLE_STATUS or response.status_code >= 500
    return ProviderFailure(
        provider,
        f"provider_http_{response.status_code}",
        f"Provider returned HTTP {response.status_code}",
        retryable=retryable,
    )


def _transport_failure(provider: ProviderName, error: Exception) -> ProviderFailure:
    if isinstance(error, httpx.TimeoutException):
        return ProviderFailure(
            provider, "provider_timeout", "Provider request timed out", retryable=True
        )
    return ProviderFailure(
        provider, "provider_transport", "Provider connection failed", retryable=True
    )


def _protocol_failure(provider: ProviderName) -> ProviderFailure:
    return ProviderFailure(
        provider,
        "provider_protocol",
        "Provider returned an invalid response",
        retryable=False,
    )


def _sse_json(line: str) -> dict[str, object] | None:
    if not line.startswith("data:"):
        return None
    value = line[5:].strip()
    if not value or value == "[DONE]":
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


class _HttpProvider(ModelProvider):
    name: ProviderName

    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout_seconds: int,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self.model = model
        self.configured = bool(self._api_key)
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    def _disabled(self) -> ProviderFailure:
        return ProviderFailure(
            self.name,
            "provider_disabled",
            "Provider is disabled because its API key is missing",
            retryable=False,
        )


class OpenAIProvider(_HttpProvider):
    name: ProviderName = "openai"
    _base_url = "https://api.openai.com/v1"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    async def validate_configuration(self) -> ProviderValidationResult:
        if not self.configured:
            return ProviderValidationResult(valid=False, model_available=False)
        try:
            async with self._client() as client:
                response = await client.get(
                    f"{self._base_url}/models/{self.model}", headers=self._headers
                )
        except httpx.HTTPError as error:
            raise _transport_failure(self.name, error) from error
        if response.status_code >= 400:
            raise _failure(self.name, response)
        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise _protocol_failure(self.name) from error
        return ProviderValidationResult(
            valid=True,
            model_available=isinstance(payload, dict) and payload.get("id") == self.model,
        )

    def _payload(self, request: ProviderRequest, *, stream: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "input": request.prompt,
            "max_output_tokens": request.max_output_tokens,
            "store": False,
            "stream": stream,
        }
        if request.system_prompt:
            payload["instructions"] = request.system_prompt
        if request.json_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "foundora_response",
                    "schema": request.json_schema,
                    "strict": True,
                }
            }
        return payload

    @staticmethod
    def _parse(payload: object) -> ProviderResponse:
        if not isinstance(payload, dict):
            raise _protocol_failure("openai")
        text_parts: list[str] = []
        output = payload.get("output", [])
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content", [])
                if not isinstance(content, list):
                    continue
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        value = part.get("text")
                        if isinstance(value, str):
                            text_parts.append(value)
        usage = payload.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        model = payload.get("model")
        if not text_parts or not isinstance(model, str):
            raise _protocol_failure("openai")
        return ProviderResponse(
            text="".join(text_parts),
            model=model,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.configured:
            raise self._disabled()
        try:
            async with self._client() as client:
                response = await client.post(
                    f"{self._base_url}/responses",
                    headers=self._headers,
                    json=self._payload(request, stream=False),
                )
        except httpx.HTTPError as error:
            raise _transport_failure(self.name, error) from error
        if response.status_code >= 400:
            raise _failure(self.name, response)
        try:
            return self._parse(response.json())
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise _protocol_failure(self.name) from error

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamEvent]:
        if not self.configured:
            raise self._disabled()
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/responses",
                    headers=self._headers,
                    json=self._payload(request, stream=True),
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise _failure(self.name, response)
                    async for line in response.aiter_lines():
                        event = _sse_json(line)
                        if event is None:
                            continue
                        event_type = event.get("type")
                        if event_type == "response.output_text.delta":
                            delta = event.get("delta")
                            if isinstance(delta, str):
                                yield ProviderStreamEvent(kind="delta", delta=delta)
                        elif event_type == "response.completed":
                            parsed = self._parse(event.get("response"))
                            yield ProviderStreamEvent(kind="done", response=parsed)
                        elif event_type in {"error", "response.failed", "response.incomplete"}:
                            raise ProviderFailure(
                                self.name,
                                "provider_stream_failed",
                                "Provider stream failed",
                                retryable=False,
                            )
        except ProviderFailure:
            raise
        except httpx.HTTPError as error:
            raise _transport_failure(self.name, error) from error


class GeminiProvider(_HttpProvider):
    name: ProviderName = "gemini"
    _base_url = "https://generativelanguage.googleapis.com/v1beta"

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}

    async def validate_configuration(self) -> ProviderValidationResult:
        if not self.configured:
            return ProviderValidationResult(valid=False, model_available=False)
        try:
            async with self._client() as client:
                response = await client.get(
                    f"{self._base_url}/models/{self.model}", headers=self._headers
                )
        except httpx.HTTPError as error:
            raise _transport_failure(self.name, error) from error
        if response.status_code >= 400:
            raise _failure(self.name, response)
        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise _protocol_failure(self.name) from error
        return ProviderValidationResult(
            valid=True,
            model_available=(
                isinstance(payload, dict) and payload.get("name") == f"models/{self.model}"
            ),
        )

    def _payload(self, request: ProviderRequest) -> dict[str, object]:
        payload: dict[str, object] = {
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            "generationConfig": {
                "maxOutputTokens": request.max_output_tokens,
                "thinkingConfig": {"thinkingLevel": "MINIMAL"},
            },
        }
        if request.system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": request.system_prompt}]}
        if request.json_schema is not None:
            config = payload["generationConfig"]
            assert isinstance(config, dict)
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = request.json_schema
        return payload

    def _text_and_usage(self, payload: object) -> tuple[str, int, int]:
        if not isinstance(payload, dict):
            raise _protocol_failure(self.name)
        candidates = payload.get("candidates", [])
        text_parts: list[str] = []
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content", {})
                parts = content.get("parts", []) if isinstance(content, dict) else []
                if isinstance(parts, list):
                    for part in parts:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            text_parts.append(str(part["text"]))
        usage = payload.get("usageMetadata", {})
        if not isinstance(usage, dict):
            usage = {}
        return (
            "".join(text_parts),
            int(usage.get("promptTokenCount", 0)),
            int(usage.get("candidatesTokenCount", 0)),
        )

    def _parse(self, payload: object) -> ProviderResponse:
        text, input_tokens, output_tokens = self._text_and_usage(payload)
        if not text:
            raise _protocol_failure(self.name)
        return ProviderResponse(
            text=text,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.configured:
            raise self._disabled()
        try:
            async with self._client() as client:
                response = await client.post(
                    f"{self._base_url}/models/{self.model}:generateContent",
                    headers=self._headers,
                    json=self._payload(request),
                )
        except httpx.HTTPError as error:
            raise _transport_failure(self.name, error) from error
        if response.status_code >= 400:
            raise _failure(self.name, response)
        try:
            return self._parse(response.json())
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise _protocol_failure(self.name) from error

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamEvent]:
        if not self.configured:
            raise self._disabled()
        full_text: list[str] = []
        input_tokens = 0
        output_tokens = 0
        received_event = False
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/models/{self.model}:streamGenerateContent?alt=sse",
                    headers=self._headers,
                    json=self._payload(request),
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise _failure(self.name, response)
                    async for line in response.aiter_lines():
                        payload = _sse_json(line)
                        if payload is None:
                            continue
                        received_event = True
                        text, chunk_input_tokens, chunk_output_tokens = self._text_and_usage(
                            payload
                        )
                        input_tokens = max(input_tokens, chunk_input_tokens)
                        output_tokens = max(output_tokens, chunk_output_tokens)
                        if text:
                            full_text.append(text)
                            yield ProviderStreamEvent(kind="delta", delta=text)
        except ProviderFailure:
            raise
        except httpx.HTTPError as error:
            raise _transport_failure(self.name, error) from error
        if not received_event or not full_text:
            raise _protocol_failure(self.name)
        yield ProviderStreamEvent(
            kind="done",
            response=ProviderResponse(
                text="".join(full_text),
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
        )


class AnthropicProvider(_HttpProvider):
    name: ProviderName = "anthropic"
    _base_url = "https://api.anthropic.com/v1"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    async def validate_configuration(self) -> ProviderValidationResult:
        if not self.configured:
            return ProviderValidationResult(valid=False, model_available=False)
        try:
            async with self._client() as client:
                response = await client.get(f"{self._base_url}/models", headers=self._headers)
        except httpx.HTTPError as error:
            raise _transport_failure(self.name, error) from error
        if response.status_code >= 400:
            raise _failure(self.name, response)
        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise _protocol_failure(self.name) from error
        data = payload.get("data", []) if isinstance(payload, dict) else []
        available = isinstance(data, list) and any(
            isinstance(item, dict) and item.get("id") == self.model for item in data
        )
        return ProviderValidationResult(valid=True, model_available=available)

    def _payload(self, request: ProviderRequest, *, stream: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": stream,
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt
        if request.json_schema is not None:
            payload["output_config"] = {
                "format": {"type": "json_schema", "schema": request.json_schema}
            }
        return payload

    def _parse(self, payload: object) -> ProviderResponse:
        if not isinstance(payload, dict):
            raise _protocol_failure(self.name)
        content = payload.get("content", [])
        text_parts = (
            [
                str(item["text"])
                for item in content
                if isinstance(item, dict) and item.get("type") == "text" and "text" in item
            ]
            if isinstance(content, list)
            else []
        )
        usage = payload.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        model = payload.get("model")
        if not text_parts or not isinstance(model, str):
            raise _protocol_failure(self.name)
        return ProviderResponse(
            text="".join(text_parts),
            model=model,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.configured:
            raise self._disabled()
        try:
            async with self._client() as client:
                response = await client.post(
                    f"{self._base_url}/messages",
                    headers=self._headers,
                    json=self._payload(request, stream=False),
                )
        except httpx.HTTPError as error:
            raise _transport_failure(self.name, error) from error
        if response.status_code >= 400:
            raise _failure(self.name, response)
        try:
            return self._parse(response.json())
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise _protocol_failure(self.name) from error

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamEvent]:
        if not self.configured:
            raise self._disabled()
        text_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        response_model = self.model
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/messages",
                    headers=self._headers,
                    json=self._payload(request, stream=True),
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise _failure(self.name, response)
                    async for line in response.aiter_lines():
                        payload = _sse_json(line)
                        if payload is None:
                            continue
                        event_type = payload.get("type")
                        if event_type == "message_start":
                            message = payload.get("message", {})
                            if isinstance(message, dict):
                                usage = message.get("usage", {})
                                if isinstance(usage, dict):
                                    input_tokens = int(usage.get("input_tokens", 0))
                                if isinstance(message.get("model"), str):
                                    response_model = str(message["model"])
                        elif event_type == "content_block_delta":
                            delta = payload.get("delta", {})
                            value = delta.get("text") if isinstance(delta, dict) else None
                            if isinstance(value, str):
                                text_parts.append(value)
                                yield ProviderStreamEvent(kind="delta", delta=value)
                        elif event_type == "message_delta":
                            usage = payload.get("usage", {})
                            if isinstance(usage, dict):
                                output_tokens = int(usage.get("output_tokens", 0))
                        elif event_type == "error":
                            raise ProviderFailure(
                                self.name,
                                "provider_stream_failed",
                                "Provider stream failed",
                                retryable=False,
                            )
        except ProviderFailure:
            raise
        except httpx.HTTPError as error:
            raise _transport_failure(self.name, error) from error
        if not text_parts:
            raise _protocol_failure(self.name)
        yield ProviderStreamEvent(
            kind="done",
            response=ProviderResponse(
                text="".join(text_parts),
                model=response_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
        )
