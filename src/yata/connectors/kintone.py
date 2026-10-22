"""kintone の API トークンによる接続。

トークンはアプリごとに発行するので、複数アプリを使うときはカンマ区切りで並べる。
送り先は *.cybozu.com と *.kintone.com だけに限る。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from yata.connectors.base import Connector, ConnectorNotConfiguredError, ConnectorState

_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.(cybozu\.com|kintone\.com)$")


def normalize_domain(value: str | None) -> str | None:
    """「https://example.cybozu.com/k/12/」なども受け取り、ホスト名だけにする。使えない値は None。"""
    if not value:
        return None
    text = value.strip().lower()
    host = urlparse(text if "//" in text else f"https://{text}").hostname or ""
    return host if _DOMAIN.match(host) else None


def clean_tokens(value: str | None) -> str | None:
    if not value:
        return None
    tokens = [token.strip() for token in value.replace("、", ",").split(",") if token.strip()]
    return ",".join(tokens) or None


class KintoneConnector(Connector):
    id = "kintone"
    label = "kintone"
    auth_kind = "token"
    setup_instructions = "設定画面の「連携」から、kintone の URL とアプリの API トークンを入れてください。"

    def __init__(self, domain: str | None, api_tokens: str | None) -> None:
        self._domain = normalize_domain(domain)
        self._tokens = clean_tokens(api_tokens)

    def status(self) -> ConnectorState:
        return ConnectorState.CONNECTED if self._domain and self._tokens else ConnectorState.NOT_CONFIGURED

    def status_note(self) -> str | None:
        if self._tokens and not self._domain:
            return "kintone の URL が正しくありません（例: https://example.cybozu.com）。"
        if self._domain and self._tokens:
            count = len(self._tokens.split(","))
            return f"{self._domain}（API トークン {count} 個）"
        return None

    def credentials(self) -> tuple[str, str] | None:
        if not self._domain or not self._tokens:
            return None
        return f"https://{self._domain}/k/v1", self._tokens

    def authorize_url(self, state: str, code_challenge: str) -> str:
        raise ConnectorNotConfiguredError(self.id)

    async def complete_authorization(self, code: str, code_verifier: str) -> None:
        raise NotImplementedError("kintone は API トークンで接続します。")

    def disconnect(self) -> bool:
        return False
