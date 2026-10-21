"""Name-addressed tool registry. Registration order is the order models see."""

from __future__ import annotations

from yata.llm.types import ToolSpec
from yata.tools.base import Tool


class DuplicateToolError(ValueError):
    pass


class UnknownToolError(KeyError):
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise DuplicateToolError(f"ツールは登録済みです: {tool.name}")
        if not tool.name.isidentifier():
            raise ValueError(f"ツール名が不正です: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(name) from exc

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def tools(self) -> list[Tool]:
        return list(self._tools.values())
