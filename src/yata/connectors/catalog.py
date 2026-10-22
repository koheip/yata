"""The default connector set. Add LINE, Chatwork, freee, or Rakuten here the
same way: implement Connector, register it, and give the matching tools a
`required_connector`.
"""

from __future__ import annotations

from yata.config import Settings
from yata.connectors.backlog import BacklogConnector
from yata.connectors.base import ConnectorRegistry
from yata.connectors.chatwork import ChatworkConnector
from yata.connectors.freee import FreeeConnector
from yata.connectors.google import GmailConnector, GoogleCalendarConnector
from yata.connectors.google_oauth import load_google_oauth_client
from yata.connectors.kintone import KintoneConnector
from yata.connectors.line import LineConnector
from yata.connectors.moneyforward import MoneyForwardConnector
from yata.connectors.rakuten import RakutenConnector
from yata.connectors.token_store import TokenStore


def build_connector_registry(settings: Settings) -> ConnectorRegistry:
    client = load_google_oauth_client(settings)
    tokens = TokenStore(settings.database_path().parent / "connectors")
    registry = ConnectorRegistry()
    registry.register(GmailConnector(client, tokens))
    registry.register(GoogleCalendarConnector(client, tokens))
    registry.register(ChatworkConnector(settings.chatwork_api_token))
    registry.register(RakutenConnector(
        settings.rakuten_application_id, settings.rakuten_access_key,
        settings.rakuten_affiliate_id, settings.rakuten_origin,
    ))
    registry.register(FreeeConnector(
        settings.freee_client_id, settings.freee_client_secret,
        f"http://127.0.0.1:{settings.yata_port}/api/connectors/freee/oauth/callback", tokens,
    ))
    registry.register(LineConnector(settings.line_channel_secret, settings.line_channel_access_token,
                                    settings.line_allowed_user_ids))
    registry.register(BacklogConnector(settings.backlog_space, settings.backlog_api_key))
    registry.register(KintoneConnector(settings.kintone_domain, settings.kintone_api_tokens))
    registry.register(MoneyForwardConnector(
        settings.moneyforward_client_id, settings.moneyforward_client_secret,
        f"http://127.0.0.1:{settings.yata_port}/api/connectors/moneyforward/oauth/callback", tokens,
    ))
    return registry
