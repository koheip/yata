"""SQLite history, facts, and the transcript the UI reloads."""

from __future__ import annotations

from pathlib import Path

from yata.llm.types import LLMMessage, ToolCall
from yata.memory.store import MemoryStore, clip_title, to_transcript
from yata.prompts import build_system_prompt


def test_conversations_messages_and_facts(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "nested" / "yata.db")
    conversation = store.create_conversation("demo")
    assert conversation.title == "新しい会話"
    store.add_message(conversation.id, LLMMessage(role="user", content="ZEN大学でAIエンジニアを目指しています"))
    store.maybe_title_from_first_message(conversation.id, "ZEN大学でAIエンジニアを目指しています")
    renamed = store.get_conversation(conversation.id)
    assert renamed is not None
    assert renamed.title.startswith("ZEN大学")

    store.add_message(
        conversation.id,
        LLMMessage(
            role="assistant",
            content="覚えます",
            tool_calls=[ToolCall(id="c1", name="save_memory", arguments={"key": "goal", "value": "AI engineer"})],
        ),
    )
    store.add_message(
        conversation.id,
        LLMMessage(
            role="tool",
            content="記憶しました",
            tool_call_id="c1",
            name="save_memory",
            artifact={"ok": True},
        ),
    )
    store.add_message(conversation.id, LLMMessage(role="assistant", content="目標を覚えました。"))
    fact = store.upsert_fact("university", "ZEN University")
    again = store.upsert_fact("university", "ZEN大学")
    assert fact.key == "university"
    assert again.value == "ZEN大学"
    assert len(store.list_facts()) == 1

    reloaded = MemoryStore(tmp_path / "nested" / "yata.db")
    messages = reloaded.list_messages(conversation.id)
    assert [item.role for item in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[1].tool_calls is not None
    assert messages[1].tool_calls[0].arguments["key"] == "goal"

    transcript = to_transcript(messages)
    assert [item["role"] for item in transcript] == ["user", "assistant"]
    steps = transcript[1]["steps"]
    assert steps[0]["type"] == "note"
    assert steps[1]["type"] == "tool"
    assert steps[1]["name"] == "save_memory"
    assert steps[1]["ok"] is True
    assert transcript[1]["content"] == "目標を覚えました。"

    assert store.delete_fact("university") is True
    assert store.delete_conversation(conversation.id) is True
    assert store.list_conversations() == []


def test_transcript_marks_denied_tools_and_clip_title() -> None:
    from yata.memory.store import StoredMessage

    stored = [
        StoredMessage(
            id="u",
            conversation_id="c",
            role="user",
            content="クリックして",
            tool_calls=None,
            tool_call_id=None,
            tool_name=None,
            artifact=None,
            created_at="t",
        ),
        StoredMessage(
            id="a",
            conversation_id="c",
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="c1", name="browser_click", arguments={"selector": "text=送信"})],
            tool_call_id=None,
            tool_name=None,
            artifact=None,
            created_at="t",
        ),
        StoredMessage(
            id="r",
            conversation_id="c",
            role="tool",
            content="ユーザーがこの操作を拒否したか、確認がタイムアウトしました。",
            tool_calls=None,
            tool_call_id="c1",
            tool_name="browser_click",
            artifact={"ok": False},
            created_at="t",
        ),
    ]
    transcript = to_transcript(stored)
    assert transcript[1]["steps"][0]["ok"] is False
    assert clip_title("  短い  ") == "短い"
    assert clip_title("あ" * 40).endswith("…")


def test_system_prompt_includes_facts() -> None:
    class Fact:
        def __init__(self, key: str, value: str):
            self.key = key
            self.value = value

    prompt = build_system_prompt([Fact("university", "ZEN大学"), Fact("goal", "AIエンジニア")])
    assert "ZEN大学" in prompt
    assert "goal: AIエンジニア" in prompt
    assert "ヤタ" in build_system_prompt([])
