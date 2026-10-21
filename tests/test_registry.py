"""Tool registry, argument checks, and the confirmation policy."""

from __future__ import annotations

import pytest

from tests.fakes import MutatingTool, RecordingTool
from tomoshibi.llm.convert import to_openai_tools
from tomoshibi.tools.base import Risk, validate_arguments
from tomoshibi.tools.catalog import build_registry
from tomoshibi.tools.policy import ToolPolicy, describe_action
from tomoshibi.tools.registry import DuplicateToolError, ToolRegistry, UnknownToolError


def test_register_get_and_schema_export() -> None:
    registry = ToolRegistry()
    tool = RecordingTool()
    registry.register(tool)
    assert registry.get("echo") is tool
    assert registry.names() == ["echo"]
    specs = registry.specs()
    exported = to_openai_tools(specs)
    assert exported[0]["function"]["name"] == "echo"
    assert "text" in exported[0]["function"]["parameters"]["properties"]


def test_duplicate_and_unknown_tool() -> None:
    registry = ToolRegistry()
    registry.register(RecordingTool())
    with pytest.raises(DuplicateToolError):
        registry.register(RecordingTool())
    with pytest.raises(UnknownToolError) as caught:
        registry.get("missing")
    assert caught.value.name == "missing"


def test_default_catalog_has_the_mvp_tools() -> None:
    registry = build_registry()
    assert registry.names() == [
        "web_search",
        "fetch_page",
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_screenshot",
        "save_memory",
    ]
    assert registry.get("browser_click").risk == Risk.MUTATE
    assert registry.get("browser_type").risk == Risk.MUTATE
    assert registry.get("web_search").risk == Risk.READ
    assert registry.get("save_memory").risk == Risk.WRITE


def test_policy_confirms_mutate_and_external_only() -> None:
    policy = ToolPolicy()
    echo = RecordingTool()
    poke = MutatingTool()
    assert policy.needs_confirmation(echo, {"text": "hi"}) is False
    assert policy.needs_confirmation(poke, {"target": "button"}) is True
    summary = describe_action(poke, {"target": "button"})
    assert "poke" in summary


def test_validate_arguments_reports_missing_and_coerces_ints() -> None:
    tool = RecordingTool()
    assert validate_arguments(tool, {}) == "必須パラメータがありません: text"
    assert validate_arguments(tool, {"text": "ok"}) is None
    assert validate_arguments(tool, {"_raw": "nope"}) == "引数を解釈できませんでした。"

    search = build_registry().get("web_search")
    arguments = {"query": "灯", "max_results": 5.0}
    assert validate_arguments(search, arguments) is None
    assert arguments["max_results"] == 5
