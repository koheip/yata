"""Manual OAuth 2.0 authorization-code + PKCE flow against Google's endpoints.

Why not google-auth-oauthlib's InstalledAppFlow: it opens its own loopback
HTTP server, and this app already has one on 127.0.0.1:8741. The lower-level
pieces here (an auth URL and two token POSTs) are small enough to own
directly with httpx, which is already a dependency.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from yata.connectors.token_store import TokenSet

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GoogleOAuthError(RuntimeError):
    pass


@dataclass
class GoogleOAuthClient:
    client_id: str
    client_secret: str
    redirect_uri: str


def load_google_oauth_client(settings: Any) -> GoogleOAuthClient | None:
    """None when no client is configured. The app still starts; connectors
    using this client just report NOT_CONFIGURED."""
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    secret_file = settings.google_oauth_client_secret_file
    if secret_file:
        try:
            data = json.loads(Path(secret_file).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        block = data.get("installed") or data.get("web") or {}
        client_id = client_id or block.get("client_id")
        client_secret = client_secret or block.get("client_secret")
    if not client_id or not client_secret:
        return None
    redirect_uri = f"http://127.0.0.1:{settings.yata_port}/api/connectors/google/oauth/callback"
    return GoogleOAuthClient(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)


def authorize_url(client: GoogleOAuthClient, *, scopes: list[str], state: str, code_challenge: str) -> str:
    params = {
        "client_id": client.client_id,
        "redirect_uri": client.redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_code(client: GoogleOAuthClient, *, code: str, code_verifier: str) -> TokenSet:
    async with httpx.AsyncClient(timeout=10) as http_client:
        response = await http_client.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": client.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    return _token_from_response(response)


async def refresh_access_token(client: GoogleOAuthClient, *, refresh_token: str, scope: str) -> TokenSet:
    async with httpx.AsyncClient(timeout=10) as http_client:
        response = await http_client.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    token = _token_from_response(response, fallback_scope=scope)
    if token.refresh_token is None:
        token.refresh_token = refresh_token
    return token


def _token_from_response(response: httpx.Response, *, fallback_scope: str = "") -> TokenSet:
    if response.status_code >= 400:
        raise GoogleOAuthError(f"Google のトークン取得に失敗しました（{response.status_code}）。")
    body = response.json()
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_at=time.time() + float(body.get("expires_in", 3600)),
        scope=body.get("scope") or fallback_scope,
    )
