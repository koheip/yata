"""freee 会計 OAuth (PKCE) and rotating refresh tokens."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlencode

import httpx

from yata.config import key_ready
from yata.connectors.base import Connector, ConnectorNotConfiguredError, ConnectorState
from yata.connectors.token_store import TokenSet, TokenStore

AUTH_ENDPOINT = "https://accounts.secure.freee.co.jp/public_api/authorize"
TOKEN_ENDPOINT = "https://accounts.secure.freee.co.jp/public_api/token"


class FreeeOAuthError(RuntimeError):
    """Public, Japanese errors; never include the provider response."""


class FreeeConnector(Connector):
    id = "freee"
    label = "freee 会計"
    auth_kind = "oauth"

    def __init__(self, client_id: str | None, client_secret: str | None,
                 redirect_uri: str, tokens: TokenStore, http_client_factory=None):
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._tokens = tokens
        self._http_client_factory = http_client_factory or httpx.AsyncClient
        self._refresh_lock = asyncio.Lock()
        self.setup_instructions = (
            "freee 会計の OAuth クライアントを設定してください。\n"
            "1. https://app.secure.freee.co.jp/developers でアプリを登録します。\n"
            f"2. コールバック URL に {redirect_uri} を登録します。\n"
            "3. .env に FREEE_CLIENT_ID と FREEE_CLIENT_SECRET を設定します。\n"
            "4. Yata を再起動して「接続」を押します。"
        )

    def status(self) -> ConnectorState:
        if not key_ready(self._client_id) or not key_ready(self._client_secret):
            return ConnectorState.NOT_CONFIGURED
        return ConnectorState.CONNECTED if self._tokens.load(self.id) else ConnectorState.NOT_CONNECTED

    def authorize_url(self, state: str, code_challenge: str) -> str:
        if self.status() == ConnectorState.NOT_CONFIGURED:
            raise ConnectorNotConfiguredError(self.id)
        return AUTH_ENDPOINT + "?" + urlencode({
            "response_type": "code", "client_id": self._client_id,
            "redirect_uri": self._redirect_uri, "state": state, "prompt": "select_company",
            "code_challenge": code_challenge, "code_challenge_method": "S256",
        })

    async def _exchange(self, form: dict, *, scope: str = "") -> TokenSet:
        if self.status() == ConnectorState.NOT_CONFIGURED:
            raise ConnectorNotConfiguredError(self.id)
        try:
            async with self._http_client_factory(timeout=10) as client:
                response = await client.post(TOKEN_ENDPOINT, data={
                    **form, "client_id": self._client_id, "client_secret": self._client_secret,
                })
        except httpx.HTTPError:
            raise FreeeOAuthError("freee との通信に失敗しました。再試行してください。") from None
        try:
            error_body = response.json() if response.status_code >= 400 else {}
        except ValueError:
            error_body = {}
        if (response.status_code in (400, 401) and form["grant_type"] == "refresh_token"
                and isinstance(error_body, dict) and error_body.get("error") == "invalid_grant"):
            self.disconnect()
            raise FreeeOAuthError("freee の認証を更新できませんでした。再接続してください。")
        if response.status_code >= 400:
            raise FreeeOAuthError("freee の認証に失敗しました。再接続してください。")
        try:
            body = response.json()
            if not isinstance(body["access_token"], str) or not body["access_token"]:
                raise ValueError
            if not isinstance(body["refresh_token"], str) or not body["refresh_token"]:
                raise ValueError
            return TokenSet(body["access_token"], body["refresh_token"],
                            time.time() + float(body.get("expires_in", 21600)), body.get("scope") or scope)
        except (ValueError, KeyError, TypeError):
            raise FreeeOAuthError("freee の認証応答を読み取れませんでした。再接続してください。") from None

    async def complete_authorization(self, code: str, code_verifier: str) -> None:
        token = await self._exchange({"grant_type": "authorization_code", "code": code,
                                      "redirect_uri": self._redirect_uri, "code_verifier": code_verifier})
        self._tokens.save(self.id, token)

    def disconnect(self) -> bool:
        return self._tokens.delete(self.id)

    async def access_token(self) -> str | None:
        if self.status() == ConnectorState.NOT_CONFIGURED:
            return None
        # A refresh token is single-use: serialize refreshes and reload inside the lock.
        async with self._refresh_lock:
            token = self._tokens.load(self.id)
            if token is None:
                return None
            if token.expires_at - time.time() > 60:
                return token.access_token
            if not token.refresh_token:
                self.disconnect()
                raise FreeeOAuthError("freee の認証が切れました。再接続してください。")
            refreshed = await self._exchange({"grant_type": "refresh_token", "refresh_token": token.refresh_token}, scope=token.scope)
            self._tokens.save(self.id, refreshed)
            return refreshed.access_token
