"""Thin REST helper shared by the Gmail and Calendar tools.

No official Google client library is used. Gmail and Calendar's v1/v3 REST
APIs are small enough that plain httpx keeps the dependency list short and
keeps tests free of a mocked google-api-python-client.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from yata.tools.base import ToolContext, ToolResult

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary"

RequestFn = Callable[..., Awaitable[tuple[dict[str, Any] | None, ToolResult | None]]]


async def google_request(
    ctx: ToolContext,
    connector_id: str,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, ToolResult | None]:
    connectors = ctx.connectors
    connector = connectors.get(connector_id) if connectors is not None else None
    if connector is None:
        return None, ToolResult(ok=False, content="この連携は使えません。")
    token = await connector.access_token()
    if token is None:
        return None, ToolResult(
            ok=False,
            content=f"{connector.label} に接続されていません。連携画面から接続してください。",
        )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        return None, ToolResult(ok=False, content=f"通信に失敗しました: {exc}")
    if response.status_code >= 400:
        return None, ToolResult(
            ok=False,
            content=f"Google API エラー（{response.status_code}）: {_error_detail(response)}",
        )
    if response.status_code == 204 or not response.content:
        return {}, None
    return response.json(), None


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        return str((body.get("error") or {}).get("message") or body)[:300]
    except ValueError:
        return response.text[:300]
