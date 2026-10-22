"""Run the API and the built chat UI on one port."""

from __future__ import annotations

import argparse
import asyncio
import logging
from contextlib import contextmanager

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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="yata", description="ヤタ — 個人用AIアシスタント")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings()
    host = args.host or settings.yata_host
    port = args.port or settings.yata_port
    app = create_app(settings)
    bridge = app.state.line_bridge
    if bridge is None or not bridge.connector.webhook_ready:
        uvicorn.run(app, host=host, port=port)
    else:
        asyncio.run(serve_with_line(app, host, port, settings))


if __name__ == "__main__":
    main()
