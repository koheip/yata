"""Provider-neutral chat types.

Every adapter translates these to the vendor's wire format and back.
Tool-call ids are required because OpenAI and Anthropic match results by id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    def __init__(self, message: str, *, provider: str):
        super().__init__(message)
        self.provider = provider


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMMessage:
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    artifact: dict[str, Any] | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str | None = None


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        model: str,
    ) -> LLMResponse:
        """Return the next model turn, including zero or more tool calls."""


def parse_arguments(raw: Any) -> dict[str, Any]:
    """Normalize vendor argument payloads to a dict the tools can read."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip() or "{}"
        try:
            value = json_loads(text)
        except ValueError:
            return {"_raw": raw}
        if isinstance(value, dict):
            return value
        return {"value": value}
    if hasattr(raw, "items"):
        return dict(raw.items())
    return {"value": raw}


def json_loads(text: str) -> Any:
    import json

    return json.loads(text)
