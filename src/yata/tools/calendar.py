"""Google Calendar tools. List, search, and free/busy checks are low risk.
Create, update, and delete go through the ConfirmationGate (Risk.EXTERNAL).
"""

from __future__ import annotations

from typing import Any

from yata.tools.base import Risk, Tool, ToolContext, ToolResult, clip_text
from yata.tools.google_api import CALENDAR_BASE, RequestFn, google_request


def _format_event(event: dict[str, Any]) -> str:
    summary = event.get("summary") or "(件名なし)"
    start = (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date") or ""
    end = (event.get("end") or {}).get("dateTime") or (event.get("end") or {}).get("date") or ""
    event_id = event.get("id", "")
    return f"{summary} ({start} 〜 {end})\n   id: {event_id}"


class CalendarListEventsTool(Tool):
    name = "calendar_list_events"
    description = "Google カレンダーの予定を一覧・検索する。時刻は RFC3339（例 2026-10-22T00:00:00+09:00）。"
    parameters = {
        "type": "object",
        "properties": {
            "time_min": {"type": "string", "description": "この時刻以降の予定を探す（省略可）"},
            "time_max": {"type": "string", "description": "この時刻以前の予定を探す（省略可）"},
            "query": {"type": "string", "description": "件名や内容の検索語（省略可）"},
            "max_results": {"type": "integer", "description": "件数。1 から 20。省略時は 10。"},
        },
        "required": [],
    }
    risk = Risk.READ
    required_connector = "google_calendar"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or google_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        max_results = arguments.get("max_results", 10)
        if not isinstance(max_results, int):
            max_results = 10
        max_results = max(1, min(20, max_results))
        params: dict[str, Any] = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max_results,
        }
        if arguments.get("time_min"):
            params["timeMin"] = str(arguments["time_min"])
        if arguments.get("time_max"):
            params["timeMax"] = str(arguments["time_max"])
        if arguments.get("query"):
            params["q"] = str(arguments["query"])

        data, error = await self._request(ctx, "google_calendar", "GET", f"{CALENDAR_BASE}/events", params=params)
        if error:
            return error
        events = (data or {}).get("items") or []
        if not events:
            return ToolResult(ok=True, content="該当する予定はありませんでした。")
        lines = [f"{index}. {_format_event(event)}" for index, event in enumerate(events, start=1)]
        return ToolResult(ok=True, content=clip_text("\n".join(lines)))


class CalendarFreeBusyTool(Tool):
    name = "calendar_check_free_busy"
    description = "指定した期間の予定の有無（空き時間）を確認する。時刻は RFC3339。"
    parameters = {
        "type": "object",
        "properties": {
            "time_min": {"type": "string", "description": "期間の開始時刻"},
            "time_max": {"type": "string", "description": "期間の終了時刻"},
        },
        "required": ["time_min", "time_max"],
    }
    risk = Risk.READ
    required_connector = "google_calendar"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or google_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        time_min = str(arguments["time_min"])
        time_max = str(arguments["time_max"])
        data, error = await self._request(
            ctx,
            "google_calendar",
            "POST",
            "https://www.googleapis.com/calendar/v3/freeBusy",
            json_body={"timeMin": time_min, "timeMax": time_max, "items": [{"id": "primary"}]},
        )
        if error:
            return error
        primary = ((data or {}).get("calendars") or {}).get("primary") or {}
        calendar_errors = primary.get("errors") or []
        if calendar_errors:
            reasons = ", ".join(str(item.get("reason", "")) for item in calendar_errors)
            return ToolResult(ok=False, content=f"空き時間を確認できませんでした: {reasons}")
        busy = primary.get("busy") or []
        if not busy:
            return ToolResult(ok=True, content=f"{time_min} 〜 {time_max} は空いています。")
        lines = [f"- {slot.get('start', '')} 〜 {slot.get('end', '')}" for slot in busy]
        return ToolResult(ok=True, content="予定がある時間帯:\n" + "\n".join(lines))


class CalendarCreateEventTool(Tool):
    name = "calendar_create_event"
    description = (
        "Google カレンダーに予定を作成する。実行前にユーザー確認が入る。"
        "start/end は RFC3339 の日時（例 2026-10-22T09:00:00+09:00）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "予定の件名"},
            "start": {"type": "string", "description": "開始日時"},
            "end": {"type": "string", "description": "終了日時"},
            "description": {"type": "string", "description": "詳細（任意）"},
            "location": {"type": "string", "description": "場所（任意）"},
        },
        "required": ["summary", "start", "end"],
    }
    risk = Risk.EXTERNAL
    required_connector = "google_calendar"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or google_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        body = {
            "summary": str(arguments["summary"]),
            "start": {"dateTime": str(arguments["start"])},
            "end": {"dateTime": str(arguments["end"])},
        }
        if arguments.get("description"):
            body["description"] = str(arguments["description"])
        if arguments.get("location"):
            body["location"] = str(arguments["location"])
        data, error = await self._request(
            ctx, "google_calendar", "POST", f"{CALENDAR_BASE}/events", json_body=body
        )
        if error:
            return error
        event_id = (data or {}).get("id", "")
        return ToolResult(ok=True, content=f"予定を作成しました。{_format_event(data or {})}" if data else f"予定を作成しました。id: {event_id}")


class CalendarUpdateEventTool(Tool):
    name = "calendar_update_event"
    description = "既存の予定を更新する。実行前にユーザー確認が入る。変更する項目だけ渡す。"
    parameters = {
        "type": "object",
        "properties": {
            "event_id": {"type": "string", "description": "更新する予定の ID"},
            "summary": {"type": "string", "description": "予定の件名（任意）"},
            "start": {"type": "string", "description": "開始日時（任意）"},
            "end": {"type": "string", "description": "終了日時（任意）"},
            "description": {"type": "string", "description": "詳細（任意）"},
            "location": {"type": "string", "description": "場所（任意）"},
        },
        "required": ["event_id"],
    }
    risk = Risk.EXTERNAL
    required_connector = "google_calendar"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or google_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        event_id = str(arguments["event_id"]).strip()
        body: dict[str, Any] = {}
        if arguments.get("summary"):
            body["summary"] = str(arguments["summary"])
        if arguments.get("start"):
            body["start"] = {"dateTime": str(arguments["start"])}
        if arguments.get("end"):
            body["end"] = {"dateTime": str(arguments["end"])}
        if arguments.get("description"):
            body["description"] = str(arguments["description"])
        if arguments.get("location"):
            body["location"] = str(arguments["location"])
        if not body:
            return ToolResult(ok=False, content="更新する項目がありません。")
        data, error = await self._request(
            ctx, "google_calendar", "PATCH", f"{CALENDAR_BASE}/events/{event_id}", json_body=body
        )
        if error:
            return error
        return ToolResult(ok=True, content=f"予定を更新しました。{_format_event(data or {})}")


class CalendarDeleteEventTool(Tool):
    name = "calendar_delete_event"
    description = "予定を削除する。実行前にユーザー確認が入る。"
    parameters = {
        "type": "object",
        "properties": {"event_id": {"type": "string", "description": "削除する予定の ID"}},
        "required": ["event_id"],
    }
    risk = Risk.EXTERNAL
    required_connector = "google_calendar"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or google_request

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        event_id = str(arguments["event_id"]).strip()
        _, error = await self._request(
            ctx, "google_calendar", "DELETE", f"{CALENDAR_BASE}/events/{event_id}"
        )
        if error:
            return error
        return ToolResult(ok=True, content=f"予定を削除しました。id: {event_id}")
