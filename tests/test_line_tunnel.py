"""LINE の入り口（cloudflared）の自動化。プロセスと通信はまねる。"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
import pytest

from yata.line.tunnel import LineTunnel, find_cloudflared, find_url

TOKEN = "line-token-for-tunnel-test"


def test_find_url():
    line = "2026-10-23T00:00:00Z INF |  https://abc-def-123.trycloudflare.com                    |"
    assert find_url(line) == "https://abc-def-123.trycloudflare.com"
    assert find_url("https://evil.example.com") is None


def test_find_cloudflared_uses_path(tmp_path):
    exe = tmp_path / ("cloudflared.exe" if sys.platform.startswith("win") else "cloudflared")
    exe.write_text("")
    exe.chmod(0o755)
    found = find_cloudflared({"PATH": str(tmp_path)})
    # Windows は大文字・小文字を区別しない（.exe が .EXE で返ることがある）
    assert found is not None and os.path.normcase(found) == os.path.normcase(str(exe))
    assert find_cloudflared({"PATH": str(tmp_path / "none")}) is None or sys.platform.startswith("win")


def line_api(active=True, put_status=200):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if request.method == "PUT":
            return httpx.Response(put_status, json={})
        return httpx.Response(200, json={"endpoint": "x", "active": active})

    return calls, httpx.MockTransport(handler)


async def test_register_sets_endpoint_and_reports_ready():
    calls, transport = line_api(active=True)
    tunnel = LineTunnel(TOKEN, 8742, transport=transport)
    await tunnel.register("https://abc.trycloudflare.com")
    assert json.loads(calls[0].content) == {"endpoint": "https://abc.trycloudflare.com/line/webhook"}
    assert tunnel.status["state"] == "ready" and tunnel.status["url"].endswith("/line/webhook")


async def test_register_tells_to_turn_on_webhook():
    _, transport = line_api(active=False)
    tunnel = LineTunnel(TOKEN, 8742, transport=transport)
    await tunnel.register("https://abc.trycloudflare.com")
    assert tunnel.status["state"] == "inactive" and "Webhookの利用" in tunnel.status["message"]


async def test_register_bad_token_hides_it():
    _, transport = line_api(put_status=401)
    tunnel = LineTunnel(TOKEN, 8742, transport=transport)
    await tunnel.register("https://abc.trycloudflare.com")
    assert tunnel.status["state"] == "error" and TOKEN not in json.dumps(tunnel.status)


async def test_missing_cloudflared(monkeypatch):
    monkeypatch.setattr("yata.line.tunnel.find_cloudflared", lambda env=None: None)
    tunnel = LineTunnel(TOKEN, 8742)
    tunnel.start()
    await asyncio.sleep(0.05)
    assert tunnel.status["state"] == "missing" and "winget" in tunnel.status["message"]
    await tunnel.stop()


@pytest.mark.skipif(sys.platform.startswith("win"), reason="シェルスクリプトで cloudflared をまねる")
async def test_runs_cloudflared_and_registers(tmp_path):
    fake = tmp_path / "cloudflared"
    fake.write_text("#!/bin/sh\necho 'INF | https://fake-tunnel-1.trycloudflare.com |' >&2\nsleep 30\n")
    fake.chmod(0o755)
    calls, transport = line_api(active=True)
    tunnel = LineTunnel(TOKEN, 8742, executable=str(fake), transport=transport)
    tunnel.start()
    for _ in range(100):
        if tunnel.status["state"] == "ready":
            break
        await asyncio.sleep(0.05)
    assert tunnel.status["url"] == "https://fake-tunnel-1.trycloudflare.com/line/webhook"
    await tunnel.stop()
    assert tunnel.status["state"] == "off"
