"""The extension point for tools, including future desktop control.

A tool declares a name, a JSON schema, and a risk. The agent loop is the only
caller. Tools that mutate a page or leave the machine ask for confirmation
through the risk, not through ad-hoc checks inside the tool.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from yata.llm.types import ToolSpec


class Risk(StrEnum):
    """How careful the loop should be before running a tool.

    READ: search, fetch, screenshot, snapshot.
    WRITE: local memory. Useful, not dangerous, so the default policy allows it.
    MUTATE: clicks and typing in the browser. Confirmation required.
    EXTERNAL: future desktop control, mail, purchases. Confirmation required.
    """

    READ = "read"
    WRITE = "write"
    MUTATE = "mutate"
    EXTERNAL = "external"


@dataclass
class ToolContext:
    conversation_id: str
    memory: Any
    browser: Any
    artifacts_dir: Any
    allow_private_urls: bool
    connectors: Any = None


@dataclass
class ToolResult:
    ok: bool
    content: str
    artifact: dict[str, Any] | None = None

    def stored_artifact(self) -> dict[str, Any]:
        data = dict(self.artifact or {})
        data["ok"] = self.ok
        return data


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk = Risk.READ
    required_connector: str | None = None

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)

    @abstractmethod
    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


def validate_arguments(tool: Tool, arguments: dict[str, Any]) -> str | None:
    if not isinstance(arguments, dict):
        return "引数がオブジェクトではありません。"
    if any(str(key).startswith("_") for key in arguments):
        return "引数を解釈できませんでした。"
    required = tool.parameters.get("required") or []
    missing = [key for key in required if key not in arguments or arguments[key] in ("", None)]
    if missing:
        return "必須パラメータがありません: " + ", ".join(missing)
    properties = tool.parameters.get("properties") or {}
    for key, value in arguments.items():
        expected = (properties.get(key) or {}).get("type")
        if expected == "string" and not isinstance(value, str):
            return f"{key} は文字列である必要があります。"
        if expected == "integer" and isinstance(value, bool):
            return f"{key} は整数である必要があります。"
        if expected == "integer" and isinstance(value, float) and value.is_integer():
            arguments[key] = int(value)
            continue
        if expected == "integer" and not isinstance(value, int):
            return f"{key} は整数である必要があります。"
        if expected == "boolean" and not isinstance(value, bool):
            return f"{key} は真偽値である必要があります。"
    return None


def clip_text(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（長すぎるので省略しました）"


@dataclass
class ToolContextFactory:
    """Build a per-conversation context without repeating the shared services."""

    memory: Any
    browser: Any
    artifacts_dir: Any
    allow_private_urls: bool
    connectors: Any = None

    def for_conversation(self, conversation_id: str) -> ToolContext:
        return ToolContext(
            conversation_id=conversation_id,
            memory=self.memory,
            browser=self.browser,
            artifacts_dir=self.artifacts_dir,
            allow_private_urls=self.allow_private_urls,
            connectors=self.connectors,
        )
