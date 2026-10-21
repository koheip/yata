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
    yata_port: int = 8741
    yata_db: str = "data/yata.db"
    yata_max_steps: int = Field(default=8, ge=1, le=24)
    yata_allow_private_urls: bool = True

    yata_gemini_model: str = "gemini-2.5-flash"
    yata_openai_model: str = "gpt-4o-mini"
    yata_anthropic_model: str = "claude-sonnet-4-5"
    yata_ollama_model: str = "gemma3:4b"

    def database_path(self) -> Path:
        return Path(self.yata_db)

    def artifacts_dir(self) -> Path:
        path = self.database_path().parent / "artifacts"
        path.mkdir(parents=True, exist_ok=True)
        return path


def key_ready(value: str | None) -> bool:
    return bool(value and value.strip() and not value.strip().lower().startswith("your-"))
