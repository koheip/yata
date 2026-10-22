"""Gemini・OpenAI・Claude 以外の AI（ネットとパソコンの中）と、オフラインモード。通信はモック。"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from yata.api import app as app_module
from yata.api.app import create_app
from yata.config import Settings
from yata.connectors.base import ConnectorRegistry
from yata.connectors.chatwork import ChatworkConnector
from yata.llm.keycheck import KeyCheck, check_key
from yata.llm.openai_provider import AUTO_MODEL, OpenAICompatibleProvider
from yata.llm.providers import CLOUD_PROVIDERS, LOCAL_SERVERS, choose_model
from yata.llm.router import ModelRouter
from yata.llm.types import LLMMessage, ProviderError
from yata.secrets_store import ALLOWED_KEYS
from yata.tools.catalog import build_registry, registry_for_model

KEY = "sk-test-kimi-0123456789"


def settings(tmp_path, **values):
    return Settings(_env_file=None, yata_db=str(tmp_path / "yata.db"), yata_model="demo",
                    yata_scheduler_enabled=False, **values)


def test_choose_model_prefers_known_names():
    assert choose_model(["grok-3", "grok-4-fast-reasoning", "grok-2"], ("grok-4-fast", "grok-3"), "x") == "grok-4-fast-reasoning"
    assert choose_model(["kimi-k2.6", "kimi-k3"], ("kimi-k2.6",), "kimi-k2.6") == "kimi-k2.6"
    assert choose_model([], ("a",), "fallback") == "fallback"


def test_every_provider_setting_can_be_saved_from_the_app():
    for item in CLOUD_PROVIDERS:
        assert item.key_setting in ALLOWED_KEYS and item.model_setting in ALLOWED_KEYS
        assert item.base_url.startswith("https://") and item.key_url.startswith("https://")
    assert {"custom_llm_base_url", "custom_llm_api_key", "custom_llm_model", "yata_offline"} <= set(ALLOWED_KEYS)


def test_router_resolves_cloud_and_local(tmp_path):
    router = ModelRouter(settings(tmp_path, kimi_api_key=KEY, kimi_model="kimi-k3",
                                  custom_llm_base_url="http://192.168.1.5:5000"))
    provider, model = router.resolve("kimi")
    assert isinstance(provider, OpenAICompatibleProvider) and model == "kimi-k3"
    assert provider._base_url == "https://api.moonshot.ai/v1"
    provider, model = router.resolve("lmstudio")
    assert provider._base_url == "http://127.0.0.1:1234/v1" and model == AUTO_MODEL
    provider, model = router.resolve("custom")
    assert provider._base_url == "http://192.168.1.5:5000/v1" and model == AUTO_MODEL
    with pytest.raises(ProviderError):
        router.resolve("deepseek")  # キーがない


def test_offline_blocks_cloud_models(tmp_path):
    router = ModelRouter(settings(tmp_path, gemini_api_key="AIza-test-key-123456", yata_offline=True))
    with pytest.raises(ProviderError, match="オフライン"):
        router.resolve("gemini")
    router.resolve("ollama")  # パソコンの中の AI は使える


def test_tools_are_narrowed_for_offline_and_local():
    connectors = ConnectorRegistry()
    connectors.register(ChatworkConnector(None))
    base = build_registry()
    full = registry_for_model(base, connectors, local_model=False, offline=False).names()
    assert "browser_click" in full and "web_search" in full
    local = registry_for_model(base, connectors, local_model=True, offline=False).names()
    assert "web_search" in local and not any(name.startswith("browser_") for name in local)
    offline = registry_for_model(base, connectors, local_model=True, offline=True).names()
    assert offline == ["save_memory", "jp_calendar", "jp_invoice_tax"]


async def test_auto_model_uses_the_loaded_model(monkeypatch):
    provider = OpenAICompatibleProvider(api_key="local", base_url="http://127.0.0.1:1234/v1", provider_name="LM Studio")
    calls = {}

    class FakeSdk:
        class models:  # noqa: N801
            @staticmethod
            async def list():
                return SimpleNamespace(data=[SimpleNamespace(id="text-embedding-x"), SimpleNamespace(id="qwen3-8b")])

        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                async def create(**request):
                    calls.update(request)
                    message = SimpleNamespace(content="こんにちは", tool_calls=None)
                    return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(provider, "_sdk", lambda: FakeSdk)
    response = await provider.complete([LLMMessage(role="user", content="やあ")], [], model=AUTO_MODEL)
    assert calls["model"] == "qwen3-8b" and response.content == "こんにちは"


async def test_auto_model_without_any_model(monkeypatch):
    provider = OpenAICompatibleProvider(api_key="local", base_url="http://127.0.0.1:1234/v1", provider_name="LM Studio")

    class FakeSdk:
        class models:  # noqa: N801
            @staticmethod
            async def list():
                return SimpleNamespace(data=[])

    monkeypatch.setattr(provider, "_sdk", lambda: FakeSdk)
    with pytest.raises(ProviderError, match="モデルが読み込まれていません"):
        await provider.complete([LLMMessage(role="user", content="やあ")], [], model=AUTO_MODEL)


async def test_keycheck_for_compatible_provider_returns_models():
    def handler(request):
        assert request.url == httpx.URL("https://api.moonshot.ai/v1/models")
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        return httpx.Response(200, json={"data": [{"id": "kimi-k2.6"}, {"id": "kimi-k3"}]})

    result = await check_key("kimi", KEY, transport=httpx.MockTransport(handler))
    assert result.ok is True and result.models == ("kimi-k2.6", "kimi-k3")
    bad = await check_key("kimi", KEY, transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    assert bad.ok is False


def make_client(tmp_path, monkeypatch, reachable=(), **values):
    async def fake_check(provider, key, transport=None):
        return KeyCheck(True, "つながりました。", ("kimi-k3", "kimi-k2.6"))

    async def fake_reachable(urls):
        return {url: url in reachable for url in urls}

    async def fake_ollama(url):
        return False

    monkeypatch.setattr(app_module, "check_key", fake_check)
    monkeypatch.setattr(app_module, "_reachable_many", fake_reachable)
    monkeypatch.setattr(app_module, "_ollama_reachable", fake_ollama)
    return TestClient(create_app(settings(tmp_path, **values)))


def test_saving_a_kimi_key_picks_a_model_and_shows_it(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        ids = [m["id"] for m in client.get("/api/models").json()["models"]]
        assert "kimi" not in ids  # キーがないネットの AI は出さない
        saved = client.put("/api/setup/ai/kimi", json={"key": KEY}).json()
        assert saved["configured"] is True and saved["model"] == "kimi-k2.6"
        models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
        assert models["kimi"]["ready"] is True
        assert KEY not in client.get("/api/setup/ai").text
        removed = client.delete("/api/setup/ai/kimi").json()
        assert removed["configured"] is False and removed["model"] is None


def test_running_local_servers_are_listed(tmp_path, monkeypatch):
    lmstudio = next(s for s in LOCAL_SERVERS if s.id == "lmstudio").default_url
    with make_client(tmp_path, monkeypatch, reachable={lmstudio}) as client:
        ids = [m["id"] for m in client.get("/api/models").json()["models"]]
        assert "lmstudio" in ids and "jan" not in ids and "ollama" in ids
        local = client.get("/api/setup/local").json()
        assert {s["id"]: s["running"] for s in local["servers"]}["lmstudio"] is True
        assert local["offline"] is False


def test_custom_server_and_offline_mode(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch, reachable={"http://192.168.1.5:5000/v1"},
                     gemini_api_key="AIza-test-key-123456") as client:
        assert client.put("/api/setup/local/custom", json={"base_url": "ftp://x"}).status_code == 400
        data = client.put("/api/setup/local/custom", json={
            "base_url": "http://192.168.1.5:5000", "model": "", "api_key": "secret-local-key-1"}).json()
        assert data["custom"]["running"] is True and data["custom"]["has_key"] is True
        assert "secret-local-key-1" not in client.get("/api/setup/local").text
        models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
        assert models["custom"]["ready"] is True and models["gemini"]["ready"] is True

        assert client.put("/api/setup/offline", json={"enabled": True}).json()["offline"] is True
        models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
        assert models["gemini"]["ready"] is False and "オフライン" in models["gemini"]["note"]
        assert models["custom"]["ready"] is True
    # 起動し直しても、オフラインのまま
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/api/setup/local").json()["offline"] is True


def test_offline_refuses_local_servers_that_point_outside(tmp_path):
    from yata.llm.providers import on_premises

    assert on_premises("http://127.0.0.1:1234/v1") and on_premises("http://192.168.1.5:5000")
    assert on_premises("http://localhost:11434") and on_premises("http://[::1]:8080/v1")
    assert not on_premises("https://api.openai.com/v1") and not on_premises("http://8.8.8.8/v1")
    router = ModelRouter(settings(tmp_path, yata_offline=True, custom_llm_base_url="https://api.openai.com/v1",
                                  lmstudio_base_url="http://192.168.0.9:1234/v1"))
    with pytest.raises(ProviderError, match="中のネットワーク"):
        router.resolve("custom")
    router.resolve("lmstudio")


async def test_local_provider_falls_back_to_an_installed_model_and_drops_tools(monkeypatch):
    from yata.llm.types import ToolSpec

    provider = OpenAICompatibleProvider(api_key="ollama", base_url="http://127.0.0.1:11434/v1",
                                        provider_name="Ollama", local=True)
    calls = []

    class FakeSdk:
        class models:  # noqa: N801
            @staticmethod
            async def list():
                return SimpleNamespace(data=[SimpleNamespace(id="gemma3:1b")])

        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                async def create(**request):
                    calls.append(request)
                    if request["model"] == "gemma3:4b":
                        raise RuntimeError("Error code: 404 - model 'gemma3:4b' not found")
                    if "tools" in request:
                        raise RuntimeError("Error code: 400 - registry.ollama.ai/library/gemma3:1b does not support tools")
                    message = SimpleNamespace(content="こんにちは", tool_calls=None)
                    return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(provider, "_sdk", lambda: FakeSdk)
    tools = [ToolSpec(name="web_search", description="d", parameters={"type": "object", "properties": {}})]
    response = await provider.complete([LLMMessage(role="user", content="やあ")], tools, model="gemma3:4b")
    assert response.content == "こんにちは" and calls[-1]["model"] == "gemma3:1b" and "tools" not in calls[-1]


def test_choose_local_models_from_the_app(tmp_path, monkeypatch):
    async def fake_ollama_models(url, timeout=2.0):
        return [{"name": "qwen3:4b", "size_gb": 2.6}, {"name": "llama3.1:8b", "size_gb": 4.9}]

    lmstudio = next(s for s in LOCAL_SERVERS if s.id == "lmstudio").default_url

    async def fake_openai_models(url, timeout=2.0):
        return ["qwen2.5-7b-instruct"]

    monkeypatch.setattr(app_module, "_ollama_models", fake_ollama_models)
    monkeypatch.setattr(app_module, "_openai_models", fake_openai_models)
    with make_client(tmp_path, monkeypatch, reachable={lmstudio}, yata_ollama_model="gemma3:4b") as client:
        local = client.get("/api/setup/local").json()
        assert local["ollama"]["models"] == ["qwen3:4b", "llama3.1:8b"] and local["ollama"]["model"] == "gemma3:4b"
        assert any(item["name"] == "qwen3:4b" for item in local["ollama"]["recommended"])
        assert {s["id"]: s["models"] for s in local["servers"]}["lmstudio"] == ["qwen2.5-7b-instruct"]

        chosen = client.put("/api/setup/local/ollama/model", json={"model": "llama3.1:8b"}).json()
        assert chosen["ollama"]["model"] == "llama3.1:8b"
        models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
        assert models["ollama"]["upstream_model"] == "llama3.1:8b"

        client.put("/api/setup/local/lmstudio/model", json={"model": "qwen2.5-7b-instruct"})
        models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
        assert models["lmstudio"]["upstream_model"] == "qwen2.5-7b-instruct"
        client.put("/api/setup/local/lmstudio/model", json={"model": ""})
        models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
        assert models["lmstudio"]["upstream_model"] == AUTO_MODEL

        assert client.put("/api/setup/local/ollama/model", json={"model": "bad name; rm"}).status_code == 400
        assert client.put("/api/setup/local/nope/model", json={"model": "x"}).status_code == 404
        assert client.post("/api/setup/local/ollama/pull", json={"model": "../../x y"}).status_code == 400
    # 起動し直しても、選んだモデルのまま
    with make_client(tmp_path, monkeypatch, yata_ollama_model="gemma3:4b") as client:
        models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
        assert models["ollama"]["upstream_model"] == "llama3.1:8b"


async def test_ollama_puller_reports_progress():
    import asyncio
    import json as _json

    from yata.llm.local_models import OllamaPuller

    seen = []

    def handler(request):
        seen.append(_json.loads(request.content))
        lines = [{"status": "pulling manifest"}, {"status": "pulling abc", "total": 100, "completed": 40},
                 {"status": "success"}]
        return httpx.Response(200, content="\n".join(_json.dumps(line) for line in lines).encode())

    puller = OllamaPuller()
    puller.start("http://127.0.0.1:11434", "qwen3:4b", transport=httpx.MockTransport(handler))
    assert puller.busy and puller.status["state"] == "running"
    for _ in range(50):
        if not puller.busy:
            break
        await asyncio.sleep(0.01)
    assert puller.status == {"state": "done", "model": "qwen3:4b", "message": "qwen3:4b を入れました。"}
    assert seen == [{"model": "qwen3:4b", "stream": True}]

    failing = OllamaPuller()
    failing.start("http://127.0.0.1:11434", "nope:1b", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=b'{"error":"pull model manifest: file does not exist"}')))
    for _ in range(50):
        if not failing.busy:
            break
        await asyncio.sleep(0.01)
    assert failing.status["state"] == "error"


def test_think_filter_and_no_think():
    from yata.llm.openai_provider import _ThinkFilter, _wants_no_think, _with_no_think

    out = []
    sink = _ThinkFilter(out.append)
    for piece in ["こん", "<thi", "nk>考え中", "…</thi", "nk>にちは", "！"]:
        sink.feed(piece)
    assert "".join(out) == "こんにちは！"
    assert _wants_no_think("qwen3:4b") and not _wants_no_think("qwen3:4b-instruct-2507") and not _wants_no_think("llama3.1:8b")
    payload = _with_no_think([{"role": "system", "content": "あなたはヤタ"}, {"role": "user", "content": "やあ"}])
    assert payload[0]["content"].endswith("/no_think")


async def test_streaming_answer_reaches_the_screen_in_pieces(monkeypatch):
    from yata.agent.loop import run_agent
    from yata.confirm.gate import InMemoryConfirmationGate
    from yata.tools.policy import ToolPolicy
    from yata.tools.registry import ToolRegistry

    provider = OpenAICompatibleProvider(api_key="local", base_url="http://127.0.0.1:11434/v1",
                                        provider_name="Ollama", local=True)
    sent = []

    def chunk(text=None, calls=None):
        delta = SimpleNamespace(content=text, tool_calls=calls)
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    class Stream:
        def __init__(self, chunks):
            self._chunks = chunks

        def __aiter__(self):
            async def gen():
                for item in self._chunks:
                    yield item
            return gen()

    class FakeSdk:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                async def create(**request):
                    sent.append(request)
                    return Stream([chunk("<think>うーん</think>"), chunk("こんに"), chunk("ちは")])

    monkeypatch.setattr(provider, "_sdk", lambda: FakeSdk)
    events = [event async for event in run_agent(
        messages=[LLMMessage(role="system", content="ヤタ"), LLMMessage(role="user", content="やあ")],
        provider=provider, model="qwen3:4b", registry=ToolRegistry(), policy=ToolPolicy(),
        gate=InMemoryConfirmationGate(), ctx=None, max_steps=2,
    )]
    deltas = [e.data["text"] for e in events if e.type == "delta"]
    answer = next(e for e in events if e.type == "answer")
    assert "".join(deltas) == "こんにちは" and answer.data["content"] == "こんにちは"
    assert sent[0]["stream"] is True and sent[0]["messages"][0]["content"].endswith("/no_think")


async def test_streaming_collects_tool_calls(monkeypatch):
    provider = OpenAICompatibleProvider(api_key="k", base_url=None, provider_name="OpenAI")

    def chunk(calls):
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=calls))])

    def call(index, id=None, name=None, args=None):
        return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=args))

    class FakeSdk:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                async def create(**request):
                    async def gen():
                        yield chunk([call(0, "c1", "web_search", '{"que')])
                        yield chunk([call(0, None, None, 'ry": "天気"}')])
                    return gen()

    monkeypatch.setattr(provider, "_sdk", lambda: FakeSdk)
    response = await provider.complete([LLMMessage(role="user", content="天気")], [], model="gpt-x", on_text=lambda t: None)
    assert response.tool_calls[0].name == "web_search" and response.tool_calls[0].arguments == {"query": "天気"}


def test_local_models_get_a_short_prompt():
    from yata.prompts import COMPACT_PROMPT, SYSTEM_PROMPT, build_system_prompt

    assert build_system_prompt([], compact=True).startswith(COMPACT_PROMPT)
    assert build_system_prompt([]).startswith(SYSTEM_PROMPT)
    assert len(COMPACT_PROMPT) < len(SYSTEM_PROMPT) / 3
