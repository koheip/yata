"""FastAPI application: conversations, streaming agent turns, and the built UI."""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from yata.agent.loop import run_agent, seal_open_tool_calls
from yata.config import Settings
from yata.confirm.gate import InMemoryConfirmationGate
from yata.llm.openai_provider import ollama_root
from yata.llm.router import ModelInfo, ModelRouter
from yata.llm.types import LLMMessage, ProviderError
from yata.memory.store import MemoryStore, to_transcript
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
from yata.tools.base import ToolContextFactory
from yata.tools.browser import BrowserSession
from yata.tools.catalog import build_registry
from yata.tools.policy import ToolPolicy

logger = logging.getLogger(__name__)
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class CreateConversation(BaseModel):
    model_id: str | None = None
    title: str | None = Field(default=None, max_length=80)


class UpdateConversation(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    model_id: str | None = None


class SendMessage(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    model_id: str | None = None


class ResolveConfirmation(BaseModel):
    approved: bool


class CreateRoutine(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=8000)
    preset: str | None = None
    schedule: str | None = Field(default=None, max_length=80)
    schedule_kind: str | None = None
    timezone: str | None = Field(default=None, max_length=64)
    model_id: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    memory = MemoryStore(settings.database_path())
    browser = BrowserSession()
    gate = InMemoryConfirmationGate()
    registry = build_registry()
    model_router = ModelRouter(settings)
    artifacts = settings.artifacts_dir()
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
    app.state.settings = settings
    app.state.memory = memory
    app.state.browser = browser
    app.state.gate = gate
    app.state.registry = registry
    app.state.model_router = model_router
    app.state.artifacts = artifacts
    app.state.routines = routines

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "name": "yata"}

    @app.get("/api/models")
    async def list_models() -> dict[str, Any]:
        models = await _visible_models(model_router, settings)
        return {
            "default_model_id": settings.yata_model,
            "models": [_model_dict(model) for model in models],
        }

    @app.get("/api/conversations")
    def list_conversations() -> dict[str, Any]:
        return {
            "conversations": [_conversation_dict(item) for item in memory.list_conversations()],
        }

    @app.post("/api/conversations", status_code=201)
    def create_conversation(body: CreateConversation) -> dict[str, Any]:
        model_id = body.model_id or settings.yata_model
        _known_model(model_router, model_id)
        title = body.title.strip() if body.title else "新しい会話"
        conversation = memory.create_conversation(model_id, title or "新しい会話")
        return _conversation_dict(conversation)

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
            "routines": [_routine_dict(item, routine_repo) for item in routine_repo.list_routines()],
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
            )
        except ScheduleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _routine_dict(routine, routine_repo)

    @app.post("/api/routines/{routine_id}/pause")
    def pause_routine(routine_id: str) -> dict[str, Any]:
        updated = routine_repo.set_enabled(routine_id, False)
        if updated is None:
            raise HTTPException(status_code=404, detail="ルーティンが見つかりません。")
        return _routine_dict(updated, routine_repo)

    @app.post("/api/routines/{routine_id}/resume")
    def resume_routine(routine_id: str) -> dict[str, Any]:
        updated = routine_repo.set_enabled(routine_id, True)
        if updated is None:
            raise HTTPException(status_code=404, detail="ルーティンが見つかりません。")
        return _routine_dict(updated, routine_repo)

    @app.delete("/api/routines/{routine_id}", status_code=204)
    def delete_routine(routine_id: str) -> None:
        if not routine_repo.delete(routine_id):
            raise HTTPException(status_code=404, detail="ルーティンが見つかりません。")

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

        llm_messages = [LLMMessage(role="system", content=build_system_prompt(memory.list_facts()))]
        llm_messages.extend(item.to_llm() for item in memory.list_messages(conversation_id))
        base_len = len(llm_messages)
        ctx = ToolContextFactory(
            memory=memory,
            browser=browser,
            artifacts_dir=artifacts,
            allow_private_urls=settings.yata_allow_private_urls,
        ).for_conversation(conversation_id)

        async def generate():
            try:
                async for event in run_agent(
                    messages=llm_messages,
                    provider=provider,
                    model=upstream,
                    registry=registry,
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
    models = router.catalog()
    if await _ollama_reachable(settings.ollama_base_url):
        return models
    visible: list[ModelInfo] = []
    for model in models:
        if model.id == "ollama":
            visible.append(
                replace(
                    model,
                    ready=False,
                    note="Ollama が応答しません。`ollama serve` と OLLAMA_BASE_URL を確認してください。",
                )
            )
        else:
            visible.append(model)
    return visible


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
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def _routine_dict(routine: Routine, repo: RoutineRepository) -> dict[str, Any]:
    latest = repo.latest_run(routine.id)
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
        "last_run": routine.last_run,
        "next_run": routine.next_run,
        "model_id": routine.model_id,
        "conversation_id": routine.conversation_id,
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


def _model_dict(model: ModelInfo) -> dict[str, Any]:
    return {
        "id": model.id,
        "label": model.label,
        "provider": model.provider,
        "upstream_model": model.upstream_model,
        "ready": model.ready,
        "note": model.note,
    }


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


app = create_app()
