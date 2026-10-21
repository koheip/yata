"""URL checks shared by fetch and browser navigation.

The initial URL is checked before any request. Redirects in the fetch tool are
checked one hop at a time. This is a personal assistant, so private hosts can
be allowed explicitly. The cloud metadata address stays blocked either way,
which matters once the same code is deployed beyond a laptop.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

METADATA_HOSTS = {"metadata.google.internal"}
METADATA_IPS = {ipaddress.ip_address("169.254.169.254")}


class UrlGuardError(ValueError):
    """The URL is not safe to open."""


def ensure_fetchable(url: str, *, allow_private: bool) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise UrlGuardError("http または https の URL だけ開けます。")
    if parsed.username or parsed.password:
        raise UrlGuardError("URL にユーザー情報は含められません。")
    host = parsed.hostname
    if host is None or host == "":
        raise UrlGuardError("URL のホストが空です。")
    if host.lower().rstrip(".") in METADATA_HOSTS:
        raise UrlGuardError("このホストにはアクセスできません。")

    try:
        port = parsed.port
    except ValueError as exc:
        raise UrlGuardError("URL のポートが不正です。") from exc
    port = port or (443 if parsed.scheme == "https" else 80)

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UrlGuardError("ホスト名を解決できませんでした。") from exc

    seen = False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        seen = True
        if ip in METADATA_IPS:
            raise UrlGuardError("このアドレスにはアクセスできません。")
        if not allow_private and _is_blocked_private(ip):
            raise UrlGuardError(
                "プライベートアドレスへのアクセスは無効です。"
                "個人利用で必要なときは TOMOSHIBI_ALLOW_PRIVATE_URLS=true にしてください。"
            )
    if not seen:
        raise UrlGuardError("ホスト名を解決できませんでした。")
    return url.strip()


def _is_blocked_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )
