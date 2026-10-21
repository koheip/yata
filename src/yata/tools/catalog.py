"""The default tool set. Add a tool by registering it here."""

from __future__ import annotations

from yata.connectors.base import ConnectorRegistry, ConnectorState
from yata.tools.browser import (
    BrowserClickTool,
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserSnapshotTool,
    BrowserTypeTool,
)
from yata.tools.calendar import (
    CalendarCreateEventTool,
    CalendarDeleteEventTool,
    CalendarFreeBusyTool,
    CalendarListEventsTool,
    CalendarUpdateEventTool,
)
from yata.tools.chatwork import (
    ChatworkCreateTaskTool,
    ChatworkGetMessagesTool,
    ChatworkListMyTasksTool,
    ChatworkListRoomsTool,
    ChatworkSendMessageTool,
)
from yata.tools.fetch import FetchPageTool
from yata.tools.freee import (
    FreeeCreateExpenseDealTool,
    FreeeGetTrialBalanceTool,
    FreeeListAccountItemsTool,
    FreeeListCompaniesTool,
    FreeeListDealsTool,
    FreeeListInvoicesTool,
)
from yata.tools.gmail import (
    GmailCreateDraftTool,
    GmailReadTool,
    GmailSearchTool,
    GmailSendEmailTool,
)
from yata.tools.memory_tool import SaveMemoryTool
from yata.tools.rakuten import RakutenItemRankingTool, RakutenSearchItemsTool
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
    registry.register(GmailSearchTool())
    registry.register(GmailReadTool())
    registry.register(GmailCreateDraftTool())
    registry.register(GmailSendEmailTool())
    registry.register(CalendarListEventsTool())
    registry.register(CalendarFreeBusyTool())
    registry.register(CalendarCreateEventTool())
    registry.register(CalendarUpdateEventTool())
    registry.register(CalendarDeleteEventTool())
    registry.register(ChatworkListRoomsTool())
    registry.register(ChatworkGetMessagesTool())
    registry.register(ChatworkListMyTasksTool())
    registry.register(ChatworkSendMessageTool())
    registry.register(ChatworkCreateTaskTool())
    registry.register(RakutenSearchItemsTool())
    registry.register(RakutenItemRankingTool())
    registry.register(FreeeListCompaniesTool())
    registry.register(FreeeListAccountItemsTool())
    registry.register(FreeeListDealsTool())
    registry.register(FreeeListInvoicesTool())
    registry.register(FreeeGetTrialBalanceTool())
    registry.register(FreeeCreateExpenseDealTool())
    return registry


def visible_registry(base: ToolRegistry, connectors: ConnectorRegistry | None) -> ToolRegistry:
    """Hide tools whose connector is not connected. The model never sees a
    tool call it cannot complete, so credentials that are missing or not yet
    authorized simply mean fewer tools, not an error.
    """
    visible = ToolRegistry()
    for tool in base.tools():
        required = tool.required_connector
        if required is not None:
            connector = connectors.get(required) if connectors is not None else None
            if connector is None or connector.status() is not ConnectorState.CONNECTED:
                continue
        visible.register(tool)
    return visible
