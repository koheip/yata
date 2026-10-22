"""Runtime settings loaded from the environment and an optional .env file."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration.

    API keys stay in the environment. Nothing in this object is written to git.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"

    yata_model: str = "gemini"
    yata_host: str = "127.0.0.1"
    # この名前で来たリクエストだけを受け付ける（DNS リバインディング対策）。カンマ区切り。
    yata_allowed_hosts: str = "127.0.0.1,localhost,::1"
    yata_port: int = 8741
    # 起動したら画面を開く。yata_app_window なら Edge / Chrome の専用ウィンドウで開く。
    yata_open_browser: bool = True
    yata_app_window: bool = True
    yata_db: str = "data/yata.db"
    yata_max_steps: int = Field(default=8, ge=1, le=24)
    yata_allow_private_urls: bool = True

    yata_gemini_model: str = "gemini-2.5-flash"
    yata_openai_model: str = "gpt-4o-mini"
    yata_anthropic_model: str = "claude-sonnet-4-5"
    yata_ollama_model: str = "gemma3:4b"

    # OpenAI 互換で話せるネットの AI（yata/llm/providers.py）。モデル名は空ならキー保存時に選ぶ。
    xai_api_key: str | None = None
    xai_model: str | None = None
    deepseek_api_key: str | None = None
    deepseek_model: str | None = None
    kimi_api_key: str | None = None
    kimi_model: str | None = None
    mistral_api_key: str | None = None
    mistral_model: str | None = None
    groq_api_key: str | None = None
    groq_model: str | None = None
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    plamo_api_key: str | None = None
    plamo_model: str | None = None

    # パソコンの中で動く AI のサーバー（Ollama のほか）。モデルは読み込まれているものを使う。
    lmstudio_base_url: str = "http://127.0.0.1:1234/v1"
    llamacpp_base_url: str = "http://127.0.0.1:8080/v1"
    jan_base_url: str = "http://127.0.0.1:1337/v1"
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    # それぞれで使うモデル。空なら、いま読み込まれているモデルを使う。
    lmstudio_model: str | None = None
    llamacpp_model: str | None = None
    jan_model: str | None = None
    vllm_model: str | None = None
    # その他の OpenAI 互換サーバー。モデル名が空なら、サーバーにある最初のモデルを使う。
    custom_llm_base_url: str | None = None
    custom_llm_api_key: str | None = None
    custom_llm_model: str | None = None
    # パソコンの中の AI には、ブラウザ操作のツールを渡さない（小さいモデルが迷わないように）。
    yata_local_browser_tools: bool = False
    # 完全オフライン。パソコンの中の AI だけを使い、ネット検索・ページ取得・ブラウザ・外部の連携を止める。
    yata_offline: bool = False

    yata_scheduler_enabled: bool = True
    yata_scheduler_interval_seconds: int = Field(default=30, ge=5, le=3600)
    yata_timezone: str = "Asia/Tokyo"
    yata_routine_confirm_timeout: float = Field(default=86_400, ge=1, le=604_800)

    # Google 連携（Gmail / カレンダー）。どちらも未設定なら連携は「未設定」のままで、
    # ツールはモデルに提示されない。
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_client_secret_file: str | None = None

    # freee 会計連携。OAuth クライアント ID とシークレットの両方が必要。
    freee_client_id: str | None = None
    freee_client_secret: str | None = None

    # Chatwork 連携。API トークンが未設定ならツールは提示されない。
    chatwork_api_token: str | None = None

    # LINE 連携。Webhook の署名検証と送信認証、許可ユーザーを設定する。
    line_channel_secret: str | None = None
    line_channel_access_token: str | None = None
    line_allowed_user_ids: str | None = None
    line_webhook_port: int = 8742
    # LINE から話しかけるための入り口（cloudflared）を、ヤタが自分で用意して LINE に登録する。
    yata_line_tunnel: bool = True

    # 楽天市場連携。アプリケーション ID とアクセスキーの両方が必要。
    rakuten_application_id: str | None = None
    rakuten_access_key: str | None = None
    rakuten_affiliate_id: str | None = None
    rakuten_origin: str | None = None

    # Backlog 連携。スペースの URL（例: https://example.backlog.jp）と API キー。
    backlog_space: str | None = None
    backlog_api_key: str | None = None

    # マネーフォワード クラウド請求書。アプリポータルで作ったアプリの Client ID と Client Secret。
    moneyforward_client_id: str | None = None
    moneyforward_client_secret: str | None = None

    # kintone 連携。URL（例: https://example.cybozu.com）とアプリの API トークン（カンマ区切り）。
    kintone_domain: str | None = None
    kintone_api_tokens: str | None = None

    def allowed_hosts(self) -> list[str]:
        return [item.strip() for item in self.yata_allowed_hosts.split(",") if item.strip()]

    def database_path(self) -> Path:
        return Path(self.yata_db)

    def artifacts_dir(self) -> Path:
        path = self.database_path().parent / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path


def key_ready(value: str | None) -> bool:
    return bool(value and value.strip() and not value.strip().lower().startswith("your-"))
