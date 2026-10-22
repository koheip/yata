"""LINE の署名、送受信、会話、確認をネットワークなしで検証する。"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from tests.fakes import RecordingTool, ScriptedProvider
from tests.test_routines import TOKYO, _service
from yata.api.app import create_app
from yata.config import Settings
from yata.confirm.gate import InMemoryConfirmationGate
from yata.connectors.base import ConnectorRegistry, ConnectorState
from yata.connectors.line import LineConnector
from yata.line.bridge import NOT_FOUND, LineBridge
from yata.line.client import LineClient, LineError, confirm_messages, split_text
from yata.line.webhook import create_webhook_app, verify_signature
from yata.llm.types import LLMResponse, ProviderError, ToolCall
from yata.memory.store import MemoryStore
from yata.routines.repository import RoutineRepository
from yata.tools.base import Risk, ToolContext
from yata.tools.catalog import visible_registry
from yata.tools.line import LinePushMessageTool
from yata.tools.policy import ToolPolicy, describe_action
from yata.tools.registry import ToolRegistry

SECRET = "8c570fa6dd201bb328f1c1eac23a96d8"
TOKEN = "test-line-access-token-secret"
BODY = b'{"destination":"U8e742f61d673b39c7fff3cecb7536ef0","events":[]}'
SIGNATURE = "GhRKmvmHys4Pi8DxkF4+EayaH0OqtJtaZxgTD9fMDLs="


def sign(body):
    return base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()


def test_signature():
    assert verify_signature(SECRET, BODY, SIGNATURE)
    assert not verify_signature(SECRET, BODY + b" ", SIGNATURE)
    for value in (None, "", "garbage", "!!!", "日本語", "a" * 44):
        assert not verify_signature(SECRET, BODY, value)
    empty_key = base64.b64encode(hmac.new(b"", BODY, hashlib.sha256).digest()).decode()
    assert not verify_signature("", BODY, empty_key)


async def test_webhook_routes_validation_and_background():
    started, release = asyncio.Event(), asyncio.Event()
    received = []

    async def callback(events):
        received.append(events)
        started.set()
        await release.wait()

    app = create_webhook_app(SECRET, callback)
    assert {route.path for route in app.routes} == {"/line/health", "/line/webhook"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/line/health")).json() == {"ok": True}
        for path in ("/api/health", "/api/connectors", "/docs", "/openapi.json", "/redoc"):
            assert (await client.get(path)).status_code == 404
        for headers in ({}, {"x-line-signature": "invalid"}):
            assert (await client.post("/line/webhook", content=BODY, headers=headers)).status_code == 401
        for body in (b"not json", b"[]", b'{"events":{}}'):
            assert (await client.post("/line/webhook", content=body,
                                      headers={"x-line-signature": sign(body)})).status_code == 400
        assert (await client.post("/line/webhook", content=b"x" * (1024 * 1024 + 1))).status_code == 413
        response = await client.post("/line/webhook", content=BODY, headers={"x-line-signature": SIGNATURE})
        assert response.status_code == 200 and response.json() == {"ok": True}
        await asyncio.wait_for(started.wait(), 1)
        assert received == [[]] and app.state.tasks
        release.set()
        await asyncio.gather(*app.state.tasks)


@pytest.mark.parametrize("secret,token", [(SECRET, None), (SECRET, "your-token"), (SECRET, " "), (None, None)])
def test_connector_not_configured(secret, token):
    connector = LineConnector(secret, token)
    assert connector.status() == ConnectorState.NOT_CONFIGURED
    assert connector.status_note() is None
    assert not connector.webhook_ready


@pytest.mark.parametrize("secret", [None, "", " ", "your-secret"])
def test_connector_token_only_is_connected_without_webhook(secret):
    connector = LineConnector(secret, TOKEN, "Uowner")
    assert connector.status() == ConnectorState.CONNECTED
    assert not connector.webhook_ready
    assert connector.status_note() == "許可ユーザー: 1 人／受信は停止中（LINE_CHANNEL_SECRET 未設定）"
    assert LineConnector(SECRET, TOKEN).webhook_ready


@pytest.mark.parametrize("secret,webhook", [(None, False), (SECRET, True)])
def test_main_starts_webhook_only_with_secret(monkeypatch, tmp_path, secret, webhook):
    from yata import main as main_module

    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda app, host, port: calls.append("main"))

    async def fake_serve_with_line(app, host, port, settings):
        calls.append("webhook")

    monkeypatch.setattr(main_module, "serve_with_line", fake_serve_with_line)
    monkeypatch.setattr(main_module, "Settings", lambda: Settings(
        _env_file=None, yata_db=str(tmp_path / "yata.db"), line_channel_secret=secret,
        line_channel_access_token=TOKEN, line_allowed_user_ids="Uowner", yata_scheduler_enabled=False,
    ))
    main_module.main(["--no-browser"])
    assert calls == (["webhook"] if webhook else ["main"])


async def test_connector_and_secret_free_api(tmp_path):
    connector = LineConnector(SECRET, TOKEN, " Uowner, , Uother ")
    assert connector.status() == ConnectorState.CONNECTED
    assert connector.allowed_user_ids == ["Uowner", "Uother"]
    assert connector.owner_user_id == "Uowner"
    assert connector.status_note() == "許可ユーザー: 2 人"
    assert await connector.access_token() == TOKEN
    assert LineConnector(SECRET, TOKEN).status_note() == "許可ユーザー未設定（LINE_ALLOWED_USER_IDS）"
    assert LineConnector(SECRET, TOKEN).owner_user_id is None
    assert SECRET not in repr(connector) and TOKEN not in str(connector)
    settings = Settings(_env_file=None, yata_db=str(tmp_path / "yata.db"),
                        line_channel_secret=SECRET, line_channel_access_token=TOKEN,
                        line_allowed_user_ids="Uowner", yata_scheduler_enabled=False)
    app = create_app(settings)
    assert app.state.line_bridge.gate is app.state.gate
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/connectors")
        assert response.status_code == 200
        assert SECRET not in response.text and TOKEN not in response.text
        line = next(c for c in response.json()["connectors"] if c["id"] == "line")
        assert line["id"] == "line" and line["note"] == "許可ユーザー: 1 人"
    assert not any(route.path.startswith("/line/") for route in app.routes)


def test_split_and_confirm():
    assert split_text("") == []
    assert split_text("abc\ndef", 5) == ["abc\n", "def"]
    text = "あ" * 30000
    parts = split_text(text)
    assert "".join(parts) == text and all(len(part) <= 5000 for part in parts)
    assert [len(part) for part in parts] == [5000] * 6
    assert split_text("x" * 5000) == ["x" * 5000]
    assert [len(part) for part in split_text("x" * 5001)] == [5000, 1]
    with pytest.raises(ValueError):
        split_text("x", 0)
    messages = confirm_messages("req-id", "自分の LINE へ送信します。")
    assert messages[0]["type"] == "text"
    template = messages[-1]
    assert len(template["altText"]) <= 400
    assert len(template["template"]["text"]) <= 240
    assert [parse_qs(action["data"]) for action in template["template"]["actions"]] == [
        {"yata-confirm": ["req-id"], "d": ["approve"]},
        {"yata-confirm": ["req-id"], "d": ["deny"]},
    ]


@pytest.mark.parametrize("reply_status", [200, 400])
async def test_reply_and_push_chunks(reply_status):
    requests = []

    def handler(request):
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(reply_status if request.url.path.endswith("reply") else 200)

    client = LineClient(TOKEN, httpx.MockTransport(handler))
    await client.send_text("Uowner", "x" * (4500 * 12), "reply-token")
    assert requests[0][1]["replyToken"] == "reply-token"
    assert all(1 <= len(body["messages"]) <= 5 for _, body in requests)
    assert all(path.endswith("push") for path, _ in requests[1:])
    assert all(body["to"] == "Uowner" for _, body in requests[1:])
    delivered = requests[1:] if reply_status == 400 else requests
    assert "".join(msg["text"] for _, body in delivered for msg in body["messages"]) == "x" * (4500 * 12)
    requests.clear()
    assert await client.push("Uowner", [{"type": "text", "text": "x"}] * 11) == 200
    assert [len(body["messages"]) for _, body in requests] == [5, 5, 1]


@pytest.mark.parametrize("status,hint", [(401, "トークン無効"), (429, "上限"), (500, "エラー")])
async def test_client_errors_hide_secrets(status, hint, caplog):
    client = LineClient(TOKEN, httpx.MockTransport(lambda request: httpx.Response(status, text=SECRET + TOKEN)))
    with pytest.raises(LineError) as caught:
        await client.send_text("Uowner", "hello")
    assert hint in str(caught.value)
    assert not any(secret in str(caught.value) + caplog.text for secret in (SECRET, TOKEN))


async def test_network_error_hides_secrets():
    def handler(request):
        raise httpx.ConnectError(TOKEN + SECRET, request=request)
    with pytest.raises(LineError) as caught:
        await LineClient(TOKEN, httpx.MockTransport(handler)).send_text("Uowner", "hello")
    assert "通信" in str(caught.value)
    assert TOKEN not in str(caught.value) and SECRET not in str(caught.value)


def text_event(user="Uowner", source="user", text="こんにちは", token="reply-token"):
    return {"type": "message", "source": {"type": source, "userId": user},
            "replyToken": token, "message": {"type": "text", "text": text}}


@pytest.fixture
def setup_bridge(tmp_path):
    def create(responses=None, allowed="Uowner,Uother", tool=None):
        settings = Settings(_env_file=None, yata_db=str(tmp_path / "yata.db"), yata_model="demo",
                            line_channel_secret=SECRET, line_channel_access_token=TOKEN,
                            line_allowed_user_ids=allowed)
        connectors = ConnectorRegistry()
        connectors.register(LineConnector(SECRET, TOKEN, allowed))
        registry = ToolRegistry()
        if tool:
            registry.register(tool)
        provider = ScriptedProvider(responses or [LLMResponse(content="こんにちは！")])
        requests = []
        sent = asyncio.Event()

        def handler(request):
            requests.append((request.url.path, json.loads(request.content)))
            sent.set()
            return httpx.Response(200)

        client = LineClient(TOKEN, httpx.MockTransport(handler))
        bridge = LineBridge(MemoryStore(settings.database_path()),
                            SimpleNamespace(resolve=lambda model: (provider, "test-model")),
                            registry, InMemoryConfirmationGate(), connectors, settings, None,
                            tmp_path, client, confirm_timeout=1)
        return bridge, requests, provider, sent
    return create


async def drain(bridge):
    await asyncio.wait_for(asyncio.gather(*bridge._tasks), 2)


async def test_allowlist_and_ignored_events(setup_bridge, caplog):
    bridge, requests, provider, _ = setup_bridge()
    with caplog.at_level(logging.INFO):
        await bridge.handle_events([text_event(user="Uunknown", text="非公開の本文"),
                                    text_event(source="group"), text_event(source="room"),
                                    {"type": "follow", "source": {"type": "user", "userId": "Uowner"}}])
    assert "Uunknown" in caplog.text and "LINE_ALLOWED_USER_IDS" in caplog.text
    assert "非公開の本文" not in caplog.text
    assert not requests and not provider.seen and not bridge.memory.list_conversations()


async def test_text_conversation_persistence_and_sequential_turns(setup_bridge):
    bridge, requests, provider, _ = setup_bridge([LLMResponse(content="回答1"), LLMResponse(content="回答2")])
    await bridge.handle_events([text_event(text="質問1"), text_event(text="質問2", token="token2")])
    await drain(bridge)
    conversations = bridge.memory.list_conversations()
    assert len(conversations) == 1 and conversations[0].title == "LINE"
    messages = bridge.memory.list_messages(conversations[0].id)
    assert [m.content for m in messages] == ["質問1", "回答1", "質問2", "回答2"]
    assert [body["replyToken"] for _, body in requests] == ["reply-token", "token2"]
    assert all(path.endswith("reply") for path, _ in requests)
    assert provider.seen[1][0].role == "system"
    reloaded, _, _, _ = setup_bridge()
    assert reloaded._conversation("Uowner").id == conversations[0].id
    bridge.memory.delete_conversation(conversations[0].id)
    assert reloaded._conversation("Uowner").id != conversations[0].id


class ExternalTool(RecordingTool):
    risk = Risk.EXTERNAL


@pytest.mark.parametrize("decision,expected", [("approve", True), ("deny", False)])
async def test_confirmation_postback_controls_tool(setup_bridge, decision, expected):
    tool = ExternalTool()
    bridge, requests, _, sent = setup_bridge([
        LLMResponse(tool_calls=[ToolCall("call", "echo", {"text": "実行内容"})]),
        LLMResponse(content="完了"),
    ], tool=tool)
    await bridge.handle_events([text_event()])
    await asyncio.wait_for(sent.wait(), 1)
    request_id = next(iter(bridge.pending))
    template = requests[0][1]["messages"][-1]
    assert template["type"] == "template"
    assert request_id in template["template"]["actions"][0]["data"]
    await bridge.handle_events([{"type": "postback", "source": {"type": "user", "userId": "Uowner"},
                                "replyToken": "postback-token",
                                "postback": {"data": f"yata-confirm={request_id}&d={decision}"}}])
    await drain(bridge)
    assert bool(tool.calls) is expected
    assert not bridge.pending
    assert requests[1][1]["messages"][0]["text"] == ("許可しました。" if expected else "拒否しました。")
    assert requests[-1][0].endswith("push")


async def test_postback_other_user_and_invalid_never_resolve(setup_bridge):
    bridge, requests, _, _ = setup_bridge()
    bridge.pending["valid"] = "Uowner"
    calls = []
    bridge.gate = SimpleNamespace(resolve=lambda *args: calls.append(args))
    for user, data in (("Uother", "yata-confirm=valid&d=approve"),
                       ("Uowner", "yata-confirm=missing&d=approve"),
                       ("Uowner", "yata-confirm=valid&d=bad")):
        await bridge.handle_postback(user, data, "token")
    assert not calls and bridge.pending == {"valid": "Uowner"}
    assert all(body["messages"][0]["text"] == NOT_FOUND for _, body in requests)
    bridge.gate = SimpleNamespace(resolve=lambda *args: False)
    await bridge.handle_postback("Uowner", "yata-confirm=valid&d=approve", "token")
    assert requests[-1][1]["messages"][0]["text"] == NOT_FOUND


async def test_web_confirmation_still_works(setup_bridge):
    tool = ExternalTool()
    bridge, _, _, sent = setup_bridge([
        LLMResponse(tool_calls=[ToolCall("call", "echo", {"text": "実行"})]), LLMResponse(content="完了"),
    ], tool=tool)
    await bridge.handle_events([text_event()])
    await asyncio.wait_for(sent.wait(), 1)
    assert bridge.gate.resolve(next(iter(bridge.pending)), True)
    await drain(bridge)
    assert tool.calls and not bridge.pending


async def test_tool_confirmation_owner_and_errors(setup_bridge, caplog):
    bridge, requests, _, _ = setup_bridge()
    tool = LinePushMessageTool(client_factory=lambda token: bridge.client)
    ctx = ToolContext("conv", bridge.memory, None, None, True, bridge.connectors)
    assert tool.risk == Risk.EXTERNAL and tool.required_connector == "line"
    assert ToolPolicy().needs_confirmation(tool, {"text": "通知"})
    assert describe_action(tool, {"text": "通知"}) == "自分の LINE にメッセージを送信します。\n本文:\n通知"
    registry = ToolRegistry()
    registry.register(tool)
    assert visible_registry(registry, None).names() == []
    result = await tool.run({"text": "通知"}, ctx)
    assert result.ok and requests[-1][1]["to"] == "Uowner"
    assert TOKEN not in result.content and SECRET not in result.content
    assert await bridge.push_to_owner("通知")
    bridge.connector = LineConnector(SECRET, TOKEN)
    assert not await bridge.push_to_owner("通知")
    bridge.connectors.register(bridge.connector)
    result = await tool.run({"text": "通知"}, ctx)
    assert not result.ok and "LINE_ALLOWED_USER_IDS" in result.content
    assert TOKEN not in caplog.text and SECRET not in caplog.text


async def test_router_and_agent_errors_are_safe(setup_bridge, caplog):
    bridge, requests, _, _ = setup_bridge()

    def fail(model):
        raise ProviderError("モデルが未設定です。" + TOKEN, provider="test")

    bridge.router = SimpleNamespace(resolve=fail)
    await bridge.run_chat("Uowner", "hello", "token")
    assert "モデルが未設定" in requests[-1][1]["messages"][0]["text"]
    assert TOKEN not in json.dumps(requests)

    def explode(model):
        raise RuntimeError(SECRET + TOKEN)

    bridge.router = SimpleNamespace(resolve=explode)
    await bridge.run_chat("Uowner", "hello", "token")
    assert requests[-1][1]["messages"][0]["text"] == "エージェントの実行中に失敗しました。"
    assert SECRET not in caplog.text and TOKEN not in caplog.text


async def test_line_push_agent_requires_approval(setup_bridge):
    bridge, requests, _, sent = setup_bridge([
        LLMResponse(tool_calls=[ToolCall("call", "line_push_message", {"text": "通知"})]),
        LLMResponse(content="送信完了"),
    ])
    bridge.registry.register(LinePushMessageTool(client_factory=lambda token: bridge.client))
    await bridge.handle_events([text_event(user="Uother")])
    await asyncio.wait_for(sent.wait(), 1)
    assert len(requests) == 1 and requests[0][0].endswith("reply")
    assert requests[0][1]["messages"][-1]["type"] == "template"
    request_id = next(iter(bridge.pending))
    await bridge.handle_postback("Uother", f"yata-confirm={request_id}&d=approve", "postback-token")
    await drain(bridge)
    pushes = [body for path, body in requests if path.endswith("push")]
    assert pushes[0] == {"to": "Uowner", "messages": [{"type": "text", "text": "通知"}]}


async def test_timeout_persists_tool_result(setup_bridge):
    tool = ExternalTool()
    bridge, _, _, _ = setup_bridge([
        LLMResponse(tool_calls=[ToolCall("call", "echo", {"text": "実行"})]),
        LLMResponse(content="タイムアウトしました。"),
    ], tool=tool)
    bridge.confirm_timeout = 0.01
    await bridge.handle_events([text_event()])
    await drain(bridge)
    assert not tool.calls and not bridge.pending
    conversation = bridge.memory.list_conversations()[0]
    messages = bridge.memory.list_messages(conversation.id)
    assert any(message.role == "tool" and "タイムアウト" in message.content for message in messages)


async def test_push_tool_error_hides_secrets(setup_bridge):
    bridge, _, _, _ = setup_bridge()

    class FailingClient:
        async def send_text(self, *args):
            raise LineError(SECRET + TOKEN)

    tool = LinePushMessageTool(client_factory=lambda token: FailingClient())
    ctx = ToolContext("conv", bridge.memory, None, None, True, bridge.connectors)
    result = await tool.run({"text": "通知"}, ctx)
    assert not result.ok and SECRET not in result.content and TOKEN not in result.content
    bridge.client = FailingClient()
    assert not await bridge.push_to_owner("通知")


@pytest.mark.parametrize("enabled,raises", [(True, False), (False, False), (True, True)])
async def test_routine_line_notification(tmp_path, enabled, raises, caplog):
    answer = "結果" * 600
    service, _ = _service(tmp_path, ScriptedProvider([LLMResponse(content=answer)]))
    sent = []

    async def notify(text):
        # The result is persisted before sending, and the notification is not clipped.
        assert service.routines.latest_run(routine.id).status == "ok"
        sent.append(text)
        if raises:
            raise RuntimeError("通知失敗")
        return True

    service.notifier = notify
    routine = service.create(
        name="朝の確認", prompt="確認して", model_id="demo", preset="hourly",
        notify_line=enabled, now=datetime(2026, 10, 21, 8, 30, tzinfo=TOKYO),
    )
    assert service.routines.get(routine.id).notify_line is enabled
    await service.run_due(datetime(2026, 10, 21, 9, 5, tzinfo=TOKYO))
    await service.wait_for([routine.id])
    assert sent == ([f"【ルーティン】朝の確認\n{answer}"] if enabled else [])
    finished = service.routines.latest_run(routine.id)
    assert finished.status == "ok" and finished.finished_at is not None
    if raises:
        assert "ルーティンの LINE 通知に失敗しました" in caplog.text


async def test_routine_line_notification_error(tmp_path):
    service, _ = _service(tmp_path, ScriptedProvider([]))
    sent = []

    def fail(model):
        raise ProviderError("モデルが未設定です。", provider="test")

    async def notify(text):
        sent.append(text)
        return True

    service.router = SimpleNamespace(resolve=fail)
    service.notifier = notify
    routine = service.create(
        name="確認", prompt="確認して", model_id="demo", preset="hourly",
        notify_line=True, now=datetime(2026, 10, 21, 8, 30, tzinfo=TOKYO),
    )
    await service.run_due(datetime(2026, 10, 21, 9, 5, tzinfo=TOKYO))
    await service.wait_for([routine.id])
    assert sent == ["【ルーティン】確認\nモデルが未設定です。"]
    assert service.routines.latest_run(routine.id).status == "error"


async def test_routine_line_notification_api(tmp_path):
    settings = Settings(_env_file=None, yata_db=str(tmp_path / "app.db"), yata_model="demo",
                        yata_scheduler_enabled=False, line_channel_secret=SECRET,
                        line_channel_access_token=TOKEN, line_allowed_user_ids="Uowner")
    app = create_app(settings)
    assert app.state.routines.notifier == app.state.line_bridge.push_to_owner
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        body = {"name": "確認", "prompt": "確認して", "preset": "hourly", "model_id": "demo"}
        response = await client.post("/api/routines", json=body)
        assert response.status_code == 201
        routine = response.json()
        assert routine["notify_line"] is False
        path = f"/api/routines/{routine['id']}/notify_line"
        for enabled in (True, False):
            response = await client.post(path, json={"enabled": enabled})
            assert response.status_code == 200
            assert response.json()["notify_line"] is enabled
            assert (await client.get("/api/routines")).json()["routines"][0]["notify_line"] is enabled
        response = await client.post("/api/routines/missing/notify_line", json={"enabled": True})
        assert response.status_code == 404
        assert response.json()["detail"] == "ルーティンが見つかりません。"
        response = await client.post("/api/routines", json={**body, "notify_line": True})
        assert response.json()["notify_line"] is True


def test_routine_line_notification_migrates_old_database(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE routines (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL,
                schedule_kind TEXT NOT NULL, schedule TEXT NOT NULL, timezone TEXT NOT NULL,
                enabled INTEGER NOT NULL, last_run TEXT, next_run TEXT, model_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO routines VALUES (
                'old', '確認', '確認して', 'cron', '0 * * * *', 'Asia/Tokyo',
                1, NULL, NULL, 'demo', 'conversation', '2026-10-21', '2026-10-21'
            )
        """)
    repo = RoutineRepository(path)
    assert repo.get("old").notify_line is False
    with sqlite3.connect(path) as conn:
        column = next(row for row in conn.execute("PRAGMA table_info(routines)") if row[1] == "notify_line")
        assert column[2:5] == ("INTEGER", 1, "0")
    assert repo.set_notify_line("old", True).notify_line is True
    assert RoutineRepository(path).get("old").notify_line is True
    assert repo.set_notify_line("missing", True) is None


@pytest.mark.parametrize("failure", [SystemExit(1), OSError("port in use")])
async def test_webhook_bind_failure_keeps_main_server_running(monkeypatch, caplog, failure):
    from yata import main as main_module

    webhook_attempted = asyncio.Event()
    completed = []

    class MainServer:
        def __init__(self, config):
            pass

        async def serve(self):
            await webhook_attempted.wait()
            await asyncio.sleep(0)
            completed.append(True)

    class FailedWebhookServer:
        should_exit = False

        def __init__(self, config):
            pass

        async def serve(self):
            webhook_attempted.set()
            raise failure

    monkeypatch.setattr(main_module.uvicorn, "Server", MainServer)
    monkeypatch.setattr(main_module, "WebhookServer", FailedWebhookServer)
    bridge = SimpleNamespace(connector=SimpleNamespace(channel_secret=SECRET), handle_events=None)
    app = SimpleNamespace(state=SimpleNamespace(line_bridge=bridge))
    await asyncio.wait_for(main_module.serve_with_line(
        app, "127.0.0.1", 8741, SimpleNamespace(line_webhook_port=8742),
    ), 1)
    assert completed == [True]
    assert "LINE Webhook を 127.0.0.1:8742 で起動できませんでした。LINE_WEBHOOK_PORT を確認してください。" in caplog.text


async def test_broadcast_and_quota_tools():
    import httpx as _httpx

    from yata.connectors.base import ConnectorRegistry as _Registry
    from yata.connectors.line import LineConnector as _Line
    from yata.line.client import LineClient as _Client
    from yata.tools.base import ToolContext as _Ctx
    from yata.tools.line import LineBroadcastTool, LineMessageQuotaTool
    from yata.tools.policy import describe_action as _describe

    sent = []

    def handler(request):
        sent.append(request)
        if request.url.path.endswith("/quota"):
            return _httpx.Response(200, json={"type": "limited", "value": 200})
        if request.url.path.endswith("/consumption"):
            return _httpx.Response(200, json={"totalUsage": 12})
        return _httpx.Response(200, json={})

    factory = lambda token: _Client(token, transport=_httpx.MockTransport(handler))  # noqa: E731
    registry = _Registry()
    registry.register(_Line("secret-x", "token-broadcast-x", "Uowner"))
    ctx = _Ctx("conv", None, None, None, True, connectors=registry)
    assert LineBroadcastTool.risk == Risk.EXTERNAL and LineMessageQuotaTool.risk == Risk.READ
    quota = await LineMessageQuotaTool(factory).run({}, ctx)
    assert quota.ok and "12 通 / 上限 200 通" in quota.content
    result = await LineBroadcastTool(factory).run({"text": "本日は臨時休業です"}, ctx)
    assert result.ok and sent[-1].url.path.endswith("/broadcast")
    assert "本日は臨時休業です" in sent[-1].content.decode()
    assert "取り消せません" in _describe(LineBroadcastTool(), {"text": "a"})
    empty = await LineBroadcastTool(factory).run({"text": "  "}, ctx)
    assert not empty.ok
