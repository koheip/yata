"""The extension point for real-life connectors.

Gmail and Google Calendar are the first two. LINE, Chatwork, freee, and
Rakuten can register the same way later: implement `Connector` and add it to
`connectors/catalog.py`. The agent loop never imports a connector directly;
it only sees the tools that `yata.tools.catalog.visible_registry` exposes
once a connector reports CONNECTED.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class ConnectorState(StrEnum):
    """未設定 / 未接続 / 接続済み, in that order of how far setup has gone."""

    NOT_CONFIGURED = "not_configured"
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"


class ConnectorNotConfiguredError(RuntimeError):
    def __init__(self, connector_id: str):
        super().__init__(f"connector not configured: {connector_id}")
        self.connector_id = connector_id


class Connector(ABC):
    id: str
    label: str
    setup_instructions: str = ""

    @abstractmethod
    def status(self) -> ConnectorState: ...

    @abstractmethod
    def authorize_url(self, state: str, code_challenge: str) -> str:
        """Raise ConnectorNotConfiguredError if there is no OAuth client yet."""

    @abstractmethod
    async def complete_authorization(self, code: str, code_verifier: str) -> None: ...

    @abstractmethod
    def disconnect(self) -> bool:
        """Delete the stored token. Returns False if there was nothing to delete."""


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.id] = connector

    def get(self, connector_id: str) -> Connector | None:
        return self._connectors.get(connector_id)

    def list(self) -> list[Connector]:
        return list(self._connectors.values())
