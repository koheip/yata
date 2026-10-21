"""Agent loop with a scripted model. No network."""

from __future__ import annotations

import asyncio

from tests.fakes import ExplodingTool, MutatingTool, RecordingTool, ScriptedProvider
from tomoshibi.agent.loop import run_agent
from tomoshibi.confirm.gate import InMemoryConfirmationGate, ScriptedGate
from tomoshibi.llm.types import LLMMessage, LLMResponse, ProviderError, ToolCall
from tomoshibi.tools.base import ToolContext
from tomoshibi.tools.policy import ToolPolicy
from tomoshibi.tools.registry import ToolRegistry


def _ctx() -> ToolContext:
    return ToolContext(
        conversation_id="conv",
        memory=None,
        browser=None,
        artifacts_dir=None,
        allow_private_urls=True,
    )


def _registry(*tools) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


async def _events(**kwargs):
    items = []
    async for event in run_agent(**kwargs):
        items.append(event)
    return items


async def test_confirmation_gate_resolves_from_another_task() -> None:
    gate = InMemoryConfirmationGate()
    request_id = gate.open()

    async def approve() -> None:
        await asyncio.sleep(0.01)
        assert gate.resolve(request_id, True) is True

    task = asyncio.create_task(approve())
    assert await gate.wait(request_id, timeout=1) is True
    await task
    assert gate.resolve(request_id, False) is False


async def test_answers_without_tools() -> None:
    provider = ScriptedProvider([LLMResponse(content="こんにちは", tool_calls=[])])
    messages = [LLMMessage(role="user", content="やあ")]
    events = await _events(
        messages=messages,
        provider=provider,
        model="test",
        registry=_registry(RecordingTool()),
        policy=ToolPolicy(),
        gate=ScriptedGate([]),
        ctx=_ctx(),
        max_steps=4,
    )
    assert [event.type for event in events] == ["step", "answer", "done"]
    assert events[1].data["content"] == "こんにちは"
    assert messages[-1].content == "こんにちは"


async def test_tool_call_then_answer_feeds_observation_back() -> None:
    tool = RecordingTool()
    provider = ScriptedProvider(
        [
            LLMResponse(
                content="検索します",
                tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "灯"})],
            ),
            LLMResponse(content="灯について答えます", tool_calls=[]),
        ]
    )
    messages = [LLMMessage(role="user", content="灯は？")]
    events = await _events(
        messages=messages,
        provider=provider,
        model="test",
        registry=_registry(tool),
        policy=ToolPolicy(),
        gate=ScriptedGate([]),
        ctx=_ctx(),
        max_steps=4,
    )
    assert [event.type for event in events] == [
        "step",
        "note",
        "tool_call",
        "tool_result",
        "step",
        "answer",
        "done",
    ]
    assert tool.calls == [{"text": "灯"}]
    assert events[3].data["content"] == "echo:灯"
    second_call = provider.seen[1]
    assert second_call[-1].role == "tool"
    assert second_call[-1].content == "echo:灯"
    assert messages[-1].content == "灯について答えます"


async def test_max_steps_stops_after_the_limit() -> None:
    tool = RecordingTool()
    provider = ScriptedProvider(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "1"})]),
            LLMResponse(content="should not run", tool_calls=[]),
        ]
    )
    messages = [LLMMessage(role="user", content="続けて")]
    events = await _events(
        messages=messages,
        provider=provider,
        model="test",
        registry=_registry(tool),
        policy=ToolPolicy(),
        gate=ScriptedGate([]),
        ctx=_ctx(),
        max_steps=1,
    )
    assert events[-2].type == "answer"
    assert events[-2].data["truncated"] is True
    assert "最大ステップ数" in events[-2].data["content"]
    assert len(provider.seen) == 1
    assert tool.calls == [{"text": "1"}]


async def test_confirmation_denied_does_not_run_tool() -> None:
    tool = MutatingTool()
    provider = ScriptedProvider(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="poke", arguments={"target": "送信"})]),
            LLMResponse(content="確認が拒否されたので止まります", tool_calls=[]),
        ]
    )
    messages = [LLMMessage(role="user", content="押して")]
    events = await _events(
        messages=messages,
        provider=provider,
        model="test",
        registry=_registry(tool),
        policy=ToolPolicy(),
        gate=ScriptedGate([False]),
        ctx=_ctx(),
        max_steps=4,
    )
    assert tool.calls == []
    kinds = [event.type for event in events]
    assert kinds.index("confirmation_required") < kinds.index("tool_result")
    result = next(event for event in events if event.type == "tool_result")
    assert result.data["ok"] is False
    assert "拒否" in result.data["content"]
    assert "拒否" in provider.seen[1][-1].content


async def test_confirmation_approved_runs_tool() -> None:
    tool = MutatingTool()
    provider = ScriptedProvider(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="poke", arguments={"target": "次へ"})]),
            LLMResponse(content="クリックしました", tool_calls=[]),
        ]
    )
    messages = [LLMMessage(role="user", content="次へ")]
    events = await _events(
        messages=messages,
        provider=provider,
        model="test",
        registry=_registry(tool),
        policy=ToolPolicy(),
        gate=ScriptedGate([True]),
        ctx=_ctx(),
        max_steps=4,
    )
    assert tool.calls == [{"target": "次へ"}]
    resolved = next(event for event in events if event.type == "confirmation_resolved")
    assert resolved.data["approved"] is True


async def test_confirmation_is_emitted_before_the_loop_waits() -> None:
    class HoldGate:
        def __init__(self) -> None:
            self.wait_entered = asyncio.Event()
            self.allow = asyncio.Event()

        def open(self) -> str:
            return "req-1"

        async def wait(self, request_id: str, timeout: float) -> bool:
            del request_id, timeout
            self.wait_entered.set()
            await self.allow.wait()
            return True

        def resolve(self, request_id: str, approved: bool) -> bool:
            del request_id, approved
            return True

    tool = MutatingTool()
    gate = HoldGate()
    provider = ScriptedProvider(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="poke", arguments={"target": "go"})]),
            LLMResponse(content="done", tool_calls=[]),
        ]
    )
    seen: list[str] = []

    async def consume() -> None:
        async for event in run_agent(
            messages=[LLMMessage(role="user", content="go")],
            provider=provider,
            model="test",
            registry=_registry(tool),
            policy=ToolPolicy(),
            gate=gate,
            ctx=_ctx(),
            max_steps=3,
        ):
            seen.append(event.type)
            if event.type == "confirmation_required":
                assert gate.wait_entered.is_set() is False
                assert tool.calls == []
                gate.allow.set()

    await consume()
    assert tool.calls == [{"target": "go"}]
    assert seen[0] == "step"
    assert "confirmation_required" in seen


async def test_unknown_tool_and_exception_become_observations() -> None:
    tool = ExplodingTool()
    provider = ScriptedProvider(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="missing", arguments={})]),
            LLMResponse(tool_calls=[ToolCall(id="c2", name="explode", arguments={"text": "x"})]),
            LLMResponse(content="両方失敗しました", tool_calls=[]),
        ]
    )
    messages = [LLMMessage(role="user", content="やって")]
    events = await _events(
        messages=messages,
        provider=provider,
        model="test",
        registry=_registry(tool),
        policy=ToolPolicy(),
        gate=ScriptedGate([]),
        ctx=_ctx(),
        max_steps=4,
    )
    results = [event.data["content"] for event in events if event.type == "tool_result"]
    assert any("未知のツール" in content for content in results)
    assert any("ツール実行エラー" in content for content in results)
    assert events[-2].data["content"] == "両方失敗しました"


async def test_provider_error_stops_the_loop() -> None:
    class Boom:
        async def complete(self, messages, tools, *, model: str):
            del messages, tools, model
            raise ProviderError("Gemini の API キーが拒否されました。", provider="gemini")

    messages = [LLMMessage(role="user", content="やあ")]
    events = await _events(
        messages=messages,
        provider=Boom(),
        model="gemini-2.5-flash",
        registry=_registry(RecordingTool()),
        policy=ToolPolicy(),
        gate=ScriptedGate([]),
        ctx=_ctx(),
        max_steps=3,
    )
    assert events[-2].type == "error"
    assert "API キー" in events[-2].data["message"]
    assert messages[-1].role == "assistant"
