"""Chatwork tools. External operations use the shared ConfirmationGate."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from yata.tools.base import Risk, Tool, ToolContext, ToolResult, clip_text

CHATWORK_BASE = "https://api.chatwork.com/v2"
RequestFn = Callable[..., Awaitable[tuple[dict[str, Any] | list[Any] | None, ToolResult | None]]]


async def chatwork_request(
    ctx: ToolContext,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | list[Any] | None, ToolResult | None]:
    connector = ctx.connectors.get("chatwork") if ctx.connectors is not None else None
    token = await connector.access_token() if connector is not None else None
    if not token:
        return None, ToolResult(
            ok=False,
            content="Chatwork に接続されていません。.env の CHATWORK_API_TOKEN を設定して Yata を再起動してください。",
        )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(
                method, f"{CHATWORK_BASE}{path}", params=params, data=data,
                headers={"X-ChatWorkToken": token},
            )
    except httpx.HTTPError:
        return None, ToolResult(ok=False, content="Chatwork との通信に失敗しました。接続を確認して再試行してください。")
    if response.status_code == 401:
        return None, ToolResult(
            ok=False, content="Chatwork の API トークンが無効です。.env の CHATWORK_API_TOKEN を確認してください。",
        )
    if response.status_code == 429:
        return None, ToolResult(
            ok=False, content="Chatwork API の利用回数の上限に達しました。しばらく待ってから再試行してください。",
        )
    if response.status_code >= 400:
        try:
            body = response.json()
            errors = body.get("errors") if isinstance(body, dict) else None
            detail = "; ".join(str(error) for error in errors) if isinstance(errors, list) else response.text
        except ValueError:
            detail = response.text
        return None, ToolResult(ok=False, content=f"Chatwork API エラー（{response.status_code}）: {detail[:300]}")
    if response.status_code == 204 or not response.content:
        return ([] if method.upper() == "GET" else {}), None
    return response.json(), None


def _result(data: Any) -> ToolResult:
    return ToolResult(ok=True, content=clip_text(json.dumps(data, ensure_ascii=False)))


class ChatworkListRoomsTool(Tool):
    name = "chatwork_list_rooms"
    description = "Chatwork の参加ルーム一覧と未読数・メンション数を取得する。"
    parameters = {"type": "object", "properties": {}}
    risk = Risk.READ
    required_connector = "chatwork"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or chatwork_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        data, error = await self._request(ctx, "GET", "/rooms")
        if error:
            return error
        keys = ("room_id", "name", "type", "unread_num", "mention_num")
        return _result([{key: room.get(key) for key in keys} for room in data or []])


class ChatworkGetMessagesTool(Tool):
    name = "chatwork_get_messages"
    description = "Chatwork のルームのメッセージを取得する。force=true で既読分も取得する。"
    parameters = {
        "type": "object",
        "properties": {
            "room_id": {"type": "integer", "description": "ルーム ID"},
            "force": {"type": "boolean", "description": "既読分も取得する。省略時は false。"},
        },
        "required": ["room_id"],
    }
    risk = Risk.READ
    required_connector = "chatwork"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or chatwork_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        data, error = await self._request(
            ctx, "GET", f"/rooms/{arguments['room_id']}/messages",
            params={"force": 1 if arguments.get("force", False) else 0},
        )
        if error:
            return error
        return _result([
            {"message_id": message.get("message_id"), "account_name": (message.get("account") or {}).get("name"),
             "body": message.get("body"), "send_time": message.get("send_time")}
            for message in data or []
        ])


class ChatworkListMyTasksTool(Tool):
    name = "chatwork_list_my_tasks"
    description = "Chatwork の自分の未完了タスクを取得する。"
    parameters = {"type": "object", "properties": {}}
    risk = Risk.READ
    required_connector = "chatwork"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or chatwork_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        data, error = await self._request(ctx, "GET", "/my/tasks", params={"status": "open"})
        return error if error else _result(data or [])


class ChatworkSendMessageTool(Tool):
    name = "chatwork_send_message"
    description = "Chatwork のルームにメッセージを送信する。ルームと本文を表示し、ユーザーの確認後に送信する。"
    parameters = {
        "type": "object",
        "properties": {
            "room_id": {"type": "integer", "description": "送信先ルーム ID"},
            "body": {"type": "string", "description": "送信する本文"},
        },
        "required": ["room_id", "body"],
    }
    risk = Risk.EXTERNAL
    required_connector = "chatwork"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or chatwork_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        data, error = await self._request(
            ctx, "POST", f"/rooms/{arguments['room_id']}/messages", data={"body": arguments["body"]},
        )
        return error if error else _result(data or {})


class ChatworkCreateTaskTool(Tool):
    name = "chatwork_create_task"
    description = "Chatwork のルームにタスクを作成する。ルーム・本文・担当者・期限を表示し、ユーザーの確認後に作成する。"
    parameters = {
        "type": "object",
        "properties": {
            "room_id": {"type": "integer", "description": "ルーム ID"},
            "body": {"type": "string", "description": "タスクの本文"},
            "to_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "description": "担当者のアカウント ID 一覧"},
            "limit": {"type": ["integer", "null"], "description": "期限の Unix 秒（任意）"},
        },
        "required": ["room_id", "body", "to_ids"],
    }
    risk = Risk.EXTERNAL
    required_connector = "chatwork"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or chatwork_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        to_ids = arguments["to_ids"]
        if not isinstance(to_ids, list) or not to_ids or any(type(value) is not int for value in to_ids):
            return ToolResult(ok=False, content="to_ids は担当者 ID（整数）の空でない一覧にしてください。")
        limit = arguments.get("limit")
        if limit is not None and type(limit) is not int:
            return ToolResult(ok=False, content="limit は期限の Unix 秒（整数）にしてください。")
        form = {"body": arguments["body"], "to_ids": ",".join(str(value) for value in to_ids)}
        if limit is not None:
            form["limit"] = limit
        data, error = await self._request(ctx, "POST", f"/rooms/{arguments['room_id']}/tasks", data=form)
        return error if error else _result(data or {})
