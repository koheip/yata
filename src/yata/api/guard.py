"""ヤタの API を、この PC のヤタの画面からだけ使えるようにする。

- ホスト名の確認：127.0.0.1 / localhost 以外の名前で来たリクエストを断る。
  悪意あるサイトが自分のドメインを 127.0.0.1 に向ける「DNS リバインディング」を防ぐ。
- ほかのサイトからの書き込みを断る：POST などで、ブラウザが付ける Origin や
  Sec-Fetch-Site がほかのサイトを示していたら断る（CSRF を防ぐ）。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable
from typing import Any
from urllib.parse import urlsplit

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def host_name(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    if value.count(":") > 1:  # かっこのない IPv6
        return value
    return value.split(":", 1)[0]


class LocalOnlyGuard:
    def __init__(self, app: Callable[..., Awaitable[None]], allowed_hosts: Iterable[str]):
        self.app = app
        self.allowed = {host_name(item) for item in allowed_hosts if item.strip()}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        if host_name(headers.get("host", "")) not in self.allowed:
            await self._reject(send, 400, "このアドレスからはヤタを使えません。http://127.0.0.1 で開いてください。")
            return
        method = scope.get("method", "GET").upper()
        if scope["type"] == "http" and method not in SAFE_METHODS and scope.get("path", "").startswith("/api/"):
            site = headers.get("sec-fetch-site")
            origin = headers.get("origin")
            cross_site = site is not None and site not in ("same-origin", "none")
            foreign_origin = origin is not None and (origin == "null" or host_name(urlsplit(origin).netloc) not in self.allowed)
            if cross_site or foreign_origin:
                await self._reject(send, 403, "ほかのサイトからの操作は受け付けません。")
                return
        await self.app(scope, receive, send)

    async def _reject(self, send: Send, status: int, message: str) -> None:
        body = json.dumps({"detail": message}, ensure_ascii=False).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
