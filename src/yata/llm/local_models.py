"""パソコンの中の AI（Ollama・LM Studio など）に入っているモデルの一覧と、Ollama へのモデルの取りこみ。"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from yata.llm.openai_provider import ollama_root

# Ollama のモデル名（例: qwen3:4b、hf.co/user/model:Q4_K_M）。
MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,119}$")

# 画面で「おすすめ」として出すモデル。どれもツール（検索や連携）を使える。
RECOMMENDED_OLLAMA = (
    {"name": "qwen3:4b", "note": "軽い（メモリ 8GB〜）。日本語もそこそこ"},
    {"name": "qwen3:8b", "note": "ふつう（メモリ 16GB〜）。おすすめ"},
    {"name": "llama3.1:8b", "note": "ふつう（メモリ 16GB〜）"},
    {"name": "gpt-oss:20b", "note": "重い（メモリ 16GB〜、GPU があると快適）"},
)


async def ollama_models(base_url: str, timeout: float = 2.0) -> list[dict[str, Any]] | None:
    """Ollama に入っているモデル。つながらなければ None。"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(ollama_root(base_url).rstrip("/") + "/api/tags")
        if response.status_code >= 400:
            return None
        models = response.json().get("models") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    result = []
    for item in models:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            size = item.get("size")
            result.append({"name": item["name"], "size_gb": round(size / 1e9, 1) if isinstance(size, int | float) else None})
    return sorted(result, key=lambda item: item["name"])


async def openai_models(base_url: str, timeout: float = 2.0) -> list[str] | None:
    """OpenAI 互換サーバー（…/v1）にあるモデル。つながらなければ None。"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(base_url.rstrip("/") + "/models")
        if response.status_code >= 400:
            return None
        data = response.json().get("data") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    return sorted(item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str))


class OllamaPuller:
    """Ollama にモデルを取りこむ（ollama pull と同じ）。1度に1つだけ。進み具合を覚えておく。"""

    def __init__(self) -> None:
        self.status: dict[str, Any] = {"state": "idle"}
        self._task: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, base_url: str, model: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.status = {"state": "running", "model": model, "message": "準備しています…", "completed": 0, "total": 0}
        self._task = asyncio.create_task(self._run(base_url, model, transport))

    async def _run(self, base_url: str, model: str, transport) -> None:
        url = ollama_root(base_url).rstrip("/") + "/api/pull"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=600), transport=transport) as client:
                async with client.stream("POST", url, json={"model": model, "stream": True}) as response:
                    if response.status_code >= 400:
                        self.status = {"state": "error", "model": model,
                                       "message": "モデルを取りこめませんでした。名前を確かめてください。"}
                        return
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get("error"):
                            self.status = {"state": "error", "model": model,
                                           "message": f"取りこめませんでした: {str(event['error'])[:200]}"}
                            return
                        total, completed = event.get("total"), event.get("completed")
                        if isinstance(total, int) and total > 0:
                            self.status.update(total=total, completed=completed if isinstance(completed, int) else 0)
                        self.status["message"] = _pull_message(str(event.get("status", "")))
        except httpx.HTTPError:
            self.status = {"state": "error", "model": model, "message": "Ollama とつながりませんでした。Ollama が動いているか確かめてください。"}
            return
        self.status = {"state": "done", "model": model, "message": f"{model} を入れました。"}


def _pull_message(status: str) -> str:
    if status.startswith("pulling manifest"):
        return "モデルの情報を読んでいます…"
    if status.startswith("pulling") or status.startswith("downloading"):
        return "ダウンロードしています…"
    if status.startswith("verifying"):
        return "確かめています…"
    if status.startswith("writing") or status.startswith("success"):
        return "仕上げています…"
    return "取りこんでいます…"
