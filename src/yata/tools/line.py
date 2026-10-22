"""確認後に自分の LINE へ送信するツール。"""
from yata.line.client import LineClient, LineError
from yata.tools.base import Risk, Tool, ToolContext, ToolResult


class LinePushMessageTool(Tool):
    name = "line_push_message"
    description = "自分の LINE にメッセージを送信する。本文を表示し、確認後に送信する。"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    risk = Risk.EXTERNAL
    required_connector = "line"

    def __init__(self, client_factory=None):
        self._client_factory = client_factory or LineClient

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        connector = ctx.connectors.get("line") if ctx.connectors is not None else None
        if connector is None or not connector.owner_user_id:
            return ToolResult(ok=False, content="LINE_ALLOWED_USER_IDS に自分のユーザー ID を設定してください。")
        token = await connector.access_token()
        if not token:
            return ToolResult(ok=False, content="LINE_CHANNEL_ACCESS_TOKEN を設定してください。")
        try:
            await self._client_factory(token).send_text(connector.owner_user_id, arguments["text"])
        except LineError as exc:
            text = str(exc)
            for secret in (token, connector.channel_secret):
                if secret:
                    text = text.replace(secret, "（非表示）")
            return ToolResult(ok=False, content=text)
        except Exception:
            return ToolResult(ok=False, content="LINE への送信に失敗しました。")
        return ToolResult(ok=True, content="自分の LINE にメッセージを送信しました。")
