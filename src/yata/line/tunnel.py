"""LINE からヤタに話しかけるための入り口を、ヤタが自分で用意する。

- cloudflared の「クイックトンネル」で、LINE 用の Webhook（127.0.0.1:8742）だけを外に出す。
  ヤタの画面や API（8741）は出さない。届いたメッセージは署名を確かめ、許可したユーザー以外は無視する。
- 出てきた https://….trycloudflare.com/line/webhook を、LINE の API で Webhook URL に登録する。
- cloudflared が止まったら起動し直し、URL が変われば登録し直す。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

LINE_API = "https://api.line.me/v2/bot/channel/webhook"
WEBHOOK_PATH = "/line/webhook"
_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
INSTALL_HINT = "winget install --id Cloudflare.cloudflared"


def find_cloudflared(env: dict[str, str] | None = None) -> str | None:
    """cloudflared の場所。PATH になくても、Windows のよくある置き場所を探す。"""
    env = dict(os.environ) if env is None else env
    found = shutil.which("cloudflared", path=env.get("PATH"))
    if found:
        return found
    if sys.platform.startswith("win"):
        candidates = [
            Path(env.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "cloudflared.exe",
            Path(env.get("ProgramFiles", r"C:\Program Files")) / "cloudflared" / "cloudflared.exe",
            Path(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "cloudflared" / "cloudflared.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


def find_url(line: str) -> str | None:
    match = _URL.search(line)
    return match.group(0) if match else None


class LineTunnel:
    """cloudflared を動かし続け、その URL を LINE に登録する。状態は `status` で見られる。"""

    def __init__(self, access_token: str, port: int, *, executable: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, retry_seconds: float = 15.0):
        self._token = access_token
        self._port = port
        self._executable = executable
        self._transport = transport
        self._retry = retry_seconds
        self._task: asyncio.Task | None = None
        self._process: asyncio.subprocess.Process | None = None
        self.status: dict[str, Any] = {"state": "off", "message": "止まっています。"}

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self._kill()
        self.status = {"state": "off", "message": "止まっています。"}

    async def _kill(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()

    def _set(self, state: str, message: str, **extra: Any) -> None:
        self.status = {"state": state, "message": message, **extra}

    async def _run(self) -> None:
        executable = self._executable or find_cloudflared()
        if executable is None:
            self._set("missing", "cloudflared が入っていないので、LINE からは話しかけられません。"
                      f"PowerShell で「{INSTALL_HINT}」を実行して、ヤタを起動し直してください。",
                      install=INSTALL_HINT)
            return
        while True:
            try:
                await self._once(executable)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("LINE の入り口（cloudflared）で問題が起きました")
                self._set("error", "LINE の入り口を用意できませんでした。少し待ってからやり直します。")
            await self._kill()
            await asyncio.sleep(self._retry)

    async def _once(self, executable: str) -> None:
        self._set("starting", "LINE の入り口を用意しています…")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        self._process = await asyncio.create_subprocess_exec(
            executable, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{self._port}",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, creationflags=flags,
        )
        assert self._process.stderr is not None
        registered = False
        while True:
            raw = await self._process.stderr.readline()
            if not raw:
                break  # cloudflared が終わった
            url = None if registered else find_url(raw.decode("utf-8", "replace"))
            if url:
                registered = True
                await self.register(url)
        self._set("error", "LINE の入り口が止まりました。起動し直しています…")

    async def register(self, base_url: str) -> None:
        """LINE に Webhook URL を登録し、「Webhookの利用」がオンかを確かめる。"""
        endpoint = base_url.rstrip("/") + WEBHOOK_PATH
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(timeout=15, transport=self._transport) as client:
            response = await client.put(f"{LINE_API}/endpoint", json={"endpoint": endpoint}, headers=headers)
            if response.status_code in (401, 403):
                self._set("error", "LINE のチャネルアクセストークンが使えませんでした。設定を確かめてください。", url=endpoint)
                return
            if response.status_code >= 400:
                self._set("error", f"LINE に Webhook URL を登録できませんでした（{response.status_code}）。", url=endpoint)
                return
            active = None
            try:
                info = await client.get(f"{LINE_API}/endpoint", headers=headers)
                if info.status_code < 300:
                    active = bool(info.json().get("active"))
            except (httpx.HTTPError, ValueError, AttributeError):
                active = None
        if active is False:
            self._set("inactive", "Webhook URL は登録しました。LINE Developers の「Messaging API設定」で"
                      "「Webhookの利用」をオンにすると、LINE から話しかけられます。", url=endpoint, active=False)
            return
        self._set("ready", "LINE から話しかけられます。", url=endpoint, active=active)
