"""Think, call a tool, observe, repeat, answer.

The loop streams AgentEvent values as soon as each step is known. It does not
know about HTTP or the database. Callers persist the messages appended to
`messages` after the stream finishes (including on cancellation).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from yata.confirm.gate import ConfirmationGate
from yata.llm.types import LLMMessage, LLMProvider, ProviderError, ToolCall
from yata.tools.base import ToolContext, ToolResult, validate_arguments
from yata.tools.policy import ToolPolicy, describe_action
from yata.tools.registry import ToolRegistry, UnknownToolError

logger = logging.getLogger(__name__)


def seal_open_tool_calls(messages: list[LLMMessage]) -> None:
    """Close tool calls that never received a result, so the next turn is valid."""
    answered = {message.tool_call_id for message in messages if message.role == "tool" and message.tool_call_id}
    extras: list[LLMMessage] = []
    for message in messages:
        if message.role != "assistant" or not message.tool_calls:
            continue
        for call in message.tool_calls:
            if call.id in answered:
                continue
            extras.append(
                LLMMessage(
                    role="tool",
                    content="操作は中断されました。",
                    tool_call_id=call.id,
                    name=call.name,
                    artifact={"ok": False},
                )
            )
            answered.add(call.id)
    messages.extend(extras)


@dataclass(frozen=True)
class AgentEvent:
    type: str
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}


async def run_agent(
    *,
    messages: list[LLMMessage],
    provider: LLMProvider,
    model: str,
    registry: ToolRegistry,
    policy: ToolPolicy,
    gate: ConfirmationGate,
    ctx: ToolContext,
    max_steps: int,
    confirm_timeout: float = 180,
) -> AsyncIterator[AgentEvent]:
    specs = registry.specs()
    for step in range(1, max_steps + 1):
        yield AgentEvent("step", {"step": step, "max_steps": max_steps, "phase": "thinking"})
        try:
            response = await provider.complete(messages, specs, model=model)
        except ProviderError as exc:
            text = str(exc)
            messages.append(LLMMessage(role="assistant", content=text))
            yield AgentEvent("error", {"message": text})
            yield AgentEvent("done", {"ok": False})
            return

        calls = response.tool_calls
        interim = (response.content or "").strip()
        if calls:
            messages.append(LLMMessage(role="assistant", content=interim or None, tool_calls=calls))
            if interim:
                yield AgentEvent("note", {"text": interim})
            for call in calls:
                async for event in _run_call(
                    call,
                    registry=registry,
                    policy=policy,
                    gate=gate,
                    ctx=ctx,
                    messages=messages,
                    confirm_timeout=confirm_timeout,
                ):
                    yield event
            continue

        text = interim or "応答が空でした。聞き方を変えてもう一度試してください。"
        messages.append(LLMMessage(role="assistant", content=text))
        yield AgentEvent("answer", {"content": text, "truncated": False})
        yield AgentEvent("done", {"ok": True, "truncated": False})
        return

    text = (
        f"最大ステップ数（{max_steps}）に達したため、ここで打ち切ります。"
        "わかった範囲で、質問を分けてもう一度聞いてください。"
    )
    messages.append(LLMMessage(role="assistant", content=text))
    yield AgentEvent("answer", {"content": text, "truncated": True})
    yield AgentEvent("done", {"ok": True, "truncated": True})


def _record(messages: list[LLMMessage], call: ToolCall, result: ToolResult) -> AgentEvent:
    messages.append(
        LLMMessage(
            role="tool",
            content=result.content,
            tool_call_id=call.id,
            name=call.name,
            artifact=result.stored_artifact(),
        )
    )
    return AgentEvent(
        "tool_result",
        {
            "id": call.id,
            "name": call.name,
            "ok": result.ok,
            "content": result.content,
            "image_url": (result.artifact or {}).get("image_url"),
        },
    )


async def _run_call(
    call: ToolCall,
    *,
    registry: ToolRegistry,
    policy: ToolPolicy,
    gate: ConfirmationGate,
    ctx: ToolContext,
    messages: list[LLMMessage],
    confirm_timeout: float,
) -> AsyncIterator[AgentEvent]:
    """Yield confirmation before waiting, so the UI can approve the call."""
    yield AgentEvent(
        "tool_call",
        {"id": call.id, "name": call.name, "arguments": call.arguments},
    )
    try:
        tool = registry.get(call.name)
    except UnknownToolError:
        yield _record(messages, call, ToolResult(ok=False, content=f"未知のツールです: {call.name}"))
        return

    invalid = validate_arguments(tool, call.arguments)
    if invalid:
        yield _record(messages, call, ToolResult(ok=False, content=invalid))
        return

    if policy.needs_confirmation(tool, call.arguments):
        request_id = gate.open()
        yield AgentEvent(
            "confirmation_required",
            {
                "request_id": request_id,
                "tool": tool.name,
                "risk": tool.risk.value,
                "summary": describe_action(tool, call.arguments),
                "arguments": call.arguments,
            },
        )
        approved = await gate.wait(request_id, confirm_timeout)
        yield AgentEvent(
            "confirmation_resolved",
            {"request_id": request_id, "approved": approved, "tool": tool.name},
        )
        if not approved:
            yield _record(
                messages,
                call,
                ToolResult(ok=False, content="ユーザーがこの操作を拒否したか、確認がタイムアウトしました。"),
            )
            return

    try:
        result = await tool.run(call.arguments, ctx)
    except Exception as exc:
        logger.exception("tool %s failed", tool.name)
        result = ToolResult(ok=False, content=f"ツール実行エラー: {exc}")
    yield _record(messages, call, result)
