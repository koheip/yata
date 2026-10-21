"""Gmail and Google Calendar connectors. Both share one OAuth client and one
token store, but connect, disconnect, and scopes independently.
"""

from __future__ import annotations

import time

from yata.connectors.base import Connector, ConnectorNotConfiguredError, ConnectorState
from yata.connectors.google_oauth import (
    GoogleOAuthClient,
    authorize_url,
    exchange_code,
    refresh_access_token,
)
from yata.connectors.token_store import TokenStore

SETUP_INSTRUCTIONS = (
    "Google 連携（Gmail / カレンダー）にはまだ OAuth クライアントが設定されていません。\n"
    "1. Google Cloud Console でプロジェクトを作成し、「Gmail API」と「Google Calendar API」を有効にします。\n"
    "2. 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuth クライアント ID」で、"
    "アプリケーションの種類に「デスクトップアプリ」を選んで作成します。\n"
    "3. 「OAuth 同意画面」でテストユーザーとして自分の Google アカウントを追加します。\n"
    "4. ダウンロードした client_secret*.json のパスを .env の GOOGLE_OAUTH_CLIENT_SECRET_FILE に設定するか、"
    "client_id と client_secret を GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET に設定します。\n"
    "5. サーバーを再起動してから、この画面の「接続」を押します。"
)


class GoogleConnector(Connector):
    scopes: list[str] = []

    def __init__(self, client: GoogleOAuthClient | None, tokens: TokenStore) -> None:
        self._client = client
        self._tokens = tokens
        self.setup_instructions = SETUP_INSTRUCTIONS

    def status(self) -> ConnectorState:
        if self._client is None:
            return ConnectorState.NOT_CONFIGURED
        if self._tokens.load(self.id) is None:
            return ConnectorState.NOT_CONNECTED
        return ConnectorState.CONNECTED

    def authorize_url(self, state: str, code_challenge: str) -> str:
        if self._client is None:
            raise ConnectorNotConfiguredError(self.id)
        return authorize_url(self._client, scopes=self.scopes, state=state, code_challenge=code_challenge)

    async def complete_authorization(self, code: str, code_verifier: str) -> None:
        if self._client is None:
            raise ConnectorNotConfiguredError(self.id)
        token = await exchange_code(self._client, code=code, code_verifier=code_verifier)
        self._tokens.save(self.id, token)

    def disconnect(self) -> bool:
        return self._tokens.delete(self.id)

    async def access_token(self) -> str | None:
        """A valid bearer token, refreshed if close to expiry. None when disconnected."""
        if self._client is None:
            return None
        token = self._tokens.load(self.id)
        if token is None:
            return None
        if token.expires_at - time.time() > 60:
            return token.access_token
        if not token.refresh_token:
            return None
        refreshed = await refresh_access_token(self._client, refresh_token=token.refresh_token, scope=token.scope)
        self._tokens.save(self.id, refreshed)
        return refreshed.access_token


class GmailConnector(GoogleConnector):
    id = "gmail"
    label = "Gmail"
    scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.compose",
    ]


class GoogleCalendarConnector(GoogleConnector):
    id = "google_calendar"
    label = "Google カレンダー"
    scopes = [
        "https://www.googleapis.com/auth/calendar.events",
        # calendar.events alone does not authorize freebusy.query; this is
        # needed for calendar_check_free_busy.
        "https://www.googleapis.com/auth/calendar.events.freebusy",
    ]
