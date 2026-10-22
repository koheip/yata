"""日本の仕事でよく使う計算のツール（祝日・営業日・和暦、インボイスの消費税）。

どれもパソコンの中だけで計算する（ネットに出ない）。オフラインモードでも使える。
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, Decimal

from yata.jp_calendar import (
    CalendarRangeError,
    add_business_days,
    business_days_between,
    holiday_name,
    holidays,
    is_business_day,
    to_wareki,
)
from yata.tools.base import Risk, Tool, ToolContext, ToolResult

WEEKDAYS = "月火水木金土日"


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _describe(day: date) -> dict:
    return {"date": day.isoformat(), "曜日": WEEKDAYS[day.weekday()], "和暦": to_wareki(day),
            "祝日": holiday_name(day)}


class JpCalendarTool(Tool):
    name = "jp_calendar"
    description = (
        "日本の祝日・営業日・和暦を計算する（土日・祝日・年末年始 12/29〜1/3 を休みとして数える）。"
        "action: holidays（その年の祝日一覧）/ day（その日の曜日・祝日・和暦・営業日か）/"
        " add_business_days（date から days 営業日あと。負の数で前）/ count_business_days（date〜end の営業日数）。"
        "支払期限や納期を決めるときに使う。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["holidays", "day", "add_business_days", "count_business_days"]},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "end": {"type": "string", "description": "count_business_days の終わりの日 YYYY-MM-DD"},
            "days": {"type": "integer", "description": "add_business_days で進める営業日の数"},
            "year": {"type": "integer", "description": "holidays の年"},
            "year_end_closed": {"type": "boolean", "description": "12/29〜1/3 を休みにする。既定は true"},
        },
        "required": ["action"],
    }
    risk = Risk.READ

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        action = arguments.get("action")
        closed = arguments.get("year_end_closed", True) is not False
        try:
            if action == "holidays":
                year = arguments.get("year")
                if type(year) is not int:
                    start = _date(arguments.get("date"))
                    year = start.year if start else date.today().year
                data = [{"date": d.isoformat(), "曜日": WEEKDAYS[d.weekday()], "name": n} for d, n in holidays(year).items()]
                return ToolResult(ok=True, content=json.dumps(data, ensure_ascii=False))
            start = _date(arguments.get("date"))
            if start is None:
                return ToolResult(ok=False, content="date は YYYY-MM-DD の形にしてください。")
            if action == "day":
                data = {**_describe(start), "営業日": is_business_day(start, year_end_closed=closed)}
            elif action == "add_business_days":
                days = arguments.get("days")
                if type(days) is not int:
                    return ToolResult(ok=False, content="days は整数にしてください。")
                data = {"from": start.isoformat(), "days": days,
                        **_describe(add_business_days(start, days, year_end_closed=closed))}
            elif action == "count_business_days":
                end = _date(arguments.get("end"))
                if end is None:
                    return ToolResult(ok=False, content="end は YYYY-MM-DD の形にしてください。")
                data = {"from": start.isoformat(), "to": end.isoformat(),
                        "営業日数": business_days_between(start, end, year_end_closed=closed)}
            else:
                return ToolResult(ok=False, content="action が正しくありません。")
        except CalendarRangeError as exc:
            return ToolResult(ok=False, content=str(exc))
        return ToolResult(ok=True, content=json.dumps(data, ensure_ascii=False))


ROUNDING = {"切り捨て": ROUND_DOWN, "四捨五入": ROUND_HALF_UP, "切り上げ": ROUND_CEILING}
_REGISTRATION = re.compile(r"^T\d{13}$")


class JpInvoiceTaxTool(Tool):
    name = "jp_invoice_tax"
    description = (
        "インボイス（適格請求書）の消費税を計算する。税率ごと（10% と 8% の軽減税率）に合計してから、"
        "1つの請求書につき税率ごとに1回だけ端数を処理する（インボイス制度の決まり）。"
        "price_mode は 税抜 か 税込。登録番号（T＋13桁）を渡すと形を確かめる。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "price": {"type": "integer", "description": "単価（円）"},
                        "quantity": {"type": "number"},
                        "rate": {"type": "integer", "enum": [10, 8, 0], "description": "税率（%）。0 は非課税・対象外"},
                    },
                    "required": ["price", "quantity", "rate"],
                },
            },
            "price_mode": {"type": "string", "enum": ["税抜", "税込"]},
            "rounding": {"type": "string", "enum": list(ROUNDING), "description": "端数処理。既定は切り捨て"},
            "registration_number": {"type": ["string", "null"], "description": "適格請求書発行事業者の登録番号（任意）"},
        },
        "required": ["items"],
    }
    risk = Risk.READ

    async def run(self, arguments: dict, ctx: ToolContext) -> ToolResult:
        items = arguments.get("items")
        if not isinstance(items, list) or not items:
            return ToolResult(ok=False, content="品目を1つ以上入れてください。")
        inclusive = arguments.get("price_mode") == "税込"
        rounding = ROUNDING.get(arguments.get("rounding") or "切り捨て", ROUND_DOWN)
        totals: dict[int, Decimal] = {}
        for item in items:
            if not isinstance(item, dict) or type(item.get("price")) is not int or item.get("rate") not in (10, 8, 0):
                return ToolResult(ok=False, content="各品目に price（整数の円）と rate（10・8・0）を入れてください。")
            try:
                quantity = Decimal(str(item.get("quantity", 1)))
            except ArithmeticError:
                return ToolResult(ok=False, content="quantity は数にしてください。")
            totals[item["rate"]] = totals.get(item["rate"], Decimal(0)) + Decimal(item["price"]) * quantity
        rows = []
        grand_excl = grand_tax = Decimal(0)
        for rate in sorted(totals, reverse=True):
            amount = totals[rate].quantize(Decimal(1), rounding=rounding)
            if rate == 0:
                excl, tax = amount, Decimal(0)
            elif inclusive:
                tax = (amount * rate / (100 + rate)).quantize(Decimal(1), rounding=rounding)
                excl = amount - tax
            else:
                excl = amount
                tax = (amount * rate / 100).quantize(Decimal(1), rounding=rounding)
            grand_excl += excl
            grand_tax += tax
            label = "非課税・対象外" if rate == 0 else (f"{rate}%（軽減税率）" if rate == 8 else f"{rate}%")
            rows.append({"税率": label, "対象額（税抜）": int(excl), "消費税": int(tax), "合計（税込）": int(excl + tax)})
        result: dict = {"税率ごと": rows, "小計（税抜）": int(grand_excl), "消費税": int(grand_tax),
                        "請求金額（税込）": int(grand_excl + grand_tax)}
        number = arguments.get("registration_number")
        if number:
            text = str(number).strip().upper().replace("-", "").replace(" ", "")
            result["登録番号"] = (
                f"{text}（形は正しい。実在するかは国税庁の公表サイト https://www.invoice-kohyo.nta.go.jp/ で確かめる）"
                if _REGISTRATION.match(text) else f"{number}（形が違います。T のあとに数字 13 桁です）"
            )
        result["インボイスに必要な記載"] = (
            "発行者の名前と登録番号、取引の日付、取引の内容（軽減税率の品目はその旨）、"
            "税率ごとの合計額と適用税率、税率ごとの消費税額、受け取る人の名前"
        )
        return ToolResult(ok=True, content=json.dumps(result, ensure_ascii=False))
