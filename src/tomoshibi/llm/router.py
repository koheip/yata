"""Pick a concrete provider from a model id chosen in the UI or .env."""

from __future__ import annotations

from dataclasses import dataclass

from tomoshibi.config import Settings, key_ready
from tomoshibi.llm.anthropic_provider import AnthropicProvider
from tomoshibi.llm.demo import DemoProvider
from tomoshibi.llm.gemini_provider import GeminiProvider
from tomoshibi.llm.openai_provider import OpenAICompatibleProvider, ollama_openai_base
from tomoshibi.llm.types import LLMProvider, ProviderError


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    provider: str
    upstream_model: str
    ready: bool
    note: str | None = None


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
                upstream_model=self.settings.tomoshibi_gemini_model,
                ready=gemini_ready,
                note=None if gemini_ready else "GEMINI_API_KEY が未設定です。",
            ),
            ModelInfo(
                id="openai",
                label="GPT-4o mini",
                provider="OpenAI",
                upstream_model=self.settings.tomoshibi_openai_model,
                ready=openai_ready,
                note=None if openai_ready else "OPENAI_API_KEY が未設定です。",
            ),
            ModelInfo(
                id="anthropic",
                label="Claude",
                provider="Anthropic",
                upstream_model=self.settings.tomoshibi_anthropic_model,
                ready=anthropic_ready,
                note=None if anthropic_ready else "ANTHROPIC_API_KEY が未設定です。",
            ),
            ModelInfo(
                id="ollama",
                label="Ollama（ローカル）",
                provider="OpenAI互換",
                upstream_model=self.settings.tomoshibi_ollama_model,
                ready=True,
                note="Ollama など OpenAI 互換サーバーが起動している必要があります。",
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
            ), info.upstream_model
        raise ProviderError(f"未知のモデルです: {model_id}", provider="router")
