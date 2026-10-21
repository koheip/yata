"""Turn vendor exceptions into short Japanese sentences for the chat."""

from __future__ import annotations


def humanize_provider_error(provider: str, exc: Exception) -> str:
    text = str(exc).strip()
    lowered = text.lower()
    if any(token in lowered for token in ("api key", "api_key", "unauthorized", "permission")) or "401" in text:
        return f"{provider} の API キーが拒否されました。.env のキーを確認してください。"
    if "429" in text or "rate limit" in lowered or "quota" in lowered:
        return f"{provider} の利用枠に達しました。しばらくしてからもう一度試してください。"
    if "404" in text or "not found" in lowered or "model" in lowered and "exist" in lowered:
        return f"{provider} のモデルが見つかりません。モデル名の設定を確認してください。"
    if any(token in lowered for token in ("connection", "connect", "timed out", "timeout", "refused")):
        return f"{provider} に接続できませんでした。ネットワークと、ローカルサーバーの URL を確認してください。"
    detail = text.replace("\n", " ")
    if len(detail) > 280:
        detail = detail[:280] + "…"
    return f"{provider} の呼び出しに失敗しました: {detail}"
