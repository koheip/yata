"""この PC のヤタの画面からだけ API を使えることを検証する。"""
import pytest
from fastapi.testclient import TestClient

from yata.api.app import create_app
from yata.api.guard import host_name
from yata.config import Settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YATA_ALLOWED_HOSTS", "127.0.0.1,localhost,::1")
    settings = Settings(_env_file=None, yata_db=str(tmp_path / "yata.db"), yata_model="demo",
                        yata_scheduler_enabled=False)
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8741") as test_client:
        yield test_client


@pytest.mark.parametrize("value, expected", [
    ("127.0.0.1:8741", "127.0.0.1"), ("LOCALHOST:8742", "localhost"), ("[::1]:8741", "::1"),
    ("::1", "::1"), ("evil.example", "evil.example"), ("", ""),
])
def test_host_name(value, expected):
    assert host_name(value) == expected


def test_own_screen_works(client):
    assert client.get("/api/setup/ai").status_code == 200
    assert client.get("/api/setup/ai", headers={"Host": "localhost:8741"}).status_code == 200
    assert client.get("/api/setup/ai", headers={"Host": "[::1]:8741"}).status_code == 200
    created = client.post("/api/bots", json={"name": "係"},
                          headers={"Origin": "http://127.0.0.1:8741", "Sec-Fetch-Site": "same-origin"})
    assert created.status_code == 201
    # 開発用の Vite（8742）からも使える
    assert client.post("/api/bots", json={"name": "係2"}, headers={"Origin": "http://localhost:8742"}).status_code == 201


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8741", "192.168.0.10:8741", "127.0.0.1.nip.io"])
def test_dns_rebinding_is_blocked(client, host):
    response = client.get("/api/setup/ai", headers={"Host": host})
    assert response.status_code == 400 and "127.0.0.1" in response.json()["detail"]
    assert client.get("/", headers={"Host": host}).status_code == 400


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
def test_cross_site_writes_are_blocked(client, headers):
    routine = client.post("/api/routines", json={"name": "x", "prompt": "y", "preset": "hourly", "model_id": "demo"}).json()
    response = client.post(f"/api/routines/{routine['id']}/pause", headers=headers)
    assert response.status_code == 403
    assert client.get("/api/routines").json()["routines"][0]["enabled"] is True
    assert client.delete(f"/api/routines/{routine['id']}", headers=headers).status_code == 403
    # 読むだけなら（画面の表示やリンク）断らない
    assert client.get("/api/routines", headers=headers).status_code == 200


def test_oauth_callback_redirect_still_works(client):
    # Google などから戻ってくるときは、ほかのサイトからの GET になる
    response = client.get("/api/connectors/google/oauth/callback?state=x&code=y",
                          headers={"Sec-Fetch-Site": "cross-site"}, follow_redirects=False)
    assert response.status_code in (302, 307)
