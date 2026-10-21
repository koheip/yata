"""Chatwork の API トークンによる接続。"""

from __future__ import annotations

from yata.connectors.base import Connector, ConnectorNotConfiguredError, ConnectorState


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

    def __init__(self, token: str | None) -> None:
        self._token = token.strip() if token else None

    def status(self) -> ConnectorState:
        return ConnectorState.CONNECTED if self._token else ConnectorState.NOT_CONFIGURED

    async def access_token(self) -> str | None:
        return self._token or None

    def authorize_url(self, state: str, code_challenge: str) -> str:
        raise ConnectorNotConfiguredError(self.id)

    async def complete_authorization(self, code: str, code_verifier: str) -> None:
        raise NotImplementedError("Chatwork は API トークンで接続します。")

    def disconnect(self) -> bool:
        return False
