"""kagi（AI エージェント用のシークレット・ブローカー）を通して LLM を呼ぶ。

この使い方では、ヤタは本物の API キーを持たない。持つのは次の2つだけ。

- mTLS のクライアント証明書（kagi がヤタを見分ける）
- 数分で切れるトークン（kagi に必要なときだけ発行してもらう）

本物のキーは kagi が上流の API に送る直前に付ける。プロンプトインジェクションで
ヤタがだまされても、キーそのものは漏れず、kagi のポリシーで許した API しか呼べない。
kagi: https://github.com/koheip/kagi
"""

from __future__ import annotations

import asyncio
import functools
import importlib
import re
import ssl
import time
from datetime import datetime

import httpx

# kagi が「トークンを取り直せば通る」ときに付けるヘッダー（期限切れ・回数の上限）。
# 上流の API 自身が返す 401 / 429 とは区別して、そちらでは取り直さない。
RENEW_HEADER = "x-kagi-token"
# 期限の少し前に取り直す（通信の途中で切れないように）
REFRESH_MARGIN_SECONDS = 30
_UPSTREAM_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class KagiError(Exception):
    """kagi からトークンをもらえなかった。"""


def valid_upstream(name: str) -> bool:
    return bool(_UPSTREAM_NAME.match(name))


class _KagiFlow:
    """リクエストごとに kagi のトークンを付ける。なければ取り、切れそうなら取り直す。

    OpenAI SDK は版によって httpx と httpx2 のどちらかを使う。処理はここに1つだけ書き、
    実際に使うライブラリの Auth と組み合わせる（_auth_class）。
    """

    _http = httpx

    def __init__(self, broker_url: str, upstream: str, *, ttl: str = "10m", purpose: str = "ヤタの会話"):
        self._token_url = broker_url.rstrip("/") + "/v1/token"
        self._body = {"upstream": upstream, "ttl": ttl, "purpose": purpose}
        self._token: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()
        self.now = time.time

    def _fresh(self) -> bool:
        return self._token is not None and self.now() < self._expires - REFRESH_MARGIN_SECONDS

    def _token_request(self):
        return self._http.Request("POST", self._token_url, json=self._body)

    def _store(self, response) -> None:
        if response.status_code != 200:
            try:
                detail = response.json().get("error", "")
            except ValueError:
                detail = ""
            raise KagiError(f"kagi がトークンを発行しませんでした（{response.status_code} {detail}）。"
                            "kagi のポリシーに、このエージェントの許可があるか確認してください。")
        data = response.json()
        self._token = data["token"]
        self._expires = datetime.fromisoformat(data["expires_at"]).timestamp()

    def _sign(self, request) -> None:
        # OpenAI SDK が付けた仮の Authorization を、kagi のトークンで上書きする
        request.headers["Authorization"] = f"Bearer {self._token}"

    @staticmethod
    def _renewable(response) -> bool:
        return response.headers.get(RENEW_HEADER) == "renew"

    def sync_auth_flow(self, request):
        if not self._fresh():
            response = yield self._token_request()
            response.read()
            self._store(response)
        self._sign(request)
        response = yield request
        if self._renewable(response):
            token_response = yield self._token_request()
            token_response.read()
            self._store(token_response)
            self._sign(request)
            yield request

    async def async_auth_flow(self, request):
        # 同時に何本も呼ばれても、トークンを取りに行くのは1本だけにする
        async with self._lock:
            if not self._fresh():
                response = yield self._token_request()
                await response.aread()
                self._store(response)
        self._sign(request)
        response = yield request
        if self._renewable(response):
            async with self._lock:
                self._token = None
                token_response = yield self._token_request()
                await token_response.aread()
                self._store(token_response)
            self._sign(request)
            yield request


@functools.cache
def _auth_class(module):
    return type("KagiAuth", (_KagiFlow, module.Auth), {"_http": module})


# 素の httpx 用（テストや、httpx を直接使う呼び出し元向け）
KagiAuth = _auth_class(httpx)


def _sdk_http_module():
    """OpenAI SDK が実際に使っている HTTP ライブラリ（httpx か httpx2）。"""
    from openai import DefaultAsyncHttpxClient

    for base in DefaultAsyncHttpxClient.__mro__[1:]:
        if base.__name__ == "AsyncClient":
            return importlib.import_module(base.__module__.split(".")[0])
    return httpx


def kagi_http_client(
    *,
    broker_url: str,
    upstream: str,
    ca_file: str,
    cert_file: str,
    key_file: str,
    ttl: str = "10m",
) -> httpx.AsyncClient:  # SDK によっては httpx2.AsyncClient
    """kagi 用の通信クライアント。TLS 1.3 で、kagi の CA だけを信頼し、証明書で名乗る。"""
    from openai import DefaultAsyncHttpxClient

    context = ssl.create_default_context(cafile=ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(cert_file, key_file)
    http = _sdk_http_module()
    return DefaultAsyncHttpxClient(
        verify=context,
        auth=_auth_class(http)(broker_url, upstream, ttl=ttl),
        timeout=http.Timeout(90, connect=10),
    )
