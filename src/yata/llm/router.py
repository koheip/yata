"""Pick a concrete provider from a model id chosen in the UI or .env."""

from __future__ import annotations

from dataclasses import dataclass

from yata.config import Settings, key_ready
from yata.llm.anthropic_provider import AnthropicProvider
from yata.llm.demo import DemoProvider
from yata.llm.gemini_provider import GeminiProvider
from yata.llm.openai_provider import AUTO_MODEL, OpenAICompatibleProvider, ollama_openai_base
from yata.llm.providers import (
    CLOUD_PROVIDERS,
    LOCAL_IDS,
    LOCAL_SERVERS,
    cloud_provider,
    local_server,
    on_premises,
    openai_base,
)
from yata.llm.types import LLMProvider, ProviderError


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    provider: str
    upstream_model: str
    ready: bool
    note: str | None = None
    # パソコンの中で動く AI か（オフラインでも使える。小さいモデル向けにツールを絞る）
    local: bool = False


OFFLINE_NOTE = "オフラインモード中は、パソコンの中の AI（Ollama や LM Studio など）だけを使えます。"
OFFLINE_REMOTE_NOTE = "オフラインモード中は、このパソコンか社内・家の中のネットワークにあるサーバーだけを使えます。"


class ModelRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._demo = DemoProvider()

    def catalog(self) -> list[ModelInfo]:
        gemini_ready = key_ready(self.settings.gemini_api_key)
        openai_ready = key_ready(self.settings.openai_api_key)
        anthropic_ready = key_ready(self.settings.anthropic_api_key)
        return [
            ModelInfo(
                id="gemini",
                label="Gemini",
                provider="Google",
                upstream_model=self.settings.yata_gemini_model,
                ready=gemini_ready,
                note=None if gemini_ready else "GEMINI_API_KEY が未設定です。",
            ),
            ModelInfo(
                id="openai",
                label="GPT-4o mini",
                provider="OpenAI",
                upstream_model=self.settings.yata_openai_model,
                ready=openai_ready,
                note=None if openai_ready else "OPENAI_API_KEY が未設定です。",
            ),
            ModelInfo(
                id="anthropic",
                label="Claude",
                provider="Anthropic",
                upstream_model=self.settings.yata_anthropic_model,
                ready=anthropic_ready,
                note=None if anthropic_ready else "ANTHROPIC_API_KEY が未設定です。",
            ),
            *self._cloud_models(),
            ModelInfo(
                id="ollama",
                label="Ollama",
                provider="パソコンの中",
                upstream_model=(self.settings.yata_ollama_model or "").strip() or AUTO_MODEL,
                ready=True,
                note="Ollama が起動している必要があります。",
                local=True,
            ),
            *(
                ModelInfo(
                    id=server.id, label=server.label, provider="パソコンの中",
                    upstream_model=(getattr(self.settings, server.model_setting) or "").strip() or AUTO_MODEL,
                    ready=True, note=f"{server.label} が起動している必要があります。{server.how}", local=True,
                )
                for server in LOCAL_SERVERS
            ),
            ModelInfo(
                id="custom",
                label="その他の OpenAI 互換サーバー",
                provider="パソコンの中",
                upstream_model=(self.settings.custom_llm_model or "").strip() or AUTO_MODEL,
                ready=bool((self.settings.custom_llm_base_url or "").strip()),
                note=None if (self.settings.custom_llm_base_url or "").strip()
                else "設定画面の「パソコンの中の AI」で、サーバーの URL を入れてください。",
                local=True,
            ),
            ModelInfo(
                id="demo",
                label="デモ（キー不要）",
                provider="内蔵",
                upstream_model="demo",
                ready=True,
                note="ツールの流れを確認する簡易モデルです。普段使いの回答品質はありません。",
            ),
        ]

    def _cloud_models(self) -> list[ModelInfo]:
        models = []
        for item in CLOUD_PROVIDERS:
            ready = key_ready(getattr(self.settings, item.key_setting))
            model = (getattr(self.settings, item.model_setting) or "").strip() or item.default_model
            models.append(ModelInfo(
                id=item.id, label=item.label, provider=item.provider, upstream_model=model, ready=ready,
                note=None if ready else f"設定画面の「AI をつなぐ」で {item.label} のキーを入れてください。",
            ))
        return models

    def is_local(self, model_id: str) -> bool:
        return model_id in LOCAL_IDS

    def offline_safe(self, model_id: str) -> bool:
        """オフラインモードでも使えるか（パソコンの中の AI で、行き先も中のネットワーク）。"""
        if model_id == "demo":
            return True
        return model_id in LOCAL_IDS and on_premises(self.local_base_url(model_id))

    def tools_for(self, model_id: str, base, connectors):
        """そのモデルに見せるツール（オフラインと、パソコンの中の小さいモデルの分を絞る）。"""
        from yata.tools.catalog import registry_for_model

        return registry_for_model(
            base, connectors, local_model=self.is_local(model_id), offline=bool(self.settings.yata_offline),
            browser_for_local=bool(self.settings.yata_local_browser_tools),
        )

    def local_base_url(self, model_id: str) -> str | None:
        """パソコンの中の AI の、OpenAI 互換の URL（…/v1）。"""
        if model_id == "ollama":
            return ollama_openai_base(self.settings.ollama_base_url)
        if model_id == "custom":
            url = (self.settings.custom_llm_base_url or "").strip()
            return openai_base(url) if url else None
        server = local_server(model_id)
        return openai_base(getattr(self.settings, server.url_setting)) if server else None

    def get(self, model_id: str) -> ModelInfo:
        for info in self.catalog():
            if info.id == model_id:
                return info
        raise ProviderError(f"未知のモデルです: {model_id}", provider="router")

    def resolve(self, model_id: str) -> tuple[LLMProvider, str]:
        info = self.get(model_id)
        if model_id == "demo":
            return self._demo, info.upstream_model
        if not info.ready:
            raise ProviderError(info.note or "このモデルはまだ使えません。", provider=model_id)
        if self.settings.yata_offline and model_id not in LOCAL_IDS:
            raise ProviderError(OFFLINE_NOTE, provider=model_id)
        if self.settings.yata_offline and not self.offline_safe(model_id):
            raise ProviderError(OFFLINE_REMOTE_NOTE, provider=model_id)
        if model_id == "gemini":
            return GeminiProvider(api_key=self.settings.gemini_api_key or ""), info.upstream_model
        if model_id == "openai":
            return OpenAICompatibleProvider(
                api_key=self.settings.openai_api_key or "",
                base_url=None,
                provider_name="OpenAI",
            ), info.upstream_model
        if model_id == "anthropic":
            return AnthropicProvider(api_key=self.settings.anthropic_api_key or ""), info.upstream_model
        if model_id == "ollama":
            return OpenAICompatibleProvider(
                api_key="ollama",
                base_url=ollama_openai_base(self.settings.ollama_base_url),
                provider_name="Ollama",
                local=True,
            ), info.upstream_model
        cloud = cloud_provider(model_id)
        if cloud is not None:
            return OpenAICompatibleProvider(
                api_key=getattr(self.settings, cloud.key_setting) or "", base_url=cloud.base_url,
                provider_name=cloud.provider,
            ), info.upstream_model
        if model_id in LOCAL_IDS:
            base_url = self.local_base_url(model_id)
            if base_url is None:
                raise ProviderError(info.note or "このモデルはまだ使えません。", provider=model_id)
            key = (self.settings.custom_llm_api_key or "").strip() if model_id == "custom" else ""
            return OpenAICompatibleProvider(
                api_key=key or "local", base_url=base_url, provider_name=info.label, local=True,
            ), info.upstream_model
        raise ProviderError(f"未知のモデルです: {model_id}", provider="router")
