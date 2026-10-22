"""ボット（ヤタの分身）の保存、API、会話・ルーティンとのひもづけを検証する。"""
import random
import sqlite3

import pytest
from fastapi.testclient import TestClient

from yata.api.app import create_app
from yata.bots import BOT_ACCESSORIES, BOT_COLORS, DEFAULT_BOT_ID, BotError, pick_look
from yata.config import Settings
from yata.memory.store import MemoryStore
from yata.prompts import build_system_prompt


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, yata_db=str(tmp_path / "yata.db"), yata_model="demo",
                        yata_scheduler_enabled=False)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_default_bot_exists_and_cannot_be_deleted(tmp_path):
    store = MemoryStore(tmp_path / "yata.db")
    bots = store.list_bots()
    assert [(b.id, b.name, b.color, b.accessory) for b in bots] == [(DEFAULT_BOT_ID, "ヤタ", "purple", "none")]
    with pytest.raises(BotError):
        store.delete_bot(DEFAULT_BOT_ID)
    # 2回開いても既定のボットは増えない
    assert len(MemoryStore(tmp_path / "yata.db").list_bots()) == 1


def test_old_database_gets_bot_column(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                        model_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute("INSERT INTO conversations VALUES ('old', '前の会話', 'demo', '2026-10-01', '2026-10-01')")
    store = MemoryStore(path)
    assert store.get_conversation("old").bot_id == DEFAULT_BOT_ID
    assert [c.id for c in store.list_conversations(DEFAULT_BOT_ID)] == ["old"]


def test_bot_validation(tmp_path):
    store = MemoryStore(tmp_path / "yata.db")
    for kwargs in ({"name": "  "}, {"name": "あ" * 21}, {"name": "係", "job": "x" * 201},
                   {"name": "係", "color": "gold"}, {"name": "係", "accessory": "hat"}):
        args = {"job": "", "color": "blue", "accessory": "none", **kwargs}
        with pytest.raises(BotError):
            store.create_bot(**args)
    bot = store.create_bot(name="  ニュース   係 ", job=" 毎朝 まとめる ", color="blue", accessory="phones")
    assert (bot.name, bot.job) == ("ニュース 係", "毎朝 まとめる")
    with pytest.raises(BotError):
        store.update_bot(bot.id, color="gold")
    assert store.update_bot("missing", name="x") is None


def test_pick_look_prefers_unused_combinations():
    every = [(c, a) for c in BOT_COLORS for a in BOT_ACCESSORIES]
    rng = random.Random(1)
    for _ in range(50):
        assert pick_look(every[1:], rng) == every[0]
    color, accessory = pick_look(every, rng)  # 全部使っていても何かは返す
    assert color in BOT_COLORS and accessory in BOT_ACCESSORIES


def test_bots_api_crud_and_auto_look(client):
    listed = client.get("/api/bots").json()
    assert [b["id"] for b in listed["bots"]] == [DEFAULT_BOT_ID]
    assert listed["bots"][0]["is_default"] is True
    assert {c["id"] for c in listed["colors"]} == set(BOT_COLORS)
    assert {a["id"] for a in listed["accessories"]} == set(BOT_ACCESSORIES)

    looks = {("purple", "none")}
    for index in range(5):
        response = client.post("/api/bots", json={"name": f"係{index}", "job": "仕事"})
        assert response.status_code == 201
        bot = response.json()
        look = (bot["color"], bot["accessory"])
        assert look not in looks  # 作るたびに違う見た目になる
        looks.add(look)

    chosen = client.post("/api/bots", json={"name": "経理係", "color": "green", "accessory": "glasses"}).json()
    assert (chosen["color"], chosen["accessory"], chosen["is_default"]) == ("green", "glasses", False)
    assert client.post("/api/bots", json={"name": ""}).status_code == 400
    assert client.post("/api/bots", json={"name": "係", "color": "gold"}).status_code == 400

    renamed = client.patch(f"/api/bots/{chosen['id']}", json={"name": "会計係", "accessory": "bow"}).json()
    assert (renamed["name"], renamed["color"], renamed["accessory"]) == ("会計係", "green", "bow")
    assert client.patch("/api/bots/missing", json={"name": "x"}).status_code == 404
    assert client.patch(f"/api/bots/{chosen['id']}", json={"color": "gold"}).status_code == 400

    assert client.delete(f"/api/bots/{DEFAULT_BOT_ID}").status_code == 400
    assert client.delete(f"/api/bots/{chosen['id']}").status_code == 204
    assert client.delete(f"/api/bots/{chosen['id']}").status_code == 404
    assert chosen["id"] not in [b["id"] for b in client.get("/api/bots").json()["bots"]]


def test_conversations_and_routines_belong_to_a_bot(client):
    bot = client.post("/api/bots", json={"name": "ニュース係"}).json()
    default_conv = client.post("/api/conversations", json={"model_id": "demo"}).json()
    bot_conv = client.post("/api/conversations", json={"model_id": "demo", "bot_id": bot["id"]}).json()
    assert default_conv["bot_id"] == DEFAULT_BOT_ID and bot_conv["bot_id"] == bot["id"]
    assert client.post("/api/conversations", json={"model_id": "demo", "bot_id": "missing"}).status_code == 404

    only_bot = client.get("/api/conversations", params={"bot_id": bot["id"]}).json()["conversations"]
    assert [c["id"] for c in only_bot] == [bot_conv["id"]]
    assert len(client.get("/api/conversations").json()["conversations"]) == 2

    routine = client.post("/api/routines", json={"name": "朝のニュース", "prompt": "まとめて", "preset": "morning",
                                                 "model_id": "demo", "bot_id": bot["id"]}).json()
    assert routine["bot_id"] == bot["id"]
    assert client.get(f"/api/conversations/{routine['conversation_id']}").json()["bot_id"] == bot["id"]
    plain = client.post("/api/routines", json={"name": "毎時", "prompt": "確認", "preset": "hourly",
                                               "model_id": "demo"}).json()
    assert plain["bot_id"] == DEFAULT_BOT_ID

    # チャットで登録したルーティンは、その会話のボットのものになる
    with client.stream("POST", f"/api/conversations/{bot_conv['id']}/messages",
                       json={"content": "毎朝8時に天気を教えて", "model_id": "demo"}) as response:
        assert response.status_code == 200
        response.read()
    routines = client.get("/api/routines").json()["routines"]
    from_chat = [r for r in routines if r["id"] not in (routine["id"], plain["id"])]
    assert len(from_chat) == 1 and from_chat[0]["bot_id"] == bot["id"]

    # ボットを消しても、会話とルーティンは「ヤタ」に引き継がれる
    assert client.delete(f"/api/bots/{bot['id']}").status_code == 204
    assert client.get(f"/api/conversations/{bot_conv['id']}").json()["bot_id"] == DEFAULT_BOT_ID
    assert {r["bot_id"] for r in client.get("/api/routines").json()["routines"]} == {DEFAULT_BOT_ID}


def test_system_prompt_names_the_bot(tmp_path):
    store = MemoryStore(tmp_path / "yata.db")
    bot = store.create_bot(name="経理係", job="freee の請求書を見ておく", color="green", accessory="glasses")
    prompt = build_system_prompt([], bot)
    assert "「経理係」" in prompt and "freee の請求書を見ておく" not in prompt  # 任せる仕事は使わない
    default = build_system_prompt([], store.get_bot(DEFAULT_BOT_ID))
    assert default == build_system_prompt([])


async def test_routine_runs_as_its_bot(tmp_path):
    from datetime import datetime

    from tests.fakes import ScriptedProvider
    from tests.test_routines import TOKYO, _service
    from yata.llm.types import LLMResponse

    provider = ScriptedProvider([LLMResponse(content="今朝のニュースは3件です。")])
    service, memory = _service(tmp_path, provider)
    bot = memory.create_bot(name="ニュース係", job="朝のニュースをまとめる", color="blue", accessory="phones")
    routine = service.create(name="朝のニュース", prompt="ニュースを要約して", model_id="demo", preset="morning",
                             now=datetime(2000, 1, 1, 7, 0, tzinfo=TOKYO), bot_id=bot.id)
    assert memory.get_conversation(routine.conversation_id).bot_id == bot.id
    await service.run_due(datetime(2000, 1, 1, 8, 1, tzinfo=TOKYO))
    await service.wait_for([routine.id])
    system = provider.seen[0][0]
    assert system.role == "system" and "「ニュース係」" in system.content
