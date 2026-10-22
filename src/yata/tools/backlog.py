"""Backlog の課題を読む・足すツール。外に書きこむ操作は確認ゲートを通す。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from yata.connectors.backlog import BacklogConnector
from yata.connectors.base import ConnectorState
from yata.tools.base import Risk, Tool, ToolContext, ToolResult, clip_text

RequestFn = Callable[..., Awaitable[tuple[Any, ToolResult | None]]]
NOT_CONNECTED = "Backlog に接続されていません。設定画面の「連携」で、スペースの URL と API キーを入れてください。"


async def backlog_request(
    ctx: ToolContext, method: str, path: str, *,
    params: dict[str, Any] | list[tuple[str, Any]] | None = None,
    data: dict[str, Any] | list[tuple[str, Any]] | None = None,
) -> tuple[Any, ToolResult | None]:
    connector = ctx.connectors.get("backlog") if ctx.connectors is not None else None
    if not isinstance(connector, BacklogConnector) or connector.status() is not ConnectorState.CONNECTED:
        return None, ToolResult(ok=False, content=NOT_CONNECTED)
    credentials = connector.credentials()
    if credentials is None:
        return None, ToolResult(ok=False, content=NOT_CONNECTED)
    base_url, api_key = credentials
    query = list(params.items()) if isinstance(params, dict) else list(params or [])
    query.append(("apiKey", api_key))
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(method, f"{base_url}{path}", params=query, data=data)
    except httpx.HTTPError:
        return None, ToolResult(ok=False, content="Backlog との通信に失敗しました。接続を確認して再試行してください。")
    if response.status_code in (401, 403):
        return None, ToolResult(ok=False, content="Backlog の API キーが無効か、権限がありません。")
    if response.status_code == 429:
        return None, ToolResult(ok=False, content="Backlog API の利用回数の上限に達しました。しばらく待ってから再試行してください。")
    if response.status_code >= 400:
        try:
            errors = response.json().get("errors") or []
            detail = "; ".join(str(error.get("message", "")) for error in errors if isinstance(error, dict))
        except (ValueError, AttributeError):
            detail = ""
        detail = (detail or response.text[:300]).replace(api_key, "[非表示]")
        return None, ToolResult(ok=False, content=f"Backlog API エラー（{response.status_code}）: {detail[:300]}")
    if not response.content:
        return {}, None
    return response.json(), None


def _result(data: Any) -> ToolResult:
    return ToolResult(ok=True, content=clip_text(json.dumps(data, ensure_ascii=False)))


def _name(value: Any) -> Any:
    return value.get("name") if isinstance(value, dict) else None


def _issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "issueKey": issue.get("issueKey"), "id": issue.get("id"), "summary": issue.get("summary"),
        "status": _name(issue.get("status")), "priority": _name(issue.get("priority")),
        "assignee": _name(issue.get("assignee")), "dueDate": issue.get("dueDate"),
        "updated": issue.get("updated"),
    }


class _BacklogTool(Tool):
    required_connector = "backlog"

    def __init__(self, request_fn: RequestFn | None = None):
        self._request = request_fn or backlog_request


class BacklogListProjectsTool(_BacklogTool):
    name = "backlog_list_projects"
    description = "Backlog の参加プロジェクトと、各プロジェクトの課題の種別を取得する。課題を追加する前に使う。"
    parameters = {"type": "object", "properties": {}}
    risk = Risk.READ

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        projects, error = await self._request(ctx, "GET", "/projects")
        if error:
            return error
        result = []
        for project in (projects or [])[:20]:
            types, error = await self._request(ctx, "GET", f"/projects/{project.get('id')}/issueTypes")
            result.append({
                "id": project.get("id"), "projectKey": project.get("projectKey"), "name": project.get("name"),
                "issueTypes": [{"id": t.get("id"), "name": t.get("name")} for t in types or []] if not error else [],
            })
        return _result(result)


class BacklogSearchIssuesTool(_BacklogTool):
    name = "backlog_search_issues"
    description = (
        "Backlog の課題を探す。mine=true で自分が担当の課題、open_only=true（既定）で未完了だけ。"
        "keyword で件名や詳細を検索する。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "project_id": {"type": ["integer", "null"], "description": "プロジェクト ID（任意）"},
            "keyword": {"type": ["string", "null"], "description": "検索語（任意）"},
            "mine": {"type": "boolean", "description": "自分が担当の課題だけにする"},
            "open_only": {"type": "boolean", "description": "未完了の課題だけにする。既定は true"},
            "count": {"type": "integer", "description": "最大件数（1〜100、既定 20）"},
        },
    }
    risk = Risk.READ

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        params: list[tuple[str, Any]] = [("sort", "updated"), ("order", "desc")]
        count = arguments.get("count") or 20
        params.append(("count", max(1, min(int(count), 100)) if type(count) is int else 20))
        if type(arguments.get("project_id")) is int:
            params.append(("projectId[]", arguments["project_id"]))
        if arguments.get("keyword"):
            params.append(("keyword", str(arguments["keyword"])[:100]))
        if arguments.get("open_only", True):
            params += [("statusId[]", 1), ("statusId[]", 2), ("statusId[]", 3)]  # 未対応・処理中・処理済み
        if arguments.get("mine"):
            me, error = await self._request(ctx, "GET", "/users/myself")
            if error:
                return error
            params.append(("assigneeId[]", me.get("id")))
        issues, error = await self._request(ctx, "GET", "/issues", params=params)
        return error if error else _result([_issue(issue) for issue in issues or []])


class BacklogAddIssueTool(_BacklogTool):
    name = "backlog_add_issue"
    description = (
        "Backlog に課題を追加する。project_id と issue_type_id は backlog_list_projects で調べる。"
        "内容を表示し、ユーザーの確認後に追加する。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "project_id": {"type": "integer", "description": "プロジェクト ID"},
            "issue_type_id": {"type": "integer", "description": "課題の種別 ID"},
            "summary": {"type": "string", "description": "件名"},
            "description": {"type": ["string", "null"], "description": "詳細（任意）"},
            "due_date": {"type": ["string", "null"], "description": "期限日 YYYY-MM-DD（任意）"},
            "priority": {"type": "string", "enum": ["高", "中", "低"], "description": "優先度。既定は中"},
        },
        "required": ["project_id", "issue_type_id", "summary"],
    }
    risk = Risk.EXTERNAL

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        priority = {"高": 2, "中": 3, "低": 4}.get(arguments.get("priority") or "中", 3)
        form: dict[str, Any] = {
            "projectId": arguments["project_id"], "issueTypeId": arguments["issue_type_id"],
            "summary": arguments["summary"], "priorityId": priority,
        }
        if arguments.get("description"):
            form["description"] = arguments["description"]
        if arguments.get("due_date"):
            form["dueDate"] = arguments["due_date"]
        issue, error = await self._request(ctx, "POST", "/issues", data=form)
        return error if error else _result(_issue(issue or {}))


class BacklogAddCommentTool(_BacklogTool):
    name = "backlog_add_comment"
    description = "Backlog の課題にコメントを書く。課題キー（例: PROJ-12）と本文を表示し、ユーザーの確認後に書く。"
    parameters = {
        "type": "object",
        "properties": {
            "issue_key": {"type": "string", "description": "課題キー（例: PROJ-12）"},
            "content": {"type": "string", "description": "コメントの本文"},
        },
        "required": ["issue_key", "content"],
    }
    risk = Risk.EXTERNAL

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        key = str(arguments["issue_key"]).strip()
        if not key or "/" in key or "?" in key:
            return ToolResult(ok=False, content="issue_key は「PROJ-12」のような課題キーにしてください。")
        comment, error = await self._request(ctx, "POST", f"/issues/{key}/comments", data={"content": arguments["content"]})
        if error:
            return error
        return _result({"id": (comment or {}).get("id"), "created": (comment or {}).get("created")})
