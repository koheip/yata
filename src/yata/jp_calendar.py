"""日本の祝日・営業日・和暦の計算（ネットにつながずに計算する）。

祝日は「国民の祝日に関する法律」の 2020 年以降の決まりで計算する（2020〜2099 年）。
春分・秋分の日は毎年2月に官報で決まるので、ここでは天文計算の近似式を使う。
"""

from __future__ import annotations

from datetime import date, timedelta

MIN_YEAR, MAX_YEAR = 2020, 2099


class CalendarRangeError(ValueError):
    pass


def _nth_monday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (0 - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _equinox(year: int, base: float) -> int:
    return int(base + 0.242194 * (year - 1980) - int((year - 1980) / 4))


def holidays(year: int) -> dict[date, str]:
    """その年の祝日（振替休日・国民の休日を含む）。"""
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise CalendarRangeError(f"祝日は {MIN_YEAR}〜{MAX_YEAR} 年のものだけ計算できます。")
    days: dict[date, str] = {
        date(year, 1, 1): "元日",
        _nth_monday(year, 1, 2): "成人の日",
        date(year, 2, 11): "建国記念の日",
        date(year, 2, 23): "天皇誕生日",
        date(year, 3, _equinox(year, 20.8431)): "春分の日",
        date(year, 4, 29): "昭和の日",
        date(year, 5, 3): "憲法記念日",
        date(year, 5, 4): "みどりの日",
        date(year, 5, 5): "こどもの日",
        _nth_monday(year, 9, 3): "敬老の日",
        date(year, 9, _equinox(year, 23.2488)): "秋分の日",
        date(year, 11, 3): "文化の日",
        date(year, 11, 23): "勤労感謝の日",
    }
    # 東京オリンピック・パラリンピックの年だけ、海の日・スポーツの日・山の日が動いた。
    special = {
        2020: (date(2020, 7, 23), date(2020, 7, 24), date(2020, 8, 10)),
        2021: (date(2021, 7, 22), date(2021, 7, 23), date(2021, 8, 8)),
    }
    if year in special:
        umi, sports, yama = special[year]
    else:
        umi, sports, yama = _nth_monday(year, 7, 3), _nth_monday(year, 10, 2), date(year, 8, 11)
    days[umi] = "海の日"
    days[sports] = "スポーツの日"
    days[yama] = "山の日"

    # 国民の休日：前日と翌日が祝日のふつうの日。
    for day in sorted(days):
        middle = day + timedelta(days=1)
        if middle not in days and middle + timedelta(days=1) in days and middle.weekday() != 6:
            days[middle] = "国民の休日"
    # 振替休日：祝日が日曜なら、そのあとの最初の祝日でない日。
    for day in sorted(days):
        if day.weekday() == 6 and days[day] != "振替休日":
            substitute = day + timedelta(days=1)
            while substitute in days:
                substitute += timedelta(days=1)
            days[substitute] = "振替休日"
    return dict(sorted(days.items()))


def holiday_name(day: date) -> str | None:
    return holidays(day.year).get(day)


def is_business_day(day: date, *, year_end_closed: bool = True) -> bool:
    """土日・祝日（と、指定があれば 12/29〜1/3 の年末年始）を除いた日。"""
    if day.weekday() >= 5 or holiday_name(day):
        return False
    if year_end_closed and ((day.month == 12 and day.day >= 29) or (day.month == 1 and day.day <= 3)):
        return False
    return True


def add_business_days(start: date, count: int, *, year_end_closed: bool = True) -> date:
    """start から count 営業日あと（負なら前）の日。start 自身は数えない。"""
    if abs(count) > 1000:
        raise CalendarRangeError("営業日は 1000 日までにしてください。")
    step = 1 if count >= 0 else -1
    day, left = start, abs(count)
    while left:
        day += timedelta(days=step)
        if is_business_day(day, year_end_closed=year_end_closed):
            left -= 1
    return day


def business_days_between(start: date, end: date, *, year_end_closed: bool = True) -> int:
    """start から end まで（両端を含む）の営業日の数。"""
    if start > end:
        start, end = end, start
    if (end - start).days > 3660:
        raise CalendarRangeError("期間は 10 年までにしてください。")
    count, day = 0, start
    while day <= end:
        count += is_business_day(day, year_end_closed=year_end_closed)
        day += timedelta(days=1)
    return count


ERAS = (
    (date(2019, 5, 1), "令和"),
    (date(1989, 1, 8), "平成"),
    (date(1926, 12, 25), "昭和"),
    (date(1912, 7, 30), "大正"),
    (date(1868, 10, 23), "明治"),
)


def to_wareki(day: date) -> str:
    """2026-10-22 → 令和8年10月22日。"""
    for start, name in ERAS:
        if day >= start:
            year = day.year - start.year + 1
            return f"{name}{'元' if year == 1 else year}年{day.month}月{day.day}日"
    raise CalendarRangeError("明治より前の日付は和暦にできません。")
