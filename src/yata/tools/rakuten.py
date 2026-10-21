"""楽天市場の商品検索とランキング（読み取り専用）。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, quote_plus

import httpx

from yata.connectors.base import ConnectorState
from yata.connectors.rakuten import RakutenConnector
from yata.tools.base import Risk, Tool, ToolContext, ToolResult, clip_text

RAKUTEN_BASE = "https://openapi.rakuten.co.jp"
SEARCH_PATH = "/ichibams/api/IchibaItem/Search/20260701"
RANKING_PATH = "/ichibaranking/api/IchibaItem/Ranking/20220601"
RequestFn = Callable[..., Awaitable[tuple[dict[str, Any] | None, ToolResult | None]]]
_request_lock = asyncio.Lock()
_last_request: float | None = None


def _safe_text(text: str, credentials: dict[str, str | None], *, hide_urls: bool = False) -> str:
    if hide_urls:
        text = re.sub(r"https?://[^\s<>\"']+", "[URL省略]", text, flags=re.IGNORECASE)
    variants = set()
    for key in ("applicationId", "accessKey", "affiliateId"):
        value = credentials.get(key)
        if value:
            variants.update({value, quote(value, safe=""), quote_plus(value),
                             json.dumps(value, ensure_ascii=False)[1:-1]})
    for variant in sorted(variants, key=len, reverse=True):
        text = text.replace(variant, "[非表示]")
    return text


async def rakuten_request(
    ctx: ToolContext, method: str, path: str, *, params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, ToolResult | None]:
    connector = ctx.connectors.get("rakuten") if ctx.connectors is not None else None
    if not isinstance(connector, RakutenConnector) or connector.status() is not ConnectorState.CONNECTED:
        return None, ToolResult(
            ok=False, content="楽天市場に接続されていません。.env の RAKUTEN_APPLICATION_ID と"
            " RAKUTEN_ACCESS_KEY を設定して Yata を再起動してください。",
        )
    credentials = connector.credentials()
    query = {**(params or {}), "applicationId": credentials["applicationId"],
             "format": "json", "formatVersion": 2}
    headers = {"accessKey": credentials["accessKey"]}
    if credentials["affiliateId"]:
        query["affiliateId"] = credentials["affiliateId"]
    if credentials["Origin"]:
        headers["Origin"] = credentials["Origin"]
    global _last_request
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # 検索とランキングで共通。並行呼び出しも開始間隔を 1 秒以上にする。
            async with _request_lock:
                if _last_request is not None:
                    delay = 1 - (time.monotonic() - _last_request)
                    if delay > 0:
                        await asyncio.sleep(delay)
                _last_request = time.monotonic()
                response = await client.request(method, f"{RAKUTEN_BASE}{path}", params=query, headers=headers)
    except httpx.HTTPError:
        return None, ToolResult(ok=False, content="楽天市場との通信に失敗しました。接続を確認して再試行してください。")
    if response.status_code == 404:
        return {"Items": [], "count": 0}, None
    if response.status_code in (401, 403):
        return None, ToolResult(
            ok=False, content="楽天市場の認証に失敗しました。IP/Origin が許可されていない可能性があります。"
            ".env の RAKUTEN_APPLICATION_ID・RAKUTEN_ACCESS_KEY・RAKUTEN_ORIGIN と許可IPを確認してください。",
        )
    if response.status_code == 429:
        return None, ToolResult(ok=False, content="楽天市場 API の利用回数の上限に達しました。1秒以上あけて再試行してください。")
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400 or (isinstance(body, dict) and ("error" in body or "errors" in body)):
        errors = body.get("errors") if isinstance(body, dict) else None
        detail = (errors.get("errorMessage") if isinstance(errors, dict) else None)
        if not detail and isinstance(body, dict):
            detail = body.get("error_description") or body.get("error")
        detail = _safe_text(str(detail or "詳細情報はありません。"), credentials, hide_urls=True)[:300]
        return None, ToolResult(ok=False, content=f"楽天市場 API エラー（{response.status_code}）: {detail}")
    if not isinstance(body, dict) or not isinstance(body.get("Items"), list):
        return None, ToolResult(ok=False, content="楽天市場 API の応答を解析できませんでした。再試行してください。")
    return body, None


def _result(data: dict[str, Any] | None, ctx: ToolContext, *, ranking: bool = False) -> ToolResult:
    items = (data or {}).get("Items", [])
    if ranking:
        items = sorted(items, key=lambda item: int(item.get("rank", 0)))
    rows = []
    for item in items:
        row = {
            "name": item.get("itemName"), "price": item.get("itemPrice"),
            "shop": item.get("shopName"), "review_average": item.get("reviewAverage"),
            "review_count": item.get("reviewCount"), "url": item.get("affiliateUrl") or item.get("itemUrl"),
        }
        if ranking:
            row = {"rank": item.get("rank"), **row}
        rows.append(row)
    content = json.dumps(rows, ensure_ascii=False)
    connector = ctx.connectors.get("rakuten") if ctx.connectors is not None else None
    if isinstance(connector, RakutenConnector):
        credentials = connector.credentials()
        content = _safe_text(content, {key: credentials[key] for key in ("applicationId", "accessKey")})
    return ToolResult(ok=True, content=clip_text(content))


class RakutenSearchItemsTool(Tool):
    name = "rakuten_search_items"
    description = "楽天市場で商品をキーワード検索し、価格・店舗・レビュー・商品 URL を取得する。"
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "検索キーワード"},
            "min_price": {"type": "integer", "description": "最低価格（円）"},
            "max_price": {"type": "integer", "description": "最高価格（円）"},
            "sort": {"type": "string", "description": "standard, +itemPrice, -itemPrice, -reviewCount, -reviewAverage, -updateTimestamp など"},
            "hits": {"type": "integer", "description": "取得件数（1〜30、既定10）"},
        },
        "required": ["keyword"],
    }
    risk = Risk.READ
    required_connector = "rakuten"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or rakuten_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        try:
            hits = int(arguments.get("hits", 10))
        except (TypeError, ValueError, OverflowError):
            hits = 10
        params = {"keyword": arguments["keyword"], "hits": max(1, min(30, hits))}
        for source, target in (("min_price", "minPrice"), ("max_price", "maxPrice")):
            if arguments.get(source) is not None:
                try:
                    params[target] = int(arguments[source])
                except (TypeError, ValueError, OverflowError):
                    label = "最低価格" if source == "min_price" else "最高価格"
                    return ToolResult(ok=False, content=f"{label}は整数で指定してください。")
        if arguments.get("sort") is not None:
            params["sort"] = arguments["sort"]
        data, error = await self._request(ctx, "GET", SEARCH_PATH, params=params)
        return error if error else _result(data, ctx)


class RakutenItemRankingTool(Tool):
    name = "rakuten_item_ranking"
    description = "楽天市場の商品ランキングを順位順に取得する。ジャンル省略時は総合ランキング。"
    parameters = {
        "type": "object",
        "properties": {"genre_id": {"type": "integer", "description": "ジャンル ID（任意）"}},
    }
    risk = Risk.READ
    required_connector = "rakuten"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or rakuten_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        params = {"genreId": arguments["genre_id"]} if arguments.get("genre_id") is not None else {}
        data, error = await self._request(ctx, "GET", RANKING_PATH, params=params)
        return error if error else _result(data, ctx, ranking=True)
