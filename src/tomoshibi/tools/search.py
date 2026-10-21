"""Web search via DuckDuckGo. No API key.

The search function is injectable so tests do not hit the network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from tomoshibi.tools.base import Tool, ToolContext, ToolResult, clip_text

SearchFn = Callable[[str, int], list[dict[str, Any]]]


def _ddg_text(query: str, max_results: int, region: str | None) -> list[dict[str, Any]]:
    from ddgs import DDGS

    kwargs: dict[str, Any] = {"max_results": max_results}
    if region:
        kwargs["region"] = region
    try:
        return list(DDGS().text(query, **kwargs) or [])
    except Exception:
        return []


def ddg_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """Search DuckDuckGo. An empty result is success; the tool tells the model that."""
    results = _ddg_text(query, max_results, "jp-jp")
    if results:
        return results
    return _ddg_text(query, max_results, None)


def format_search_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "該当する検索結果はありませんでした。"
    lines: list[str] = []
    for index, item in enumerate(results, start=1):
        title = (item.get("title") or "(無題)").strip()
        href = (item.get("href") or item.get("url") or "").strip()
        body = " ".join((item.get("body") or "").split())
        lines.append(f"{index}. {title}\n   {href}\n   {body}")
    return "\n\n".join(lines)


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "ウェブを検索する。最新情報、事実確認、調べものに使う。"
        "query には具体的な検索語を入れる。ブラウザを開く前に、まずこれで足りるか考える。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "検索語"},
            "max_results": {"type": "integer", "description": "件数。1 から 8。省略時は 5。"},
        },
        "required": ["query"],
    }

    def __init__(self, search_fn: SearchFn | None = None):
        self._search = search_fn or ddg_search

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        del ctx
        query = str(arguments["query"]).strip()
        if not query:
            return ToolResult(ok=False, content="検索語が空です。")
        max_results = arguments.get("max_results", 5)
        if not isinstance(max_results, int):
            max_results = 5
        max_results = max(1, min(8, max_results))
        try:
            results = await asyncio.to_thread(self._search, query, max_results)
        except Exception as exc:
            return ToolResult(ok=False, content=f"検索に失敗しました: {exc}")
        return ToolResult(ok=True, content=clip_text(format_search_results(results)))
