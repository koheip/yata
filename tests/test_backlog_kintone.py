"""Backlog と kintone の連携とツール。通信はすべてモックにする。"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest

from yata.connectors.backlog import BacklogConnector, normalize_space
from yata.connectors.base import ConnectorRegistry, ConnectorState
from yata.connectors.kintone import KintoneConnector, clean_tokens, normalize_domain
from yata.tools.backlog import (
    BacklogAddCommentTool,
    BacklogAddIssueTool,
    BacklogListProjectsTool,
    BacklogSearchIssuesTool,
)
from yata.tools.base import Risk, ToolContext
from yata.tools.catalog import build_registry, visible_registry
from yata.tools.kintone import (
    KintoneAddRecordTool,
    KintoneGetFieldsTool,
    KintoneGetRecordsTool,
    KintoneUpdateRecordTool,
)
from yata.tools.policy import describe_action

BACKLOG_KEY = "test-backlog-secret-key"
KINTONE_TOKEN = "test-kintone-token-a"


def ok_me(request):
    return httpx.Response(200, json={"id": 7, "name": "テスト花子"})


def backlog_connector(handler=ok_me):
    return BacklogConnector("https://example.backlog.jp/dashboard", BACKLOG_KEY,
                            transport=httpx.MockTransport(handler))


@pytest.fixture
def mock_http(monkeypatch):
    client_type = httpx.AsyncClient
    requests = []

    def install(module, handler):
        def wrapped(request):
            requests.append(request)
            return handler(request)

        transport = httpx.MockTransport(wrapped)
        monkeypatch.setattr(f"{module}.httpx.AsyncClient", lambda **kw: client_type(transport=transport, **kw))
        return requests

    return install


def ctx_with(*connectors):
    registry = ConnectorRegistry()
    for connector in connectors:
        registry.register(connector)
    return ToolContext("conv", None, None, None, True, connectors=registry)


# --- Backlog ---------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("https://example.backlog.jp/dashboard", "example.backlog.jp"),
    ("Example.Backlog.com", "example.backlog.com"),
    ("https://evil.example.com", None),
    ("https://example.backlog.jp.evil.com", None),
    ("", None),
])
def test_normalize_space(value, expected):
    assert normalize_space(value) == expected


def test_backlog_status_checks_the_key_once():
    calls = []

    def handler(request):
        calls.append(request)
        return ok_me(request)

    connector = backlog_connector(handler)
    assert connector.status() is ConnectorState.CONNECTED
    assert connector.status() is ConnectorState.CONNECTED
    assert len(calls) == 1 and calls[0].url.host == "example.backlog.jp"
    assert connector.status_note() == "API キー確認済み（テスト花子）"


def test_backlog_invalid_key_is_not_connected():
    connector = backlog_connector(lambda request: httpx.Response(401))
    assert connector.status() is ConnectorState.NOT_CONNECTED
    assert BACKLOG_KEY not in (connector.status_note() or "")


def test_backlog_needs_both_values():
    assert BacklogConnector(None, BACKLOG_KEY).status() is ConnectorState.NOT_CONFIGURED
    assert BacklogConnector("https://evil.example.com", BACKLOG_KEY).status() is ConnectorState.NOT_CONFIGURED


async def test_backlog_search_mine_open(mock_http):
    def handler(request):
        if request.url.path.endswith("/users/myself"):
            return ok_me(request)
        return httpx.Response(200, json=[{"issueKey": "P-1", "id": 1, "summary": "見積もり",
                                          "status": {"name": "未対応"}, "assignee": {"name": "テスト花子"}}])

    requests = mock_http("yata.tools.backlog", handler)
    connector = backlog_connector()
    result = await BacklogSearchIssuesTool().run({"mine": True}, ctx_with(connector))
    assert result.ok and "P-1" in result.content and BACKLOG_KEY not in result.content
    query = parse_qs(requests[-1].url.query.decode())
    assert query["assigneeId[]"] == ["7"] and query["statusId[]"] == ["1", "2", "3"]
    assert query["apiKey"] == [BACKLOG_KEY]


async def test_backlog_add_issue_posts_form(mock_http):
    requests = mock_http("yata.tools.backlog", lambda r: httpx.Response(201, json={"issueKey": "P-2", "summary": "請求書"}))
    result = await BacklogAddIssueTool().run(
        {"project_id": 3, "issue_type_id": 9, "summary": "請求書", "priority": "高", "due_date": "2026-11-30"},
        ctx_with(backlog_connector()),
    )
    assert result.ok and "P-2" in result.content
    form = parse_qs(requests[-1].content.decode())
    assert form == {"projectId": ["3"], "issueTypeId": ["9"], "summary": ["請求書"], "priorityId": ["2"],
                    "dueDate": ["2026-11-30"]}


async def test_backlog_error_hides_the_key(mock_http):
    mock_http("yata.tools.backlog", lambda r: httpx.Response(400, text=f"bad apiKey={BACKLOG_KEY}"))
    result = await BacklogAddCommentTool().run({"issue_key": "P-1", "content": "了解です"}, ctx_with(backlog_connector()))
    assert not result.ok and BACKLOG_KEY not in result.content


async def test_backlog_comment_rejects_odd_keys():
    result = await BacklogAddCommentTool().run({"issue_key": "../x", "content": "a"}, ctx_with(backlog_connector()))
    assert not result.ok


async def test_backlog_list_projects_includes_issue_types(mock_http):
    def handler(request):
        if request.url.path.endswith("/issueTypes"):
            return httpx.Response(200, json=[{"id": 9, "name": "タスク"}])
        return httpx.Response(200, json=[{"id": 3, "projectKey": "P", "name": "社内"}])

    mock_http("yata.tools.backlog", handler)
    result = await BacklogListProjectsTool().run({}, ctx_with(backlog_connector()))
    assert json.loads(result.content) == [{"id": 3, "projectKey": "P", "name": "社内",
                                           "issueTypes": [{"id": 9, "name": "タスク"}]}]


# --- kintone ---------------------------------------------------------------

def kintone_connector():
    return KintoneConnector("https://example.cybozu.com/k/12/", f"{KINTONE_TOKEN}、 test-kintone-token-b")


def test_kintone_values():
    assert normalize_domain("https://Example.cybozu.com/k/1/") == "example.cybozu.com"
    assert normalize_domain("https://example.com") is None
    assert clean_tokens(" a , b、c ,") == "a,b,c"
    connector = kintone_connector()
    assert connector.status() is ConnectorState.CONNECTED
    assert connector.status_note() == "example.cybozu.com（API トークン 2 個）"
    assert KintoneConnector("https://example.com", "t").status() is ConnectorState.NOT_CONFIGURED


async def test_kintone_get_records_uses_override_and_flattens(mock_http):
    requests = mock_http("yata.tools.kintone", lambda r: httpx.Response(200, json={
        "records": [{"会社名": {"type": "SINGLE_LINE_TEXT", "value": "A社"}, "$id": {"value": "5"}}]}))
    result = await KintoneGetRecordsTool().run({"app": 12, "query": "order by 更新日時 desc"}, ctx_with(kintone_connector()))
    assert json.loads(result.content) == [{"会社名": "A社", "$id": "5"}]
    request = requests[-1]
    assert request.method == "POST" and request.headers["X-HTTP-Method-Override"] == "GET"
    assert request.headers["X-Cybozu-API-Token"] == f"{KINTONE_TOKEN},test-kintone-token-b"
    assert json.loads(request.content) == {"app": 12, "query": "order by 更新日時 desc limit 20"}


async def test_kintone_add_record_wraps_values(mock_http):
    requests = mock_http("yata.tools.kintone", lambda r: httpx.Response(200, json={"id": "8", "revision": "1"}))
    result = await KintoneAddRecordTool().run({"app": 12, "record": {"会社名": "B社"}}, ctx_with(kintone_connector()))
    assert result.ok
    assert json.loads(requests[-1].content) == {"app": 12, "record": {"会社名": {"value": "B社"}}}


async def test_kintone_error_hides_tokens(mock_http):
    mock_http("yata.tools.kintone", lambda r: httpx.Response(400, json={"message": f"token {KINTONE_TOKEN} bad"}))
    result = await KintoneUpdateRecordTool().run({"app": 12, "id": 1, "record": {"a": 1}}, ctx_with(kintone_connector()))
    assert not result.ok and KINTONE_TOKEN not in result.content


async def test_kintone_rejects_bad_app():
    result = await KintoneGetFieldsTool().run({"app": "12"}, ctx_with(kintone_connector()))
    assert not result.ok


# --- 共通 ------------------------------------------------------------------

def test_risks_and_visibility():
    assert BacklogSearchIssuesTool.risk is Risk.READ and BacklogAddIssueTool.risk is Risk.EXTERNAL
    assert BacklogAddCommentTool.risk is Risk.EXTERNAL
    assert KintoneGetRecordsTool.risk is Risk.READ
    assert KintoneAddRecordTool.risk is Risk.EXTERNAL and KintoneUpdateRecordTool.risk is Risk.EXTERNAL
    hidden = visible_registry(build_registry(), ctx_with(BacklogConnector(None, None), KintoneConnector(None, None)).connectors)
    assert not any(name.startswith(("backlog_", "kintone_")) for name in hidden.names())
    shown = visible_registry(build_registry(), ctx_with(backlog_connector(), kintone_connector()).connectors)
    assert "backlog_add_issue" in shown.names() and "kintone_add_record" in shown.names()


def test_confirmation_text_shows_the_content():
    text = describe_action(KintoneAddRecordTool(), {"app": 12, "record": {"会社名": "B社"}})
    assert "会社名: B社" in text
    text = describe_action(BacklogAddCommentTool(), {"issue_key": "P-1", "content": "了解です"})
    assert "P-1" in text and "了解です" in text
