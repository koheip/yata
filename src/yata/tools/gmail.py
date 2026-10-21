"""Gmail tools. Search, read, and drafting are low risk. Sending leaves the
machine, so it is Risk.EXTERNAL and always waits on the ConfirmationGate —
there is no code path in these tools that sends without that gate running.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any

from yata.tools.base import Risk, Tool, ToolContext, ToolResult, clip_text
from yata.tools.fetch import html_to_text
from yata.tools.google_api import GMAIL_BASE, RequestFn, google_request


def _decode_part(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_text(payload: dict[str, Any]) -> str:
    mime = payload.get("mimeType", "")
    body = payload.get("body") or {}
    if mime == "text/plain" and body.get("data"):
        return _decode_part(body["data"])
    for part in payload.get("parts") or []:
        if part.get("mimeType") == "text/plain" and (part.get("body") or {}).get("data"):
            return _decode_part(part["body"]["data"])
    for part in payload.get("parts") or []:
        text = _extract_text(part)
        if text:
            return text
    if mime == "text/html" and body.get("data"):
        return html_to_text(_decode_part(body["data"]), "https://mail.google.com/")
    return ""


def _header(payload: dict[str, Any], name: str) -> str:
    for header in payload.get("headers") or []:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _format_message(message: dict[str, Any]) -> str:
    payload = message.get("payload") or {}
    subject = _header(payload, "Subject") or "(件名なし)"
    sender = _header(payload, "From")
    date = _header(payload, "Date")
    body = _extract_text(payload) or message.get("snippet", "")
    return f"件名: {subject}\n差出人: {sender}\n日付: {date}\n\n{body}"


def _build_raw_message(to: str, subject: str, body: str, cc: str | None) -> str:
    msg = MIMEText(body, _charset="utf-8")
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


class GmailSearchTool(Tool):
    name = "gmail_search"
    description = (
        "Gmail のメールを検索する。query には Gmail の検索演算子が使える"
        "（例: from:example@test.com newer_than:7d is:unread）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail の検索語"},
            "max_results": {"type": "integer", "description": "件数。1 から 10。省略時は 5。"},
        },
        "required": ["query"],
    }
    risk = Risk.READ
    required_connector = "gmail"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or google_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        query = str(arguments["query"]).strip()
        max_results = arguments.get("max_results", 5)
        if not isinstance(max_results, int):
            max_results = 5
        max_results = max(1, min(10, max_results))

        listing, error = await self._request(
            ctx, "gmail", "GET", f"{GMAIL_BASE}/messages", params={"q": query, "maxResults": max_results}
        )
        if error:
            return error
        entries = (listing or {}).get("messages") or []
        if not entries:
            return ToolResult(ok=True, content="該当するメールはありませんでした。")

        lines: list[str] = []
        for index, entry in enumerate(entries, start=1):
            message_id = entry.get("id")
            detail, detail_error = await self._request(
                ctx,
                "gmail",
                "GET",
                f"{GMAIL_BASE}/messages/{message_id}",
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
            )
            if detail_error:
                return detail_error
            payload = (detail or {}).get("payload") or {}
            subject = _header(payload, "Subject") or "(件名なし)"
            sender = _header(payload, "From")
            date = _header(payload, "Date")
            lines.append(f"{index}. {subject}\n   差出人: {sender}\n   日付: {date}\n   id: {message_id}")
        return ToolResult(ok=True, content=clip_text("\n\n".join(lines)))


class GmailReadTool(Tool):
    name = "gmail_read"
    description = "Gmail のメッセージまたはスレッドを id で読む。gmail_search で得た id を使う。"
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "メッセージまたはスレッドの ID"},
            "kind": {"type": "string", "description": "message か thread。省略時は message。"},
        },
        "required": ["id"],
    }
    risk = Risk.READ
    required_connector = "gmail"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or google_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        target_id = str(arguments["id"]).strip()
        kind = str(arguments.get("kind") or "message").strip().lower()
        if kind not in {"message", "thread"}:
            return ToolResult(ok=False, content="kind は message か thread のどちらかにしてください。")

        if kind == "message":
            data, error = await self._request(
                ctx, "gmail", "GET", f"{GMAIL_BASE}/messages/{target_id}", params={"format": "full"}
            )
            if error:
                return error
            return ToolResult(ok=True, content=clip_text(_format_message(data or {})))

        data, error = await self._request(
            ctx, "gmail", "GET", f"{GMAIL_BASE}/threads/{target_id}", params={"format": "full"}
        )
        if error:
            return error
        messages = (data or {}).get("messages") or []
        if not messages:
            return ToolResult(ok=False, content="スレッドにメッセージがありませんでした。")
        rendered = "\n\n---\n\n".join(_format_message(message) for message in messages)
        return ToolResult(ok=True, content=clip_text(rendered))


class GmailCreateDraftTool(Tool):
    name = "gmail_create_draft"
    description = "Gmail に下書きを作成する。まだ送信しない。確認なしで実行できる。"
    parameters = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "宛先のメールアドレス"},
            "subject": {"type": "string", "description": "件名"},
            "body": {"type": "string", "description": "本文"},
            "cc": {"type": "string", "description": "CC のメールアドレス（任意）"},
        },
        "required": ["to", "subject", "body"],
    }
    risk = Risk.WRITE
    required_connector = "gmail"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or google_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        to = str(arguments["to"]).strip()
        subject = str(arguments["subject"])
        body = str(arguments["body"])
        cc = arguments.get("cc")
        raw = _build_raw_message(to, subject, body, str(cc) if cc else None)
        data, error = await self._request(
            ctx, "gmail", "POST", f"{GMAIL_BASE}/drafts", json_body={"message": {"raw": raw}}
        )
        if error:
            return error
        draft_id = (data or {}).get("id", "")
        return ToolResult(ok=True, content=f"下書きを作成しました。宛先: {to}\n件名: {subject}\n下書きID: {draft_id}")


class GmailSendEmailTool(Tool):
    name = "gmail_send_email"
    description = (
        "Gmail からメールを送信する。実行前に必ずユーザー確認が入り、"
        "宛先・件名・本文を見せてから許可されたときだけ送信する。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "宛先のメールアドレス"},
            "subject": {"type": "string", "description": "件名"},
            "body": {"type": "string", "description": "本文"},
            "cc": {"type": "string", "description": "CC のメールアドレス（任意）"},
        },
        "required": ["to", "subject", "body"],
    }
    risk = Risk.EXTERNAL
    required_connector = "gmail"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or google_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        to = str(arguments["to"]).strip()
        subject = str(arguments["subject"])
        body = str(arguments["body"])
        cc = arguments.get("cc")
        raw = _build_raw_message(to, subject, body, str(cc) if cc else None)
        data, error = await self._request(
            ctx, "gmail", "POST", f"{GMAIL_BASE}/messages/send", json_body={"raw": raw}
        )
        if error:
            return error
        message_id = (data or {}).get("id", "")
        return ToolResult(ok=True, content=f"送信しました。宛先: {to}\n件名: {subject}\nメッセージID: {message_id}")
