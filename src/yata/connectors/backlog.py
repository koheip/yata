"""Backlog の API キーによる接続。

API キーは URL の apiKey パラメータで送る決まりなので、送り先は
*.backlog.jp と *.backlog.com のスペースだけに限る（別のホストにキーを渡さない）。
"""

from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urlparse

import httpx

from yata.connectors.base import Connector, ConnectorNotConfiguredError, ConnectorState

RETRY_AFTER_SECONDS = 60.0
_SPACE_HOST = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.backlog\.(jp|com)$")
INVALID_KEY_NOTE = "API キーが正しくありません。Backlog の「個人設定」→「API」で発行し直してください。"


def normalize_space(value: str | None) -> str | None:
    """「https://example.backlog.jp/dashboard」なども受け取り、ホスト名だけにする。使えない値は None。"""
    if not value:
        return None
    text = value.strip().lower()
    host = urlparse(text if "//" in text else f"https://{text}").hostname or ""
    return host if _SPACE_HOST.match(host) else None


class BacklogConnector(Connector):
    id = "backlog"
    label = "Backlog"
    auth_kind = "token"
    setup_instructions = "設定画面の「連携」から、スペースの URL と API キーを入れてください。"

    def __init__(self, space: str | None, api_key: str | None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._space = normalize_space(space)
        self._api_key = api_key.strip() if api_key else None
        self._transport = transport
        self._valid: bool | None = None
        self._note: str | None = None
        self._retry_at = 0.0

    @property
    def base_url(self) -> str | None:
        return f"https://{self._space}/api/v2" if self._space else None

    def _verify(self) -> None:
        """GET /users/myself でキーを確かめる（Chatwork と同じく、イベントループの外でだけ）。"""
        if not self.base_url or not self._api_key or self._valid is not None or time.monotonic() < self._retry_at:
            return
        try:
            asyncio.get_running_loop()
            return
        except RuntimeError:
            pass
        try:
            with httpx.Client(transport=self._transport, timeout=10) as client:
                response = client.get(f"{self.base_url}/users/myself", params={"apiKey": self._api_key})
        except httpx.HTTPError:
            self._retry_later("Backlog に接続できず、API キーを確認できませんでした。スペースの URL と通信環境を確認してください。")
            return
        if response.status_code in (401, 403):
            self._valid = False
            self._note = INVALID_KEY_NOTE
        elif response.status_code == 200:
            self._valid = True
            try:
                body = response.json()
                name = body.get("name") if isinstance(body, dict) else None
            except ValueError:
                name = None
            self._note = f"API キー確認済み（{name}）" if isinstance(name, str) and name else "API キー確認済み"
        else:
            self._retry_later(f"Backlog で API キーを確認できませんでした（{response.status_code}）。スペースの URL を確認してください。")

    def _retry_later(self, note: str) -> None:
        self._note = note
        self._retry_at = time.monotonic() + RETRY_AFTER_SECONDS

    def status(self) -> ConnectorState:
        if not self._space or not self._api_key:
            return ConnectorState.NOT_CONFIGURED
        self._verify()
        return ConnectorState.NOT_CONNECTED if self._valid is False else ConnectorState.CONNECTED

    def status_note(self) -> str | None:
        return self._note if self._api_key else None

    def credentials(self) -> tuple[str, str] | None:
        if not self.base_url or not self._api_key:
            return None
        return self.base_url, self._api_key

    def authorize_url(self, state: str, code_challenge: str) -> str:
        raise ConnectorNotConfiguredError(self.id)

    async def complete_authorization(self, code: str, code_verifier: str) -> None:
        raise NotImplementedError("Backlog は API キーで接続します。")

    def disconnect(self) -> bool:
        return False
