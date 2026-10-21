"""freee accounting tools. Writes use the shared confirmation policy."""

from __future__ import annotations

import json as jsonlib
from datetime import date
from typing import Any

import httpx

from yata.connectors.freee import FreeeOAuthError
from yata.tools.base import Risk, Tool, ToolContext, ToolResult, clip_text

FREEE_BASE = "https://api.freee.co.jp/api/1"
INVOICES_URL = "https://api.freee.co.jp/iv/invoices"


async def freee_request(ctx: ToolContext, method: str, url_or_path: str, *, params=None, json=None):
    connector = ctx.connectors.get("freee") if ctx.connectors is not None else None
    try:
        token = await connector.access_token() if connector else None
    except FreeeOAuthError as exc:
        return None, ToolResult(ok=False, content=str(exc))
    if not token:
        return None, ToolResult(ok=False, content="freee に接続されていません。連携画面から再接続してください。")
    url = INVOICES_URL if url_or_path == INVOICES_URL else FREEE_BASE + url_or_path
    if not url_or_path.startswith("/") and url_or_path != INVOICES_URL:
        return None, ToolResult(ok=False, content="freee API の URL が不正です。")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(method, url, params=params, json=json,
                                            headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return None, ToolResult(ok=False, content="freee との通信に失敗しました。接続を確認して再試行してください。")
    messages = {
        401: "freee の認証が無効です。再接続してください。",
        403: "freee API を利用する権限がありません。アプリの権限を確認してください。",
        429: "freee API の利用回数の上限に達しました。しばらく待ってから再試行してください。",
    }
    if response.status_code in messages:
        return None, ToolResult(ok=False, content=messages[response.status_code])
    # Redact credentials even if an upstream server echoes them in an error or result.
    secrets = [token, getattr(connector, "_client_secret", None), getattr(connector, "_client_id", None)]
    store = getattr(connector, "_tokens", None)
    saved = store.load("freee") if store else None
    if saved:
        secrets.append(saved.refresh_token)

    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()
                    if k.lower() not in {"access_token", "refresh_token", "client_secret", "authorization"}}
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, str):
            for secret in secrets:
                if secret:
                    value = value.replace(secret, "[非表示]")
        return value

    try:
        body = clean(response.json()) if response.content else {}
    except ValueError:
        return None, ToolResult(ok=False, content="freee API の応答を読み取れませんでした。")
    if response.status_code >= 400:
        detail = (body.get("message") or body.get("errors")) if isinstance(body, dict) else None
        detail = detail or "処理に失敗しました。"
        return None, ToolResult(ok=False, content=f"freee API エラー（{response.status_code}）: {str(detail)[:300]}")
    return body, None


def _schema(properties=None, required=None):
    return {"type": "object", "properties": properties or {}, "required": required or []}


COMPANY = {"company_id": {"type": "integer", "description": "事業所 ID"}}
DATES = {"start_date": {"type": "string", "description": "開始日 YYYY-MM-DD"},
         "end_date": {"type": "string", "description": "終了日 YYYY-MM-DD"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}}


class _FreeeTool(Tool):
    required_connector = "freee"
    risk = Risk.READ

    def __init__(self, request_fn=None):
        self._request = request_fn or freee_request

    async def _call(self, ctx, method, path, *, params=None, json=None, collection=None, keys=None):
        data, error = await self._request(ctx, method, path, params=params, json=json)
        if error:
            return error
        if collection:
            data = (data or {}).get(collection, [])
        if keys:
            data = [{key: row.get(key) for key in keys} for row in data or []]
        return ToolResult(ok=True, content=clip_text(jsonlib.dumps(data, ensure_ascii=False)))


class FreeeListCompaniesTool(_FreeeTool):
    name = "freee_list_companies"
    description = "freee の事業所一覧を取得する。"
    parameters = _schema()

    async def run(self, arguments, ctx):
        return await self._call(ctx, "GET", "/companies", collection="companies")


class FreeeListAccountItemsTool(_FreeeTool):
    name = "freee_list_account_items"
    description = "freee の勘定科目と既定の税区分を取得する。"
    parameters = _schema(COMPANY, ["company_id"])

    async def run(self, arguments, ctx):
        return await self._call(ctx, "GET", "/account_items", params={"company_id": arguments["company_id"]},
                                collection="account_items", keys=("id", "name", "default_tax_code", "account_category"))


class FreeeListDealsTool(_FreeeTool):
    name = "freee_list_deals"
    description = "freee の取引一覧を期間・収支区分で取得する。"
    parameters = _schema({**COMPANY, **DATES, "type": {"type": "string", "enum": ["income", "expense"]}}, ["company_id"])
    path = "/deals"
    collection = "deals"
    date_keys = ("start_issue_date", "end_issue_date")

    async def run(self, arguments, ctx):
        limit = arguments.get("limit", 50)
        if type(limit) is not int or not 1 <= limit <= 100:
            return ToolResult(ok=False, content="取得件数は 1〜100 の整数にしてください。")
        params = {"company_id": arguments["company_id"], "limit": limit}
        for source, target in zip(("start_date", "end_date"), self.date_keys):
            if arguments.get(source) is not None:
                params[target] = arguments[source]
        if self.collection == "deals" and arguments.get("type") is not None:
            if arguments["type"] not in ("income", "expense"):
                return ToolResult(ok=False, content="収支区分は income または expense にしてください。")
            params["type"] = arguments["type"]
        return await self._call(ctx, "GET", self.path, params=params, collection=self.collection)


class FreeeListInvoicesTool(FreeeListDealsTool):
    name = "freee_list_invoices"
    description = "freee 請求書の請求書一覧を取得する。"
    parameters = _schema({**COMPANY, **DATES}, ["company_id"])
    path = INVOICES_URL
    collection = "invoices"
    date_keys = ("billing_date_start", "billing_date_end")


class FreeeGetTrialBalanceTool(_FreeeTool):
    name = "freee_get_trial_balance"
    description = "freee の損益計算書の試算表を簡潔に取得する。"
    parameters = _schema({**COMPANY, "fiscal_year": {"type": "integer", "description": "会計年度"}}, ["company_id"])

    async def run(self, arguments, ctx):
        params = {key: arguments[key] for key in ("company_id", "fiscal_year") if arguments.get(key) is not None}
        data, error = await self._request(ctx, "GET", "/reports/trial_pl", params=params)
        if error:
            return error
        rows = (data or {}).get("trial_pl", {}).get("balances", [])
        summary = [{"name": row.get("account_item_name") or row.get("account_category_name"),
                    "closing_balance": row.get("closing_balance")} for row in rows]
        return ToolResult(ok=True, content=clip_text(jsonlib.dumps(summary, ensure_ascii=False)))


class FreeeCreateExpenseDealTool(_FreeeTool):
    name = "freee_create_expense_deal"
    description = "freee に支出取引を登録する。内容を表示し、ユーザーの確認後に登録する。"
    risk = Risk.EXTERNAL
    parameters = _schema({**COMPANY,
        "issue_date": {"type": "string", "description": "発生日 YYYY-MM-DD"},
        "amount": {"type": "integer", "minimum": 1, "description": "金額（円）"},
        "account_item_id": {"type": "integer", "description": "勘定科目 ID"},
        "tax_code": {"type": "integer", "description": "税区分コード"},
        "description": {"type": "string", "description": "内容"},
        "partner_id": {"type": "integer", "description": "取引先 ID（任意）"},
    }, ["company_id", "issue_date", "amount", "account_item_id", "tax_code", "description"])

    async def run(self, arguments, ctx):
        if type(arguments.get("amount")) is not int or arguments["amount"] <= 0:
            return ToolResult(ok=False, content="金額は 1 円以上の整数にしてください。")
        try:
            value = arguments["issue_date"]
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return ToolResult(ok=False, content="発生日は YYYY-MM-DD 形式の有効な日付にしてください。")
        body = {"company_id": arguments["company_id"], "issue_date": value, "type": "expense",
                "details": [{key: arguments[key] for key in ("account_item_id", "tax_code", "amount", "description")}]}
        if arguments.get("partner_id") is not None:
            body["partner_id"] = arguments["partner_id"]
        return await self._call(ctx, "POST", "/deals", json=body)
