"""画面から API キーを入れて AI をつなぐ流れを検証する（ネットワークなし）。"""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from yata.api import app as app_module
from yata.api.app import create_app
from yata.config import Settings
from yata.llm.keycheck import KeyCheck, check_key
from yata.secrets_store import SecretStore

KEY = "AIzaTestKey-1234567890abcdef"
OK = KeyCheck(True, "つながりました。")


def make_client(tmp_path, monkeypatch, result=OK, **settings):
    checked = []

    async def fake_check(provider, key, transport=None):
        checked.append((provider, key))
        return result

    monkeypatch.setattr(app_module, "check_key", fake_check)
    config = Settings(_env_file=None, yata_db=str(tmp_path / "yata.db"), yata_model="demo",
                      yata_scheduler_enabled=False, **settings)
    return TestClient(create_app(config)), checked


def test_setup_lists_providers_without_keys(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    with client:
        data = client.get("/api/setup/ai").json()
    assert data["needs_setup"] is True
    ids = [p["id"] for p in data["providers"]]
    assert ids[:3] == ["gemini", "openai", "anthropic"]
    assert {"xai", "deepseek", "kimi", "mistral", "groq", "openrouter", "plamo"} <= set(ids)
    assert all(p["more"] for p in data["providers"][3:]) and not any(p["more"] for p in data["providers"][:3])
    gemini = data["providers"][0]
    assert gemini["configured"] is False and gemini["source"] is None
    assert gemini["key_url"].startswith("https://aistudio.google.com/") and len(gemini["steps"]) == 3


def test_saving_a_key_makes_the_model_ready_without_restart(tmp_path, monkeypatch):
    client, checked = make_client(tmp_path, monkeypatch)
    with client:
        before = {m["id"]: m["ready"] for m in client.get("/api/models").json()["models"]}
        assert before["gemini"] is False
        response = client.put("/api/setup/ai/gemini", json={"key": f"  {KEY}\n"})
        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is True and body["source"] == "app" and body["verified"] is True
        assert KEY not in response.text
        after = {m["id"]: m["ready"] for m in client.get("/api/models").json()["models"]}
        assert after["gemini"] is True
        assert client.get("/api/setup/ai").json()["needs_setup"] is False
        assert KEY not in client.get("/api/setup/ai").text
    assert checked == [("gemini", KEY)]  # 前後の空白や改行は取り除いてから確かめる
    stored = json.loads((tmp_path / "secrets.json").read_text(encoding="utf-8"))
    assert stored == {"gemini_api_key": KEY}

    # 起動し直しても、保存したキーが使われる
    again, _ = make_client(tmp_path, monkeypatch)
    with again:
        models = {m["id"]: m["ready"] for m in again.get("/api/models").json()["models"]}
        assert models["gemini"] is True


def test_invalid_key_is_not_saved(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch, result=KeyCheck(False, "このキーは使えませんでした。"))
    with client:
        response = client.put("/api/setup/ai/gemini", json={"key": KEY})
        assert response.status_code == 400 and "使えませんでした" in response.json()["detail"]
        assert client.get("/api/setup/ai").json()["needs_setup"] is True
        assert client.put("/api/setup/ai/gemini", json={"key": "short"}).status_code == 400
        assert client.put("/api/setup/ai/unknown", json={"key": KEY}).status_code == 404
    assert not (tmp_path / "secrets.json").exists()


def test_unverified_key_is_saved_with_a_note(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch, result=KeyCheck(None, "確かめられませんでした。"))
    with client:
        body = client.put("/api/setup/ai/openai", json={"key": "sk-test-abcdefghijkl"}).json()
    assert body["configured"] is True and body["verified"] is None and "保存しました" in body["message"]


def test_env_key_and_removal(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch, gemini_api_key="env-key-1234567890")
    with client:
        gemini = client.get("/api/setup/ai").json()["providers"][0]
        assert gemini["source"] == "env"
        client.put("/api/setup/ai/gemini", json={"key": KEY})
        assert client.get("/api/setup/ai").json()["providers"][0]["source"] == "app"
        removed = client.delete("/api/setup/ai/gemini").json()
        assert removed["source"] == "env"  # 画面のキーを外すと、.env のキーに戻る
        models = {m["id"]: m["ready"] for m in client.get("/api/models").json()["models"]}
        assert models["gemini"] is True
    assert SecretStore(tmp_path / "secrets.json").load() == {}


def test_secret_store_ignores_unknown_and_broken(tmp_path):
    path = tmp_path / "secrets.json"
    path.write_text('{"gemini_api_key": "k", "other": "x", "openai_api_key": 3}', encoding="utf-8")
    assert SecretStore(path).load() == {"gemini_api_key": "k"}
    path.write_text("not json", encoding="utf-8")
    assert SecretStore(path).load() == {}
    with pytest.raises(KeyError):
        SecretStore(path).set("yata_db", "x")


@pytest.mark.parametrize("status, ok", [(200, True), (429, True), (400, False), (401, False), (403, False), (500, None)])
@pytest.mark.parametrize("provider", ["gemini", "openai", "anthropic"])
async def test_check_key_statuses(provider, status, ok):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status, json={})

    result = await check_key(provider, KEY, transport=httpx.MockTransport(handler))
    assert result.ok is ok and KEY not in result.message
    sent = seen[0]
    assert sent.method == "GET" and "?key=" not in str(sent.url)  # キーは URL に入れない
    assert KEY in " ".join(sent.headers.values())


async def test_check_key_network_error():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    result = await check_key("gemini", KEY, transport=httpx.MockTransport(handler))
    assert result.ok is None and "インターネット" in result.message
