"""Run the API and the built chat UI on one port."""

from __future__ import annotations

import argparse
import logging

import uvicorn

from tomoshibi.api.app import create_app
from tomoshibi.config import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tomoshibi", description="灯 — 個人用AIアシスタント")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings()
    host = args.host or settings.tomoshibi_host
    port = args.port or settings.tomoshibi_port
    uvicorn.run(create_app(settings), host=host, port=port)


if __name__ == "__main__":
    main()
