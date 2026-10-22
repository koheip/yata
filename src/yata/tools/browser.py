"""One Playwright browser, with a page per conversation.

PC-wide desktop control is intentionally not here. The same Tool interface
and Risk.EXTERNAL are the slot it would plug into. Click and type are
Risk.MUTATE, so the agent loop asks the user before they run.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from yata.netguard import UrlGuardError, ensure_fetchable
from yata.tools.base import Risk, Tool, ToolContext, ToolResult, clip_text

logger = logging.getLogger(__name__)

# Playwright 付属の Chromium がなければ、PC に入っている Edge → Chrome の順に使う。
# Windows には Edge が最初から入っているので、約150MB の Chromium を落とさずに済む。
FALLBACK_CHANNELS = ("msedge", "chrome")
NO_BROWSER_MESSAGE = (
    "ブラウザ操作に使えるブラウザが見つかりませんでした。"
    "Microsoft Edge か Google Chrome を入れてから、もう一度試してください。"
)


class BrowserUnavailableError(RuntimeError):
    pass


def _missing_executable(exc: Exception) -> bool:
    text = str(exc)
    return "Executable doesn't exist" in text or "is not found at" in text or "Please run the following command" in text


async def launch_browser(chromium: Any) -> Any:
    try:
        return await chromium.launch(headless=True)
    except Exception as exc:
        if not _missing_executable(exc):
            raise
    for channel in FALLBACK_CHANNELS:
        try:
            browser = await chromium.launch(headless=True, channel=channel)
        except Exception as exc:  # このチャンネルのブラウザが入っていない
            logger.debug("browser channel %s unavailable: %s", channel, exc)
            continue
        logger.info("Playwright の Chromium がないため、%s を使います", channel)
        return browser
    raise BrowserUnavailableError(NO_BROWSER_MESSAGE)


class BrowserSession:
    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._pages: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._start_lock = asyncio.Lock()

    def lock_for(self, conversation_id: str) -> asyncio.Lock:
        lock = self._locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[conversation_id] = lock
        return lock

    async def get_page(self, conversation_id: str) -> Any:
        async with self._start_lock:
            page = self._pages.get(conversation_id)
            if page is not None and not page.is_closed():
                return page
            if self._browser is None:
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
                try:
                    self._browser = await launch_browser(self._playwright.chromium)
                except Exception:
                    await self._playwright.stop()
                    self._playwright = None
                    raise
            page = await self._browser.new_page(viewport={"width": 1280, "height": 800})
            self._pages[conversation_id] = page
            return page

    async def close(self) -> None:
        for page in self._pages.values():
            try:
                await page.close()
            except Exception:
                logger.debug("page close failed", exc_info=True)
        self._pages.clear()
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


def _browser_error(exc: Exception) -> str:
    text = str(exc)
    if isinstance(exc, BrowserUnavailableError) or _missing_executable(exc):
        return NO_BROWSER_MESSAGE
    return f"ブラウザ操作に失敗しました: {text[:300]}"


class BrowserNavigateTool(Tool):
    name = "browser_navigate"
    description = "ブラウザで URL を開く。クリックや入力が必要なページで、最初にこれを使う。"
    parameters = {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "開く URL"}},
        "required": ["url"],
    }

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        url = str(arguments["url"]).strip()
        try:
            safe = ensure_fetchable(url, allow_private=ctx.allow_private_urls)
        except UrlGuardError as exc:
            return ToolResult(ok=False, content=str(exc))
        try:
            async with ctx.browser.lock_for(ctx.conversation_id):
                page = await ctx.browser.get_page(ctx.conversation_id)
                await page.goto(safe, wait_until="domcontentloaded", timeout=20000)
                title = await page.title()
                current = page.url
            return ToolResult(ok=True, content=f"開きました。タイトル: {title}\nURL: {current}")
        except Exception as exc:
            return ToolResult(ok=False, content=_browser_error(exc))


class BrowserSnapshotTool(Tool):
    name = "browser_snapshot"
    description = "開いているページのタイトル、URL、見えているテキストを返す。クリック前に状態を確認する。"
    parameters = {"type": "object", "properties": {}, "required": []}

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        del arguments
        try:
            async with ctx.browser.lock_for(ctx.conversation_id):
                page = await ctx.browser.get_page(ctx.conversation_id)
                title = await page.title()
                current = page.url
                text = await page.inner_text("body")
            body = clip_text(" ".join(text.split()) if text else "")
            if not current or current == "about:blank":
                return ToolResult(ok=False, content="まだページを開いていません。先に browser_navigate を使ってください。")
            return ToolResult(ok=True, content=f"タイトル: {title}\nURL: {current}\n\n{body}")
        except Exception as exc:
            return ToolResult(ok=False, content=_browser_error(exc))


class BrowserClickTool(Tool):
    name = "browser_click"
    description = (
        "Playwright のセレクタをクリックする。例: role=button[name=\"検索\"] や text=次へ。"
        "実行前にユーザー確認が入る。"
    )
    parameters = {
        "type": "object",
        "properties": {"selector": {"type": "string", "description": "Playwright のセレクタ"}},
        "required": ["selector"],
    }
    risk = Risk.MUTATE

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        selector = str(arguments["selector"])
        try:
            async with ctx.browser.lock_for(ctx.conversation_id):
                page = await ctx.browser.get_page(ctx.conversation_id)
                await page.click(selector, timeout=8000)
                title = await page.title()
                current = page.url
            return ToolResult(ok=True, content=f"クリックしました。今のタイトル: {title}\nURL: {current}")
        except Exception as exc:
            return ToolResult(ok=False, content=_browser_error(exc))


class BrowserTypeTool(Tool):
    name = "browser_type"
    description = (
        "セレクタの入力欄を、指定した文字で置き換える。submit が true なら Enter を送る。"
        "実行前にユーザー確認が入る。パスワードや送信は、ユーザーが明示したときだけ使う。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "入力欄の Playwright セレクタ"},
            "text": {"type": "string", "description": "入力する文字"},
            "submit": {"type": "boolean", "description": "入力後に Enter を送る。省略時は false。"},
        },
        "required": ["selector", "text"],
    }
    risk = Risk.MUTATE

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        selector = str(arguments["selector"])
        text = str(arguments["text"])
        submit = bool(arguments.get("submit", False))
        try:
            async with ctx.browser.lock_for(ctx.conversation_id):
                page = await ctx.browser.get_page(ctx.conversation_id)
                await page.fill(selector, text, timeout=8000)
                if submit:
                    await page.press(selector, "Enter")
                title = await page.title()
                current = page.url
            action = "入力して Enter を送りました" if submit else "入力しました"
            return ToolResult(ok=True, content=f"{action}。今のタイトル: {title}\nURL: {current}")
        except Exception as exc:
            return ToolResult(ok=False, content=_browser_error(exc))


class BrowserScreenshotTool(Tool):
    name = "browser_screenshot"
    description = "開いているページのスクリーンショットを撮る。見た目の確認に使う。クリックの代わりにはしない。"
    parameters = {"type": "object", "properties": {}, "required": []}

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        del arguments
        filename = f"{ctx.conversation_id[:8]}-{uuid.uuid4().hex[:8]}.png"
        path = Path(ctx.artifacts_dir) / filename
        try:
            async with ctx.browser.lock_for(ctx.conversation_id):
                page = await ctx.browser.get_page(ctx.conversation_id)
                current = page.url
                if not current or current == "about:blank":
                    return ToolResult(ok=False, content="まだページを開いていません。")
                await page.screenshot(path=str(path), full_page=False)
                title = await page.title()
                url = page.url
            return ToolResult(
                ok=True,
                content=f"スクリーンショットを取得しました。タイトル: {title}\nURL: {url}",
                artifact={"image_url": f"/api/artifacts/{filename}", "url": url, "title": title},
            )
        except Exception as exc:
            return ToolResult(ok=False, content=_browser_error(exc))
