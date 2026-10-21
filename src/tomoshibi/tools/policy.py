"""Decide which tool calls must wait for the user.

Desktop tools should use Risk.EXTERNAL. They will stop here without any
change to the agent loop.
"""

from __future__ import annotations

from tomoshibi.tools.base import Risk, Tool

CONFIRM_RISKS = {Risk.MUTATE, Risk.EXTERNAL}


class ToolPolicy:
    def needs_confirmation(self, tool: Tool, arguments: dict) -> bool:
        del arguments
        return tool.risk in CONFIRM_RISKS


def describe_action(tool: Tool, arguments: dict) -> str:
    if tool.name == "browser_click":
        return f"ブラウザで「{arguments.get('selector', '')}」をクリックします。"
    if tool.name == "browser_type":
        submit = "その後 Enter を送ります。" if arguments.get("submit") else "Enter は送りません。"
        text = arguments.get("text", "")
        selector = arguments.get("selector", "")
        return f"ブラウザの「{selector}」に「{text}」と入力します。{submit}"
    if tool.risk == Risk.EXTERNAL:
        return f"外部操作「{tool.name}」を実行します。引数: {arguments}"
    return f"「{tool.name}」を実行します。引数: {arguments}"
