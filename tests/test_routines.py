"""Schedule math and the routine runner, with a mocked model."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from tests.fakes import MutatingTool, ScriptedProvider
from yata.api.app import create_app
from yata.config import Settings
from yata.confirm.gate import InMemoryConfirmationGate
from yata.llm.types import LLMResponse, ToolCall
from yata.memory.store import MemoryStore
from yata.routines.repository import RoutineRepository
from yata.routines.schedule import ScheduleError, next_run, parse_routine_utterance, schedule_label
from yata.routines.scheduler import RoutineScheduler
from yata.routines.service import RoutineService
from yata.tools.registry import ToolRegistry

TOKYO = ZoneInfo("Asia/Tokyo")


class FixedRouter:
    def __init__(self, provider: ScriptedProvider):
        self.provider = provider

    def resolve(self, model_id: str) -> tuple[ScriptedProvider, str]:
        del model_id
        return self.provider, "fake-model"


def test_next_run_for_morning_cron_and_interval() -> None:
    before = datetime(2026, 10, 21, 7, 30, tzinfo=TOKYO)
    morning = next_run("cron", "0 8 * * *", "Asia/Tokyo", before)
    assert morning.astimezone(TOKYO) == datetime(2026, 10, 21, 8, 0, tzinfo=TOKYO)

    on_the_dot = datetime(2026, 10, 21, 8, 0, tzinfo=TOKYO)
    rolled = next_run("cron", "0 8 * * *", "Asia/Tokyo", on_the_dot)
    assert rolled.astimezone(TOKYO) == datetime(2026, 10, 22, 8, 0, tzinfo=TOKYO)

    monday = next_run("cron", "0 9 * * 1", "Asia/Tokyo", datetime(2026, 10, 21, 10, 0, tzinfo=TOKYO))
    assert monday.astimezone(TOKYO) == datetime(2026, 10, 26, 9, 0, tzinfo=TOKYO)

    hourly = next_run("interval", "3600", "Asia/Tokyo", before)
    assert hourly.astimezone(TOKYO) == datetime(2026, 10, 21, 8, 30, tzinfo=TOKYO)
    assert schedule_label("cron", "0 8 * * *", "Asia/Tokyo").startswith("毎朝 8:00")


def test_utterance_becomes_a_morning_routine() -> None:
    draft = parse_routine_utterance("毎朝8時にニュースを要約して")
    assert draft is not None
    assert draft.schedule == "0 8 * * *"
    assert draft.schedule_kind == "cron"
    assert draft.prompt == "ニュースを要約して"
    assert draft.timezone == "Asia/Tokyo"

    short = parse_routine_utterance("毎朝8時にニュース要約")
    assert short is not None
    assert short.prompt == "ニュース要約"

    monday = parse_routine_utterance("毎週月曜9時に週報をまとめて")
    assert monday is not None
    assert monday.schedule == "0 9 * * 1"

    hourly = parse_routine_utterance("毎時に新着を確認して")
    assert hourly is not None
    assert hourly.schedule == "0 * * * *"
    assert parse_routine_utterance("こんにちは") is None
    try:
        parse_routine_utterance("毎朝99時に何かして")
        raise AssertionError("hour 99 should be rejected")
    except ScheduleError:
        pass


def _service(
    tmp_path: Path,
    provider: ScriptedProvider,
    *,
    registry: ToolRegistry | None = None,
    gate: InMemoryConfirmationGate | None = None,
    confirm_timeout: float = 5,
) -> tuple[RoutineService, MemoryStore]:
    memory = MemoryStore(tmp_path / "routines.db")
    routines = RoutineRepository(memory.path)
    tools = registry or ToolRegistry()
    service = RoutineService(
        memory=memory,
        routines=routines,
        router=FixedRouter(provider),
        registry=tools,
        gate=gate or InMemoryConfirmationGate(),
        browser=object(),
        artifacts_dir=tmp_path,
        allow_private_urls=False,
        max_steps=4,
        confirm_timeout=confirm_timeout,
        default_timezone="Asia/Tokyo",
    )
    return service, memory


async def test_scheduler_runs_the_agent_loop(tmp_path: Path) -> None:
    provider = ScriptedProvider([LLMResponse(content="今朝のニュースは3件です。")])
    service, memory = _service(tmp_path, provider)
    routine = service.create(
        name="朝のニュース",
        prompt="ニュースを要約して",
        model_id="demo",
        preset="morning",
        now=datetime(2000, 1, 1, 7, 0, tzinfo=TOKYO),
    )
    scheduler = RoutineScheduler(service, interval_seconds=3600)
    await scheduler.start()
    try:
        assert scheduler.scheduler is not None
        assert scheduler.scheduler.get_job("yata-routines") is not None
        await service.wait_for([routine.id])
    finally:
        await scheduler.stop()

    stored = service.routines.get(routine.id)
    assert stored is not None
    assert stored.last_run is not None
    assert stored.next_run is not None
    assert stored.next_run > stored.last_run
    run = service.routines.latest_run(routine.id)
    assert run is not None
    assert run.status == "ok"
    assert "ニュース" in run.snippet
    messages = memory.list_messages(routine.conversation_id)
    assert messages[0].role == "user"
    assert messages[0].content == "ニュースを要約して"
    assert messages[-1].role == "assistant"
    assert "ニュース" in (messages[-1].content or "")
    assert provider.seen
    assert provider.seen[0][0].role == "system"


async def test_routine_waits_for_confirmation(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="poke", arguments={"target": "news"})]),
            LLMResponse(content="確認のあと、要約しました。"),
        ]
    )
    tool = MutatingTool()
    registry = ToolRegistry()
    registry.register(tool)
    gate = InMemoryConfirmationGate()
    service, memory = _service(tmp_path, provider, registry=registry, gate=gate)
    routine = service.create(
        name="確認がいる仕事",
        prompt="ページを開いて要約して",
        model_id="demo",
        preset="hourly",
        now=datetime(2026, 10, 21, 8, 30, tzinfo=TOKYO),
    )
    launched = await service.run_due(datetime(2026, 10, 21, 9, 5, tzinfo=TOKYO))
    assert launched == [routine.id]

    pending = None
    for _ in range(50):
        pending = service.routines.latest_run(routine.id)
        if pending and pending.status == "waiting_confirmation":
            break
        await __import__("asyncio").sleep(0.02)
    assert pending is not None
    assert pending.status == "waiting_confirmation"
    assert pending.confirmation_id
    assert gate.resolve(pending.confirmation_id, True) is True

    await service.wait_for([routine.id])
    finished = service.routines.latest_run(routine.id)
    assert finished is not None
    assert finished.status == "ok"
    assert "要約" in finished.snippet
    assert tool.calls == [{"target": "news"}]
    transcript = memory.list_messages(routine.conversation_id)
    assert any(message.role == "assistant" and "要約" in (message.content or "") for message in transcript)


def test_api_creates_pauses_and_accepts_a_chat_utterance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(
        gemini_api_key=None,
        openai_api_key=None,
        anthropic_api_key=None,
        yata_db=str(tmp_path / "app.db"),
        yata_model="demo",
        yata_scheduler_enabled=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        created = client.post("/api/conversations", json={"model_id": "demo"})
        assert created.status_code == 201
        conversation_id = created.json()["id"]
        with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "毎朝8時にニュースを要約して", "model_id": "demo"},
        ) as response:
            body = "".join(response.iter_text())
        assert "ルーティン" in body
        assert "毎朝 8:00" in body

        listed = client.get("/api/routines")
        assert listed.status_code == 200
        routines = listed.json()["routines"]
        assert len(routines) == 1
        routine = routines[0]
        assert routine["schedule"] == "0 8 * * *"
        assert routine["prompt"] == "ニュースを要約して"
        assert routine["enabled"] is True
        assert routine["timezone"] == "Asia/Tokyo"

        paused = client.post(f"/api/routines/{routine['id']}/pause")
        assert paused.status_code == 200
        assert paused.json()["enabled"] is False
        resumed = client.post(f"/api/routines/{routine['id']}/resume")
        assert resumed.json()["enabled"] is True

        manual = client.post(
            "/api/routines",
            json={"name": "毎時チェック", "prompt": "新着を見て", "preset": "hourly", "model_id": "demo"},
        )
        assert manual.status_code == 201
        assert manual.json()["schedule"] == "0 * * * *"

        monday = client.post(
            "/api/routines",
            json={"name": "月曜", "prompt": "週の予定", "preset": "monday", "model_id": "demo"},
        )
        assert monday.status_code == 201
        assert monday.json()["schedule"] == "0 9 * * 1"

        rejected = client.post(
            "/api/routines",
            json={"name": "壊れた", "prompt": "何か", "schedule": "not cron", "model_id": "demo"},
        )
        assert rejected.status_code == 400

        assert client.delete(f"/api/routines/{routine['id']}").status_code == 204
        remaining = client.get("/api/routines").json()["routines"]
        assert routine["id"] not in {item["id"] for item in remaining}
        assert client.delete(f"/api/routines/{routine['id']}").status_code == 404
