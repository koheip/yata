"""LINE Webhook を受信から返信まで通しで検証する（ネットワークなし）。"""
import asyncio
import json
import re

import httpx
import pytest

from tests.test_line import (
    SECRET,
    TOKEN,
    ExternalTool,
    drain,
    setup_bridge,  # noqa: F401  フィクスチャとして再利用する
    sign,
    text_event,
)
from yata.api.app import create_app
from yata.config import Settings
from yata.confirm.gate import InMemoryConfirmationGate
from yata.line.client import LineClient
from yata.line.webhook import create_webhook_app
from yata.llm.types import LLMResponse, ToolCall


@pytest.mark.parametrize("failure", ["status", "network"])
async def test_reply_failure_falls_back_to_push(failure):
    requests = []

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("reply"):
            if failure == "network":
                raise httpx.ConnectError(TOKEN, request=request)
            return httpx.Response(500, text=TOKEN)
        return httpx.Response(200)

    await LineClient(TOKEN, httpx.MockTransport(handler)).send_text("Uowner", "こんにちは", "reply-token")
    assert [path.rsplit("/", 1)[-1] for path, _ in requests] == ["reply", "push"]
    assert requests[1][1] == {"to": "Uowner", "messages": [{"type": "text", "text": "こんにちは"}]}


async def test_signed_webhook_answers_immediately_and_conversation_is_visible(tmp_path):
    settings = Settings(_env_file=None, yata_db=str(tmp_path / "yata.db"), yata_model="demo",
                        line_channel_secret=SECRET, line_channel_access_token=TOKEN,
                        line_allowed_user_ids="Uowner", yata_scheduler_enabled=False)
    app = create_app(settings)
    bridge = app.state.line_bridge
    requests, release = [], asyncio.Event()

    async def handler(request):
        await release.wait()
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200)

    bridge.client = LineClient(TOKEN, httpx.MockTransport(handler))
    webhook = create_webhook_app(bridge.connector.channel_secret, bridge.handle_events)
    body = json.dumps({"events": [text_event(text="こんにちは")]}).encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=webhook), base_url="http://test") as client:
        response = await client.post("/line/webhook", content=body, headers={"x-line-signature": sign(body)})
    assert response.status_code == 200 and not requests  # 返信より先に 200 を返している
    await asyncio.gather(*webhook.state.tasks)
    release.set()
    await drain(bridge)
    assert requests[0][0].endswith("reply") and requests[0][1]["replyToken"] == "reply-token"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        listed = (await client.get("/api/conversations")).json()["conversations"]
    assert [item["title"] for item in listed] == ["LINE"]


async def test_confirmation_ids_are_random(request):
    create = request.getfixturevalue("setup_bridge")
    tool = ExternalTool()
    responses = [LLMResponse(tool_calls=[ToolCall("call", "echo", {"text": "送信内容"})]),
                 LLMResponse(content="完了")]
    bridge, requests, _, sent = create(responses, tool=tool)
    await bridge.handle_events([text_event(text="送って")])
    await asyncio.wait_for(sent.wait(), 2)
    (request_id,) = bridge.pending
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    assert type(bridge.gate) is InMemoryConfirmationGate
    actions = requests[-1][1]["messages"][-1]["template"]["actions"]
    assert [action["label"] for action in actions] == ["許可する", "拒否する"]
    await bridge.handle_postback("Uowner", f"yata-confirm={request_id}&d=deny")
    await drain(bridge)
