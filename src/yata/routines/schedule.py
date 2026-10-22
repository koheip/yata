"""Cron and interval schedules, in Asia/Tokyo unless a routine says otherwise.

Stored cron expressions use standard crontab numbering: day-of-week 0 and 7 are
Sunday, 1 is Monday. APScheduler 3.x numbers Monday as 0, so the trigger is
converted at calculation time. The value saved in SQLite stays standard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger

from yata.memory.store import clip_title

PRESETS: dict[str, tuple[str, str, str]] = {
    "morning": ("cron", "0 8 * * *", "毎朝 8:00"),
    "hourly": ("cron", "0 * * * *", "毎時 0分"),
    "monday": ("cron", "0 9 * * 1", "毎週月曜 9:00"),
    "weekday": ("cron", "30 8 * * 1-5", "平日 8:30"),
    "monthly25": ("cron", "0 9 25 * *", "毎月25日 9:00"),
}

_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_MORNING = re.compile(r"毎朝\s*(\d{1,2})(?:\s*時(?:\s*(\d{1,2})\s*分)?|:(\d{2}))\s*に(.+)")
_HOURLY = re.compile(r"(?:毎時|1時間ごと)\s*(?:に)?(.+)")
_MONDAY = re.compile(r"毎週\s*月曜(?:日)?\s*(\d{1,2})(?:\s*時(?:\s*(\d{1,2})\s*分)?|:(\d{2}))\s*に(.+)")


class ScheduleError(ValueError):
    """A schedule the user typed cannot be run."""


@dataclass(frozen=True)
class RoutineDraft:
    name: str
    prompt: str
    schedule_kind: str
    schedule: str
    timezone: str


def as_utc_iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).replace(microsecond=0).isoformat(timespec="seconds")


def parse_utc_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ScheduleError(f"タイムゾーンを解釈できません: {name}") from exc


def schedule_label(kind: str, expression: str, zone: str) -> str:
    if kind == "interval":
        seconds = int(expression)
        if seconds % 86400 == 0:
            text = f"{seconds // 86400}日ごと"
        elif seconds % 3600 == 0:
            text = f"{seconds // 3600}時間ごと"
        elif seconds % 60 == 0:
            text = f"{seconds // 60}分ごと"
        else:
            text = f"{seconds}秒ごと"
        return f"{text}（{zone}）"
    parts = expression.split()
    if len(parts) == 5 and parts[2] == "*" and parts[3] == "*":
        minute, hour, dow = parts[0], parts[1], parts[4]
        if minute == "0" and hour == "*" and dow == "*":
            return f"毎時 0分（{zone}）"
        if minute.isdigit() and hour.isdigit() and dow == "*":
            clock = f"{int(hour):02d}:{int(minute):02d}"
            if int(hour) == 8 and int(minute) == 0:
                return f"毎朝 8:00（{zone}）"
            return f"毎日 {clock}（{zone}）"
        if minute.isdigit() and hour.isdigit() and dow == "1":
            return f"毎週月曜 {int(hour):02d}:{int(minute):02d}（{zone}）"
    return f"{expression}（{zone}）"


def preset_list() -> list[dict[str, str]]:
    return [
        {"id": key, "label": label, "schedule": expression, "schedule_kind": kind}
        for key, (kind, expression, label) in PRESETS.items()
    ]


def resolve_schedule(
    *,
    preset: str | None,
    schedule: str | None,
    schedule_kind: str | None,
    zone: str,
    minimum_interval: int = 60,
) -> tuple[str, str]:
    """Return (kind, expression) or raise ScheduleError."""
    if preset:
        try:
            kind, expression, _label = PRESETS[preset]
        except KeyError as exc:
            raise ScheduleError("その定型スケジュールはありません。") from exc
        return kind, expression
    if not schedule or not schedule.strip():
        raise ScheduleError("スケジュールを指定してください。")
    expression = " ".join(schedule.strip().split())
    kind = schedule_kind or ("interval" if expression.isdigit() else "cron")
    if kind == "interval":
        if not expression.isdigit():
            raise ScheduleError("間隔は秒数で指定してください。")
        seconds = int(expression)
        if seconds < minimum_interval:
            raise ScheduleError(f"間隔は {minimum_interval} 秒以上にしてください。")
        return "interval", str(seconds)
    if kind != "cron":
        raise ScheduleError("スケジュールの種類が不正です。")
    # Validate by calculating one fire time. The result is discarded.
    next_run("cron", expression, zone, datetime.now(UTC))
    return "cron", expression


def next_run(kind: str, expression: str, zone: str, after: datetime) -> datetime:
    """The first fire time strictly after `after`."""
    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    if kind == "interval":
        try:
            seconds = int(expression)
        except ValueError as exc:
            raise ScheduleError("間隔は秒数で指定してください。") from exc
        if seconds < 1:
            raise ScheduleError("間隔は 1 秒以上にしてください。")
        return after + timedelta(seconds=seconds)
    if kind != "cron":
        raise ScheduleError("スケジュールの種類が不正です。")
    parts = expression.split()
    if len(parts) != 5:
        raise ScheduleError("cron は5つの欄です。例: 0 8 * * *")
    try:
        day = _standard_dow_to_apscheduler(parts[4])
    except ScheduleError:
        raise
    except ValueError as exc:
        raise ScheduleError("cron の曜日を解釈できませんでした。") from exc
    try:
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=day,
            timezone=timezone(zone),
        )
    except (ValueError, ScheduleError) as exc:
        raise ScheduleError("cron の形式を確認してください。例: 0 8 * * *") from exc
    nxt = trigger.get_next_fire_time(None, after)
    if nxt is not None and nxt <= after:
        nxt = trigger.get_next_fire_time(nxt, after + timedelta(seconds=1))
    if nxt is None:
        raise ScheduleError("次の実行時刻を計算できませんでした。")
    return nxt


def parse_routine_utterance(text: str, *, zone: str = "Asia/Tokyo") -> RoutineDraft | None:
    """Turn 「毎朝8時にニュースを要約して」 into a routine, when the shape matches."""
    raw = " ".join(text.strip().translate(_DIGITS).replace("\u3000", " ").split())
    raw = re.sub(r"^ルーティン[:：]\s*", "", raw)
    morning = _MORNING.fullmatch(raw)
    if morning:
        hour = int(morning.group(1))
        minute = int(morning.group(2) or morning.group(3) or 0)
        body = morning.group(4).strip()
        return _draft(body, minute, hour, "*", zone)
    monday = _MONDAY.fullmatch(raw)
    if monday:
        hour = int(monday.group(1))
        minute = int(monday.group(2) or monday.group(3) or 0)
        body = monday.group(4).strip()
        return _draft(body, minute, hour, "1", zone)
    hourly = _HOURLY.fullmatch(raw)
    if hourly:
        body = hourly.group(1).strip()
        if not body:
            return None
        return RoutineDraft(
            name=clip_title(body),
            prompt=body,
            schedule_kind="cron",
            schedule="0 * * * *",
            timezone=zone,
        )
    return None


def _draft(body: str, minute: int, hour: int, dow: str, zone: str) -> RoutineDraft | None:
    if not body:
        return None
    if hour > 23 or minute > 59:
        raise ScheduleError("時刻は 0:00 から 23:59 までです。")
    return RoutineDraft(
        name=clip_title(body),
        prompt=body,
        schedule_kind="cron",
        schedule=f"{minute} {hour} * * {dow}",
        timezone=zone,
    )


def _standard_dow_to_apscheduler(field: str) -> str:
    """Convert crontab day-of-week (0/7 = Sunday) to APScheduler (0 = Monday)."""
    if field == "*" or any(character.isalpha() for character in field):
        return field

    def convert_number(token: str) -> str:
        if token == "7":
            token = "0"
        value = int(token)
        if value < 0 or value > 6:
            raise ScheduleError("曜日は 0 から 7 です。0 と 7 は日曜、1 は月曜です。")
        return str((value - 1) % 7)

    def convert_token(token: str) -> str:
        step = ""
        base = token
        if "/" in token:
            base, step_value = token.split("/", 1)
            step = "/" + step_value
        if base in {"", "*"}:
            return token
        if "-" in base:
            start, end = base.split("-", 1)
            start_n = convert_number(start)
            end_n = convert_number(end)
            if int(start_n) > int(end_n):
                raise ScheduleError("曜日の範囲が週をまたぐ場合は mon-fri のように書いてください。")
            return f"{start_n}-{end_n}{step}"
        return convert_number(base) + step

    return ",".join(convert_token(part) for part in field.split(","))
