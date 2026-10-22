"""依存を追加しない LINE Messaging API クライアント。"""
import httpx


class LineError(Exception):
    pass


def split_text(text: str, limit: int = 5000) -> list[str]:
    if limit < 1:
        raise ValueError("分割文字数は 1 以上にしてください。")
    chunks = []
    while len(text) > limit:
        end = text.rfind("\n", 0, limit) + 1
        end = end or limit
        chunks.append(text[:end])
        text = text[end:]
    if text:
        chunks.append(text)
    return chunks


def confirm_messages(confirmation_id: str, summary: str) -> list[dict]:
    actions = []
    for label, decision in (("許可する", "approve"), ("拒否する", "deny")):
        data = f"yata-confirm={confirmation_id}&d={decision}"
        if len(data) > 300:
            raise LineError("確認 ID が長すぎます。")
        actions.append(dict(type="postback", label=label, data=data, displayText=label))
    return ([{"type": "text", "text": part} for part in split_text(summary)] + [{
        "type": "template", "altText": "操作の確認", "template": {
            "type": "confirm", "text": "この操作を許可しますか？", "actions": actions,
        },
    }])


class LineClient:
    def __init__(self, access_token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._token = access_token
        self._transport = transport

    confirm_messages = staticmethod(confirm_messages)

    async def _request(self, path: str, payload: dict) -> int:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=15) as client:
                response = await client.post(
                    f"https://api.line.me/v2/bot/message/{path}", json=payload,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
        except httpx.HTTPError:
            raise LineError("LINE との通信に失敗しました。接続を確認してください。") from None
        status = response.status_code
        if status == 401:
            raise LineError("LINE のトークン無効です。LINE_CHANNEL_ACCESS_TOKEN を確認してください。")
        if status == 429:
            raise LineError("LINE の送信回数または月間利用上限に達しました。")
        if status >= 400 and not (path == "reply" and status == 400):
            raise LineError(f"LINE API エラー（{status}）が発生しました。")
        return status

    async def reply(self, reply_token: str, messages: list[dict]) -> int:
        if not 1 <= len(messages) <= 5:
            raise LineError("返信は 1～5 件のメッセージにしてください。")
        return await self._request("reply", {"replyToken": reply_token, "messages": messages})

    async def push(self, to: str, messages: list[dict]) -> int:
        status = 200
        for start in range(0, len(messages), 5):
            status = await self._request("push", {"to": to, "messages": messages[start:start + 5]})
        return status

    async def send_messages(self, to: str, messages: list[dict], reply_token: str | None = None):
        if not messages:
            return
        if reply_token:
            try:
                status = await self.reply(reply_token, messages[:5])
            except LineError:
                status = None  # reply が失敗したら、全件を push で送り直す。
            if status is not None and status != 400:
                messages = messages[5:]
        await self.push(to, messages)

    async def send_text(self, to: str, text: str, reply_token: str | None = None):
        await self.send_messages(to, [{"type": "text", "text": part} for part in split_text(text)], reply_token)
