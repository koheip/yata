"""連携（Chatwork・楽天・LINE・freee・Google）を画面から設定する流れを検証する（ネットワークなし）。"""
import httpx
import pytest
from fastapi.testclient import TestClient

from yata.api import app as app_module
from yata.api.app import create_app
from yata.config import Settings
from yata.connectors.setup import check_line_token
from yata.secrets_store import SecretStore

TOKEN = "chatwork-token-1234567890"


@pytest.fixture
def chatwork_me(monkeypatch):
    """Chatwork の GET /me を差し替える。status を変えると、トークンの正しさが変わる。"""
    state = {"status": 200}
    client_type = httpx.Client

    def make_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(state["status"], json={"name": "テスト"}))
        return client_type(**kwargs)

    monkeypatch.setattr("yata.connectors.chatwork.httpx.Client", make_client)
    return state


def make_client(tmp_path, **settings):
    config = Settings(_env_file=None, yata_db=str(tmp_path / "yata.db"), yata_model="demo",
                      yata_scheduler_enabled=False, **settings)
    return TestClient(create_app(config))


def statuses(client):
    return {c["id"]: c["status"] for c in client.get("/api/connectors").json()["connectors"]}


def test_setup_list_describes_every_connector(tmp_path):
    with make_client(tmp_path) as client:
        data = client.get("/api/setup/connectors").json()
    ids = [s["id"] for s in data["setups"]]
    assert ids == ["chatwork", "line", "backlog", "kintone", "rakuten", "freee", "moneyforward", "google"]
    assert data["connector_to_setup"]["gmail"] == "google"
    for setup in data["setups"]:
        assert setup["steps"] and setup["key_url"].startswith("https://")
        assert setup["configured"] is False and setup["from_app"] is False
    freee = next(s for s in data["setups"] if s["id"] == "freee")
    assert any("/api/connectors/freee/oauth/callback" in step for step in freee["steps"])


def test_chatwork_token_is_checked_saved_and_used_right_away(tmp_path, chatwork_me):
    with make_client(tmp_path) as client:
        assert statuses(client)["chatwork"] == "not_configured"
        response = client.put("/api/setup/connectors/chatwork", json={"values": {"chatwork_api_token": f" {TOKEN} "}})
        assert response.status_code == 200 and TOKEN not in response.text
        assert response.json()["configured"] is True and response.json()["from_app"] is True
        assert statuses(client)["chatwork"] == "connected"
        assert TOKEN not in client.get("/api/setup/connectors").text
    assert SecretStore(tmp_path / "secrets.json").load() == {"chatwork_api_token": TOKEN}

    # 起動し直しても使える
    with make_client(tmp_path) as client:
        assert statuses(client)["chatwork"] == "connected"
        # 外すと未設定に戻る
        removed = client.delete("/api/setup/connectors/chatwork").json()
        assert removed["configured"] is False
        assert statuses(client)["chatwork"] == "not_configured"


def test_wrong_chatwork_token_is_rolled_back(tmp_path, chatwork_me):
    chatwork_me["status"] = 401
    with make_client(tmp_path) as client:
        response = client.put("/api/setup/connectors/chatwork", json={"values": {"chatwork_api_token": TOKEN}})
        assert response.status_code == 400 and "使えませんでした" in response.json()["detail"]
        assert statuses(client)["chatwork"] == "not_configured"
    assert SecretStore(tmp_path / "secrets.json").load() == {}


def test_rakuten_requires_both_values_and_keeps_existing_ones(tmp_path):
    with make_client(tmp_path) as client:
        missing = client.put("/api/setup/connectors/rakuten", json={"values": {"rakuten_application_id": "1234"}})
        assert missing.status_code == 400 and "アクセスキー" in missing.json()["detail"]
        ok = client.put("/api/setup/connectors/rakuten",
                        json={"values": {"rakuten_application_id": "1234", "rakuten_access_key": "pk_abc", "rakuten_affiliate_id": ""}})
        assert ok.status_code == 200
        assert statuses(client)["rakuten"] == "connected"
        # 空欄で送った項目は、今の値をそのまま使う
        again = client.put("/api/setup/connectors/rakuten", json={"values": {"rakuten_application_id": "5678", "rakuten_access_key": ""}})
        assert again.status_code == 200
    assert SecretStore(tmp_path / "secrets.json").load() == {"rakuten_application_id": "5678", "rakuten_access_key": "pk_abc"}


def test_bad_requests(tmp_path):
    with make_client(tmp_path) as client:
        assert client.put("/api/setup/connectors/unknown", json={"values": {}}).status_code == 404
        assert client.put("/api/setup/connectors/chatwork", json={"values": {"gemini_api_key": "x"}}).status_code == 400
        assert client.put("/api/setup/connectors/chatwork", json={"values": {"chatwork_api_token": "x" * 401}}).status_code == 400


def test_line_needs_restart_and_rejects_bad_token(tmp_path, monkeypatch):
    results = {"value": False}
    monkeypatch.setattr(app_module, "check_line_token", lambda token: results["value"])
    values = {"line_channel_access_token": "line-token-123", "line_channel_secret": "secret-abc",
              "line_allowed_user_ids": "U123"}
    with make_client(tmp_path) as client:
        bad = client.put("/api/setup/connectors/line", json={"values": values})
        assert bad.status_code == 400
        results["value"] = None  # 確かめられないときは保存する
        ok = client.put("/api/setup/connectors/line", json={"values": values})
        assert ok.status_code == 200 and "起動し直して" in ok.json()["message"]
        assert statuses(client)["line"] == "connected"


def test_oauth_clients_can_be_entered_on_screen(tmp_path):
    with make_client(tmp_path) as client:
        response = client.put("/api/setup/connectors/google", json={"values": {
            "google_oauth_client_id": "abc.apps.googleusercontent.com", "google_oauth_client_secret": "GOCSPX-x"}})
        assert response.status_code == 200 and "接続する" in response.json()["message"]
        state = statuses(client)
        assert state["gmail"] == "not_connected" and state["google_calendar"] == "not_connected"
        url = client.post("/api/connectors/gmail/connect").json()["authorize_url"]
        assert "client_id=abc.apps.googleusercontent.com" in url
        client.put("/api/setup/connectors/freee", json={"values": {"freee_client_id": "id", "freee_client_secret": "sec"}})
        assert statuses(client)["freee"] == "not_connected"


def test_env_value_counts_as_configured(tmp_path):
    with make_client(tmp_path, chatwork_api_token="from-env-token") as client:
        chatwork = client.get("/api/setup/connectors").json()["setups"][0]
        assert chatwork["configured"] is True and chatwork["fields"][0]["source"] == "env"
        assert "from-env-token" not in client.get("/api/setup/connectors").text


@pytest.mark.parametrize("status, expected", [(200, True), (401, False), (403, False), (500, None)])
def test_check_line_token(status, expected):
    transport = httpx.MockTransport(lambda request: httpx.Response(status))
    assert check_line_token("t", transport=transport) is expected


def test_check_line_token_offline():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    assert check_line_token("t", transport=httpx.MockTransport(handler)) is None
