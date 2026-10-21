"""楽天市場のアプリケーション ID とアクセスキーによる接続。"""

from __future__ import annotations

from yata.connectors.base import Connector, ConnectorNotConfiguredError, ConnectorState


class RakutenConnector(Connector):
    id = "rakuten"
    label = "楽天市場"
    auth_kind = "token"
    setup_instructions = (
        "1. https://webservice.rakuten.co.jp/ に楽天会員でログインします。\n"
        "2.「+アプリID発行」で新規アプリを登録します。アプリケーションタイプは"
        "「バックエンドサービス」を選び、許可IPアドレスにこのPCのグローバルIPを登録します。\n"
        "3. 表示された「アプリケーションID」と「アクセスキー（pk_…）」を .env の"
        " RAKUTEN_APPLICATION_ID と RAKUTEN_ACCESS_KEY に設定します。\n"
        "4. 任意で RAKUTEN_AFFILIATE_ID を設定します。Webアプリケーションの場合は"
        " RAKUTEN_ORIGIN に登録サイトと完全一致する Origin を設定します。\n"
        "5. Yata を再起動してください。"
    )

    def __init__(
        self, application_id: str | None, access_key: str | None,
        affiliate_id: str | None = None, origin: str | None = None,
    ) -> None:
        self._application_id = application_id.strip() if application_id else None
        self._access_key = access_key.strip() if access_key else None
        self._affiliate_id = affiliate_id.strip() if affiliate_id else None
        self._origin = origin.strip() if origin else None

    def status(self) -> ConnectorState:
        return (ConnectorState.CONNECTED if self._application_id and self._access_key
                else ConnectorState.NOT_CONFIGURED)

    def credentials(self) -> dict[str, str | None]:
        return {
            "applicationId": self._application_id, "accessKey": self._access_key,
            "affiliateId": self._affiliate_id, "Origin": self._origin,
        }

    def authorize_url(self, state: str, code_challenge: str) -> str:
        raise ConnectorNotConfiguredError(self.id)

    async def complete_authorization(self, code: str, code_verifier: str) -> None:
        raise NotImplementedError("楽天市場はアプリケーション ID とアクセスキーで接続します。")

    def disconnect(self) -> bool:
        return False
