"""Offline provider used to exercise the real agent loop without an API key.

It is intentionally simple. The point is the loop, the tools, and the UI,
not the quality of the prose. The model picker says so.
"""

from __future__ import annotations

import re
import uuid

from tomoshibi.llm.types import LLMMessage, LLMResponse, ToolCall, ToolSpec

_URL = re.compile(r"https?://[^\s)>\]]+")


class DemoProvider:
    """Deterministic stand-in that still emits real tool calls."""

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        model: str,
    ) -> LLMResponse:
        names = {tool.name for tool in tools}
        pending = _trailing_tool_results(messages)
        if pending:
            return LLMResponse(content=_summarize(pending), tool_calls=[], model=model)

        user_text = _last_user_text(messages)
        url_match = _URL.search(user_text)

        if "save_memory" in names and any(word in user_text for word in ("覚えて", "記憶して")):
            key, value = _memory_pair(user_text)
            return _call("save_memory", {"key": key, "value": value})

        if (
            url_match
            and "browser_navigate" in names
            and any(word in user_text for word in ("開いて", "ブラウザ", "クリック"))
        ):
            return _call("browser_navigate", {"url": url_match.group(0)})

        if url_match and "fetch_page" in names:
            return _call("fetch_page", {"url": url_match.group(0)})

        if "web_search" in names and any(
            word in user_text for word in ("検索", "調べ", "ニュース", "search", "Search")
        ):
            return _call("web_search", {"query": user_text, "max_results": 5})

        return LLMResponse(
            content=(
                "デモモデルです。外部の LLM は呼んでいません。\n\n"
                "「調べて」「検索」、URL、または「覚えて」を含むメッセージで、"
                "本物のツール（検索、ページ読み取り、記憶）をこのループから呼びます。"
                "普段使いには Gemini、OpenAI、Claude、Ollama を選んでください。"
            ),
            tool_calls=[],
        )


def _call(name: str, arguments: dict) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[ToolCall(id=f"demo_{uuid.uuid4().hex[:10]}", name=name, arguments=arguments)],
    )


def _last_user_text(messages: list[LLMMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user" and not message.tool_call_id:
            return message.content or ""
    return ""


def _trailing_tool_results(messages: list[LLMMessage]) -> list[LLMMessage]:
    found: list[LLMMessage] = []
    for message in reversed(messages):
        if message.role != "tool":
            break
        found.append(message)
    found.reverse()
    return found


def _summarize(results: list[LLMMessage]) -> str:
    parts = ["デモモデルの整理です。外部の LLM は呼んでいません。", ""]
    for result in results:
        parts.append(f"【{result.name or 'tool'}】")
        parts.append(result.content or "")
        parts.append("")
    text = "\n".join(parts).strip()
    if len(text) > 6000:
        return text[:6000] + "\n…（デモモデルが省略しました）"
    return text


def _memory_pair(text: str) -> tuple[str, str]:
    body = text
    for prefix in ("覚えておいて", "覚えて", "記憶して"):
        if prefix in body:
            body = body.split(prefix, 1)[1]
            break
    body = body.strip(" 。:：,、")
    if "=" in body or "は" in body:
        separator = "=" if "=" in body else "は"
        key, value = body.split(separator, 1)
        key = key.strip(" 「」") or "memo"
        value = value.strip(" 「」。") or text
        return key[:40], value[:500]
    return "memo", text[:500]
