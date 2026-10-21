"""Shared fakes for the agent loop tests."""

from __future__ import annotations

from tomoshibi.llm.types import LLMMessage, LLMResponse, ToolSpec
from tomoshibi.tools.base import Risk, Tool, ToolContext, ToolResult


class ScriptedProvider:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.seen: list[list[LLMMessage]] = []

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        model: str,
    ) -> LLMResponse:
        del tools, model
        self.seen.append(list(messages))
        if not self.responses:
            return LLMResponse(content="script exhausted", tool_calls=[])
        return self.responses.pop(0)


class RecordingTool(Tool):
    name = "echo"
    description = "Repeat text."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    risk = Risk.READ

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        del ctx
        self.calls.append(arguments)
        return ToolResult(ok=True, content=f"echo:{arguments['text']}")


class ExplodingTool(RecordingTool):
    name = "explode"

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        del arguments, ctx
        raise RuntimeError("boom")


class MutatingTool(RecordingTool):
    name = "poke"
    description = "Change something."
    risk = Risk.MUTATE
    parameters = {
        "type": "object",
        "properties": {"target": {"type": "string"}},
        "required": ["target"],
    }

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        del ctx
        self.calls.append(arguments)
        return ToolResult(ok=True, content=f"poked:{arguments['target']}")
