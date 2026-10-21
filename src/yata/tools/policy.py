"""Decide which tool calls must wait for the user.

Desktop tools should use Risk.EXTERNAL. They will stop here without any
change to the agent loop.
"""

from __future__ import annotations

from yata.tools.base import Risk, Tool

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
    if tool.name == "gmail_send_email":
        return (
            "メールを送信します。\n"
            f"宛先: {arguments.get('to', '')}\n"
            f"件名: {arguments.get('subject', '')}\n"
            f"本文:\n{arguments.get('body', '')}"
        )
    if tool.name == "chatwork_send_message":
        return (
            "Chatwork にメッセージを送信します。\n"
            f"ルーム ID: {arguments.get('room_id', '')}\n"
            f"本文:\n{arguments.get('body', '')}"
        )
    if tool.name == "chatwork_create_task":
        return (
            "Chatwork にタスクを作成します。\n"
            f"ルーム ID: {arguments.get('room_id', '')}\n"
            f"担当者 ID: {arguments.get('to_ids', [])}\n"
            f"期限（Unix 秒）: {arguments.get('limit') if arguments.get('limit') is not None else '未設定'}\n"
            f"本文:\n{arguments.get('body', '')}"
        )
    if tool.name == "calendar_create_event":
        return (
            "カレンダーに予定を作成します。\n"
            f"件名: {arguments.get('summary', '')}\n"
            f"開始: {arguments.get('start', '')}\n"
            f"終了: {arguments.get('end', '')}"
        )
    if tool.name == "calendar_update_event":
        return f"カレンダーの予定（ID: {arguments.get('event_id', '')}）を更新します。引数: {arguments}"
    if tool.name == "calendar_delete_event":
        return f"カレンダーの予定（ID: {arguments.get('event_id', '')}）を削除します。"
    if tool.risk == Risk.EXTERNAL:
        return f"外部操作「{tool.name}」を実行します。引数: {arguments}"
    return f"「{tool.name}」を実行します。引数: {arguments}"
