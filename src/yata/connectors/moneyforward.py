"""マネーフォワード クラウド請求書の OAuth（PKCE つき）。

リフレッシュトークンは一度しか使えないので、更新はロックで1つずつ行う（freee と同じ）。
クライアントの認証は、マネーフォワードの案内どおり Basic 認証で送る。
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlencode

import httpx

from yata.config import key_ready
from yata.connectors.base import Connector, ConnectorNotConfiguredError, ConnectorState
from yata.connectors.token_store import TokenSet, TokenStore

AUTH_ENDPOINT = "https://api.biz.moneyforward.com/authorize"
TOKEN_ENDPOINT = "https://api.biz.moneyforward.com/token"
SCOPES = "mfc/invoice/data.read mfc/invoice/data.write"


class MoneyForwardOAuthError(RuntimeError):
    """画面に出してよい日本語のエラー。相手の応答の中身は入れない。"""


class MoneyForwardConnector(Connector):
    id = "moneyforward"
    label = "マネーフォワード クラウド請求書"
    auth_kind = "oauth"
    setup_instructions = "設定画面の「連携」から、アプリの Client ID と Client Secret を入れてください。"

    def __init__(self, client_id: str | None, client_secret: str | None, redirect_uri: str,
                 tokens: TokenStore, http_client_factory=None):
        self._client_id = client_id.strip() if client_id else None
        self._client_secret = client_secret.strip() if client_secret else None
        self._redirect_uri = redirect_uri
        self._tokens = tokens
        self._http_client_factory = http_client_factory or httpx.AsyncClient
        self._refresh_lock = asyncio.Lock()

    def status(self) -> ConnectorState:
        if not key_ready(self._client_id) or not key_ready(self._client_secret):
            return ConnectorState.NOT_CONFIGURED
        return ConnectorState.CONNECTED if self._tokens.load(self.id) else ConnectorState.NOT_CONNECTED

    def authorize_url(self, state: str, code_challenge: str) -> str:
        if self.status() == ConnectorState.NOT_CONFIGURED:
            raise ConnectorNotConfiguredError(self.id)
        return AUTH_ENDPOINT + "?" + urlencode({
            "response_type": "code", "client_id": self._client_id, "redirect_uri": self._redirect_uri,
            "scope": SCOPES, "state": state, "code_challenge": code_challenge, "code_challenge_method": "S256",
        })

    async def _exchange(self, form: dict) -> TokenSet:
        if self.status() == ConnectorState.NOT_CONFIGURED:
            raise ConnectorNotConfiguredError(self.id)
        try:
            async with self._http_client_factory(timeout=10) as client:
                response = await client.post(
                    TOKEN_ENDPOINT, data=form, auth=(self._client_id or "", self._client_secret or ""),
                )
        except httpx.HTTPError:
            raise MoneyForwardOAuthError("マネーフォワードとの通信に失敗しました。再試行してください。") from None
        if response.status_code in (400, 401) and form["grant_type"] == "refresh_token":
            self.disconnect()
            raise MoneyForwardOAuthError("マネーフォワードの認証を更新できませんでした。もう一度「接続する」を押してください。")
        if response.status_code >= 400:
            raise MoneyForwardOAuthError("マネーフォワードの認証に失敗しました。もう一度「接続する」を押してください。")
        try:
            body = response.json()
            access, refresh = body["access_token"], body["refresh_token"]
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                raise ValueError
            return TokenSet(access, refresh, time.time() + float(body.get("expires_in", 3600)), body.get("scope") or SCOPES)
        except (ValueError, KeyError, TypeError):
            raise MoneyForwardOAuthError("マネーフォワードの認証の応答を読み取れませんでした。") from None

    async def complete_authorization(self, code: str, code_verifier: str) -> None:
        token = await self._exchange({"grant_type": "authorization_code", "code": code,
                                      "redirect_uri": self._redirect_uri, "code_verifier": code_verifier})
        self._tokens.save(self.id, token)

    def disconnect(self) -> bool:
        return self._tokens.delete(self.id)

    def secrets(self) -> list[str]:
        """エラー文から消す値。"""
        saved = self._tokens.load(self.id)
        values = [self._client_secret, self._client_id]
        if saved:
            values += [saved.access_token, saved.refresh_token]
        return [value for value in values if value]

    async def access_token(self) -> str | None:
        if self.status() == ConnectorState.NOT_CONFIGURED:
            return None
        async with self._refresh_lock:
            token = self._tokens.load(self.id)
            if token is None:
                return None
            if token.expires_at - time.time() > 60:
                return token.access_token
            refreshed = await self._exchange({"grant_type": "refresh_token", "refresh_token": token.refresh_token})
            self._tokens.save(self.id, refreshed)
            return refreshed.access_token
