"""Google Gemini adapter using the google-genai SDK.

Function declarations are passed as schema, not as Python callables, so the
SDK does not run tools itself. The agent loop is the only executor.
"""

from __future__ import annotations

from typing import Any

from yata.llm.convert import parse_gemini_response, to_gemini_contents
from yata.llm.errors import humanize_provider_error
from yata.llm.types import LLMMessage, LLMResponse, ProviderError, ToolSpec

_GEMINI_TYPES = {
    "object": "OBJECT",
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
}


def to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """JSON Schema subset to the uppercase types Gemini's SDK expects."""
    converted: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            converted["type"] = _GEMINI_TYPES.get(value.lower(), value.upper())
        elif key == "properties" and isinstance(value, dict):
            converted["properties"] = {name: to_gemini_schema(child) for name, child in value.items()}
        elif key == "items" and isinstance(value, dict):
            converted["items"] = to_gemini_schema(value)
        else:
            converted[key] = value
    converted.setdefault("type", "OBJECT")
    return converted


class GeminiProvider:
    provider_name = "Gemini"

    def __init__(self, *, api_key: str):
        self._api_key = api_key
        self._client = None

    def _sdk(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        model: str,
    ) -> LLMResponse:
        from google.genai import types

        system, contents = to_gemini_contents(messages)
        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters,
            )
            for tool in tools
        ]
        config_kwargs: dict[str, Any] = {"temperature": 0.4}
        if system:
            config_kwargs["system_instruction"] = system
        if declarations:
            config_kwargs["tools"] = [types.Tool(function_declarations=declarations)]
        config_kwargs = _with_thinking_disabled(types, config_kwargs)
        try:
            response = await self._sdk().aio.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:
            raise ProviderError(
                humanize_provider_error(self.provider_name, exc),
                provider="gemini",
            ) from exc
        try:
            return parse_gemini_response(response, model=model)
        except ValueError as exc:
            raise ProviderError(str(exc), provider="gemini") from exc


def _with_thinking_disabled(types: Any, config_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Gemini 2.5 may spend the turn on hidden thoughts. Prefer a direct answer."""
    thinking_config = getattr(types, "ThinkingConfig", None)
    if thinking_config is None:
        return config_kwargs
    try:
        config_kwargs["thinking_config"] = thinking_config(thinking_budget=0)
    except TypeError:
        return config_kwargs
    return config_kwargs
