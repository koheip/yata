"""OpenAI, and any server that speaks the OpenAI chat-completions API.

Ollama, LM Studio, and vLLM are the same adapter with a different base URL
and a placeholder API key. That is the OpenAI-compatible path in this MVP.
"""

from __future__ import annotations

from tomoshibi.llm.convert import parse_openai_message, to_openai_messages, to_openai_tools
from tomoshibi.llm.errors import humanize_provider_error
from tomoshibi.llm.types import LLMMessage, LLMResponse, ProviderError, ToolSpec


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        provider_name: str,
    ):
        self.provider_name = provider_name
        self._api_key = api_key
        self._base_url = base_url
        self._client = None

    def _sdk(self):
        if self._client is None:
            from openai import AsyncOpenAI

            kwargs: dict = {"api_key": self._api_key, "timeout": 90}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        model: str,
    ) -> LLMResponse:
        request: dict = {
            "model": model,
            "messages": to_openai_messages(messages),
            "temperature": 0.4,
        }
        if tools:
            request["tools"] = to_openai_tools(tools)
            request["tool_choice"] = "auto"
        try:
            response = await self._sdk().chat.completions.create(**request)
        except Exception as exc:
            raise ProviderError(
                humanize_provider_error(self.provider_name, exc),
                provider=self.provider_name,
            ) from exc
        if not response.choices:
            raise ProviderError(f"{self.provider_name} から候補が返りませんでした。", provider=self.provider_name)
        return parse_openai_message(response.choices[0].message, model=model)


def ollama_openai_base(url: str) -> str:
    root = url.rstrip("/")
    if root.endswith("/v1"):
        return root
    return root + "/v1"


def ollama_root(url: str) -> str:
    root = url.rstrip("/")
    if root.endswith("/v1"):
        return root[: -len("/v1")]
    return root
