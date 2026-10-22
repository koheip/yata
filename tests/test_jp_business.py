"""祝日・営業日・和暦と、インボイスの消費税の計算。"""

from __future__ import annotations

import json
from datetime import date

import pytest

from yata.jp_calendar import (
    CalendarRangeError,
    add_business_days,
    business_days_between,
    holidays,
    to_wareki,
)
from yata.tools.base import Risk
from yata.tools.jp_business import JpCalendarTool, JpInvoiceTaxTool


def test_holidays_2026():
    days = {d.isoformat(): name for d, name in holidays(2026).items()}
    assert days == {
        "2026-01-01": "元日", "2026-01-12": "成人の日", "2026-02-11": "建国記念の日", "2026-02-23": "天皇誕生日",
        "2026-03-20": "春分の日", "2026-04-29": "昭和の日", "2026-05-03": "憲法記念日", "2026-05-04": "みどりの日",
        "2026-05-05": "こどもの日", "2026-05-06": "振替休日", "2026-07-20": "海の日", "2026-08-11": "山の日",
        "2026-09-21": "敬老の日", "2026-09-22": "国民の休日", "2026-09-23": "秋分の日",
        "2026-10-12": "スポーツの日", "2026-11-03": "文化の日", "2026-11-23": "勤労感謝の日",
    }


def test_special_olympic_years_and_substitutes():
    h2021 = holidays(2021)
    assert h2021[date(2021, 7, 22)] == "海の日" and h2021[date(2021, 8, 9)] == "振替休日"
    assert holidays(2025)[date(2025, 5, 6)] == "振替休日"  # 5/4（日）の振替
    assert holidays(2024)[date(2024, 2, 12)] == "振替休日"  # 2/11（日）の振替
    with pytest.raises(CalendarRangeError):
        holidays(2019)


def test_business_days():
    # 2026-09-18（金）の 1 営業日あとは、連休あけの 9/24（木）
    assert add_business_days(date(2026, 9, 18), 1) == date(2026, 9, 24)
    assert add_business_days(date(2026, 9, 24), -1) == date(2026, 9, 18)
    # 年末年始は休み（12/28 月 の次は 1/4 月）
    assert add_business_days(date(2026, 12, 28), 1) == date(2027, 1, 4)
    assert add_business_days(date(2026, 12, 28), 1, year_end_closed=False) == date(2026, 12, 29)
    assert business_days_between(date(2026, 10, 1), date(2026, 10, 31)) == 21


def test_wareki():
    assert to_wareki(date(2026, 10, 22)) == "令和8年10月22日"
    assert to_wareki(date(2019, 5, 1)) == "令和元年5月1日"
    assert to_wareki(date(2019, 4, 30)) == "平成31年4月30日"


async def test_calendar_tool():
    tool = JpCalendarTool()
    assert tool.risk is Risk.READ and tool.required_connector is None
    day = json.loads((await tool.run({"action": "day", "date": "2026-11-23"}, None)).content)
    assert day == {"date": "2026-11-23", "曜日": "月", "和暦": "令和8年11月23日", "祝日": "勤労感謝の日", "営業日": False}
    later = json.loads((await tool.run({"action": "add_business_days", "date": "2026-10-22", "days": 5}, None)).content)
    assert later["date"] == "2026-10-29"
    bad = await tool.run({"action": "day", "date": "10/22"}, None)
    assert not bad.ok


async def test_invoice_tax_rounds_once_per_rate():
    tool = JpInvoiceTaxTool()
    result = json.loads((await tool.run({"items": [
        {"name": "お弁当", "price": 498, "quantity": 3, "rate": 8},
        {"name": "お茶", "price": 98, "quantity": 3, "rate": 8},
        {"name": "配送料", "price": 550, "quantity": 1, "rate": 10},
    ], "price_mode": "税抜", "registration_number": "T1234567890123"}, None)).content)
    rows = {row["税率"]: row for row in result["税率ごと"]}
    assert rows["8%（軽減税率）"] == {"税率": "8%（軽減税率）", "対象額（税抜）": 1788, "消費税": 143, "合計（税込）": 1931}
    assert rows["10%"]["消費税"] == 55
    assert result["請求金額（税込）"] == 1931 + 605
    assert "形は正しい" in result["登録番号"]


async def test_invoice_tax_inclusive_prices():
    result = json.loads((await JpInvoiceTaxTool().run({"items": [
        {"price": 1100, "quantity": 2, "rate": 10}], "price_mode": "税込"}, None)).content)
    assert result["税率ごと"][0]["消費税"] == 200 and result["請求金額（税込）"] == 2200
    bad = await JpInvoiceTaxTool().run({"items": [{"price": 10.5, "quantity": 1, "rate": 10}]}, None)
    assert not bad.ok
