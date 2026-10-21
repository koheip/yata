"""Provider abstraction: message conversion, response parsing, and model routing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yata.config import Settings
from yata.llm.anthropic_provider import AnthropicProvider
from yata.llm.convert import (
    parse_anthropic_response,
    parse_gemini_response,
    parse_openai_message,
    to_anthropic_payload,
    to_gemini_contents,
    to_openai_messages,
    to_openai_tools,
)
from yata.llm.demo import DemoProvider
from yata.llm.gemini_provider import to_gemini_schema
from yata.llm.openai_provider import OpenAICompatibleProvider, ollama_openai_base, ollama_root
from yata.llm.router import ModelRouter
from yata.llm.types import LLMMessage, ProviderError, ToolCall, ToolSpec


def _spec() -> ToolSpec:
    return ToolSpec(
        name="web_search",
        description="search",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )


def test_openai_round_trip_shape() -> None:
    messages = [
        LLMMessage(role="system", content="be brief"),
        LLMMessage(role="user", content="天気は？"),
        LLMMessage(
            role="assistant",
            content="調べます",
            tool_calls=[ToolCall(id="call_1", name="web_search", arguments={"query": "天気"})],
        ),
        LLMMessage(role="tool", content="晴れ", tool_call_id="call_1", name="web_search"),
    ]
    payload = to_openai_messages(messages)
    assert payload[0]["role"] == "system"
    assert payload[2]["tool_calls"][0]["function"]["name"] == "web_search"
    assert '"query"' in payload[2]["tool_calls"][0]["function"]["arguments"]
    assert payload[3]["role"] == "tool"
    assert payload[3]["tool_call_id"] == "call_1"
    tools = to_openai_tools([_spec()])
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["parameters"]["required"] == ["query"]


def test_parse_openai_tool_call_and_broken_json() -> None:
    message = SimpleNamespace(
        content="  ",
        tool_calls=[
            SimpleNamespace(
                id="call_9",
                function=SimpleNamespace(name="web_search", arguments='{"query": "灯"}'),
            ),
            SimpleNamespace(
                id="call_10",
                function=SimpleNamespace(name="web_search", arguments="{not json"),
            ),
        ],
    )
    parsed = parse_openai_message(message, model="gpt-4o-mini")
    assert parsed.content is None
    assert parsed.tool_calls[0].arguments == {"query": "灯"}
    assert parsed.tool_calls[1].arguments == {"_raw": "{not json"}
    assert parsed.model == "gpt-4o-mini"


def test_anthropic_groups_tool_results_and_splits_system() -> None:
    messages = [
        LLMMessage(role="system", content="sys"),
        LLMMessage(role="user", content="質問"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(id="a", name="web_search", arguments={"query": "one"}),
                ToolCall(id="b", name="fetch_page", arguments={"url": "https://example.com"}),
            ],
        ),
        LLMMessage(role="tool", content="r1", tool_call_id="a", name="web_search"),
        LLMMessage(role="tool", content="r2", tool_call_id="b", name="fetch_page"),
    ]
    system, payload, tools = to_anthropic_payload(messages, [_spec()])
    assert system == "sys"
    assert payload[1]["role"] == "assistant"
    assert payload[1]["content"][0]["type"] == "tool_use"
    assert payload[2]["role"] == "user"
    assert [block["tool_use_id"] for block in payload[2]["content"]] == ["a", "b"]
    assert tools[0]["input_schema"]["type"] == "object"


def test_parse_anthropic_blocks() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="結論"),
            SimpleNamespace(type="tool_use", id="toolu_1", name="web_search", input={"query": "x"}),
        ]
    )
    parsed = parse_anthropic_response(response, model="claude")
    assert parsed.content == "結論"
    assert parsed.tool_calls[0].id == "toolu_1"
    assert parsed.tool_calls[0].arguments == {"query": "x"}


def test_gemini_contents_skip_system_and_ignore_thoughts() -> None:
    messages = [
        LLMMessage(role="system", content="sys"),
        LLMMessage(role="user", content="こんにちは"),
        LLMMessage(
            role="assistant",
            content="検索します",
            tool_calls=[ToolCall(id="g1", name="web_search", arguments={"query": "灯"})],
        ),
        LLMMessage(role="tool", content="結果", tool_call_id="g1", name="web_search"),
    ]
    system, contents = to_gemini_contents(messages)
    assert system == "sys"
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][1]["function_call"]["name"] == "web_search"
    assert contents[2]["parts"][0]["function_response"]["name"] == "web_search"

    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(thought=True, text="hidden", function_call=None),
                        SimpleNamespace(
                            thought=False,
                            text=None,
                            function_call=SimpleNamespace(name="web_search", args={"query": "灯"}, id=None),
                        ),
                    ]
                )
            )
        ]
    )
    parsed = parse_gemini_response(response, model="gemini-2.5-flash")
    assert parsed.content is None
    assert parsed.tool_calls[0].name == "web_search"
    assert parsed.tool_calls[0].arguments == {"query": "灯"}


def test_gemini_schema_uses_uppercase_types() -> None:
    schema = to_gemini_schema(
        {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    )
    assert schema["type"] == "OBJECT"
    assert schema["properties"]["query"]["type"] == "STRING"


def test_ollama_base_url_normalization() -> None:
    assert ollama_openai_base("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1"
    assert ollama_openai_base("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    assert ollama_root("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434"


def test_router_hides_models_without_keys_and_resolves_ollama() -> None:
    settings = Settings(
        gemini_api_key=None,
        openai_api_key="sk-test",
        anthropic_api_key="",
        yata_model="gemini",
    )
    router = ModelRouter(settings)
    by_id = {item.id: item for item in router.catalog()}
    assert by_id["gemini"].ready is False
    assert by_id["openai"].ready is True
    assert by_id["anthropic"].ready is False
    assert by_id["demo"].ready is True
    assert by_id["ollama"].ready is True

    provider, upstream = router.resolve("ollama")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.provider_name == "Ollama"
    assert upstream == settings.yata_ollama_model

    demo, _ = router.resolve("demo")
    assert isinstance(demo, DemoProvider)
    with pytest.raises(ProviderError):
        router.resolve("gemini")
    with pytest.raises(ProviderError):
        router.resolve("nope")


def test_router_resolves_official_sdks() -> None:
    settings = Settings(
        gemini_api_key="g-key",
        openai_api_key="o-key",
        anthropic_api_key="a-key",
    )
    router = ModelRouter(settings)
    gemini, gemini_model = router.resolve("gemini")
    openai, openai_model = router.resolve("openai")
    anthropic, anthropic_model = router.resolve("anthropic")
    assert gemini.__class__.__name__ == "GeminiProvider"
    assert isinstance(openai, OpenAICompatibleProvider)
    assert openai._base_url is None
    assert isinstance(anthropic, AnthropicProvider)
    assert gemini_model == settings.yata_gemini_model
    assert openai_model == settings.yata_openai_model
    assert anthropic_model == settings.yata_anthropic_model


@pytest.mark.asyncio
async def test_demo_provider_calls_search_then_summarizes() -> None:
    provider = DemoProvider()
    tools = [_spec(), ToolSpec(name="save_memory", description="m", parameters={})]
    first = await provider.complete(
        [LLMMessage(role="user", content="今日のAIニュースを調べて")],
        tools,
        model="demo",
    )
    assert first.tool_calls[0].name == "web_search"
    second = await provider.complete(
        [
            LLMMessage(role="user", content="今日のAIニュースを調べて"),
            LLMMessage(role="assistant", tool_calls=first.tool_calls),
            LLMMessage(role="tool", content="1. 見出し", tool_call_id=first.tool_calls[0].id, name="web_search"),
        ],
        tools,
        model="demo",
    )
    assert second.tool_calls == []
    assert "見出し" in (second.content or "")
    assert "デモモデル" in (second.content or "")
