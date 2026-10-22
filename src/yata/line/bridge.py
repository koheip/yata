"""許可された LINE ユーザーの会話を既存のエージェントに接続する。"""
import asyncio
import json
import logging
from urllib.parse import parse_qs

from yata.agent.loop import run_agent, seal_open_tool_calls
from yata.line.client import LineClient, LineError
from yata.llm.types import LLMMessage, ProviderError
from yata.prompts import build_system_prompt
from yata.tools.base import ToolContextFactory
from yata.tools.catalog import visible_registry
from yata.tools.policy import ToolPolicy

logger = logging.getLogger(__name__)
NOT_FOUND = "この確認は見つからないか、すでに処理済みです。"
FAILED = "エージェントの実行中に失敗しました。"


class LineBridge:
    def __init__(self, memory, router, registry, gate, connectors, settings, browser,
                 artifacts_dir, client: LineClient, confirm_timeout=600):
        self.memory = memory
        self.router = router
        self.registry = registry
        self.gate = gate
        self.connectors = connectors
        self.connector = connectors.get("line")
        self.settings = settings
        self.browser = browser
        self.artifacts_dir = artifacts_dir
        self.client = client
        self.confirm_timeout = confirm_timeout
        self.pending: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()
        self._path = settings.database_path().parent / "line_conversations.json"
        try:
            mapping = json.loads(self._path.read_text(encoding="utf-8"))
            self._conversations = {k: v for k, v in mapping.items() if isinstance(v, str)}
        except (OSError, ValueError, AttributeError):
            self._conversations = {}

    async def close(self):
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def handle_events(self, events):
        for event in events:
            source = event.get("source") or {}
            if source.get("type") != "user":
                continue
            user_id = source.get("userId")
            if not isinstance(user_id, str) or not user_id:
                continue
            if user_id not in self.connector.allowed_user_ids:
                logger.info("LINE: 許可されていないユーザーからのイベントを無視しました。自分の場合は LINE_ALLOWED_USER_IDS に %s を追加してください。", user_id)
                continue
            token = event.get("replyToken")
            if event.get("type") == "postback":
                await self.handle_postback(user_id, (event.get("postback") or {}).get("data", ""), token)
            elif event.get("type") == "message":
                message = event.get("message") or {}
                if message.get("type") == "text" and isinstance(message.get("text"), str):
                    task = asyncio.create_task(self.run_chat(user_id, message["text"], token))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)

    def _conversation(self, user_id):
        conversation_id = self._conversations.get(user_id)
        conversation = self.memory.get_conversation(conversation_id) if conversation_id else None
        if conversation is None:
            conversation = self.memory.create_conversation(self.settings.yata_model, "LINE")
            self._conversations[user_id] = conversation.id
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._conversations, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._path)
        return conversation

    def _safe(self, text):
        for secret in (self.settings.line_channel_secret, self.settings.line_channel_access_token):
            if secret:
                text = text.replace(secret, "（非表示）")
        return text

    async def run_chat(self, user_id, text, reply_token=None):
        async with self._locks.setdefault(user_id, asyncio.Lock()):
            messages = []
            base_len = 0
            conversation = None
            request_ids = set()

            def take_token():
                nonlocal reply_token
                token, reply_token = reply_token, None
                return token

            try:
                conversation = self._conversation(user_id)
                try:
                    provider, upstream = self.router.resolve(conversation.model_id)
                except ProviderError as exc:
                    await self.client.send_text(user_id, self._safe(str(exc)), take_token())
                    return
                self.memory.add_message(conversation.id, LLMMessage(role="user", content=text))
                messages = [LLMMessage(role="system", content=build_system_prompt(self.memory.list_facts()))]
                messages.extend(item.to_llm() for item in self.memory.list_messages(conversation.id))
                base_len = len(messages)
                ctx = ToolContextFactory(
                    memory=self.memory, browser=self.browser, artifacts_dir=self.artifacts_dir,
                    allow_private_urls=self.settings.yata_allow_private_urls, connectors=self.connectors,
                ).for_conversation(conversation.id)
                async for event in run_agent(
                    messages=messages, provider=provider, model=upstream,
                    registry=visible_registry(self.registry, self.connectors), policy=ToolPolicy(),
                    gate=self.gate, ctx=ctx, max_steps=self.settings.yata_max_steps,
                    confirm_timeout=self.confirm_timeout,
                ):
                    if event.type == "confirmation_required":
                        request_id = event.data["request_id"]
                        self.pending[request_id] = user_id
                        request_ids.add(request_id)
                        await self.client.send_messages(user_id, self.client.confirm_messages(
                            request_id, self._safe(event.data["summary"])), take_token())
                    elif event.type == "confirmation_resolved":
                        self.pending.pop(event.data["request_id"], None)
                    elif event.type == "answer":
                        await self.client.send_text(user_id, self._safe(event.data["content"]), take_token())
                    elif event.type == "error":
                        await self.client.send_text(user_id, FAILED, take_token())
            except Exception:
                logger.error("LINE: エージェントの実行中に失敗しました。")
                if messages:
                    messages.append(LLMMessage(role="assistant", content=FAILED))
                try:
                    await self.client.send_text(user_id, FAILED, take_token())
                except LineError:
                    logger.error("LINE: エラー通知を送信できませんでした。")
            finally:
                for request_id in request_ids:
                    if self.pending.pop(request_id, None) is not None:
                        self.gate.resolve(request_id, False)
                        await self.gate.wait(request_id, self.confirm_timeout)
                if messages and conversation is not None:
                    seal_open_tool_calls(messages)
                    for message in messages[base_len:]:
                        self.memory.add_message(conversation.id, message)

    async def handle_postback(self, user_id, data, reply_token=None):
        params = parse_qs(data) if isinstance(data, str) else {}
        ids, decisions = params.get("yata-confirm", []), params.get("d", [])
        request_id = ids[0] if len(ids) == 1 else None
        decision = decisions[0] if len(decisions) == 1 else None
        text = NOT_FOUND
        if (request_id in self.pending and self.pending[request_id] == user_id
                and decision in ("approve", "deny")):
            resolved = self.gate.resolve(request_id, decision == "approve")
            self.pending.pop(request_id, None)
            if resolved:
                text = "許可しました。" if decision == "approve" else "拒否しました。"
        await self.client.send_text(user_id, text, reply_token)

    async def push_to_owner(self, text) -> bool:
        owner = self.connector.owner_user_id
        if not owner:
            return False
        try:
            await self.client.send_text(owner, self._safe(text))
            return True
        except LineError:
            return False
