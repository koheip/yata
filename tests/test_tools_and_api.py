"""Tool helpers that stay offline, plus the HTTP surface with the demo model."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from yata.api.app import create_app
from yata.config import Settings
from yata.netguard import UrlGuardError, ensure_fetchable
from yata.tools.base import ToolContext
from yata.tools.browser import BrowserClickTool, BrowserNavigateTool, BrowserScreenshotTool
from yata.tools.fetch import FetchPageTool, html_to_text
from yata.tools.search import format_search_results


def test_url_guard_blocks_metadata_and_optionally_private() -> None:
    assert ensure_fetchable("http://1.1.1.1/path", allow_private=False).startswith("http://1.1.1.1")
    try:
        ensure_fetchable("http://127.0.0.1/", allow_private=False)
        raise AssertionError("private host should be blocked")
    except UrlGuardError:
        pass
    assert ensure_fetchable("http://127.0.0.1/notes", allow_private=True).endswith("/notes")
    for url in ("http://169.254.169.254/latest/meta-data/", "file:///etc/passwd", "http://metadata.google.internal/"):
        try:
            ensure_fetchable(url, allow_private=True)
            raise AssertionError(f"should block {url}")
        except UrlGuardError:
            pass


def test_search_formatting_and_fetch_extract(tmp_path: Path) -> None:
    text = format_search_results(
        [{"title": "灯", "href": "https://example.com/a", "body": "個人用  アシスタント"}]
    )
    assert "https://example.com/a" in text
    assert "個人用 アシスタント" in text

    html = "<html><head><style>p{}</style></head><body><article><h1>灯</h1><p>本文です</p></article></body></html>"
    extracted = html_to_text(html, "https://example.com")
    assert "本文です" in extracted
    assert "p{}" not in extracted

    async def fake_fetch(url: str, allow_private: bool) -> tuple[str, str]:
        assert allow_private is True
        assert url == "https://example.com"
        return url, html

    tool = FetchPageTool(fetch_fn=fake_fetch)
    result = asyncio.run(
        tool.run(
            {"url": "https://example.com"},
            ToolContext("c", None, None, tmp_path, True),
        )
    )
    assert result.ok is True
    assert "本文です" in result.content


def test_browser_tools_use_the_session_double(tmp_path: Path) -> None:
    class Page:
        def __init__(self) -> None:
            self.url = "about:blank"
            self.clicked = None
            self.filled = None

        async def goto(self, url: str, wait_until: str, timeout: int) -> None:
            del wait_until, timeout
            self.url = url

        async def title(self) -> str:
            return "Example"

        async def click(self, selector: str, timeout: int) -> None:
            del timeout
            self.clicked = selector

        async def screenshot(self, path: str, full_page: bool = False) -> None:
            del full_page
            Path(path).write_bytes(b"png")

    class Browser:
        def __init__(self, page: Page) -> None:
            self.page = page
            self._lock = asyncio.Lock()

        def lock_for(self, conversation_id: str) -> asyncio.Lock:
            del conversation_id
            return self._lock

        async def get_page(self, conversation_id: str) -> Page:
            del conversation_id
            return self.page

    page = Page()
    browser = Browser(page)
    ctx = ToolContext("conversation-1", None, browser, tmp_path, False)

    blocked = asyncio.run(BrowserNavigateTool().run({"url": "http://127.0.0.1/secret"}, ctx))
    assert blocked.ok is False

    ctx_open = ToolContext("conversation-1", None, browser, tmp_path, True)
    opened = asyncio.run(BrowserNavigateTool().run({"url": "http://127.0.0.1/notes"}, ctx_open))
    assert opened.ok is True
    assert page.url == "http://127.0.0.1/notes"

    clicked = asyncio.run(BrowserClickTool().run({"selector": "text=次へ"}, ctx_open))
    assert clicked.ok is True
    assert page.clicked == "text=次へ"

    shot = asyncio.run(BrowserScreenshotTool().run({}, ctx_open))
    assert shot.ok is True
    assert shot.artifact is not None
    assert shot.artifact["image_url"].startswith("/api/artifacts/")
    assert (tmp_path / shot.artifact["image_url"].split("/")[-1]).is_file()


def test_api_demo_chat_persists_tool_steps(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(
        gemini_api_key=None,
        openai_api_key=None,
        anthropic_api_key=None,
        yata_db=str(tmp_path / "app.db"),
        yata_model="demo",
        yata_allow_private_urls=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        models = client.get("/api/models").json()
        by_id = {item["id"]: item for item in models["models"]}
        assert by_id["demo"]["ready"] is True
        assert by_id["gemini"]["ready"] is False

        created = client.post("/api/conversations", json={"model_id": "demo"})
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "こんにちは", "model_id": "demo"},
        ) as response:
            body = "".join(response.iter_text())
        assert '"type": "answer"' in body or '"type":"answer"' in body
        assert "デモモデル" in body

        detail = client.get(f"/api/conversations/{conversation_id}").json()
        assert detail["messages"][0]["role"] == "user"
        assert detail["messages"][1]["role"] == "assistant"
        assert "デモモデル" in detail["messages"][1]["content"]

        with client.stream(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "覚えて: university は ZEN大学", "model_id": "demo"},
        ) as response:
            memory_body = "".join(response.iter_text())
        assert "save_memory" in memory_body
        facts = client.get("/api/facts").json()["facts"]
        assert facts[0]["key"] == "university"
        assert facts[0]["value"] == "ZEN大学"

        denied = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "天気を調べて", "model_id": "gemini"},
        )
        assert denied.status_code == 400

        missing = client.post("/api/confirmations/does-not-exist", json={"approved": True})
        assert missing.status_code == 404
