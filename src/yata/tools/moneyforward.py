"""マネーフォワード クラウド請求書のツール。請求書を作るのは確認ゲートを通す。

作った請求書は「下書き」のままにする。送付や入金状況の変更は、人がマネーフォワードの画面で行う。
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from yata.connectors.moneyforward import MoneyForwardConnector, MoneyForwardOAuthError
from yata.tools.base import Risk, Tool, ToolContext, ToolResult, clip_text

MF_BASE = "https://invoice.moneyforward.com/api/v3"
RequestFn = Callable[..., Awaitable[tuple[Any, ToolResult | None]]]
NOT_CONNECTED = "マネーフォワード クラウド請求書に接続されていません。設定画面の「連携」から接続してください。"
EXCISE = {"10%": "ten_percent", "8%（軽減）": "eight_percent_as_reduced_tax_rate", "非課税": "untaxable", "対象外": "non_taxable"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


async def mf_request(ctx: ToolContext, method: str, path: str, *, params=None, body=None) -> tuple[Any, ToolResult | None]:
    connector = ctx.connectors.get("moneyforward") if ctx.connectors is not None else None
    if not isinstance(connector, MoneyForwardConnector):
        return None, ToolResult(ok=False, content=NOT_CONNECTED)
    try:
        token = await connector.access_token()
    except MoneyForwardOAuthError as exc:
        return None, ToolResult(ok=False, content=str(exc))
    if not token:
        return None, ToolResult(ok=False, content=NOT_CONNECTED)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method, f"{MF_BASE}{path}", params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
    except httpx.HTTPError:
        return None, ToolResult(ok=False, content="マネーフォワードとの通信に失敗しました。接続を確認して再試行してください。")
    if response.status_code == 401:
        return None, ToolResult(ok=False, content="マネーフォワードの認証が切れました。設定画面から接続し直してください。")
    if response.status_code == 403:
        return None, ToolResult(ok=False, content="マネーフォワードでこの操作をする権限がありません。")
    if response.status_code == 429:
        return None, ToolResult(ok=False, content="マネーフォワード API の利用回数の上限に達しました。しばらく待ってください。")
    if response.status_code >= 400:
        detail = response.text[:300]
        for secret in connector.secrets():
            detail = detail.replace(secret, "[非表示]")
        return None, ToolResult(ok=False, content=f"マネーフォワード API エラー（{response.status_code}）: {detail}")
    return (response.json() if response.content else {}), None


def _items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get("data", [])
    return [item for item in data or [] if isinstance(item, dict)]


def _result(data: Any) -> ToolResult:
    return ToolResult(ok=True, content=clip_text(json.dumps(data, ensure_ascii=False)))


class _MfTool(Tool):
    required_connector = "moneyforward"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or mf_request


class MfListPartnersTool(_MfTool):
    name = "mf_list_partners"
    description = "マネーフォワード クラウド請求書の取引先と、その部門（請求書の宛先）の ID を取得する。請求書を作る前に使う。"
    parameters = {
        "type": "object",
        "properties": {"name": {"type": ["string", "null"], "description": "取引先名で絞りこむ（任意）"}},
    }
    risk = Risk.READ

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        params = {"per_page": 100}
        if arguments.get("name"):
            params["name"] = str(arguments["name"])[:100]
        data, error = await self._request(ctx, "GET", "/partners", params=params)
        if error:
            return error
        return _result([
            {"id": p.get("id"), "name": p.get("name"), "code": p.get("code"),
             "departments": [{"id": d.get("id"), "name": d.get("name") or d.get("person_name")}
                             for d in p.get("departments") or [] if isinstance(d, dict)]}
            for p in _items(data)
        ])


class MfListBillingsTool(_MfTool):
    name = "mf_list_billings"
    description = "マネーフォワード クラウド請求書の請求書を、請求日の範囲で取得する（日付は YYYY-MM-DD）。"
    parameters = {
        "type": "object",
        "properties": {
            "from": {"type": "string", "description": "請求日の開始 YYYY-MM-DD"},
            "to": {"type": "string", "description": "請求日の終了 YYYY-MM-DD"},
        },
        "required": ["from", "to"],
    }
    risk = Risk.READ

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        start, end = str(arguments.get("from", "")), str(arguments.get("to", ""))
        if not _DATE.match(start) or not _DATE.match(end):
            return ToolResult(ok=False, content="from と to は YYYY-MM-DD の形にしてください。")
        data, error = await self._request(
            ctx, "GET", "/billings", params={"range_key": "billing_date", "from": start, "to": end, "per_page": 100},
        )
        if error:
            return error
        keys = ("id", "billing_number", "title", "partner_name", "billing_date", "due_date",
                "total_price", "payment_status", "posting_status")
        return _result([{key: b.get(key) for key in keys} for b in _items(data)])


class MfCreateBillingTool(_MfTool):
    name = "mf_create_billing"
    description = (
        "マネーフォワード クラウド請求書に、請求書を「下書き」で作る（インボイス対応の新しい形式）。"
        "department_id は mf_list_partners で調べる。税率は品目ごとに 10% / 8%（軽減）/ 非課税 / 対象外。"
        "内容を表示し、ユーザーの確認後に作る。送付は人がマネーフォワードの画面で行う。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "department_id": {"type": "string", "description": "取引先の部門 ID"},
            "title": {"type": "string", "description": "件名"},
            "billing_date": {"type": "string", "description": "請求日 YYYY-MM-DD"},
            "due_date": {"type": "string", "description": "お支払期限 YYYY-MM-DD"},
            "items": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "price": {"type": "integer", "description": "単価（円、税抜）"},
                        "quantity": {"type": "number"},
                        "tax": {"type": "string", "enum": list(EXCISE)},
                    },
                    "required": ["name", "price", "quantity"],
                },
            },
            "note": {"type": ["string", "null"], "description": "備考（任意）"},
        },
        "required": ["department_id", "title", "billing_date", "due_date", "items"],
    }
    risk = Risk.EXTERNAL

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        for key in ("billing_date", "due_date"):
            if not _DATE.match(str(arguments.get(key, ""))):
                return ToolResult(ok=False, content=f"{key} は YYYY-MM-DD の形にしてください。")
        items = arguments.get("items")
        if not isinstance(items, list) or not items:
            return ToolResult(ok=False, content="品目を1つ以上入れてください。")
        lines = []
        for item in items:
            if not isinstance(item, dict) or type(item.get("price")) is not int:
                return ToolResult(ok=False, content="品目の単価は整数（円）にしてください。")
            lines.append({"name": str(item.get("name", ""))[:150], "price": item["price"],
                          "quantity": item.get("quantity", 1), "excise": EXCISE.get(item.get("tax") or "10%", "ten_percent")})
        body: dict[str, Any] = {
            "department_id": str(arguments["department_id"]), "title": str(arguments["title"])[:100],
            "billing_date": arguments["billing_date"], "due_date": arguments["due_date"], "items": lines,
        }
        if arguments.get("note"):
            body["note"] = str(arguments["note"])[:1000]
        data, error = await self._request(ctx, "POST", "/invoice_template_billings", body=body)
        if error:
            return error
        data = data if isinstance(data, dict) else {}
        return _result({"id": data.get("id"), "billing_number": data.get("billing_number"),
                        "total_price": data.get("total_price"), "状態": "下書き（送付はマネーフォワードの画面で）"})
