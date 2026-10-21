"""Fetch a page and return its readable text."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin

import httpx

from yata.netguard import UrlGuardError, ensure_fetchable
from yata.tools.base import Tool, ToolContext, ToolResult, clip_text

USER_AGENT = "Yata/0.1 (personal research assistant)"
FetchFn = Callable[[str, bool], Awaitable[tuple[str, str]]]


def html_to_text(html: str, url: str) -> str:
    import trafilatura

    extracted = trafilatura.extract(html, url=url, include_comments=False, include_tables=False)
    if extracted and extracted.strip():
        return extracted.strip()
    return _bs4_text(html)


def _bs4_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    lines = [" ".join(line.split()) for line in soup.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line).strip()


async def fetch_html(url: str, allow_private: bool) -> tuple[str, str]:
    current = ensure_fetchable(url, allow_private=allow_private)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        for _ in range(4):
            response = await client.get(
                current,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            )
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise UrlGuardError("リダイレクト先がありません。")
                current = ensure_fetchable(urljoin(current, location), allow_private=allow_private)
                continue
            if response.status_code >= 400:
                raise UrlGuardError(f"ページが {response.status_code} を返しました。")
            content = response.content[:1_000_000]
            encoding = response.encoding or "utf-8"
            return current, content.decode(encoding, errors="replace")
    raise UrlGuardError("リダイレクトが多すぎます。")


class FetchPageTool(Tool):
    name = "fetch_page"
    description = (
        "URL の本文を取り出して読む。検索結果のリンクや、ユーザーが渡した URL を確認するときに使う。"
        "ログインやクリックが必要なら、代わりにブラウザツールを使う。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "http または https の URL"},
        },
        "required": ["url"],
    }

    def __init__(self, fetch_fn: FetchFn | None = None):
        self._fetch = fetch_fn or fetch_html

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        url = str(arguments["url"]).strip()
        try:
            final_url, html = await self._fetch(url, ctx.allow_private_urls)
            text = await asyncio.to_thread(html_to_text, html, final_url)
        except UrlGuardError as exc:
            return ToolResult(ok=False, content=str(exc))
        except Exception as exc:
            return ToolResult(ok=False, content=f"ページを読めませんでした: {exc}")
        if not text:
            return ToolResult(ok=False, content="本文を抽出できませんでした。ブラウザで開くことを検討してください。")
        body = clip_text(text)
        return ToolResult(ok=True, content=f"URL: {final_url}\n\n{body}")
