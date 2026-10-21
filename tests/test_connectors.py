"""Connector framework: token storage, OAuth state, status endpoint, and the
Gmail/Calendar tools. No network; Google calls are always mocked."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tests.fakes import ScriptedProvider
from yata.agent.loop import run_agent
from yata.api.app import create_app
from yata.config import Settings
from yata.confirm.gate import ScriptedGate
from yata.connectors.base import Connector, ConnectorRegistry, ConnectorState
from yata.connectors.google import GmailConnector, GoogleCalendarConnector
from yata.connectors.google_oauth import GoogleOAuthClient
from yata.connectors.oauth_state import OAuthStateStore
from yata.connectors.pkce import challenge_for, new_verifier
from yata.connectors.token_store import TokenSet, TokenStore
from yata.llm.types import LLMResponse, ToolCall
from yata.tools.base import ToolContext
from yata.tools.calendar import CalendarCreateEventTool, CalendarDeleteEventTool, CalendarFreeBusyTool
from yata.tools.catalog import build_registry, visible_registry
from yata.tools.gmail import GmailSendEmailTool
from yata.tools.policy import ToolPolicy, describe_action
from yata.tools.registry import ToolRegistry

# --- token storage -----------------------------------------------------------


def test_token_store_round_trip_and_delete(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "connectors")
    assert store.load("gmail") is None

    token = TokenSet(access_token="tok", refresh_token="ref", expires_at=time.time() + 3600, scope="s")
    store.save("gmail", token)
    loaded = store.load("gmail")
    assert loaded is not None
    assert loaded.access_token == "tok"
    assert loaded.refresh_token == "ref"

    assert store.delete("gmail") is True
    assert store.load("gmail") is None
    assert store.delete("gmail") is False


def test_token_store_save_leaves_only_the_final_file_and_restricts_permissions(tmp_path: Path) -> None:
    directory = tmp_path / "connectors"
    store = TokenStore(directory)
    token = TokenSet(access_token="tok", refresh_token="ref", expires_at=time.time() + 3600, scope="s")

    store.save("gmail", token)

    files = list(directory.iterdir())
    assert files == [directory / "gmail.json"]  # no leftover temp file

    if sys.platform != "win32":
        import stat

        mode = stat.S_IMODE((directory / "gmail.json").stat().st_mode)
        assert mode == stat.S_IRUSR | stat.S_IWUSR

    # Saving again (refresh) still leaves exactly one file behind.
    store.save("gmail", TokenSet(access_token="tok2", refresh_token="ref", expires_at=time.time() + 3600, scope="s"))
    assert list(directory.iterdir()) == [directory / "gmail.json"]
    assert store.load("gmail").access_token == "tok2"


# --- connector status and token refresh -------------------------------------


def test_connector_not_configured_without_an_oauth_client(tmp_path: Path) -> None:
    connector = GmailConnector(None, TokenStore(tmp_path))
    assert connector.status() == ConnectorState.NOT_CONFIGURED
    assert "OAuth" in connector.setup_instructions


def test_connector_connects_and_disconnects(tmp_path: Path) -> None:
    tokens = TokenStore(tmp_path)
    client = GoogleOAuthClient(client_id="id", client_secret="secret", redirect_uri="http://127.0.0.1:8741/cb")
    connector = GmailConnector(client, tokens)
    assert connector.status() == ConnectorState.NOT_CONNECTED

    tokens.save("gmail", TokenSet(access_token="tok", refresh_token="ref", expires_at=time.time() + 3600, scope="s"))
    assert connector.status() == ConnectorState.CONNECTED

    assert connector.disconnect() is True
    assert connector.status() == ConnectorState.NOT_CONNECTED


async def test_access_token_refreshes_near_expiry(tmp_path: Path, monkeypatch) -> None:
    tokens = TokenStore(tmp_path)
    client = GoogleOAuthClient(client_id="id", client_secret="secret", redirect_uri="http://127.0.0.1:8741/cb")
    connector = GmailConnector(client, tokens)
    tokens.save(
        "gmail",
        TokenSet(access_token="old", refresh_token="ref", expires_at=time.time() - 10, scope="s"),
    )

    async def fake_refresh(client_arg, *, refresh_token: str, scope: str):
        assert client_arg is client
        assert refresh_token == "ref"
        return TokenSet(access_token="new", refresh_token="ref", expires_at=time.time() + 3600, scope=scope)

    monkeypatch.setattr("yata.connectors.google.refresh_access_token", fake_refresh)
    assert await connector.access_token() == "new"
    assert tokens.load("gmail").access_token == "new"


async def test_access_token_is_none_without_a_refresh_token(tmp_path: Path) -> None:
    tokens = TokenStore(tmp_path)
    client = GoogleOAuthClient(client_id="id", client_secret="secret", redirect_uri="http://127.0.0.1:8741/cb")
    connector = GmailConnector(client, tokens)
    tokens.save("gmail", TokenSet(access_token="old", refresh_token=None, expires_at=time.time() - 10, scope="s"))
    assert await connector.access_token() is None


# --- OAuth state (CSRF) and PKCE ---------------------------------------------


def test_oauth_state_store_is_single_use_and_rejects_unknown_state() -> None:
    store = OAuthStateStore()
    state = store.open("gmail", "verifier-123")
    assert store.pop("not-a-real-state") is None
    assert store.pop(state) == ("gmail", "verifier-123")
    assert store.pop(state) is None  # consumed once


def test_google_calendar_connector_requests_the_freebusy_scope() -> None:
    assert "https://www.googleapis.com/auth/calendar.events.freebusy" in GoogleCalendarConnector.scopes


def test_pkce_challenge_is_derived_from_the_verifier() -> None:
    verifier = new_verifier()
    assert challenge_for(verifier) == challenge_for(verifier)
    assert challenge_for(verifier) != challenge_for(new_verifier())


# --- tool risk levels and visibility ------------------------------------------


def test_gmail_and_calendar_tools_require_confirmation_only_when_external() -> None:
    policy = ToolPolicy()
    assert policy.needs_confirmation(GmailSendEmailTool(), {"to": "a@b.com", "subject": "s", "body": "b"}) is True
    assert policy.needs_confirmation(CalendarCreateEventTool(), {"summary": "x", "start": "s", "end": "e"}) is True
    assert policy.needs_confirmation(CalendarDeleteEventTool(), {"event_id": "1"}) is True

    summary = describe_action(GmailSendEmailTool(), {"to": "a@b.com", "subject": "件名です", "body": "本文です"})
    assert "a@b.com" in summary
    assert "件名です" in summary
    assert "本文です" in summary


def test_visible_registry_hides_tools_until_the_connector_is_connected() -> None:
    class FakeConnector(Connector):
        id = "gmail"
        label = "Gmail"

        def __init__(self, state: ConnectorState):
            self._state = state
            self.setup_instructions = ""

        def status(self) -> ConnectorState:
            return self._state

        def authorize_url(self, state: str, code_challenge: str) -> str:
            raise NotImplementedError

        async def complete_authorization(self, code: str, code_verifier: str) -> None:
            raise NotImplementedError

        def disconnect(self) -> bool:
            return False

    base = build_registry()
    non_connector_names = [name for name in base.names() if base.get(name).required_connector is None]

    assert visible_registry(base, None).names() == non_connector_names

    not_connected = ConnectorRegistry()
    not_connected.register(FakeConnector(ConnectorState.NOT_CONNECTED))
    visible = visible_registry(base, not_connected)
    assert "gmail_search" not in visible.names()
    assert "web_search" in visible.names()

    connected = ConnectorRegistry()
    connected.register(FakeConnector(ConnectorState.CONNECTED))
    visible_connected = visible_registry(base, connected)
    assert "gmail_search" in visible_connected.names()
    # google_calendar was never registered in this registry, so its tools stay hidden
    assert "calendar_list_events" not in visible_connected.names()


# --- tool behavior with a mocked Google API -----------------------------------


async def test_gmail_create_draft_builds_a_valid_raw_message() -> None:
    import base64
    from email import message_from_bytes
    from email.header import decode_header

    def _decode(value: str) -> str:
        parts = decode_header(value)
        return "".join(
            text.decode(encoding or "utf-8") if isinstance(text, bytes) else text for text, encoding in parts
        )

    captured: dict = {}

    async def fake_request_fn(ctx, connector_id, method, url, *, params=None, json_body=None):
        captured["connector_id"] = connector_id
        captured["method"] = method
        captured["url"] = url
        captured["json_body"] = json_body
        return {"id": "draft-1"}, None

    from yata.tools.gmail import GmailCreateDraftTool

    tool = GmailCreateDraftTool(request_fn=fake_request_fn)
    ctx = ToolContext("conv", None, None, None, True, connectors=None)
    result = await tool.run({"to": "a@b.com", "subject": "件名", "body": "本文です"}, ctx)

    assert result.ok is True
    assert "draft-1" in result.content
    assert captured["connector_id"] == "gmail"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/drafts")

    raw = captured["json_body"]["message"]["raw"]
    decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    parsed = message_from_bytes(decoded)
    assert parsed["To"] == "a@b.com"
    assert _decode(parsed["Subject"]) == "件名"


async def test_calendar_create_event_sends_the_given_start_and_end() -> None:
    captured: dict = {}

    async def fake_request_fn(ctx, connector_id, method, url, *, params=None, json_body=None):
        captured["connector_id"] = connector_id
        captured["method"] = method
        captured["json_body"] = json_body
        return {"id": "evt-1", "summary": json_body["summary"], "start": json_body["start"], "end": json_body["end"]}, None

    tool = CalendarCreateEventTool(request_fn=fake_request_fn)
    ctx = ToolContext("conv", None, None, None, True, connectors=None)
    result = await tool.run(
        {"summary": "打ち合わせ", "start": "2026-10-22T09:00:00+09:00", "end": "2026-10-22T10:00:00+09:00"},
        ctx,
    )

    assert result.ok is True
    assert captured["connector_id"] == "google_calendar"
    assert captured["method"] == "POST"
    assert captured["json_body"]["start"] == {"dateTime": "2026-10-22T09:00:00+09:00"}
    assert captured["json_body"]["end"] == {"dateTime": "2026-10-22T10:00:00+09:00"}


async def test_calendar_free_busy_surfaces_per_calendar_errors_instead_of_reporting_free() -> None:
    async def fake_request_fn(ctx, connector_id, method, url, *, params=None, json_body=None):
        return {
            "calendars": {
                "primary": {
                    "errors": [{"domain": "global", "reason": "notFound"}],
                    "busy": [],
                }
            }
        }, None

    tool = CalendarFreeBusyTool(request_fn=fake_request_fn)
    ctx = ToolContext("conv", None, None, None, True, connectors=None)
    result = await tool.run(
        {"time_min": "2026-10-22T00:00:00+09:00", "time_max": "2026-10-23T00:00:00+09:00"}, ctx
    )

    assert result.ok is False
    assert "notFound" in result.content
    assert "空いています" not in result.content


async def test_calendar_free_busy_reports_free_when_no_busy_slots() -> None:
    async def fake_request_fn(ctx, connector_id, method, url, *, params=None, json_body=None):
        return {"calendars": {"primary": {"busy": []}}}, None

    tool = CalendarFreeBusyTool(request_fn=fake_request_fn)
    ctx = ToolContext("conv", None, None, None, True, connectors=None)
    result = await tool.run(
        {"time_min": "2026-10-22T00:00:00+09:00", "time_max": "2026-10-23T00:00:00+09:00"}, ctx
    )

    assert result.ok is True
    assert "空いています" in result.content


async def test_google_request_reports_disconnected_without_any_network_call(tmp_path: Path) -> None:
    from yata.tools.google_api import google_request

    connectors = ConnectorRegistry()
    connectors.register(GmailConnector(None, TokenStore(tmp_path)))  # not configured -> no token
    ctx = ToolContext("conv", None, None, None, True, connectors=connectors)

    data, error = await google_request(ctx, "gmail", "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages")
    assert data is None
    assert error is not None
    assert error.ok is False
    assert "接続" in error.content


# --- sending mail always waits for confirmation -------------------------------


async def test_gmail_send_email_only_runs_after_confirmation() -> None:
    sent: list[dict] = []

    async def fake_request_fn(ctx, connector_id, method, url, *, params=None, json_body=None):
        sent.append({"connector_id": connector_id, "method": method, "url": url, "json_body": json_body})
        return {"id": "msg-1"}, None

    tool = GmailSendEmailTool(request_fn=fake_request_fn)
    registry = ToolRegistry()
    registry.register(tool)
    ctx = ToolContext(
        conversation_id="conv",
        memory=None,
        browser=None,
        artifacts_dir=None,
        allow_private_urls=True,
        connectors=None,
    )

    provider = ScriptedProvider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="gmail_send_email",
                        arguments={"to": "a@b.com", "subject": "件名", "body": "本文"},
                    )
                ]
            ),
            LLMResponse(content="送信しました", tool_calls=[]),
        ]
    )

    denied_events = []
    async for event in run_agent(
        messages=[],
        provider=provider,
        model="test",
        registry=registry,
        policy=ToolPolicy(),
        gate=ScriptedGate([False]),
        ctx=ctx,
        max_steps=4,
    ):
        denied_events.append(event)
    assert sent == []  # never sent when the user denies
    assert any(event.type == "confirmation_required" for event in denied_events)

    provider2 = ScriptedProvider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="gmail_send_email",
                        arguments={"to": "a@b.com", "subject": "件名", "body": "本文"},
                    )
                ]
            ),
            LLMResponse(content="送信しました", tool_calls=[]),
        ]
    )
    approved_events = []
    async for event in run_agent(
        messages=[],
        provider=provider2,
        model="test",
        registry=registry,
        policy=ToolPolicy(),
        gate=ScriptedGate([True]),
        ctx=ctx,
        max_steps=4,
    ):
        approved_events.append(event)
    assert len(sent) == 1
    assert sent[0]["method"] == "POST"
    assert any(event.type == "confirmation_required" for event in approved_events)


# --- API surface ---------------------------------------------------------------


def test_connectors_status_endpoint_reports_not_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET_FILE", raising=False)
    settings = Settings(
        yata_db=str(tmp_path / "app.db"),
        yata_model="demo",
        yata_scheduler_enabled=False,
        google_oauth_client_id=None,
        google_oauth_client_secret=None,
        google_oauth_client_secret_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        data = client.get("/api/connectors").json()
        by_id = {item["id"]: item for item in data["connectors"]}
        assert by_id["gmail"]["status"] == "not_configured"
        assert by_id["google_calendar"]["status"] == "not_configured"
        assert by_id["gmail"]["setup_instructions"]

        assert client.post("/api/connectors/gmail/connect").status_code == 400
        assert client.post("/api/connectors/does-not-exist/connect").status_code == 404
        assert client.post("/api/connectors/does-not-exist/disconnect").status_code == 404


def test_connect_builds_an_authorize_url_and_rejects_a_bad_state(tmp_path: Path) -> None:
    settings = Settings(
        yata_db=str(tmp_path / "app.db"),
        yata_model="demo",
        yata_scheduler_enabled=False,
        google_oauth_client_id="test-client",
        google_oauth_client_secret="test-secret",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        connect = client.post("/api/connectors/gmail/connect")
        assert connect.status_code == 200
        url = connect.json()["authorize_url"]
        assert url.startswith("https://accounts.google.com/")
        assert "code_challenge=" in url
        assert "state=" in url

        bad = client.get(
            "/api/connectors/google/oauth/callback",
            params={"code": "abc", "state": "not-a-real-state"},
            follow_redirects=False,
        )
        assert bad.status_code in (302, 307)
        assert "connector_error" in bad.headers["location"]

        status = client.get("/api/connectors").json()
        by_id = {item["id"]: item for item in status["connectors"]}
        assert by_id["gmail"]["status"] == "not_connected"


def test_oauth_callback_completes_and_disconnect_clears_the_token(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        yata_db=str(tmp_path / "app.db"),
        yata_model="demo",
        yata_scheduler_enabled=False,
        google_oauth_client_id="test-client",
        google_oauth_client_secret="test-secret",
    )
    app = create_app(settings)

    async def fake_exchange_code(client, *, code: str, code_verifier: str):
        assert code == "auth-code"
        assert code_verifier
        return TokenSet(access_token="tok", refresh_token="ref", expires_at=time.time() + 3600, scope="s")

    monkeypatch.setattr("yata.connectors.google.exchange_code", fake_exchange_code)

    with TestClient(app) as client:
        connect = client.post("/api/connectors/gmail/connect").json()
        state = connect["authorize_url"].split("state=")[1].split("&")[0]

        callback = client.get(
            "/api/connectors/google/oauth/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )
        assert callback.status_code in (302, 307)
        assert "connector_connected=gmail" in callback.headers["location"]

        status = client.get("/api/connectors").json()
        by_id = {item["id"]: item for item in status["connectors"]}
        assert by_id["gmail"]["status"] == "connected"

        disconnect = client.post("/api/connectors/gmail/disconnect")
        assert disconnect.status_code == 200
        assert disconnect.json()["status"] == "not_connected"

        status_after = client.get("/api/connectors").json()
        by_id_after = {item["id"]: item for item in status_after["connectors"]}
        assert by_id_after["gmail"]["status"] == "not_connected"
