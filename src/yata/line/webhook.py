"""公開側には署名付き Webhook と死活確認だけを公開する。"""
import asyncio
import base64
import hashlib
import hmac
import inspect
import json
import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request

logger = logging.getLogger(__name__)


def verify_signature(channel_secret: str, body: bytes, signature: str | None) -> bool:
    if not signature or not channel_secret:
        return False
    try:
        supplied = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError):
        return False
    expected = hmac.new(channel_secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(expected, supplied)


def create_webhook_app(channel_secret: str,
                       on_events: Callable[[list[dict]], Awaitable[None] | None]) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    tasks: set[asyncio.Task] = set()
    app.state.tasks = tasks

    async def dispatch(events):
        try:
            result = on_events(events)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.error("LINE Webhook のイベント処理に失敗しました。")

    @app.get("/line/health")
    async def health():
        return {"ok": True}

    @app.post("/line/webhook")
    async def webhook(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                raise HTTPException(413, "リクエストが大きすぎます。")
        if not verify_signature(channel_secret, bytes(body), request.headers.get("x-line-signature")):
            raise HTTPException(401, "署名が無効です。")
        try:
            payload = json.loads(body)
            events = payload.get("events", [])
            if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
                raise ValueError
        except (ValueError, AttributeError, UnicodeDecodeError):
            raise HTTPException(400, "JSON が無効です。") from None
        task = asyncio.create_task(dispatch(events))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"ok": True}

    return app
