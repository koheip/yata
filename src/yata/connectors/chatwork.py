"""Chatwork の API トークンによる接続。"""

from __future__ import annotations

import asyncio
import time

import httpx

from yata.connectors.base import Connector, ConnectorNotConfiguredError, ConnectorState

CHATWORK_ME_URL = "https://api.chatwork.com/v2/me"
# 確認できなかったとき（通信エラーなど）は、この秒数のあいだ再確認しない。
RETRY_AFTER_SECONDS = 60.0

INVALID_TOKEN_NOTE = (
    "API トークンが正しくありません。.env の CHATWORK_API_TOKEN を確認して、Yata を再起動してください。"
)


class ChatworkConnector(Connector):
    id = "chatwork"
    label = "Chatwork"
    auth_kind = "token"
    setup_instructions = (
        "1. Chatwork の「サービス連携」→「API トークン」でトークンを発行します。\n"
        "https://www.chatwork.com/service/packages/chatwork/subpackages/api/token.php\n"
        "2. .env の CHATWORK_API_TOKEN に設定します。\n"
        "3. Yata を再起動してください。"
    )

    def __init__(self, token: str | None, transport: httpx.BaseTransport | None = None) -> None:
        self._token = token.strip() if token else None
        self._transport = transport
        # None: まだ確かめていない / True: GET /me が成功 / False: トークンが無効
        self._valid: bool | None = None
        self._note: str | None = None
        self._retry_at = 0.0

    def _verify(self) -> None:
        """GET /me でトークンを確かめる。結果が確定したら覚えておき、二度目以降は通信しない。

        同期の HTTP 呼び出しなので、イベントループの中（チャットの処理中など）では行わない。
        連携一覧の API はスレッドで動くため、そこで最初に確かめることになる。
        """
        if not self._token or self._valid is not None or time.monotonic() < self._retry_at:
            return
        try:
            asyncio.get_running_loop()
            return
        except RuntimeError:
            pass
        try:
            with httpx.Client(transport=self._transport, timeout=10) as client:
                response = client.get(CHATWORK_ME_URL, headers={"X-ChatWorkToken": self._token})
        except httpx.HTTPError:
            self._retry_later("Chatwork に接続できず、トークンを確認できませんでした。通信環境を確認してください。")
            return
        if response.status_code == 401:
            self._valid = False
            self._note = INVALID_TOKEN_NOTE
        elif response.status_code == 200:
            self._valid = True
            try:
                body = response.json()
                name = body.get("name") if isinstance(body, dict) else None
            except ValueError:
                name = None
            self._note = f"トークン確認済み（{name}）" if isinstance(name, str) and name else "トークン確認済み"
        else:
            self._retry_later(
                f"Chatwork でトークンを確認できませんでした（{response.status_code}）。しばらくしてから再読み込みしてください。"
            )

    def _retry_later(self, note: str) -> None:
        self._note = note
        self._retry_at = time.monotonic() + RETRY_AFTER_SECONDS

    def status(self) -> ConnectorState:
        if not self._token:
            return ConnectorState.NOT_CONFIGURED
        self._verify()
        return ConnectorState.NOT_CONNECTED if self._valid is False else ConnectorState.CONNECTED

    def status_note(self) -> str | None:
        return self._note if self._token else None

    async def access_token(self) -> str | None:
        return self._token or None

    def authorize_url(self, state: str, code_challenge: str) -> str:
        raise ConnectorNotConfiguredError(self.id)

    async def complete_authorization(self, code: str, code_verifier: str) -> None:
        raise NotImplementedError("Chatwork は API トークンで接続します。")

    def disconnect(self) -> bool:
        return False
