"""Anthropic Messages API adapter."""

from __future__ import annotations

from tomoshibi.llm.convert import parse_anthropic_response, to_anthropic_payload
from tomoshibi.llm.errors import humanize_provider_error
from tomoshibi.llm.types import LLMMessage, LLMResponse, ProviderError, ToolSpec


class AnthropicProvider:
    provider_name = "Anthropic"

    def __init__(self, *, api_key: str):
        self._api_key = api_key
        self._client = None

    def _sdk(self):
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self._api_key, timeout=90)
        return self._client

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        model: str,
    ) -> LLMResponse:
        system, payload, tool_payload = to_anthropic_payload(messages, tools)
        request: dict = {
            "model": model,
            "max_tokens": 4096,
            "messages": payload,
            "temperature": 0.4,
        }
        if system:
            request["system"] = system
        if tool_payload:
            request["tools"] = tool_payload
        try:
            response = await self._sdk().messages.create(**request)
        except Exception as exc:
            raise ProviderError(
                humanize_provider_error(self.provider_name, exc),
                provider="anthropic",
            ) from exc
        return parse_anthropic_response(response, model=model)
