"""Run the API and the built chat UI on one port."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from yata.api.app import create_app
from yata.config import Settings
from yata.line.webhook import create_webhook_app


class WebhookServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        yield


async def serve_with_line(app, host, port, settings):
    main_server = uvicorn.Server(uvicorn.Config(app, host=host, port=port))
    bridge = app.state.line_bridge
    webhook = WebhookServer(uvicorn.Config(
        create_webhook_app(bridge.connector.channel_secret, bridge.handle_events),
        host="127.0.0.1", port=settings.line_webhook_port,
    ))
    logging.getLogger(__name__).info(
        "LINE Webhook を 127.0.0.1:%s で待ち受けます", settings.line_webhook_port,
    )

    async def serve_main():
        try:
            await main_server.serve()
        finally:
            webhook.should_exit = True

    async def serve_webhook():
        try:
            await webhook.serve()
        except (Exception, SystemExit):
            logging.getLogger(__name__).exception(
                "LINE Webhook を 127.0.0.1:%s で起動できませんでした。LINE_WEBHOOK_PORT を確認してください。",
                settings.line_webhook_port,
            )

    await asyncio.gather(serve_main(), serve_webhook())


def browser_url(host: str, port: int) -> str:
    # 0.0.0.0 などで待ち受けていても、ブラウザでは自分の PC として開く。
    if host in ("", "0.0.0.0", "::"):
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}"


def find_app_browser(platform: str | None = None, env: dict[str, str] | None = None) -> str | None:
    """アプリモード（--app）で開ける Edge か Chrome を探す。見つからなければ None。"""
    platform = platform or sys.platform
    env = dict(os.environ) if env is None else env
    candidates: list[Path] = []
    if platform.startswith("win"):
        roots = [env.get("ProgramFiles(x86)"), env.get("ProgramFiles"), env.get("LOCALAPPDATA")]
        for root in filter(None, roots):
            candidates.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        for root in filter(None, roots):
            candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif platform == "darwin":
        candidates += [
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    else:
        for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def open_app_window(url: str, browser: str | None = None) -> bool:
    """タブやアドレスバーのない、ヤタ専用のウィンドウで開く。開けなければ False。"""
    executable = browser or find_app_browser()
    if executable is None:
        return False
    try:
        subprocess.Popen(  # noqa: S603 - 自分で探したブラウザに、ヤタの URL だけを渡す
            [executable, f"--app={url}", "--window-size=1100,820"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        return False
    return True


def open_browser_when_ready(
    host: str, port: int, timeout: float = 30.0, app_window: bool = True
) -> threading.Thread:
    """サーバーが接続を受け付けるようになってから、画面を開く。

    app_window が True なら専用ウィンドウで開き、できなければいつものブラウザで開く。
    """
    url = browser_url(host, port)
    target = url.split("//", 1)[1].rsplit(":", 1)[0].strip("[]")

    def wait_and_open() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((target, port), timeout=1):
                    break
            except OSError:
                time.sleep(0.3)
        else:
            return
        if app_window and open_app_window(url):
            logging.getLogger(__name__).info("ヤタの画面を専用ウィンドウで開きました（%s）", url)
            return
        logging.getLogger(__name__).info("ブラウザで %s を開きます", url)
        webbrowser.open(url)

    thread = threading.Thread(target=wait_and_open, name="open-browser", daemon=True)
    thread.start()
    return thread


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="yata", description="ヤタ — 個人用AIアシスタント")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true", help="起動時に画面を開かない")
    parser.add_argument("--browser-tab", action="store_true", help="専用ウィンドウではなく、ブラウザのタブで開く")
    args = parser.parse_args(argv)

    # アプリ版（desktop.py）が先にログの書き先を決めていれば、それを使う。
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    # httpx は INFO で URL をまるごとログに出す。URL に API キーを付ける連携（Backlog など）があるので止める。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings()
    host = args.host or settings.yata_host
    port = args.port or settings.yata_port
    app = create_app(settings)
    if settings.yata_open_browser and not args.no_browser:
        open_browser_when_ready(host, port, app_window=settings.yata_app_window and not args.browser_tab)
    bridge = app.state.line_bridge
    if bridge is None or not bridge.connector.webhook_ready:
        uvicorn.run(app, host=host, port=port)
    else:
        asyncio.run(serve_with_line(app, host, port, settings))


if __name__ == "__main__":
    main()
