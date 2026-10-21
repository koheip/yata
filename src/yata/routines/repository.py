"""SQLite persistence for routines and their runs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from yata.routines.schedule import as_utc_iso, next_run, parse_utc_iso


@dataclass
class Routine:
    id: str
    name: str
    prompt: str
    schedule_kind: str
    schedule: str
    timezone: str
    enabled: bool
    last_run: str | None
    next_run: str | None
    model_id: str
    conversation_id: str
    created_at: str
    updated_at: str


@dataclass
class RoutineRun:
    id: str
    routine_id: str
    conversation_id: str
    status: str
    snippet: str
    confirmation_id: str | None
    confirmation_summary: str | None
    confirmation_tool: str | None
    confirmation_risk: str | None
    confirmation_arguments: dict[str, Any] | None
    started_at: str
    finished_at: str | None


class RoutineRepository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS routines (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    schedule_kind TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    last_run TEXT,
                    next_run TEXT,
                    model_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routine_runs (
                    id TEXT PRIMARY KEY,
                    routine_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    snippet TEXT NOT NULL DEFAULT '',
                    confirmation_id TEXT,
                    confirmation_summary TEXT,
                    confirmation_tool TEXT,
                    confirmation_risk TEXT,
                    confirmation_arguments_json TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY (routine_id) REFERENCES routines(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_routine_runs_routine
                    ON routine_runs(routine_id, started_at);
                """
            )

    def insert(
        self,
        *,
        name: str,
        prompt: str,
        schedule_kind: str,
        schedule: str,
        timezone: str,
        model_id: str,
        conversation_id: str,
        now: datetime | None = None,
    ) -> Routine:
        moment = now or datetime.now(UTC)
        stamp = as_utc_iso(moment)
        nxt = as_utc_iso(next_run(schedule_kind, schedule, timezone, moment))
        routine = Routine(
            id=uuid.uuid4().hex,
            name=name.strip(),
            prompt=prompt.strip(),
            schedule_kind=schedule_kind,
            schedule=schedule,
            timezone=timezone,
            enabled=True,
            last_run=None,
            next_run=nxt,
            model_id=model_id,
            conversation_id=conversation_id,
            created_at=stamp,
            updated_at=stamp,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO routines (
                    id, name, prompt, schedule_kind, schedule, timezone, enabled,
                    last_run, next_run, model_id, conversation_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    routine.id,
                    routine.name,
                    routine.prompt,
                    routine.schedule_kind,
                    routine.schedule,
                    routine.timezone,
                    routine.next_run,
                    routine.model_id,
                    routine.conversation_id,
                    routine.created_at,
                    routine.updated_at,
                ),
            )
        return routine

    def list_routines(self) -> list[Routine]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM routines
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [_routine(row) for row in rows]

    def get(self, routine_id: str) -> Routine | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
        return _routine(row) if row else None

    def delete(self, routine_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
            return cursor.rowcount > 0

    def set_enabled(self, routine_id: str, enabled: bool, *, now: datetime | None = None) -> Routine | None:
        current = self.get(routine_id)
        if current is None:
            return None
        moment = now or datetime.now(UTC)
        stamp = as_utc_iso(moment)
        nxt = current.next_run
        if enabled and (nxt is None or parse_utc_iso(nxt) <= moment):
            nxt = as_utc_iso(next_run(current.schedule_kind, current.schedule, current.timezone, moment))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE routines
                SET enabled = ?, next_run = ?, updated_at = ?
                WHERE id = ?
                """,
                (1 if enabled else 0, nxt, stamp, routine_id),
            )
        return self.get(routine_id)

    def replace_conversation(self, routine_id: str, conversation_id: str) -> None:
        stamp = as_utc_iso(datetime.now(UTC))
        with self._connect() as conn:
            conn.execute(
                "UPDATE routines SET conversation_id = ?, updated_at = ? WHERE id = ?",
                (conversation_id, stamp, routine_id),
            )

    def due_routines(self, now: datetime) -> list[Routine]:
        stamp = as_utc_iso(now)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM routines
                WHERE enabled = 1 AND next_run IS NOT NULL AND next_run <= ?
                ORDER BY next_run ASC
                """,
                (stamp,),
            ).fetchall()
        return [_routine(row) for row in rows]

    def claim(self, routine_id: str, now: datetime, nxt: datetime) -> RoutineRun | None:
        """Mark one due routine as running and advance next_run, in one transaction."""
        now_iso = as_utc_iso(now)
        nxt_iso = as_utc_iso(nxt)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
            if row is None or row["enabled"] != 1:
                return None
            if row["next_run"] is None or row["next_run"] > now_iso:
                return None
            open_run = conn.execute(
                """
                SELECT id FROM routine_runs
                WHERE routine_id = ? AND status IN ('running', 'waiting_confirmation')
                """,
                (routine_id,),
            ).fetchone()
            if open_run is not None:
                return None
            run_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO routine_runs (
                    id, routine_id, conversation_id, status, snippet, started_at
                ) VALUES (?, ?, ?, 'running', '', ?)
                """,
                (run_id, routine_id, row["conversation_id"], now_iso),
            )
            conn.execute(
                """
                UPDATE routines
                SET last_run = ?, next_run = ?, updated_at = ?
                WHERE id = ?
                """,
                (now_iso, nxt_iso, now_iso, routine_id),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> RoutineRun | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM routine_runs WHERE id = ?", (run_id,)).fetchone()
        return _run(row) if row else None

    def latest_run(self, routine_id: str) -> RoutineRun | None:
        runs = self.recent_runs(routine_id, limit=1)
        return runs[0] if runs else None

    def recent_runs(self, routine_id: str, *, limit: int = 3) -> list[RoutineRun]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM routine_runs
                WHERE routine_id = ?
                ORDER BY started_at DESC, rowid DESC
                LIMIT ?
                """,
                (routine_id, limit),
            ).fetchall()
        return [_run(row) for row in rows]

    def mark_waiting(
        self,
        run_id: str,
        *,
        summary: str,
        confirmation_id: str,
        tool: str,
        risk: str,
        arguments: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE routine_runs
                SET status = 'waiting_confirmation',
                    snippet = ?,
                    confirmation_id = ?,
                    confirmation_summary = ?,
                    confirmation_tool = ?,
                    confirmation_risk = ?,
                    confirmation_arguments_json = ?
                WHERE id = ?
                """,
                (
                    summary[:500],
                    confirmation_id,
                    summary[:500],
                    tool,
                    risk,
                    json.dumps(arguments, ensure_ascii=False),
                    run_id,
                ),
            )

    def finish_run(self, run_id: str, *, status: str, snippet: str) -> None:
        stamp = as_utc_iso(datetime.now(UTC))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE routine_runs
                SET status = ?, snippet = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, snippet[:500], stamp, run_id),
            )

    def interrupt_open_runs(self, snippet: str) -> list[RoutineRun]:
        stamp = as_utc_iso(datetime.now(UTC))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM routine_runs
                WHERE status IN ('running', 'waiting_confirmation')
                """
            ).fetchall()
            conn.execute(
                """
                UPDATE routine_runs
                SET status = 'error', snippet = ?, finished_at = ?
                WHERE status IN ('running', 'waiting_confirmation')
                """,
                (snippet[:500], stamp),
            )
        return [_run(row) for row in rows]


def _routine(row: sqlite3.Row) -> Routine:
    return Routine(
        id=row["id"],
        name=row["name"],
        prompt=row["prompt"],
        schedule_kind=row["schedule_kind"],
        schedule=row["schedule"],
        timezone=row["timezone"],
        enabled=bool(row["enabled"]),
        last_run=row["last_run"],
        next_run=row["next_run"],
        model_id=row["model_id"],
        conversation_id=row["conversation_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _run(row: sqlite3.Row) -> RoutineRun:
    arguments = None
    if row["confirmation_arguments_json"]:
        loaded = json.loads(row["confirmation_arguments_json"])
        if isinstance(loaded, dict):
            arguments = loaded
    return RoutineRun(
        id=row["id"],
        routine_id=row["routine_id"],
        conversation_id=row["conversation_id"],
        status=row["status"],
        snippet=row["snippet"] or "",
        confirmation_id=row["confirmation_id"],
        confirmation_summary=row["confirmation_summary"],
        confirmation_tool=row["confirmation_tool"],
        confirmation_risk=row["confirmation_risk"],
        confirmation_arguments=arguments,
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )
