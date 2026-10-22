"""kintone のレコードを読む・足すツール。書きこみは確認ゲートを通す。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from yata.connectors.base import ConnectorState
from yata.connectors.kintone import KintoneConnector
from yata.tools.base import Risk, Tool, ToolContext, ToolResult, clip_text

RequestFn = Callable[..., Awaitable[tuple[Any, ToolResult | None]]]
NOT_CONNECTED = "kintone に接続されていません。設定画面の「連携」で、URL と API トークンを入れてください。"


async def kintone_request(
    ctx: ToolContext, method: str, path: str, *,
    params: dict[str, Any] | None = None, body: dict[str, Any] | None = None,
) -> tuple[Any, ToolResult | None]:
    connector = ctx.connectors.get("kintone") if ctx.connectors is not None else None
    if not isinstance(connector, KintoneConnector) or connector.status() is not ConnectorState.CONNECTED:
        return None, ToolResult(ok=False, content=NOT_CONNECTED)
    credentials = connector.credentials()
    if credentials is None:
        return None, ToolResult(ok=False, content=NOT_CONNECTED)
    base_url, tokens = credentials
    headers = {"X-Cybozu-API-Token": tokens}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if method == "GET":
                # GET でも JSON 本文を送れるが、プロキシ越しで落ちることがあるので、上書きヘッダーで POST にする。
                response = await client.post(
                    f"{base_url}{path}", json=params or {},
                    headers={**headers, "X-HTTP-Method-Override": "GET"},
                )
            else:
                response = await client.request(method, f"{base_url}{path}", json=body or {}, headers=headers)
    except httpx.HTTPError:
        return None, ToolResult(ok=False, content="kintone との通信に失敗しました。接続を確認して再試行してください。")
    if response.status_code in (401, 403):
        return None, ToolResult(
            ok=False, content="kintone の API トークンが無効か、このアプリを使う権限がありません。"
            "アプリの設定でトークンの権限（レコード閲覧・追加・編集）を確認してください。",
        )
    if response.status_code >= 400:
        try:
            message = response.json().get("message", "")
        except (ValueError, AttributeError):
            message = ""
        detail = (message or response.text[:300])
        for token in tokens.split(","):
            detail = detail.replace(token, "[非表示]")
        return None, ToolResult(ok=False, content=f"kintone API エラー（{response.status_code}）: {detail[:300]}")
    return response.json() if response.content else {}, None


def _result(data: Any) -> ToolResult:
    return ToolResult(ok=True, content=clip_text(json.dumps(data, ensure_ascii=False)))


def _flatten(record: dict[str, Any]) -> dict[str, Any]:
    """{"会社名": {"type": ..., "value": "A社"}} を {"会社名": "A社"} にする。"""
    return {code: field.get("value") if isinstance(field, dict) else field for code, field in record.items()}


def _wrap(record: dict[str, Any]) -> dict[str, Any]:
    """{"会社名": "A社"} を kintone の形 {"会社名": {"value": "A社"}} にする。"""
    return {code: value if isinstance(value, dict) and "value" in value else {"value": value}
            for code, value in record.items()}


def _app_id(arguments: dict) -> int | None:
    app = arguments.get("app")
    return app if type(app) is int and app > 0 else None


class _KintoneTool(Tool):
    required_connector = "kintone"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or kintone_request


class KintoneGetFieldsTool(_KintoneTool):
    name = "kintone_get_fields"
    description = "kintone アプリの項目（フィールドコード・名前・種類）を取得する。レコードを探す・足す前に使う。"
    parameters = {
        "type": "object",
        "properties": {"app": {"type": "integer", "description": "アプリ ID（URL の /k/ の後ろの数字）"}},
        "required": ["app"],
    }
    risk = Risk.READ

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        app = _app_id(arguments)
        if app is None:
            return ToolResult(ok=False, content="app はアプリ ID（正の整数）にしてください。")
        data, error = await self._request(ctx, "GET", "/app/form/fields.json", params={"app": app})
        if error:
            return error
        fields = (data or {}).get("properties") or {}
        return _result([{"code": code, "label": f.get("label"), "type": f.get("type")} for code, f in fields.items()])


class KintoneGetRecordsTool(_KintoneTool):
    name = "kintone_get_records"
    description = (
        "kintone アプリのレコードを取得する。query は kintone のクエリ"
        "（例: 'ステータス in (\"未対応\") order by 更新日時 desc'）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "integer", "description": "アプリ ID"},
            "query": {"type": ["string", "null"], "description": "kintone のクエリ（任意）"},
            "limit": {"type": "integer", "description": "最大件数（1〜100、既定 20）"},
        },
        "required": ["app"],
    }
    risk = Risk.READ

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        app = _app_id(arguments)
        if app is None:
            return ToolResult(ok=False, content="app はアプリ ID（正の整数）にしてください。")
        limit = arguments.get("limit")
        limit = max(1, min(limit, 100)) if type(limit) is int else 20
        query = str(arguments.get("query") or "").strip()
        if " limit " not in f" {query.lower()} ":
            query = f"{query} limit {limit}".strip()
        data, error = await self._request(ctx, "GET", "/records.json", params={"app": app, "query": query})
        if error:
            return error
        return _result([_flatten(record) for record in (data or {}).get("records") or []])


class KintoneAddRecordTool(_KintoneTool):
    name = "kintone_add_record"
    description = (
        "kintone アプリにレコードを1件追加する。record は {フィールドコード: 値}。"
        "内容を表示し、ユーザーの確認後に追加する。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "integer", "description": "アプリ ID"},
            "record": {"type": "object", "description": "{フィールドコード: 値}"},
        },
        "required": ["app", "record"],
    }
    risk = Risk.EXTERNAL

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        app = _app_id(arguments)
        record = arguments.get("record")
        if app is None or not isinstance(record, dict) or not record:
            return ToolResult(ok=False, content="app（アプリ ID）と record（{フィールドコード: 値}）を指定してください。")
        data, error = await self._request(ctx, "POST", "/record.json", body={"app": app, "record": _wrap(record)})
        return error if error else _result({"id": (data or {}).get("id"), "revision": (data or {}).get("revision")})


class KintoneUpdateRecordTool(_KintoneTool):
    name = "kintone_update_record"
    description = (
        "kintone のレコードを1件更新する。record には変える項目だけを {フィールドコード: 値} で入れる。"
        "内容を表示し、ユーザーの確認後に更新する。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "integer", "description": "アプリ ID"},
            "id": {"type": "integer", "description": "レコード番号"},
            "record": {"type": "object", "description": "{フィールドコード: 新しい値}"},
        },
        "required": ["app", "id", "record"],
    }
    risk = Risk.EXTERNAL

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        app = _app_id(arguments)
        record_id = arguments.get("id")
        record = arguments.get("record")
        if app is None or type(record_id) is not int or not isinstance(record, dict) or not record:
            return ToolResult(ok=False, content="app・id（レコード番号）・record を指定してください。")
        data, error = await self._request(
            ctx, "PUT", "/record.json", body={"app": app, "id": record_id, "record": _wrap(record)},
        )
        return error if error else _result({"revision": (data or {}).get("revision")})
