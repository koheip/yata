# PyInstaller の設定。リポジトリ直下で次のように使う:
#   npm --prefix frontend run build
#   uv run --with pyinstaller pyinstaller packaging/yata.spec --noconfirm
# できあがり: dist/Yata/Yata.exe（フォルダごと配る）
# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
DIST = ROOT / "frontend" / "dist"
if not (DIST / "index.html").is_file():
    raise SystemExit("frontend/dist がありません。先に npm --prefix frontend run build をしてください。")

datas = [(str(DIST), "frontend/dist")]
binaries = []
hiddenimports = collect_submodules("yata") + collect_submodules("uvicorn")

# データファイルを持っているライブラリはまるごと入れる。
for package in ("trafilatura", "justext", "htmldate", "courlan", "ddgs", "playwright", "certifi", "tzdata"):
    try:
        d, b, h = collect_all(package)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

icon = ROOT / "packaging" / "windows" / "yata.ico"

a = Analysis(
    [str(ROOT / "packaging" / "yata_app.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Yata",
    console=False,
    icon=str(icon) if sys.platform.startswith("win") else None,
    version=str(ROOT / "packaging" / "windows" / "version_info.txt") if sys.platform.startswith("win") else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Yata")
