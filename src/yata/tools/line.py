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


def _hide(text: str, connector, token: str) -> str:
    for secret in (token, connector.channel_secret):
        if secret:
            text = text.replace(secret, "（非表示）")
    return text


class LineBroadcastTool(Tool):
    name = "line_broadcast"
    description = (
        "LINE 公式アカウントの友だち全員に、同じメッセージを一斉配信する（お店のお知らせなど）。"
        "取り消せないので、本文を表示し、確認後に配信する。先に line_message_quota で残りの数を確かめる。"
    )
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "配信する本文（5000 文字まで）"}},
        "required": ["text"],
    }
    risk = Risk.EXTERNAL
    required_connector = "line"

    def __init__(self, client_factory=None):
        self._client_factory = client_factory or LineClient

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        connector = ctx.connectors.get("line") if ctx.connectors is not None else None
        token = await connector.access_token() if connector is not None else None
        if not token:
            return ToolResult(ok=False, content="LINE のチャネルアクセストークンを設定してください。")
        text = str(arguments.get("text") or "").strip()
        if not text or len(text) > 5000:
            return ToolResult(ok=False, content="本文は 1〜5000 文字にしてください。")
        try:
            await self._client_factory(token).broadcast([{"type": "text", "text": text}])
        except LineError as exc:
            return ToolResult(ok=False, content=_hide(str(exc), connector, token))
        except Exception:
            return ToolResult(ok=False, content="LINE の一斉配信に失敗しました。")
        return ToolResult(ok=True, content="友だち全員に一斉配信しました。")


class LineMessageQuotaTool(Tool):
    name = "line_message_quota"
    description = "LINE 公式アカウントの今月の配信の上限と、使った数を調べる。"
    parameters = {"type": "object", "properties": {}}
    risk = Risk.READ
    required_connector = "line"

    def __init__(self, client_factory=None):
        self._client_factory = client_factory or LineClient

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        connector = ctx.connectors.get("line") if ctx.connectors is not None else None
        token = await connector.access_token() if connector is not None else None
        if not token:
            return ToolResult(ok=False, content="LINE のチャネルアクセストークンを設定してください。")
        try:
            data = await self._client_factory(token).quota()
        except LineError as exc:
            return ToolResult(ok=False, content=_hide(str(exc), connector, token))
        limit = data.get("limit") or {}
        used = (data.get("used") or {}).get("totalUsage")
        if limit.get("type") == "limited":
            return ToolResult(ok=True, content=f"今月の配信: {used} 通 / 上限 {limit.get('value')} 通")
        return ToolResult(ok=True, content=f"今月の配信: {used} 通（上限なし）")
