"""LINE Messaging API の接続設定。"""
from yata.config import key_ready
from yata.connectors.base import Connector, ConnectorNotConfiguredError, ConnectorState


class LineConnector(Connector):
    id = "line"
    label = "LINE"
    auth_kind = "token"
    setup_instructions = (
        "1. LINE Official Account を作成し、Messaging API チャネルを有効にします。\n"
        "2. 「チャネル基本設定」のチャネルシークレットを .env の LINE_CHANNEL_SECRET に設定します。\n"
        "3. 「Messaging API設定」で長期チャネルアクセストークンを発行し、"
        "LINE_CHANNEL_ACCESS_TOKEN に設定します。\n"
        "4. LINE_ALLOWED_USER_IDS に許可するユーザー ID をカンマ区切りで設定します。\n"
        "5. scripts/line-tunnel.ps1 を起動し、Webhook URL を <public>/line/webhook に設定します。\n"
        "6. Yata を再起動してください。"
    )

    def __init__(self, channel_secret: str | None, access_token: str | None,
                 allowed_user_ids: str | None = None):
        self._secret = (channel_secret or "").strip()
        self._token = (access_token or "").strip()
        self._allowed = [value.strip() for value in (allowed_user_ids or "").split(",") if value.strip()]

    @property
    def channel_secret(self) -> str:
        return self._secret

    @property
    def allowed_user_ids(self) -> list[str]:
        return list(self._allowed)

    @property
    def owner_user_id(self) -> str | None:
        return next(iter(self._allowed), None)

    @property
    def webhook_ready(self) -> bool:
        # 署名検証にシークレットが要るため、受信はシークレットも揃ったときだけ有効にする。
        return key_ready(self._secret) and key_ready(self._token)

    def status(self) -> ConnectorState:
        return ConnectorState.CONNECTED if key_ready(self._token) else ConnectorState.NOT_CONFIGURED

    def status_note(self) -> str | None:
        if self.status() != ConnectorState.CONNECTED:
            return None
        note = (f"許可ユーザー: {len(self._allowed)} 人" if self._allowed
                else "許可ユーザー未設定（LINE_ALLOWED_USER_IDS）")
        if not self.webhook_ready:
            note += "／受信は停止中（LINE_CHANNEL_SECRET 未設定）"
        return note

    async def access_token(self) -> str | None:
        return self._token or None

    def authorize_url(self, state: str, code_challenge: str) -> str:
        raise ConnectorNotConfiguredError(self.id)

    async def complete_authorization(self, code: str, code_verifier: str) -> None:
        raise NotImplementedError("LINE はチャネルアクセストークンで接続します。")

    def disconnect(self) -> bool:
        return False
