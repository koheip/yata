"""インストールしたヤタ（Windows のアプリ）の入口。

- データは %LOCALAPPDATA%\\Yata に置く（インストール先は書きかえない）。
- すでに動いていれば、新しく起動せずにヤタのウィンドウだけを開く。
- コンソールのないアプリなので、ログはデータの置き場所の logs/ に書く。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "Yata"


def user_data_dir(platform: str | None = None, env: dict[str, str] | None = None) -> Path:
    platform = platform or sys.platform
    env = dict(os.environ) if env is None else env
    if env.get("YATA_HOME"):
        return Path(env["YATA_HOME"])
    if platform.startswith("win"):
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "yata"


def running_yata(url: str, timeout: float = 1.0) -> bool:
    """その URL で、ヤタがもう動いているか。"""
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as response:  # noqa: S310 - 127.0.0.1 だけ
            return json.loads(response.read().decode("utf-8")).get("name") == "yata"
    except (OSError, ValueError):
        return False


def prepare(data_dir: Path) -> None:
    """データの置き場所を用意し、設定とログをそこに向ける。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YATA_DB", str(data_dir / "yata.db"))
    # .env を置くならこの場所に。ブラウザ操作用の Chromium を入れる場合もここ。
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(data_dir / "browsers"))
    os.chdir(data_dir)
    if getattr(sys, "frozen", False):
        # コンソールのないアプリでは stdout/stderr が None になり、uvicorn が落ちるので塞いでおく。
        for name in ("stdout", "stderr"):
            if getattr(sys, name) is None:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
        logs = data_dir / "logs"
        logs.mkdir(exist_ok=True)
        handler = RotatingFileHandler(logs / "yata.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


def main(argv: list[str] | None = None) -> None:
    prepare(user_data_dir())

    from yata import main as server
    from yata.config import Settings

    settings = Settings()
    url = server.browser_url(settings.yata_host, settings.yata_port)
    if running_yata(url):
        # 2つ目を起動したときは、動いているヤタの画面を開くだけにする。
        if not (settings.yata_app_window and server.open_app_window(url)):
            import webbrowser

            webbrowser.open(url)
        return
    server.main(argv if argv is not None else [])


if __name__ == "__main__":
    main()
