"""Pure conversions between internal messages and vendor payloads.

These functions stay free of SDK clients so the provider contract can be
tested without network access.
"""

from __future__ import annotations

import json
from typing import Any

from tomoshibi.llm.types import LLMMessage, LLMResponse, ToolCall, ToolSpec, parse_arguments


def to_openai_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            payload.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content or "",
                }
            )
            continue
        if message.role == "assistant" and message.tool_calls:
            item: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in message.tool_calls
                ],
            }
            payload.append(item)
            continue
        payload.append({"role": message.role, "content": message.content or ""})
    return payload


def to_openai_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]


def parse_openai_message(message: Any, *, model: str | None = None) -> LLMResponse:
    calls: list[ToolCall] = []
    for call in getattr(message, "tool_calls", None) or []:
        function = call.function
        calls.append(
            ToolCall(
                id=call.id,
                name=function.name,
                arguments=parse_arguments(function.arguments),
            )
        )
    content = getattr(message, "content", None)
    if isinstance(content, str):
        content = content.strip() or None
    return LLMResponse(content=content, tool_calls=calls, model=model)


def to_anthropic_payload(
    messages: list[LLMMessage],
    tools: list[ToolSpec],
) -> tuple[str | None, list[dict[str, Any]], list[dict[str, Any]]]:
    system_parts = [message.content for message in messages if message.role == "system" and message.content]
    system = "\n\n".join(system_parts) or None
    converted: list[dict[str, Any]] = []

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content or "",
            }
            if converted and converted[-1]["role"] == "user" and isinstance(converted[-1]["content"], list):
                if converted[-1]["content"] and converted[-1]["content"][0].get("type") == "tool_result":
                    converted[-1]["content"].append(block)
                    continue
            converted.append({"role": "user", "content": [block]})
            continue
        if message.role == "assistant" and message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            converted.append({"role": "assistant", "content": blocks})
            continue
        role = "assistant" if message.role == "assistant" else "user"
        converted.append({"role": role, "content": message.content or ""})

    tool_payload = [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }
        for tool in tools
    ]
    return system, converted, tool_payload


def parse_anthropic_response(response: Any, *, model: str | None = None) -> LLMResponse:
    texts: list[str] = []
    calls: list[ToolCall] = []
    for block in getattr(response, "content", None) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text" and getattr(block, "text", None):
            texts.append(block.text)
        elif block_type == "tool_use":
            calls.append(
                ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=parse_arguments(getattr(block, "input", {}) or {}),
                )
            )
    content = "\n".join(texts).strip() or None
    return LLMResponse(content=content, tool_calls=calls, model=model)


def to_gemini_contents(messages: list[LLMMessage]) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts = [message.content for message in messages if message.role == "system" and message.content]
    system = "\n\n".join(system_parts) or None
    contents: list[dict[str, Any]] = []

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            part = {
                "function_response": {
                    "name": message.name or "tool",
                    "response": {"result": message.content or ""},
                }
            }
            if contents and contents[-1]["role"] == "user" and _is_function_response(contents[-1]):
                contents[-1]["parts"].append(part)
                continue
            contents.append({"role": "user", "parts": [part]})
            continue
        if message.role == "assistant":
            parts: list[dict[str, Any]] = []
            if message.content:
                parts.append({"text": message.content})
            for call in message.tool_calls or []:
                parts.append({"function_call": {"name": call.name, "args": call.arguments}})
            if not parts:
                parts.append({"text": ""})
            contents.append({"role": "model", "parts": parts})
            continue
        contents.append({"role": "user", "parts": [{"text": message.content or ""}]})
    return system, contents


def parse_gemini_response(response: Any, *, model: str | None = None) -> LLMResponse:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        feedback = getattr(response, "prompt_feedback", None)
        raise ValueError(f"Gemini から候補が返りませんでした: {feedback}")
    content = getattr(candidates[0], "content", None)
    parts = getattr(content, "parts", None) or []
    texts: list[str] = []
    calls: list[ToolCall] = []
    for index, part in enumerate(parts):
        if getattr(part, "thought", False):
            continue
        function_call = getattr(part, "function_call", None)
        name = getattr(function_call, "name", None) if function_call is not None else None
        if name:
            call_id = getattr(function_call, "id", None) or f"gemini_{index}_{name}"
            calls.append(
                ToolCall(
                    id=str(call_id),
                    name=name,
                    arguments=parse_arguments(getattr(function_call, "args", None) or {}),
                )
            )
            continue
        text = getattr(part, "text", None)
        if text:
            texts.append(text)
    joined = "\n".join(texts).strip() or None
    return LLMResponse(content=joined, tool_calls=calls, model=model)


def _is_function_response(content: dict[str, Any]) -> bool:
    parts = content.get("parts") or []
    return bool(parts) and "function_response" in parts[0]
