"""インストール版の入口（データの置き場所、二重起動、終了）とブラウザの切り替えを検証する。"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yata import desktop
from yata import main as server_module
from yata.api import app as app_module
from yata.api.app import create_app
from yata.config import Settings
from yata.tools import browser as browser_module


@pytest.mark.parametrize("platform, env, expected", [
    ("win32", {"LOCALAPPDATA": r"C:\Users\a\AppData\Local"}, Path(r"C:\Users\a\AppData\Local") / "Yata"),
    ("linux", {"XDG_DATA_HOME": "/home/a/.data"}, Path("/home/a/.data") / "yata"),
    ("win32", {"YATA_HOME": "/custom"}, Path("/custom")),
])
def test_user_data_dir(platform, env, expected):
    assert desktop.user_data_dir(platform, env) == expected


def test_prepare_points_database_into_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("YATA_DB", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "Yata"
    desktop.prepare(data)
    assert data.is_dir() and Path.cwd() == data
    assert os.environ["YATA_DB"] == str(data / "yata.db")
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(data / "browsers")


def _serve(body: dict):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def test_running_yata_detection():
    yata = _serve({"ok": True, "name": "yata"})
    other = _serve({"ok": True, "name": "something-else"})
    try:
        assert desktop.running_yata(f"http://127.0.0.1:{yata.server_port}") is True
        assert desktop.running_yata(f"http://127.0.0.1:{other.server_port}") is False
    finally:
        yata.shutdown()
        other.shutdown()
    assert desktop.running_yata("http://127.0.0.1:1", timeout=0.2) is False


def test_second_launch_only_opens_the_window(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # prepare() が作業フォルダを移すので、テスト後に戻す
    monkeypatch.delenv("YATA_DB", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setenv("YATA_HOME", str(tmp_path / "Yata"))
    monkeypatch.setattr(desktop, "running_yata", lambda url: True)
    opened = []
    monkeypatch.setattr(server_module, "open_app_window", lambda url: opened.append(url) or True)
    monkeypatch.setattr(server_module, "main", lambda argv=None: pytest.fail("must not start a second server"))
    desktop.main([])
    assert opened == ["http://127.0.0.1:8741"]


def test_first_launch_starts_the_server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # prepare() が作業フォルダを移すので、テスト後に戻す
    monkeypatch.delenv("YATA_DB", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setenv("YATA_HOME", str(tmp_path / "Yata"))
    monkeypatch.setattr(desktop, "running_yata", lambda url: False)
    started = []
    monkeypatch.setattr(server_module, "main", lambda argv=None: started.append(argv))
    desktop.main([])
    assert started == [[]]


def test_quit_endpoint_stops_the_app(tmp_path, monkeypatch):
    timers = []

    class FakeTimer:
        def __init__(self, delay, fn, args=()):
            timers.append((delay, fn, args))

        def start(self):
            pass

    monkeypatch.setattr(app_module.threading, "Timer", FakeTimer)
    settings = Settings(_env_file=None, yata_db=str(tmp_path / "yata.db"), yata_model="demo", yata_scheduler_enabled=False)
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/app/quit").json() == {"ok": True}
        # ほかのサイトからは止められない
        assert client.post("/api/app/quit", headers={"Origin": "https://evil.example"}).status_code == 403
    assert len(timers) == 1 and timers[0][1] is app_module.signal.raise_signal


class FakeChromium:
    def __init__(self, available):
        self.available = available
        self.calls = []

    async def launch(self, headless=True, channel=None):
        self.calls.append(channel)
        if channel in self.available:
            return f"browser:{channel}"
        if channel is None:
            raise RuntimeError("BrowserType.launch: Executable doesn't exist at /x/chrome")
        raise RuntimeError(f"Chromium distribution '{channel}' is not found at /y")


@pytest.mark.parametrize("available, expected, calls", [
    ({None}, "browser:None", [None]),
    ({"msedge"}, "browser:msedge", [None, "msedge"]),
    ({"chrome"}, "browser:chrome", [None, "msedge", "chrome"]),
])
async def test_launch_falls_back_to_installed_edge_or_chrome(available, expected, calls):
    chromium = FakeChromium(available)
    assert await browser_module.launch_browser(chromium) == expected
    assert chromium.calls == calls


async def test_launch_without_any_browser_explains_in_japanese():
    with pytest.raises(browser_module.BrowserUnavailableError) as caught:
        await browser_module.launch_browser(FakeChromium(set()))
    assert "Edge" in str(caught.value)
    assert browser_module._browser_error(caught.value) == browser_module.NO_BROWSER_MESSAGE


async def test_other_launch_errors_are_not_hidden():
    class Broken:
        async def launch(self, headless=True, channel=None):
            raise RuntimeError("sandbox crashed")

    with pytest.raises(RuntimeError, match="sandbox crashed"):
        await browser_module.launch_browser(Broken())
