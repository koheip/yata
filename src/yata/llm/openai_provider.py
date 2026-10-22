"""OpenAI, and any server that speaks the OpenAI chat-completions API.

Ollama, LM Studio, and vLLM are the same adapter with a different base URL
and a placeholder API key. That is the OpenAI-compatible path in this MVP.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from types import SimpleNamespace

from yata.llm.convert import parse_openai_message, to_openai_messages, to_openai_tools
from yata.llm.errors import humanize_provider_error
from yata.llm.types import LLMMessage, LLMResponse, ProviderError, ToolSpec

# パソコンの中の AI では、いま読み込まれているモデルを使う（モデル名を聞かない）。
AUTO_MODEL = "auto"
_THINK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL)
TextSink = Callable[[str], None]


def _wants_no_think(model: str) -> bool:
    """qwen3 は既定で長く「考えて」から答えるので、パソコンの中ではそれを止める（/no_think）。"""
    name = model.lower()
    return name.startswith("qwen3") and "instruct" not in name and "2507" not in name


class _ThinkFilter:
    """流れてくる文字から <think>…</think> を取りのぞく。"""

    def __init__(self, sink: TextSink):
        self._sink = sink
        self._buffer = ""
        self._inside = False

    def feed(self, text: str) -> None:
        self._buffer += text
        while self._buffer:
            if self._inside:
                end = self._buffer.find("</think>")
                if end < 0:
                    self._buffer = self._buffer[-8:]
                    return
                self._buffer = self._buffer[end + len("</think>"):]
                self._inside = False
                continue
            start = self._buffer.find("<think>")
            if start < 0:
                # タグの途中で切れているかもしれない分だけ残す
                keep = next((i for i in range(1, 8) if "<think>".startswith(self._buffer[-i:])), 0)
                out = self._buffer[: len(self._buffer) - keep] if keep else self._buffer
                if out:
                    self._sink(out)
                self._buffer = self._buffer[len(out):]
                return
            if start:
                self._sink(self._buffer[:start])
            self._buffer = self._buffer[start + len("<think>"):]
            self._inside = True


class OpenAICompatibleProvider:
    # run_agent は、これが True のプロバイダから文字を少しずつ受け取って画面に流す。
    supports_streaming = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        provider_name: str,
        local: bool = False,
    ):
        self.provider_name = provider_name
        self._api_key = api_key
        self._base_url = base_url
        self._client = None
        # パソコンの中の AI では、指定のモデルがなければ入っているモデルを使い、
        # ツールに対応していないモデルなら、ツールなしで答えてもらう。
        self._local = local
        self._fallback_model: str | None = None
        self._no_tools: set[str] = set()

    async def _loaded_model(self) -> str:
        try:
            model = await _first_model(self._sdk())
        except Exception as exc:
            raise ProviderError(
                humanize_provider_error(self.provider_name, exc), provider=self.provider_name,
            ) from exc
        if model is None:
            raise ProviderError(
                f"{self.provider_name} にモデルが読み込まれていません。先にモデルを読み込んでください。",
                provider=self.provider_name,
            )
        return model

    async def _create(self, messages: list[LLMMessage], tools: list[ToolSpec], model: str,
                      on_text: TextSink | None = None):
        """1回ぶんの返事。on_text があれば、文字ができた端から渡す（ストリーミング）。"""
        payload = to_openai_messages(messages)
        if self._local and _wants_no_think(model):
            payload = _with_no_think(payload)
        request: dict = {"model": model, "messages": payload, "temperature": 0.4}
        if tools and model not in self._no_tools:
            request["tools"] = to_openai_tools(tools)
            request["tool_choice"] = "auto"
        if on_text is None:
            response = await self._sdk().chat.completions.create(**request)
            return response.choices[0].message if response.choices else None
        return await self._stream(request, on_text)

    async def _stream(self, request: dict, on_text: TextSink):
        stream = await self._sdk().chat.completions.create(**request, stream=True)
        text: list[str] = []
        calls: dict[int, dict] = {}
        sink = _ThinkFilter(on_text)
        got_any = False
        async for chunk in stream:
            for choice in getattr(chunk, "choices", None) or []:
                got_any = True
                delta = choice.delta
                piece = getattr(delta, "content", None)
                if piece:
                    text.append(piece)
                    sink.feed(piece)
                for call in getattr(delta, "tool_calls", None) or []:
                    slot = calls.setdefault(call.index if call.index is not None else len(calls),
                                            {"id": None, "name": "", "arguments": ""})
                    if call.id:
                        slot["id"] = call.id
                    function = getattr(call, "function", None)
                    if function is not None:
                        slot["name"] += function.name or ""
                        slot["arguments"] += function.arguments or ""
        if not got_any:
            return None
        tool_calls = [
            SimpleNamespace(id=slot["id"] or f"call_{index}",
                            function=SimpleNamespace(name=slot["name"], arguments=slot["arguments"] or "{}"))
            for index, slot in sorted(calls.items()) if slot["name"]
        ]
        return SimpleNamespace(content="".join(text), tool_calls=tool_calls or None)

    async def _local_retry(self, exc: Exception, model: str) -> str | None:
        """パソコンの中の AI で失敗したとき、やり直せるならそのモデル名を返す。"""
        text = str(exc).lower()
        if "support tools" in text or "tool" in text and "not support" in text:
            self._no_tools.add(model)
            return model
        if "404" in text or "not found" in text:
            loaded = await _first_model(self._sdk())
            if loaded and loaded != model:
                self._fallback_model = loaded
                return loaded
        return None

    def _sdk(self):
        if self._client is None:
            from openai import AsyncOpenAI

            kwargs: dict = {"api_key": self._api_key, "timeout": 90}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        *,
        model: str,
        on_text: TextSink | None = None,
    ) -> LLMResponse:
        if model == AUTO_MODEL:
            model = await self._loaded_model()
        if self._fallback_model:
            model = self._fallback_model
        # パソコンの中の AI は「モデルがない」「ツール非対応」の2つまでやり直す。
        for attempt in range(3):
            try:
                message = await self._create(messages, tools, model, on_text)
                break
            except Exception as exc:
                retry = await self._local_retry(exc, model) if self._local and attempt < 2 else None
                if retry is None:
                    raise ProviderError(
                        humanize_provider_error(self.provider_name, exc), provider=self.provider_name,
                    ) from exc
                model = retry
        if message is None:
            raise ProviderError(f"{self.provider_name} から候補が返りませんでした。", provider=self.provider_name)
        response = parse_openai_message(message, model=model)
        if response.content and "<think>" in response.content:
            response.content = _THINK.sub("", response.content).strip() or None
        return response


async def _first_model(sdk) -> str | None:
    page = await sdk.models.list()
    for item in getattr(page, "data", None) or []:
        model_id = getattr(item, "id", None)
        if isinstance(model_id, str) and model_id and "embed" not in model_id.lower():
            return model_id
    return None


def ollama_openai_base(url: str) -> str:
    root = url.rstrip("/")
    if root.endswith("/v1"):
        return root
    return root + "/v1"


def ollama_root(url: str) -> str:
    root = url.rstrip("/")
    if root.endswith("/v1"):
        return root[: -len("/v1")]
    return root


def _with_no_think(payload: list[dict]) -> list[dict]:
    copied = [dict(item) for item in payload]
    for item in copied:
        if item.get("role") == "system" and isinstance(item.get("content"), str):
            item["content"] = item["content"] + "\n/no_think"
            return copied
    return [{"role": "system", "content": "/no_think"}, *copied]
