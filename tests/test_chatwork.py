"""Chatwork connector and tools; all HTTP calls use a mock transport."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from yata.connectors.base import ConnectorRegistry, ConnectorState
from yata.connectors.chatwork import ChatworkConnector
from yata.tools.base import Risk, ToolContext
from yata.tools.catalog import build_registry, visible_registry
from yata.tools.chatwork import (
    ChatworkCreateTaskTool,
    ChatworkGetMessagesTool,
    ChatworkListMyTasksTool,
    ChatworkListRoomsTool,
    ChatworkSendMessageTool,
    chatwork_request,
)
from yata.tools.policy import ToolPolicy, describe_action


TOKEN = "test-chatwork-secret-token"
TOOL_TYPES = (
    ChatworkListRoomsTool,
    ChatworkGetMessagesTool,
    ChatworkListMyTasksTool,
    ChatworkSendMessageTool,
    ChatworkCreateTaskTool,
)


def context(token=TOKEN):
    connectors = ConnectorRegistry()
    connectors.register(ChatworkConnector(token))
    return ToolContext("conv", None, None, None, True, connectors=connectors)


@pytest.fixture
def mock_http(monkeypatch):
    client_type = httpx.AsyncClient

    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            "yata.tools.chatwork.httpx.AsyncClient",
            lambda **kwargs: client_type(transport=transport, **kwargs),
        )

    return install


@pytest.mark.parametrize("token", [None, "", "  ", TOKEN])
async def test_connector_status_and_disconnect(token) -> None:
    connector = ChatworkConnector(token)
    expected = ConnectorState.CONNECTED if token == TOKEN else ConnectorState.NOT_CONFIGURED
    assert connector.status() is expected
    assert connector.auth_kind == "token"
    assert await connector.access_token() == (TOKEN if token == TOKEN else None)
    assert connector.disconnect() is False


@pytest.mark.parametrize("token", [None, "", "  ", TOKEN])
def test_visible_registry_requires_a_token(token) -> None:
    base = build_registry()
    names = {tool.name for tool in (tool_type() for tool_type in TOOL_TYPES)}
    visible = set(visible_registry(base, context(token).connectors).names())
    assert visible & names == (names if token == TOKEN else set())
    assert not (set(visible_registry(base, None).names()) & names)


@pytest.mark.parametrize(
    "tool_type, arguments, method, path, query, form",
    [
        (ChatworkListRoomsTool, {}, "GET", "/rooms", {}, {}),
        (ChatworkGetMessagesTool, {"room_id": 123}, "GET", "/rooms/123/messages", {"force": "0"}, {}),
        (ChatworkGetMessagesTool, {"room_id": 123, "force": False}, "GET", "/rooms/123/messages", {"force": "0"}, {}),
        (ChatworkGetMessagesTool, {"room_id": 123, "force": True}, "GET", "/rooms/123/messages", {"force": "1"}, {}),
        (ChatworkListMyTasksTool, {}, "GET", "/my/tasks", {"status": "open"}, {}),
        (ChatworkSendMessageTool, {"room_id": 123, "body": "本文 & 確認"}, "POST", "/rooms/123/messages", {}, {"body": ["本文 & 確認"]}),
        (ChatworkCreateTaskTool, {"room_id": 123, "body": "本文", "to_ids": [1, 2]}, "POST", "/rooms/123/tasks", {}, {"body": ["本文"], "to_ids": ["1,2"]}),
        (ChatworkCreateTaskTool, {"room_id": 123, "body": "本文", "to_ids": [1, 2], "limit": None}, "POST", "/rooms/123/tasks", {}, {"body": ["本文"], "to_ids": ["1,2"]}),
        (ChatworkCreateTaskTool, {"room_id": 123, "body": "本文", "to_ids": [1, 2], "limit": 1800000000}, "POST", "/rooms/123/tasks", {}, {"body": ["本文"], "to_ids": ["1,2"], "limit": ["1800000000"]}),
    ],
)
async def test_tool_request_shape(mock_http, tool_type, arguments, method, path, query, form) -> None:
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == method
        assert str(request.url.copy_with(query=None)) == f"https://api.chatwork.com/v2{path}"
        assert dict(request.url.params) == query
        assert request.headers["X-ChatWorkToken"] == TOKEN
        assert parse_qs(request.content.decode()) == form
        if method == "POST":
            assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        return httpx.Response(200, json=[] if method == "GET" else {"message_id": "msg-1"})

    mock_http(handler)
    result = await tool_type().run(arguments, context())
    assert len(requests) == 1
    assert result.ok is True
    assert TOKEN not in result.content


@pytest.mark.parametrize("to_ids", [[], ["1"], [1, "2"], [1.5], [True], None, "1,2"])
async def test_create_task_rejects_invalid_assignees(to_ids) -> None:
    async def unexpected_request(*args, **kwargs):
        pytest.fail("Invalid assignees must be rejected before requesting Chatwork")

    result = await ChatworkCreateTaskTool(request_fn=unexpected_request).run(
        {"room_id": 123, "body": "本文", "to_ids": to_ids}, context()
    )
    assert result.ok is False
    assert "to_ids" in result.content
    assert TOKEN not in result.content


@pytest.mark.parametrize("tool_type", TOOL_TYPES)
def test_risk_and_confirmation_summary(tool_type) -> None:
    tool = tool_type()
    external = tool_type in (ChatworkSendMessageTool, ChatworkCreateTaskTool)
    assert tool.risk is (Risk.EXTERNAL if external else Risk.READ)
    arguments = {"room_id": 123, "body": "確認する本文", "to_ids": [1, 2]}
    assert ToolPolicy().needs_confirmation(tool, arguments) is external
    if external:
        summary = describe_action(tool, arguments)
        assert "123" in summary
        assert arguments["body"] in summary


@pytest.mark.parametrize(
    "status, expected",
    [(401, "API トークンが無効"), (429, "利用回数の上限"), (400, "400"), (403, "403")],
)
@pytest.mark.parametrize("tool_type", TOOL_TYPES)
async def test_api_errors_are_safe_and_propagated(mock_http, status, expected, tool_type) -> None:
    mock_http(lambda request: httpx.Response(status, json={"errors": ["invalid room", "permission denied"]}))
    result = await tool_type().run({"room_id": 123, "body": "本文", "to_ids": [1, 2]}, context())
    assert result.ok is False
    assert expected in result.content
    if status not in (401, 429):
        assert "invalid room" in result.content
        assert "permission denied" in result.content
    assert TOKEN not in result.content


async def test_connection_error_does_not_expose_token(mock_http) -> None:
    def handler(request):
        raise httpx.ConnectError(f"connection failed with {TOKEN}", request=request)

    mock_http(handler)
    data, error = await chatwork_request(context(), "GET", "/rooms")
    assert data is None
    assert error is not None
    assert error.ok is False
    assert "通信に失敗" in error.content
    assert TOKEN not in error.content


@pytest.mark.parametrize("token", [None, "", "  "])
async def test_disconnected_request_never_uses_network(mock_http, token) -> None:
    def handler(request):
        pytest.fail("Disconnected requests must not use HTTP")

    mock_http(handler)
    data, error = await chatwork_request(context(token), "GET", "/rooms")
    assert data is None
    assert error is not None
    assert error.ok is False
    assert "接続されていません" in error.content
    assert TOKEN not in error.content
