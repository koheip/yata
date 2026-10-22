"""画面から入力された API キーや連携のトークンを、PC の中だけに保存する。

保存先は data/secrets.json（data/ は git に入らない）。キーの値は API の応答にも
ログにも出さない。.env に書いたキーより、画面で入れたキーを優先する。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ALLOWED_KEYS = (
    "gemini_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "chatwork_api_token",
    "rakuten_application_id",
    "rakuten_access_key",
    "rakuten_affiliate_id",
    "line_channel_secret",
    "line_channel_access_token",
    "line_allowed_user_ids",
    "freee_client_id",
    "freee_client_secret",
    "google_oauth_client_id",
    "google_oauth_client_secret",
    "backlog_space",
    "backlog_api_key",
    "kintone_domain",
    "moneyforward_client_id",
    "moneyforward_client_secret",
    "kintone_api_tokens",
    "xai_api_key",
    "xai_model",
    "deepseek_api_key",
    "deepseek_model",
    "kimi_api_key",
    "kimi_model",
    "mistral_api_key",
    "mistral_model",
    "groq_api_key",
    "groq_model",
    "openrouter_api_key",
    "openrouter_model",
    "plamo_api_key",
    "plamo_model",
    "custom_llm_base_url",
    "custom_llm_api_key",
    "custom_llm_model",
    "yata_offline",
    "yata_ollama_model",
    "lmstudio_model",
    "llamacpp_model",
    "jan_model",
    "vllm_model",
)


class SecretStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if k in ALLOWED_KEYS and isinstance(v, str) and v}

    def get(self, name: str) -> str | None:
        return self.load().get(name)

    def set(self, name: str, value: str) -> None:
        if name not in ALLOWED_KEYS:
            raise KeyError(name)
        data = self.load()
        data[name] = value
        self._write(data)

    def delete(self, name: str) -> bool:
        data = self.load()
        if name not in data:
            return False
        del data[name]
        self._write(data)
        return True

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass  # Windows などで権限を変えられなくても、保存は続ける
        temporary.replace(self.path)
