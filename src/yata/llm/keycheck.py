"""API キーが使えるかを、各社のモデル一覧 API に一度だけ聞いて確かめる。"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from yata.llm.providers import cloud_provider


@dataclass(frozen=True)
class KeyCheck:
    ok: bool | None  # True: 使える / False: 使えない / None: 確かめられなかった
    message: str
    models: tuple[str, ...] = field(default=())  # 相手が返したモデル名（OpenAI 互換のときだけ）


def _request(provider: str, key: str) -> tuple[str, dict[str, str], dict[str, str]]:
    if provider == "gemini":
        return "https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": key}, {"pageSize": "1"}
    if provider == "openai":
        return "https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"}, {}
    if provider == "anthropic":
        return "https://api.anthropic.com/v1/models", {"x-api-key": key, "anthropic-version": "2023-06-01"}, {"limit": "1"}
    cloud = cloud_provider(provider)
    if cloud is not None:
        return cloud.check_url or f"{cloud.base_url}/models", {"Authorization": f"Bearer {key}"}, {}
    raise ValueError(provider)


async def check_key(provider: str, key: str, transport: httpx.AsyncBaseTransport | None = None) -> KeyCheck:
    url, headers, params = _request(provider, key)
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            response = await client.get(url, headers=headers, params=params)
    except httpx.HTTPError:
        return KeyCheck(None, "インターネットにつながらず、キーを確かめられませんでした。")
    status = response.status_code
    if status < 300:
        return KeyCheck(True, "つながりました。", _model_ids(response))
    if status == 429:
        return KeyCheck(True, "つながりました（いまは利用回数の上限に近いようです）。")
    if status == 404 and cloud_provider(provider) is not None:
        return KeyCheck(None, "いまはキーを確かめられませんでした。")
    if status in (400, 401, 403):
        return KeyCheck(False, "このキーは使えませんでした。コピーしたキーが正しいか確かめてください。")
    return KeyCheck(None, f"いまはキーを確かめられませんでした（{status}）。少し待ってからもう一度試してください。")


def _model_ids(response: httpx.Response) -> tuple[str, ...]:
    try:
        data = response.json().get("data")
    except (ValueError, AttributeError):
        return ()
    if not isinstance(data, list):
        return ()
    return tuple(item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str))
