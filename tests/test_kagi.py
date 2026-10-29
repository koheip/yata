"""kagi（シークレット・ブローカー）経由の LLM 呼び出し。通信はモック。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from yata.config import Settings
from yata.llm import kagi
from yata.llm.errors import humanize_provider_error
from yata.llm.kagi import KagiAuth, KagiError
from yata.llm.openai_provider import OpenAICompatibleProvider
from yata.llm.router import ModelRouter
from yata.llm.types import LLMMessage, ProviderError

BROKER = "https://kagi.test:8443"
BASE = f"{BROKER}/v1/proxy/openai/v1"


def settings(tmp_path, **values):
    return Settings(_env_file=None, yata_db=str(tmp_path / "yata.db"), yata_model="demo",
                    yata_scheduler_enabled=False, **values)


class FakeBroker:
    """kagi のふり。/v1/token でトークンを出し、プロキシではそのトークンを確かめる。"""

    def __init__(self, ttl=timedelta(minutes=10)):
        self.ttl = ttl
        self.issued: list[str] = []
        self.seen_auth: list[str] = []
        self.renew_next = False
        self.upstream_429_next = False
        self.deny_tokens = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/token":
            if self.deny_tokens:
                return httpx.Response(403, json={"error": "not permitted by policy"})
            body = json.loads(request.content)
            assert body["upstream"] == "openai" and body["purpose"]
            token = f"kagi_v1.token{len(self.issued)}"
            self.issued.append(token)
            expires = datetime.now(UTC) + self.ttl
            return httpx.Response(200, json={"token": token, "token_id": "id",
                                             "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ")})
        auth = request.headers.get("authorization", "")
        self.seen_auth.append(auth)
        if auth != f"Bearer {self.issued[-1]}":
            return httpx.Response(401, json={"error": "bad token"})
        if self.renew_next:
            self.renew_next = False
            return httpx.Response(429, headers={"X-Kagi-Token": "renew"},
                                  json={"error": "token request budget exhausted"})
        if self.upstream_429_next:  # 上流の API 自身の 429（kagi のヘッダーなし）
            self.upstream_429_next = False
            return httpx.Response(429, json={"error": {"message": "Rate limit reached"}})
        assert request.url.path == "/v1/proxy/openai/v1/chat/completions"
        return httpx.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "こんにちは"}}],
        })


def client(broker: FakeBroker) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(broker), auth=KagiAuth(BROKER, "openai"))


async def test_token_is_fetched_once_and_replaces_the_placeholder_key():
    broker = FakeBroker()
    async with client(broker) as http:
        for _ in range(3):
            response = await http.post(f"{BASE}/chat/completions", json={},
                                       headers={"Authorization": "Bearer kagi-managed"})
            assert response.status_code == 200
    assert broker.issued == ["kagi_v1.token0"]
    assert broker.seen_auth == ["Bearer kagi_v1.token0"] * 3


async def test_token_is_refreshed_before_it_expires():
    broker = FakeBroker()
    auth = KagiAuth(BROKER, "openai")
    async with httpx.AsyncClient(transport=httpx.MockTransport(broker), auth=auth) as http:
        await http.post(f"{BASE}/chat/completions", json={})
        auth.now = lambda: datetime.now(UTC).timestamp() + 600 - 10  # 期限の10秒前
        await http.post(f"{BASE}/chat/completions", json={})
    assert len(broker.issued) == 2


async def test_renews_only_when_kagi_says_so():
    broker = FakeBroker()
    async with client(broker) as http:
        broker.renew_next = True
        response = await http.post(f"{BASE}/chat/completions", json={})
        assert response.status_code == 200 and len(broker.issued) == 2
        # 上流の API の 429 では取り直さない（トークンを無駄に発行しない）
        broker.upstream_429_next = True
        response = await http.post(f"{BASE}/chat/completions", json={})
        assert response.status_code == 429 and len(broker.issued) == 2


async def test_refused_token_raises_a_clear_error():
    broker = FakeBroker()
    broker.deny_tokens = True
    async with client(broker) as http:
        with pytest.raises(KagiError, match="ポリシー"):
            await http.post(f"{BASE}/chat/completions", json={})


async def test_provider_talks_through_kagi_without_a_real_key():
    broker = FakeBroker()
    provider = OpenAICompatibleProvider(api_key="kagi-managed", base_url=BASE,
                                        provider_name="kagi", http_client=client(broker))
    response = await provider.complete([LLMMessage(role="user", content="やあ")], [], model="gpt-4o-mini")
    assert response.content == "こんにちは"
    assert all("kagi-managed" not in auth for auth in broker.seen_auth)


def test_router_lists_kagi_only_when_configured(tmp_path):
    by_id = {item.id: item for item in ModelRouter(settings(tmp_path)).catalog()}
    assert not by_id["kagi"].ready and "KAGI_URL" in (by_id["kagi"].note or "")
    with pytest.raises(ProviderError):
        ModelRouter(settings(tmp_path)).resolve("kagi")


def test_router_builds_the_kagi_provider(tmp_path, monkeypatch):
    made = {}

    def fake_client(**kwargs):
        made.update(kwargs)
        return "http-client"

    monkeypatch.setattr(kagi, "kagi_http_client", fake_client)
    values = dict(kagi_url="https://kagi.test:8443/", kagi_ca_file="ca.crt", kagi_cert_file="yata.crt",
                  kagi_key_file="yata.key", kagi_model="gpt-4.1-mini")
    provider, model = ModelRouter(settings(tmp_path, **values)).resolve("kagi")
    assert isinstance(provider, OpenAICompatibleProvider) and model == "gpt-4.1-mini"
    assert provider._base_url == BASE and provider._http_client == "http-client"
    assert made["upstream"] == "openai" and made["cert_file"] == "yata.crt"

    with pytest.raises(ProviderError, match="https"):
        ModelRouter(settings(tmp_path, **{**values, "kagi_url": "http://kagi.test"})).resolve("kagi")
    with pytest.raises(ProviderError, match="KAGI_UPSTREAM"):
        ModelRouter(settings(tmp_path, **values, kagi_upstream="../admin")).resolve("kagi")


def test_missing_certificate_files_give_a_japanese_error(tmp_path):
    values = dict(kagi_url="https://kagi.test", kagi_ca_file=str(tmp_path / "none.crt"),
                  kagi_cert_file=str(tmp_path / "none.crt"), kagi_key_file=str(tmp_path / "none.key"))
    with pytest.raises(ProviderError, match="証明書"):
        ModelRouter(settings(tmp_path, **values)).resolve("kagi")


def test_kagi_refusals_do_not_blame_the_env_key():
    message = humanize_provider_error("kagi", Exception("Error code: 403 - endpoint not allowed by policy"))
    assert "ポリシー" in message and ".env" not in message


def test_auth_matches_the_http_library_the_openai_sdk_uses():
    """SDK が httpx2 を使う版でも、kagi の認証を受け付けること（実機の結合テストで見つかった不具合）。"""
    from openai import DefaultAsyncHttpxClient

    http = kagi._sdk_http_module()
    auth = kagi._auth_class(http)(BROKER, "openai")
    assert isinstance(auth, http.Auth)
    DefaultAsyncHttpxClient(auth=auth)  # TypeError にならない


async def test_provider_works_with_the_sdk_http_library():
    broker = FakeBroker()
    http = kagi._sdk_http_module()


    async def handler(request):
        await request.aread()
        return http.Response(**_as_kwargs(broker(request)))

    sdk_client = http.AsyncClient(transport=http.MockTransport(handler), auth=kagi._auth_class(http)(BROKER, "openai"))
    provider = OpenAICompatibleProvider(api_key="kagi-managed", base_url=BASE,
                                        provider_name="kagi", http_client=sdk_client)
    response = await provider.complete([LLMMessage(role="user", content="やあ")], [], model="gpt-4o-mini")
    assert response.content == "こんにちは" and broker.issued == ["kagi_v1.token0"]


def _as_kwargs(response: httpx.Response) -> dict:
    """テスト用の偽 kagi（httpx の Response）を、SDK 側のライブラリの Response に移しかえる。"""
    return {"status_code": response.status_code, "headers": dict(response.headers), "content": response.content}
