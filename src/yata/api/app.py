"""FastAPI application: conversations, streaming agent turns, and the built UI."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import signal
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from yata.agent.loop import run_agent, seal_open_tool_calls
from yata.api.guard import LocalOnlyGuard
from yata.bots import BOT_ACCESSORIES, BOT_COLORS, DEFAULT_BOT_ID, BotError, pick_look
from yata.config import Settings, key_ready
from yata.confirm.gate import InMemoryConfirmationGate
from yata.connectors.backlog import normalize_space
from yata.connectors.base import Connector, ConnectorState
from yata.connectors.catalog import build_connector_registry
from yata.connectors.kintone import normalize_domain
from yata.connectors.oauth_state import OAuthStateStore
from yata.connectors.pkce import challenge_for, new_verifier
from yata.connectors.setup import CONNECTOR_TO_SETUP, check_line_token, connector_setups
from yata.line.bridge import LineBridge
from yata.line.client import LineClient
from yata.llm.keycheck import check_key
from yata.llm.local_models import MODEL_NAME, RECOMMENDED_OLLAMA, OllamaPuller
from yata.llm.local_models import ollama_models as _ollama_models
from yata.llm.local_models import openai_models as _openai_models
from yata.llm.openai_provider import ollama_root
from yata.llm.providers import (
    CLOUD_PROVIDERS,
    LOCAL_SERVERS,
    choose_model,
    cloud_provider,
    local_server,
    on_premises,
    openai_base,
)
from yata.llm.router import OFFLINE_NOTE, OFFLINE_REMOTE_NOTE, ModelInfo, ModelRouter
from yata.llm.types import LLMMessage, ProviderError
from yata.memory.store import Bot, MemoryStore, to_transcript
from yata.prompts import build_system_prompt
from yata.routines.repository import Routine, RoutineRepository, RoutineRun
from yata.routines.schedule import (
    ScheduleError,
    parse_routine_utterance,
    preset_list,
    schedule_label,
)
from yata.routines.scheduler import RoutineScheduler
from yata.routines.service import RoutineService
from yata.secrets_store import ALLOWED_KEYS as SECRET_KEYS
from yata.secrets_store import SecretStore
from yata.tools.base import ToolContextFactory
from yata.tools.browser import BrowserSession
from yata.tools.catalog import build_registry
from yata.tools.policy import ToolPolicy

logger = logging.getLogger(__name__)
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class CreateConversation(BaseModel):
    model_id: str | None = None
    title: str | None = Field(default=None, max_length=80)
    bot_id: str | None = Field(default=None, max_length=64)


class SaveAiKey(BaseModel):
    key: str = Field(max_length=400)


class SaveConnectorSetup(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


# 画面の「AI をつなぐ」に出す説明。キーの取り方は、一般の人が迷わない順に書く。
AI_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "gemini",
        "setting": "gemini_api_key",
        "label": "Google Gemini",
        "badge": "無料で使えます",
        "key_url": "https://aistudio.google.com/apikey",
        "steps": [
            "下のボタンで Google AI Studio を開き、Google アカウントでログインします。",
            "「API キーを作成」を押します。",
            "表示されたキーをコピーして、この下に貼り付けます。",
        ],
    },
    {
        "id": "openai",
        "setting": "openai_api_key",
        "label": "OpenAI（ChatGPT）",
        "badge": "使った分だけ料金がかかります",
        "key_url": "https://platform.openai.com/api-keys",
        "steps": [
            "下のボタンで OpenAI の API キーのページを開き、ログインします。",
            "「Create new secret key」を押します。",
            "表示されたキー（sk- で始まります）をコピーして、この下に貼り付けます。",
        ],
    },
    {
        "id": "anthropic",
        "setting": "anthropic_api_key",
        "label": "Anthropic（Claude）",
        "badge": "使った分だけ料金がかかります",
        "key_url": "https://console.anthropic.com/settings/keys",
        "steps": [
            "下のボタンで Anthropic Console の API キーのページを開き、ログインします。",
            "「Create Key」を押します。",
            "表示されたキー（sk-ant- で始まります）をコピーして、この下に貼り付けます。",
        ],
    },
]


AI_PROVIDERS += [
    {"id": item.id, "setting": item.key_setting, "model_setting": item.model_setting, "label": item.label,
     "badge": item.badge, "key_url": item.key_url, "steps": list(item.steps), "more": True}
    for item in CLOUD_PROVIDERS
]


class SaveCustomLlm(BaseModel):
    base_url: str = Field(max_length=400)
    model: str = Field(default="", max_length=200)
    api_key: str = Field(default="", max_length=400)


class ChooseLocalModel(BaseModel):
    model: str = Field(default="", max_length=120)


class SetOffline(BaseModel):
    enabled: bool


class CreateBot(BaseModel):
    name: str = Field(max_length=80)
    job: str | None = Field(default=None, max_length=400)
    color: str | None = Field(default=None, max_length=20)
    accessory: str | None = Field(default=None, max_length=20)


class UpdateBot(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    job: str | None = Field(default=None, max_length=400)
    color: str | None = Field(default=None, max_length=20)
    accessory: str | None = Field(default=None, max_length=20)


class UpdateConversation(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    model_id: str | None = None


class SendMessage(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    model_id: str | None = None


class ResolveConfirmation(BaseModel):
    approved: bool


class SetRoutineNotifyLine(BaseModel):
    enabled: bool


class CreateRoutine(BaseModel):
    notify_line: bool = False
    name: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=8000)
    preset: str | None = None
    schedule: str | None = Field(default=None, max_length=80)
    schedule_kind: str | None = None
    timezone: str | None = Field(default=None, max_length=64)
    model_id: str | None = None
    bot_id: str | None = Field(default=None, max_length=64)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    memory = MemoryStore(settings.database_path())
    browser = BrowserSession()
    gate = InMemoryConfirmationGate()
    registry = build_registry()
    # 画面から入れた API キーや連携の値を読み込む。.env の値より優先する。
    secrets = SecretStore(settings.database_path().parent / "secrets.json")
    env_keys = {name: getattr(settings, name) for name in SECRET_KEYS}
    for name, value in secrets.load().items():
        setattr(settings, name, value == "true" if name == "yata_offline" else value)
    connectors = build_connector_registry(settings)
    oauth_states = OAuthStateStore()
    setups = connector_setups(settings.yata_port)
    model_router = ModelRouter(settings)
    ollama_puller = OllamaPuller()
    artifacts = settings.artifacts_dir()
    line = connectors.get("line")
    line_bridge = (
        LineBridge(memory, model_router, registry, gate, connectors, settings, browser, artifacts,
                   LineClient(settings.line_channel_access_token.strip()))
        if line is not None and line.status() == ConnectorState.CONNECTED else None
    )
    routine_repo = RoutineRepository(settings.database_path())
    routines = RoutineService(
        memory=memory,
        routines=routine_repo,
        router=model_router,
        registry=registry,
        gate=gate,
        browser=browser,
        artifacts_dir=artifacts,
        allow_private_urls=settings.yata_allow_private_urls,
        max_steps=settings.yata_max_steps,
        confirm_timeout=settings.yata_routine_confirm_timeout,
        default_timezone=settings.yata_timezone,
        connectors=connectors,
        notifier=line_bridge.push_to_owner if line_bridge is not None else None,
    )
    scheduler = (
        RoutineScheduler(routines, settings.yata_scheduler_interval_seconds)
        if settings.yata_scheduler_enabled
        else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if scheduler is not None:
            await scheduler.start()
        try:
            yield
        finally:
            if app.state.line_bridge is not None:
                await app.state.line_bridge.close()
            if scheduler is not None:
                await scheduler.stop()
            await browser.close()

    app = FastAPI(title="ヤタ Yata", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:8742",
            "http://localhost:8742",
            "http://127.0.0.1:8741",
            "http://localhost:8741",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # いちばん外側で、ホスト名とほかのサイトからの書き込みを確かめる。
    app.add_middleware(LocalOnlyGuard, allowed_hosts=settings.allowed_hosts())
    app.state.settings = settings
    app.state.memory = memory
    app.state.browser = browser
    app.state.gate = gate
    app.state.registry = registry
    app.state.connectors = connectors
    app.state.model_router = model_router
    app.state.artifacts = artifacts
    app.state.routines = routines
    app.state.line_bridge = line_bridge

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "name": "yata"}

    @app.post("/api/app/quit")
    def quit_app() -> dict[str, Any]:
        # ヤタを終わらせる。画面を閉じてもヤタは動き続けるので（ルーティンのため）、
        # 終わらせたいときは設定のボタンからここを呼ぶ。
        threading.Timer(0.3, signal.raise_signal, args=(signal.SIGINT,)).start()
        return {"ok": True}

    @app.get("/api/models")
    async def list_models() -> dict[str, Any]:
        models = await _visible_models(model_router, settings)
        return {
            "default_model_id": settings.yata_model,
            "models": [_model_dict(model) for model in models],
        }

    @app.get("/api/conversations")
    def list_conversations(bot_id: str | None = None) -> dict[str, Any]:
        return {
            "conversations": [_conversation_dict(item) for item in memory.list_conversations(bot_id)],
        }

    @app.post("/api/conversations", status_code=201)
    def create_conversation(body: CreateConversation) -> dict[str, Any]:
        model_id = body.model_id or settings.yata_model
        _known_model(model_router, model_id)
        bot_id = _require_bot(memory, body.bot_id or DEFAULT_BOT_ID).id
        title = body.title.strip() if body.title else "新しい会話"
        conversation = memory.create_conversation(model_id, title or "新しい会話", bot_id=bot_id)
        return _conversation_dict(conversation)

    def ai_provider_dict(item: dict[str, Any]) -> dict[str, Any]:
        name = item["setting"]
        stored = secrets.get(name)
        source = "app" if stored else ("env" if key_ready(env_keys.get(name)) else None)
        return {
            "id": item["id"],
            "label": item["label"],
            "badge": item["badge"],
            "key_url": item["key_url"],
            "steps": item["steps"],
            "configured": source is not None,
            "source": source,
            "more": bool(item.get("more")),
            "model": getattr(settings, item["model_setting"]) if item.get("model_setting") else None,
        }

    @app.get("/api/setup/ai")
    def ai_setup() -> dict[str, Any]:
        providers = [ai_provider_dict(item) for item in AI_PROVIDERS]
        return {"providers": providers, "needs_setup": not any(p["configured"] for p in providers)}

    @app.put("/api/setup/ai/{provider_id}")
    async def save_ai_key(provider_id: str, body: SaveAiKey) -> dict[str, Any]:
        item = next((entry for entry in AI_PROVIDERS if entry["id"] == provider_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="その AI は選べません。")
        key = "".join(body.key.split())
        if len(key) < 10:
            raise HTTPException(status_code=400, detail="キーが短すぎます。コピーしたキーを全部貼り付けてください。")
        result = await check_key(provider_id, key)
        if result.ok is False:
            raise HTTPException(status_code=400, detail=result.message)
        secrets.set(item["setting"], key)
        setattr(settings, item["setting"], key)
        cloud = cloud_provider(provider_id)
        if cloud is not None and not key_ready(env_keys.get(cloud.model_setting)):
            # モデル名は変わりやすいので、相手の一覧から選んで覚えておく。
            model = choose_model(result.models, cloud.prefer, cloud.default_model)
            secrets.set(cloud.model_setting, model)
            setattr(settings, cloud.model_setting, model)
        message = result.message if result.ok else f"{result.message}キーは保存しました。動かなければキーを見直してください。"
        return {**ai_provider_dict(item), "verified": result.ok, "message": message}

    @app.delete("/api/setup/ai/{provider_id}")
    def remove_ai_key(provider_id: str) -> dict[str, Any]:
        item = next((entry for entry in AI_PROVIDERS if entry["id"] == provider_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="その AI は選べません。")
        secrets.delete(item["setting"])
        setattr(settings, item["setting"], env_keys.get(item["setting"]))
        if item.get("model_setting") and secrets.delete(item["model_setting"]):
            setattr(settings, item["model_setting"], env_keys.get(item["model_setting"]))
        return ai_provider_dict(item)

    async def local_setup_dict() -> dict[str, Any]:
        urls = {server.id: model_router.local_base_url(server.id) or "" for server in LOCAL_SERVERS}
        running = await _reachable_many(list(urls.values()))
        custom_url = (settings.custom_llm_base_url or "").strip()
        installed = await _ollama_models(settings.ollama_base_url)
        server_models = {
            server.id: (await _openai_models(urls[server.id])) or [] if running[urls[server.id]] else []
            for server in LOCAL_SERVERS
        }
        return {
            "offline": bool(settings.yata_offline),
            "ollama": {
                "url": settings.ollama_base_url, "running": installed is not None,
                "models": [item["name"] for item in installed or []],
                "sizes": {item["name"]: item["size_gb"] for item in installed or []},
                "model": (settings.yata_ollama_model or "").strip(),
                "recommended": list(RECOMMENDED_OLLAMA),
                "pull": ollama_puller.status,
            },
            "servers": [
                {"id": server.id, "label": server.label, "url": urls[server.id], "site": server.site,
                 "how": server.how, "running": running[urls[server.id]], "models": server_models[server.id],
                 "model": (getattr(settings, server.model_setting) or "").strip()}
                for server in LOCAL_SERVERS
            ],
            "custom": {
                "base_url": custom_url, "model": (settings.custom_llm_model or "").strip(),
                "has_key": bool((settings.custom_llm_api_key or "").strip()),
                "running": (await _reachable_many([openai_base(custom_url)]))[openai_base(custom_url)] if custom_url else False,
            },
        }

    @app.get("/api/setup/local")
    async def local_setup() -> dict[str, Any]:
        return await local_setup_dict()

    @app.put("/api/setup/local/{server_id}/model")
    async def choose_local_model(server_id: str, body: ChooseLocalModel) -> dict[str, Any]:
        """パソコンの中の AI で使うモデルを選ぶ。空にすると、読み込まれているモデルを使う。"""
        name = "yata_ollama_model" if server_id == "ollama" else getattr(local_server(server_id), "model_setting", None)
        if name is None:
            raise HTTPException(status_code=404, detail="その AI は選べません。")
        model = body.model.strip()
        if model and not MODEL_NAME.match(model):
            raise HTTPException(status_code=400, detail="モデル名が正しくありません。")
        if model:
            secrets.set(name, model)
        else:
            secrets.delete(name)
        setattr(settings, name, model or (env_keys.get(name) if server_id != "ollama" else None))
        return await local_setup_dict()

    @app.post("/api/setup/local/ollama/pull")
    async def pull_ollama_model(body: ChooseLocalModel) -> dict[str, Any]:
        """Ollama にモデルを入れる（ollama pull と同じ）。終わるまでは GET /api/setup/local で進み具合が見える。"""
        model = body.model.strip()
        if not MODEL_NAME.match(model):
            raise HTTPException(status_code=400, detail="モデル名が正しくありません（例: qwen3:4b）。")
        if not on_premises(settings.ollama_base_url):
            raise HTTPException(status_code=400, detail="このパソコンの Ollama にだけ、モデルを入れられます。")
        if ollama_puller.busy:
            raise HTTPException(status_code=409, detail="ほかのモデルを入れているところです。終わるまで待ってください。")
        ollama_puller.start(settings.ollama_base_url, model)
        return ollama_puller.status

    @app.put("/api/setup/local/custom")
    async def save_custom_llm(body: SaveCustomLlm) -> dict[str, Any]:
        url = body.base_url.strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HTTPException(status_code=400, detail="URL は http://127.0.0.1:1234/v1 のように入れてください。")
        values = {"custom_llm_base_url": url, "custom_llm_model": body.model.strip()}
        if body.api_key.strip():
            values["custom_llm_api_key"] = "".join(body.api_key.split())
        for name, value in values.items():
            if len(value) > 400:
                raise HTTPException(status_code=400, detail="長すぎます。")
            if value:
                secrets.set(name, value)
            else:
                secrets.delete(name)
            setattr(settings, name, value or env_keys.get(name))
        return await local_setup_dict()

    @app.delete("/api/setup/local/custom")
    async def remove_custom_llm() -> dict[str, Any]:
        for name in ("custom_llm_base_url", "custom_llm_model", "custom_llm_api_key"):
            secrets.delete(name)
            setattr(settings, name, env_keys.get(name))
        return await local_setup_dict()

    @app.put("/api/setup/offline")
    async def set_offline(body: SetOffline) -> dict[str, Any]:
        secrets.set("yata_offline", "true" if body.enabled else "false")
        settings.yata_offline = body.enabled
        return await local_setup_dict()

    def setup_dict(item: dict[str, Any]) -> dict[str, Any]:
        stored = secrets.load()
        fields = []
        for field in item["fields"]:
            name = field["name"]
            source = "app" if stored.get(name) else ("env" if key_ready(env_keys.get(name)) else None)
            fields.append({**field, "configured": source is not None, "source": source})
        return {
            "id": item["id"],
            "label": item["label"],
            "advanced": item["advanced"],
            "restart_required": item["restart_required"],
            "key_url": item["key_url"],
            "steps": item["steps"],
            "fields": fields,
            "configured": all(f["configured"] for f in fields if not f["optional"]),
            "from_app": any(f["source"] == "app" for f in fields),
        }

    def rebuild_connectors() -> None:
        # 設定が変わった連携を作り直す。同じレジストリを使っているツールにも、すぐ反映される。
        for connector in build_connector_registry(settings).list():
            connectors.register(connector)

    def find_setup(setup_id: str) -> dict[str, Any]:
        item = next((entry for entry in setups if entry["id"] == setup_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="その連携は画面から設定できません。")
        return item

    @app.get("/api/setup/connectors")
    def connector_setup_list() -> dict[str, Any]:
        return {"setups": [setup_dict(item) for item in setups], "connector_to_setup": CONNECTOR_TO_SETUP}

    @app.put("/api/setup/connectors/{setup_id}")
    def save_connector_setup(setup_id: str, body: SaveConnectorSetup) -> dict[str, Any]:
        # 同期関数にして、Chatwork のトークン確認（GET /me）をこの場で行えるようにする。
        item = find_setup(setup_id)
        allowed = {field["name"]: field for field in item["fields"]}
        updates: dict[str, str] = {}
        for name, value in body.values.items():
            if name not in allowed:
                raise HTTPException(status_code=400, detail="入力欄が正しくありません。")
            clean = value.strip() if not allowed[name]["secret"] else "".join(value.split())
            if len(clean) > 400:
                raise HTTPException(status_code=400, detail=f"{allowed[name]['label']}が長すぎます。")
            if clean:
                updates[name] = clean
        current = {name: updates.get(name) or getattr(settings, name) for name in allowed}
        missing = [allowed[name]["label"] for name, field in allowed.items()
                   if not field["optional"] and not key_ready(current.get(name))]
        if missing:
            raise HTTPException(status_code=400, detail=f"{'、'.join(missing)}を入れてください。")

        if setup_id == "backlog" and normalize_space(current.get("backlog_space")) is None:
            raise HTTPException(status_code=400, detail="スペースの URL は https://example.backlog.jp のように入れてください。")
        if setup_id == "kintone" and normalize_domain(current.get("kintone_domain")) is None:
            raise HTTPException(status_code=400, detail="kintone の URL は https://example.cybozu.com のように入れてください。")

        if setup_id == "line" and "line_channel_access_token" in updates:
            if check_line_token(updates["line_channel_access_token"]) is False:
                raise HTTPException(status_code=400, detail="このチャネルアクセストークンは使えませんでした。コピーし直してください。")

        previous = {name: getattr(settings, name) for name in updates}
        stored_before = secrets.load()
        for name, value in updates.items():
            secrets.set(name, value)
            setattr(settings, name, value)
        rebuild_connectors()

        if setup_id in ("chatwork", "backlog"):
            checked = connectors.get(setup_id)
            if checked is not None and checked.status() == ConnectorState.NOT_CONNECTED:
                # 使えないトークンは保存しない。元の状態に戻す。
                for name, value in previous.items():
                    setattr(settings, name, value)
                    if name in stored_before:
                        secrets.set(name, stored_before[name])
                    else:
                        secrets.delete(name)
                rebuild_connectors()
                raise HTTPException(status_code=400, detail="このトークンは使えませんでした。コピーし直してください。")

        message = "保存しました。"
        if item["restart_required"]:
            message = "保存しました。LINE から話しかけるには、ヤタを起動し直してください。"
        elif setup_id in ("freee", "google", "moneyforward"):
            message = "保存しました。「接続する」を押して、ログインしてください。"
        return {**setup_dict(item), "message": message}

    @app.delete("/api/setup/connectors/{setup_id}")
    def remove_connector_setup(setup_id: str) -> dict[str, Any]:
        item = find_setup(setup_id)
        for field in item["fields"]:
            name = field["name"]
            if secrets.delete(name):
                setattr(settings, name, env_keys.get(name))
        rebuild_connectors()
        return setup_dict(item)

    @app.get("/api/bots")
    def list_bots() -> dict[str, Any]:
        return {
            "bots": [_bot_dict(bot) for bot in memory.list_bots()],
            "colors": [{"id": key, "label": label} for key, label in BOT_COLORS.items()],
            "accessories": [{"id": key, "label": label} for key, label in BOT_ACCESSORIES.items()],
        }

    @app.post("/api/bots", status_code=201)
    def create_bot(body: CreateBot) -> dict[str, Any]:
        color, accessory = body.color, body.accessory
        if color is None or accessory is None:
            # 見た目を指定しなければ、まだ誰も使っていない組み合わせを割り当てる。
            auto_color, auto_accessory = pick_look((bot.color, bot.accessory) for bot in memory.list_bots())
            color = color or auto_color
            accessory = accessory or auto_accessory
        try:
            bot = memory.create_bot(name=body.name, job=body.job, color=color, accessory=accessory)
        except BotError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _bot_dict(bot)

    @app.patch("/api/bots/{bot_id}")
    def update_bot(bot_id: str, body: UpdateBot) -> dict[str, Any]:
        try:
            bot = memory.update_bot(
                bot_id, name=body.name, job=body.job, color=body.color, accessory=body.accessory
            )
        except BotError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if bot is None:
            raise HTTPException(status_code=404, detail="ボットが見つかりません。")
        return _bot_dict(bot)

    @app.delete("/api/bots/{bot_id}", status_code=204)
    def delete_bot(bot_id: str) -> None:
        try:
            deleted = memory.delete_bot(bot_id)
        except BotError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="ボットが見つかりません。")

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str) -> dict[str, Any]:
        conversation = _require_conversation(memory, conversation_id)
        messages = to_transcript(memory.list_messages(conversation_id))
        return {**_conversation_dict(conversation), "messages": messages}

    @app.patch("/api/conversations/{conversation_id}")
    def update_conversation(conversation_id: str, body: UpdateConversation) -> dict[str, Any]:
        _require_conversation(memory, conversation_id)
        if body.model_id:
            _known_model(model_router, body.model_id)
        updated = memory.update_conversation(
            conversation_id,
            title=body.title,
            model_id=body.model_id,
        )
        assert updated is not None
        return _conversation_dict(updated)

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str) -> None:
        if not memory.delete_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="会話が見つかりません。")

    @app.get("/api/facts")
    def list_facts() -> dict[str, Any]:
        return {
            "facts": [
                {"key": fact.key, "value": fact.value, "updated_at": fact.updated_at}
                for fact in memory.list_facts()
            ]
        }

    @app.delete("/api/facts/{key}", status_code=204)
    def delete_fact(key: str) -> None:
        if not memory.delete_fact(key):
            raise HTTPException(status_code=404, detail="記憶が見つかりません。")

    @app.get("/api/routines")
    def list_routines() -> dict[str, Any]:
        return {
            "presets": preset_list(),
            "routines": [_routine_dict(item, routine_repo, memory) for item in routine_repo.list_routines()],
        }

    @app.post("/api/routines", status_code=201)
    def create_routine(body: CreateRoutine) -> dict[str, Any]:
        model_id = body.model_id or settings.yata_model
        _known_model(model_router, model_id)
        try:
            routine = routines.create(
                name=body.name,
                prompt=body.prompt,
                model_id=model_id,
                preset=body.preset,
                schedule=body.schedule,
                schedule_kind=body.schedule_kind,
                timezone=body.timezone,
                notify_line=body.notify_line,
                bot_id=_require_bot(memory, body.bot_id or DEFAULT_BOT_ID).id,
            )
        except ScheduleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _routine_dict(routine, routine_repo, memory)

    @app.post("/api/routines/{routine_id}/notify_line")
    def set_routine_notify_line(routine_id: str, body: SetRoutineNotifyLine) -> dict[str, Any]:
        updated = routine_repo.set_notify_line(routine_id, body.enabled)
        if updated is None:
            raise HTTPException(status_code=404, detail="ルーティンが見つかりません。")
        return _routine_dict(updated, routine_repo, memory)

    @app.post("/api/routines/{routine_id}/pause")
    def pause_routine(routine_id: str) -> dict[str, Any]:
        updated = routine_repo.set_enabled(routine_id, False)
        if updated is None:
            raise HTTPException(status_code=404, detail="ルーティンが見つかりません。")
        return _routine_dict(updated, routine_repo, memory)

    @app.post("/api/routines/{routine_id}/resume")
    def resume_routine(routine_id: str) -> dict[str, Any]:
        updated = routine_repo.set_enabled(routine_id, True)
        if updated is None:
            raise HTTPException(status_code=404, detail="ルーティンが見つかりません。")
        return _routine_dict(updated, routine_repo, memory)

    @app.delete("/api/routines/{routine_id}", status_code=204)
    def delete_routine(routine_id: str) -> None:
        if not routine_repo.delete(routine_id):
            raise HTTPException(status_code=404, detail="ルーティンが見つかりません。")

    @app.get("/api/connectors")
    def list_connectors() -> dict[str, Any]:
        return {"connectors": [_connector_dict(item) for item in connectors.list()]}

    @app.post("/api/connectors/{connector_id}/connect")
    def connect_connector(connector_id: str) -> dict[str, Any]:
        connector = connectors.get(connector_id)
        if connector is None:
            raise HTTPException(status_code=404, detail="連携が見つかりません。")
        if connector.status() == ConnectorState.NOT_CONFIGURED:
            raise HTTPException(status_code=400, detail="この連携はまだ設定されていません。")
        verifier = new_verifier()
        state = oauth_states.open(connector_id, verifier)
        url = connector.authorize_url(state, challenge_for(verifier))
        return {"authorize_url": url}

    @app.get("/api/connectors/google/oauth/callback")
    async def google_oauth_callback(
        code: str | None = None, state: str | None = None, error: str | None = None
    ) -> Any:
        return await oauth_callback(code, state, error, {"gmail", "google_calendar"})

    @app.get("/api/connectors/freee/oauth/callback")
    async def freee_oauth_callback(
        code: str | None = None, state: str | None = None, error: str | None = None
    ) -> Any:
        return await oauth_callback(code, state, error, {"freee"})

    @app.get("/api/connectors/moneyforward/oauth/callback")
    async def moneyforward_oauth_callback(
        code: str | None = None, state: str | None = None, error: str | None = None
    ) -> Any:
        return await oauth_callback(code, state, error, {"moneyforward"})

    async def oauth_callback(code, state, error, allowed: set[str]) -> Any:
        if error or not code or not state:
            return RedirectResponse(url="/?connector_error=1")
        entry = oauth_states.pop(state)
        if entry is None:
            return RedirectResponse(url="/?connector_error=1")
        connector_id, code_verifier = entry
        connector = connectors.get(connector_id)
        if connector is None or connector_id not in allowed:
            return RedirectResponse(url="/?connector_error=1")
        try:
            await connector.complete_authorization(code, code_verifier)
        except Exception:
            logger.exception("oauth exchange failed for %s", connector_id)
            return RedirectResponse(url="/?connector_error=1")
        return RedirectResponse(url=f"/?connector_connected={connector_id}")

    @app.post("/api/connectors/{connector_id}/disconnect")
    def disconnect_connector(connector_id: str) -> dict[str, Any]:
        connector = connectors.get(connector_id)
        if connector is None:
            raise HTTPException(status_code=404, detail="連携が見つかりません。")
        connector.disconnect()
        return _connector_dict(connector)

    @app.post("/api/confirmations/{request_id}")
    def resolve_confirmation(request_id: str, body: ResolveConfirmation) -> dict[str, bool]:
        found = gate.resolve(request_id, body.approved)
        if not found:
            raise HTTPException(status_code=404, detail="確認待ちの操作が見つかりません。")
        return {"ok": True}

    @app.post("/api/conversations/{conversation_id}/messages")
    async def send_message(conversation_id: str, body: SendMessage) -> StreamingResponse:
        conversation = _require_conversation(memory, conversation_id)
        content = body.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="メッセージが空です。")
        try:
            draft = parse_routine_utterance(content, zone=settings.yata_timezone)
        except ScheduleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if draft is not None:
            model_id = body.model_id or conversation.model_id
            _known_model(model_router, model_id)
            try:
                routine = routines.create(
                    name=draft.name,
                    prompt=draft.prompt,
                    model_id=model_id,
                    schedule=draft.schedule,
                    schedule_kind=draft.schedule_kind,
                    timezone=draft.timezone,
                    bot_id=conversation.bot_id,
                )
            except ScheduleError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            label = schedule_label(routine.schedule_kind, routine.schedule, routine.timezone)
            ack = (
                f"ルーティン「{routine.name}」を登録しました。{label}に実行します。"
                "ブラウザを閉じても、ヤタのプロセスが動いていれば結果はルーティンの会話に残ります。"
            )
            memory.maybe_title_from_first_message(conversation_id, content)
            memory.add_message(conversation_id, LLMMessage(role="user", content=content))
            memory.add_message(conversation_id, LLMMessage(role="assistant", content=ack))

            async def generate_ack():
                yield _sse({"type": "answer", "content": ack, "truncated": False})
                yield _sse({"type": "done", "ok": True, "routine_id": routine.id})

            return StreamingResponse(
                generate_ack(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        model_id = body.model_id or conversation.model_id
        visible = await _visible_models(model_router, settings)
        info = next((item for item in visible if item.id == model_id), None)
        if info is None:
            raise HTTPException(status_code=400, detail=f"未知のモデルです: {model_id}")
        if not info.ready:
            raise HTTPException(status_code=400, detail=info.note or "このモデルはまだ使えません。")
        try:
            provider, upstream = model_router.resolve(model_id)
        except ProviderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        memory.update_conversation(conversation_id, model_id=model_id)
        memory.maybe_title_from_first_message(conversation_id, content)
        memory.add_message(conversation_id, LLMMessage(role="user", content=content))

        bot = memory.get_bot(conversation.bot_id)
        llm_messages = [LLMMessage(role="system", content=build_system_prompt(
            memory.list_facts(), bot, compact=model_router.is_local(model_id)))]
        llm_messages.extend(item.to_llm() for item in memory.list_messages(conversation_id))
        base_len = len(llm_messages)
        ctx = ToolContextFactory(
            memory=memory,
            browser=browser,
            artifacts_dir=artifacts,
            allow_private_urls=settings.yata_allow_private_urls,
            connectors=connectors,
        ).for_conversation(conversation_id)
        active_registry = model_router.tools_for(model_id, registry, connectors)

        async def generate():
            try:
                async for event in run_agent(
                    messages=llm_messages,
                    provider=provider,
                    model=upstream,
                    registry=active_registry,
                    policy=ToolPolicy(),
                    gate=gate,
                    ctx=ctx,
                    max_steps=settings.yata_max_steps,
                ):
                    yield _sse(event.as_dict())
            except Exception:
                logger.exception("agent turn failed")
                llm_messages.append(
                    LLMMessage(role="assistant", content="エージェントの実行中に失敗しました。")
                )
                yield _sse({"type": "error", "message": "エージェントの実行中に失敗しました。"})
                yield _sse({"type": "done", "ok": False})
            finally:
                seal_open_tool_calls(llm_messages)
                for message in llm_messages[base_len:]:
                    memory.add_message(conversation_id, message)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/artifacts/{name}")
    def get_artifact(name: str) -> FileResponse:
        if not _ARTIFACT_NAME.match(name):
            raise HTTPException(status_code=404, detail="ファイルが見つかりません。")
        path = (artifacts / name).resolve()
        if path.parent != artifacts.resolve() or not path.is_file():
            raise HTTPException(status_code=404, detail="ファイルが見つかりません。")
        return FileResponse(path)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    dist = _frontend_dist()
    if dist is None:
        @app.get("/")
        def missing_frontend() -> HTMLResponse:
            return HTMLResponse(
                "<main style='font-family:sans-serif;padding:2rem'>"
                "<h1>ヤタ</h1>"
                "<p>フロントエンドがまだビルドされていません。</p>"
                "<p><code>npm --prefix frontend install && npm --prefix frontend run build</code></p>"
                "<p>API ドキュメントは <a href='/docs'>/docs</a> です。</p>"
                "</main>"
            )
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(dist / "index.html")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)  # type: ignore[return-value]
        candidate = (dist / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(dist.resolve())):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


def _frontend_dist() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [Path.cwd() / "frontend" / "dist", * (parent / "frontend" / "dist" for parent in here.parents[:5])]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


async def _visible_models(router: ModelRouter, settings: Settings) -> list[ModelInfo]:
    """画面に出すモデル。

    - Ollama は動いていなくても（利用不可として）出す。いちばん知られているので、案内のため。
    - ほかのパソコンの中の AI は、動いているときだけ出す。
    - Gemini・OpenAI・Claude 以外のネットの AI は、キーを入れたときだけ出す。
    - オフラインモードでは、ネットの AI を利用不可にする。
    """
    models = router.catalog()
    local_urls = {model.id: router.local_base_url(model.id) for model in models
                  if model.local and model.id != "ollama" and model.ready}
    running = await _reachable_many([url for url in local_urls.values() if url])
    ollama_up = await _ollama_reachable(settings.ollama_base_url)
    visible: list[ModelInfo] = []
    for model in models:
        if model.id == "ollama":
            if not ollama_up:
                model = replace(model, ready=False,
                                note="Ollama が応答しません。`ollama serve` と OLLAMA_BASE_URL を確認してください。")
        elif model.local:
            url = local_urls.get(model.id)
            if not url or not running.get(url):
                continue
        elif cloud_provider(model.id) is not None and not model.ready:
            continue
        if settings.yata_offline and not model.local and model.id != "demo":
            model = replace(model, ready=False, note=OFFLINE_NOTE)
        elif settings.yata_offline and not router.offline_safe(model.id):
            model = replace(model, ready=False, note=OFFLINE_REMOTE_NOTE)
        visible.append(model)
    return visible


async def _reachable_many(urls: list[str]) -> dict[str, bool]:
    """OpenAI 互換サーバー（…/v1）が動いているかを、まとめて短い時間で確かめる。"""
    async def one(client: httpx.AsyncClient, url: str) -> bool:
        try:
            response = await client.get(url.rstrip("/") + "/models")
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    unique = sorted(set(urls))
    if not unique:
        return {}
    async with httpx.AsyncClient(timeout=0.4) as client:
        results = await asyncio.gather(*(one(client, url) for url in unique))
    return dict(zip(unique, results, strict=True))


async def _ollama_reachable(base_url: str) -> bool:
    url = ollama_root(base_url).rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=0.4) as client:
            response = await client.get(url)
            return response.status_code < 500
    except httpx.HTTPError:
        return False


def _known_model(router: ModelRouter, model_id: str) -> ModelInfo:
    try:
        return router.get(model_id)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_conversation(memory: MemoryStore, conversation_id: str):
    conversation = memory.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会話が見つかりません。")
    return conversation


def _conversation_dict(conversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "model_id": conversation.model_id,
        "bot_id": conversation.bot_id,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def _bot_dict(bot: Bot) -> dict[str, Any]:
    return {
        "id": bot.id,
        "name": bot.name,
        "job": bot.job,
        "color": bot.color,
        "accessory": bot.accessory,
        "is_default": bot.id == DEFAULT_BOT_ID,
        "created_at": bot.created_at,
    }


def _require_bot(memory: MemoryStore, bot_id: str) -> Bot:
    bot = memory.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="ボットが見つかりません。")
    return bot


def _routine_dict(routine: Routine, repo: RoutineRepository, memory: MemoryStore) -> dict[str, Any]:
    latest = repo.latest_run(routine.id)
    owner = memory.get_conversation(routine.conversation_id)
    pending = latest if latest and latest.status == "waiting_confirmation" else None
    return {
        "id": routine.id,
        "name": routine.name,
        "prompt": routine.prompt,
        "schedule_kind": routine.schedule_kind,
        "schedule": routine.schedule,
        "schedule_label": schedule_label(routine.schedule_kind, routine.schedule, routine.timezone),
        "timezone": routine.timezone,
        "enabled": routine.enabled,
        "notify_line": routine.notify_line,
        "last_run": routine.last_run,
        "next_run": routine.next_run,
        "model_id": routine.model_id,
        "conversation_id": routine.conversation_id,
        "bot_id": owner.bot_id if owner is not None else DEFAULT_BOT_ID,
        "last_status": latest.status if latest else None,
        "last_snippet": latest.snippet if latest else None,
        "recent_runs": [_run_dict(item) for item in repo.recent_runs(routine.id)],
        "pending_confirmation": _pending_dict(pending),
    }


def _run_dict(run: RoutineRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "snippet": run.snippet,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def _pending_dict(run: RoutineRun | None) -> dict[str, Any] | None:
    if run is None or not run.confirmation_id:
        return None
    return {
        "request_id": run.confirmation_id,
        "tool": run.confirmation_tool or "",
        "risk": run.confirmation_risk or "",
        "summary": run.confirmation_summary or run.snippet,
        "arguments": run.confirmation_arguments or {},
    }


def _connector_dict(connector: Connector) -> dict[str, Any]:
    status = connector.status()
    return {
        "id": connector.id,
        "label": connector.label,
        "auth_kind": connector.auth_kind,
        "note": connector.status_note(),
        "status": status.value,
        "setup_instructions": connector.setup_instructions if status == ConnectorState.NOT_CONFIGURED else None,
    }


def _model_dict(model: ModelInfo) -> dict[str, Any]:
    return {
        "id": model.id,
        "label": model.label,
        "provider": model.provider,
        "upstream_model": model.upstream_model,
        "ready": model.ready,
        "note": model.note,
        "local": model.local,
    }


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


app = create_app()
