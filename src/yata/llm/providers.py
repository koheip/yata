"""OpenAI 互換で話せる AI の一覧（ネットの AI と、パソコンの中で動く AI）。

どれも OpenAICompatibleProvider に base_url を変えて渡すだけで動く。
モデル名は変わりやすいので、キーを保存するときに相手のモデル一覧を見て選び、
見られなければ default_model を使う。
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class CloudProvider:
    id: str
    label: str  # 設定画面のカードの名前
    provider: str  # モデル選択に出す会社名
    base_url: str
    key_setting: str
    model_setting: str
    default_model: str
    prefer: tuple[str, ...]  # モデル一覧から選ぶときの優先順（前方一致）
    key_url: str
    steps: tuple[str, ...]
    badge: str = "使った分だけ料金がかかります"
    check_url: str | None = None  # キーの確認先。None なら base_url + /models


@dataclass(frozen=True)
class LocalServer:
    id: str
    label: str
    url_setting: str
    default_url: str
    model_setting: str
    site: str
    how: str  # 起動のしかた（1行）


CLOUD_PROVIDERS: tuple[CloudProvider, ...] = (
    CloudProvider(
        id="xai", label="xAI（Grok）", provider="xAI", base_url="https://api.x.ai/v1",
        key_setting="xai_api_key", model_setting="xai_model", default_model="grok-4-fast",
        prefer=("grok-4-fast", "grok-4", "grok-3-mini", "grok-3"),
        key_url="https://console.x.ai/",
        steps=("下のボタンで xAI のコンソールを開き、ログインします。", "「API Keys」で「Create API Key」を押します。",
               "表示されたキー（xai- で始まります）をコピーして、この下に貼り付けます。"),
    ),
    CloudProvider(
        id="deepseek", label="DeepSeek", provider="DeepSeek", base_url="https://api.deepseek.com/v1",
        key_setting="deepseek_api_key", model_setting="deepseek_model", default_model="deepseek-v4-flash",
        prefer=("deepseek-v4-flash", "deepseek-v4", "deepseek-chat"),
        key_url="https://platform.deepseek.com/api_keys", badge="安い料金で使えます",
        steps=("下のボタンで DeepSeek の API キーのページを開き、ログインします。", "「Create new API key」を押します。",
               "表示されたキー（sk- で始まります）をコピーして、この下に貼り付けます。"),
    ),
    CloudProvider(
        id="kimi", label="Kimi（Moonshot AI）", provider="Kimi", base_url="https://api.moonshot.ai/v1",
        key_setting="kimi_api_key", model_setting="kimi_model", default_model="kimi-k2.6",
        prefer=("kimi-k2.6", "kimi-k3", "kimi-k2"),
        key_url="https://platform.kimi.ai/console/api-keys", badge="安い料金で使えます",
        steps=("下のボタンで Kimi のコンソールを開き、ログインします。", "「API Keys」で新しいキーを作ります。",
               "表示されたキー（sk- で始まります）をコピーして、この下に貼り付けます。"),
    ),
    CloudProvider(
        id="mistral", label="Mistral AI", provider="Mistral", base_url="https://api.mistral.ai/v1",
        key_setting="mistral_api_key", model_setting="mistral_model", default_model="mistral-medium-latest",
        prefer=("mistral-medium-latest", "mistral-large-latest", "mistral-small-latest"),
        key_url="https://console.mistral.ai/api-keys", badge="無料の枠があります",
        steps=("下のボタンで Mistral のコンソールを開き、ログインします。", "「Create new key」を押します。",
               "表示されたキーをコピーして、この下に貼り付けます。"),
    ),
    CloudProvider(
        id="groq", label="Groq", provider="Groq", base_url="https://api.groq.com/openai/v1",
        key_setting="groq_api_key", model_setting="groq_model", default_model="openai/gpt-oss-120b",
        prefer=("openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b"),
        key_url="https://console.groq.com/keys", badge="無料の枠があります・速い",
        steps=("下のボタンで Groq のコンソールを開き、ログインします。", "「Create API Key」を押します。",
               "表示されたキー（gsk_ で始まります）をコピーして、この下に貼り付けます。"),
    ),
    CloudProvider(
        id="openrouter", label="OpenRouter（いろいろな AI をまとめて）", provider="OpenRouter",
        base_url="https://openrouter.ai/api/v1", key_setting="openrouter_api_key",
        model_setting="openrouter_model", default_model="openrouter/auto", prefer=("openrouter/auto",),
        key_url="https://openrouter.ai/settings/keys", check_url="https://openrouter.ai/api/v1/key",
        badge="無料のモデルもあります",
        steps=("下のボタンで OpenRouter のキーのページを開き、ログインします。", "「Create Key」を押します。",
               "表示されたキー（sk-or- で始まります）をコピーして、この下に貼り付けます。"),
    ),
    CloudProvider(
        id="plamo", label="PLaMo（国産・Preferred Networks）", provider="PLaMo",
        base_url="https://api.platform.preferredai.jp/v1", key_setting="plamo_api_key",
        model_setting="plamo_model", default_model="plamo-3.0-prime", prefer=("plamo-3.0-prime", "plamo"),
        key_url="https://platform.preferredai.jp/", badge="日本語に強い国産の AI",
        steps=("下のボタンで PLaMo Platform を開き、アカウントを作ってログインします。", "API キーを発行します（表示は一度だけです）。",
               "表示されたキーをコピーして、この下に貼り付けます。"),
    ),
)

LOCAL_SERVERS: tuple[LocalServer, ...] = (
    LocalServer("lmstudio", "LM Studio", "lmstudio_base_url", "http://127.0.0.1:1234/v1", "lmstudio_model",
                "https://lmstudio.ai/", "LM Studio でモデルを読み込み、「Developer」→「Start Server」を押します。"),
    LocalServer("llamacpp", "llama.cpp・LocalAI", "llamacpp_base_url", "http://127.0.0.1:8080/v1", "llamacpp_model",
                "https://github.com/ggml-org/llama.cpp", "llama-server -m モデル.gguf --jinja（LocalAI も同じ 8080 番）で起動します。"),
    LocalServer("jan", "Jan", "jan_base_url", "http://127.0.0.1:1337/v1", "jan_model",
                "https://jan.ai/", "Jan の「設定」→「Local API Server」を開いて起動します。"),
    LocalServer("vllm", "vLLM", "vllm_base_url", "http://127.0.0.1:8000/v1", "vllm_model",
                "https://docs.vllm.ai/", "vllm serve モデル名 --enable-auto-tool-choice で起動します。"),
)

LOCAL_IDS = frozenset({"ollama", "custom", *(server.id for server in LOCAL_SERVERS)})


def cloud_provider(provider_id: str) -> CloudProvider | None:
    return next((item for item in CLOUD_PROVIDERS if item.id == provider_id), None)


def local_server(server_id: str) -> LocalServer | None:
    return next((item for item in LOCAL_SERVERS if item.id == server_id), None)


def choose_model(available: Iterable[str], prefer: tuple[str, ...], default: str) -> str:
    """モデル一覧から、優先順に前方一致で選ぶ。見つからなければ default。"""
    ids = sorted(set(available))
    if default in ids:
        return default
    for prefix in prefer:
        matches = [model for model in ids if model.startswith(prefix)]
        if matches:
            return matches[0]
    return default


def openai_base(url: str) -> str:
    root = url.strip().rstrip("/")
    return root if root.endswith("/v1") else f"{root}/v1"


def on_premises(url: str | None) -> bool:
    """URL の行き先が、このパソコンか家・会社の中のネットワーク（プライベートアドレス）か。

    オフラインモードでは、「パソコンの中の AI」でも行き先が外のサーバーなら使わない。
    名前（example.com など）は、どこを指すか分からないので外とみなす。
    """
    host = (urlparse(url or "").hostname or "").lower()
    if host in ("localhost",) or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local
