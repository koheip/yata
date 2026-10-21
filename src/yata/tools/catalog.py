"""The default tool set. Add a tool by registering it here."""

from __future__ import annotations

from yata.tools.browser import (
    BrowserClickTool,
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserSnapshotTool,
    BrowserTypeTool,
)
from yata.tools.fetch import FetchPageTool
from yata.tools.memory_tool import SaveMemoryTool
from yata.tools.registry import ToolRegistry
from yata.tools.search import WebSearchTool


def build_registry(
    *,
    search_fn=None,
    fetch_fn=None,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(WebSearchTool(search_fn=search_fn))
    registry.register(FetchPageTool(fetch_fn=fetch_fn))
    registry.register(BrowserNavigateTool())
    registry.register(BrowserSnapshotTool())
    registry.register(BrowserClickTool())
    registry.register(BrowserTypeTool())
    registry.register(BrowserScreenshotTool())
    registry.register(SaveMemoryTool())
    return registry
