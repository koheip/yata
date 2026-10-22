"""起動時に、いつものブラウザで画面を開く処理を検証する。"""
import socket

import pytest

from yata import main as main_module
from yata.config import Settings


@pytest.mark.parametrize(
    "host, expected",
    [("127.0.0.1", "http://127.0.0.1:8741"), ("0.0.0.0", "http://127.0.0.1:8741"),
     ("::", "http://127.0.0.1:8741"), ("::1", "http://[::1]:8741"), ("localhost", "http://localhost:8741")],
)
def test_browser_url(host, expected):
    assert main_module.browser_url(host, 8741) == expected


@pytest.mark.parametrize("app_ok", [False, True])
def test_opens_after_server_accepts_connections(monkeypatch, app_ok):
    opened, windows = [], []
    monkeypatch.setattr(main_module.webbrowser, "open", opened.append)
    monkeypatch.setattr(main_module, "open_app_window", lambda url: windows.append(url) or app_ok)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        main_module.open_browser_when_ready("127.0.0.1", port, timeout=5).join(5)
    url = f"http://127.0.0.1:{port}"
    assert windows == [url]
    assert opened == ([] if app_ok else [url])  # 専用ウィンドウが開けなければ、いつものブラウザで開く


def test_browser_tab_mode_skips_app_window(monkeypatch):
    opened = []
    monkeypatch.setattr(main_module.webbrowser, "open", opened.append)
    monkeypatch.setattr(main_module, "open_app_window", lambda url: pytest.fail("app window must not open"))
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        main_module.open_browser_when_ready("127.0.0.1", port, timeout=5, app_window=False).join(5)
    assert opened == [f"http://127.0.0.1:{port}"]


def test_find_app_browser_prefers_edge_then_chrome(tmp_path):
    env = {"ProgramFiles(x86)": str(tmp_path / "x86"), "ProgramFiles": str(tmp_path / "pf"),
           "LOCALAPPDATA": str(tmp_path / "local")}
    assert main_module.find_app_browser("win32", env) is None
    chrome = tmp_path / "local" / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_text("")
    assert main_module.find_app_browser("win32", env) == str(chrome)
    edge = tmp_path / "pf" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_text("")
    assert main_module.find_app_browser("win32", env) == str(edge)


def test_open_app_window_launches_with_app_flag(monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            calls.append(args)

    monkeypatch.setattr(main_module.subprocess, "Popen", FakePopen)
    assert main_module.open_app_window("http://127.0.0.1:8741", browser="/x/msedge.exe") is True
    assert calls == [["/x/msedge.exe", "--app=http://127.0.0.1:8741", "--window-size=1100,820"]]
    monkeypatch.setattr(main_module, "find_app_browser", lambda: None)
    assert main_module.open_app_window("http://127.0.0.1:8741") is False

    def broken(args, **kwargs):
        raise OSError("cannot start")

    monkeypatch.setattr(main_module.subprocess, "Popen", broken)
    assert main_module.open_app_window("http://127.0.0.1:8741", browser="/x/msedge.exe") is False


def test_does_not_open_when_server_never_starts(monkeypatch):
    opened = []
    monkeypatch.setattr(main_module.webbrowser, "open", opened.append)
    monkeypatch.setattr(main_module, "open_app_window", opened.append)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    main_module.open_browser_when_ready("127.0.0.1", port, timeout=0.5).join(3)
    assert opened == []


@pytest.mark.parametrize("argv, setting, app_setting, expected", [
    ([], True, True, [("127.0.0.1", 8741, True)]),
    (["--browser-tab"], True, True, [("127.0.0.1", 8741, False)]),
    ([], True, False, [("127.0.0.1", 8741, False)]),
    (["--no-browser"], True, True, []),
    ([], False, True, []),
])
def test_main_respects_no_browser(monkeypatch, tmp_path, argv, setting, app_setting, expected):
    started = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda app, host, port: None)
    monkeypatch.setattr(main_module, "open_browser_when_ready",
                        lambda host, port, app_window: started.append((host, port, app_window)))
    monkeypatch.setattr(main_module, "Settings", lambda: Settings(
        _env_file=None, yata_db=str(tmp_path / "yata.db"), yata_scheduler_enabled=False,
        yata_open_browser=setting, yata_app_window=app_setting,
    ))
    main_module.main(argv)
    assert started == expected
