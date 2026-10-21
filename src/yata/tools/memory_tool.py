"""Let the agent write a durable fact about the user."""

from __future__ import annotations

from yata.tools.base import Risk, Tool, ToolContext, ToolResult


class SaveMemoryTool(Tool):
    name = "save_memory"
    description = (
        "ユーザーについて今後も使う事実を記憶する。"
        "key は短い項目名（name, university, goal など）、value はその内容。"
        "その場限りの質問や、ツールの検索結果は記憶しない。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "短い項目名。英数字とハイフン推奨。"},
            "value": {"type": "string", "description": "覚える内容"},
        },
        "required": ["key", "value"],
    }
    risk = Risk.WRITE

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        key = str(arguments["key"]).strip()
        value = str(arguments["value"]).strip()
        if not key or not value:
            return ToolResult(ok=False, content="key と value の両方が必要です。")
        if len(key) > 40 or len(value) > 500:
            return ToolResult(ok=False, content="key は 40 文字、value は 500 文字までです。")
        ctx.memory.upsert_fact(key, value)
        return ToolResult(ok=True, content=f"記憶しました。{key}: {value}")
