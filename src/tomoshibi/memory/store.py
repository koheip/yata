"""Small synchronous SQLite store.

Personal scale does not need a server. Each call opens its own connection so
the store is safe to use from worker threads. A multi-user deployment can
replace this module without changing the agent loop.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tomoshibi.llm.types import LLMMessage, ToolCall


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def clip_title(text: str, limit: int = 32) -> str:
    collapsed = " ".join(text.split())
    if not collapsed:
        return "新しい会話"
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


@dataclass
class Conversation:
    id: str
    title: str
    model_id: str
    created_at: str
    updated_at: str


@dataclass
class Fact:
    key: str
    value: str
    updated_at: str


@dataclass
class StoredMessage:
    id: str
    conversation_id: str
    role: str
    content: str | None
    tool_calls: list[ToolCall] | None
    tool_call_id: str | None
    tool_name: str | None
    artifact: dict[str, Any] | None
    created_at: str

    def to_llm(self) -> LLMMessage:
        return LLMMessage(
            role=self.role,
            content=self.content,
            tool_calls=self.tool_calls,
            tool_call_id=self.tool_call_id,
            name=self.tool_name,
            artifact=self.artifact,
        )


class MemoryStore:
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
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT,
                    tool_calls_json TEXT,
                    tool_call_id TEXT,
                    tool_name TEXT,
                    artifact_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id, created_at);

                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_conversation(self, model_id: str, title: str = "新しい会話") -> Conversation:
        now = utcnow()
        conversation = Conversation(
            id=uuid.uuid4().hex,
            title=title.strip() or "新しい会話",
            model_id=model_id,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, title, model_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conversation.id,
                    conversation.title,
                    conversation.model_id,
                    conversation.created_at,
                    conversation.updated_at,
                ),
            )
        return conversation

    def list_conversations(self) -> list[Conversation]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, model_id, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [_conversation(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, model_id, created_at, updated_at
                FROM conversations WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return _conversation(row) if row else None

    def update_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        model_id: str | None = None,
    ) -> Conversation | None:
        current = self.get_conversation(conversation_id)
        if current is None:
            return None
        updated = Conversation(
            id=current.id,
            title=title.strip() if title is not None else current.title,
            model_id=model_id or current.model_id,
            created_at=current.created_at,
            updated_at=utcnow(),
        )
        if updated.title == "":
            updated.title = current.title
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE conversations
                SET title = ?, model_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (updated.title, updated.model_id, updated.updated_at, updated.id),
            )
        return updated

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return cursor.rowcount > 0

    def add_message(self, conversation_id: str, message: LLMMessage) -> StoredMessage:
        stored = StoredMessage(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            role=message.role,
            content=message.content,
            tool_calls=message.tool_calls,
            tool_call_id=message.tool_call_id,
            tool_name=message.name,
            artifact=message.artifact,
            created_at=utcnow(),
        )
        tool_calls_json = None
        if stored.tool_calls:
            tool_calls_json = json.dumps(
                [
                    {"id": call.id, "name": call.name, "arguments": call.arguments}
                    for call in stored.tool_calls
                ],
                ensure_ascii=False,
            )
        artifact_json = json.dumps(stored.artifact, ensure_ascii=False) if stored.artifact else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, tool_calls_json,
                    tool_call_id, tool_name, artifact_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored.id,
                    stored.conversation_id,
                    stored.role,
                    stored.content,
                    tool_calls_json,
                    stored.tool_call_id,
                    stored.tool_name,
                    artifact_json,
                    stored.created_at,
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (stored.created_at, conversation_id),
            )
        return stored

    def list_messages(self, conversation_id: str) -> list[StoredMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, conversation_id, role, content, tool_calls_json,
                       tool_call_id, tool_name, artifact_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [_message(row) for row in rows]

    def maybe_title_from_first_message(self, conversation_id: str, text: str) -> None:
        conversation = self.get_conversation(conversation_id)
        if conversation and conversation.title == "新しい会話":
            self.update_conversation(conversation_id, title=clip_title(text))

    def upsert_fact(self, key: str, value: str) -> Fact:
        fact = Fact(key=key.strip(), value=value.strip(), updated_at=utcnow())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO facts (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (fact.key, fact.value, fact.updated_at),
            )
        return fact

    def list_facts(self, limit: int = 40) -> list[Fact]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key, value, updated_at FROM facts
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [Fact(key=row["key"], value=row["value"], updated_at=row["updated_at"]) for row in rows]

    def delete_fact(self, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM facts WHERE key = ?", (key,))
            return cursor.rowcount > 0


def to_transcript(messages: list[StoredMessage]) -> list[dict[str, Any]]:
    """Fold tool traffic into the assistant turn that the chat UI shows."""
    items: list[dict[str, Any]] = []
    pending_steps: list[dict[str, Any]] = []
    pending_calls: list[ToolCall] = []

    def flush_if_needed(final_id: str, content: str) -> None:
        nonlocal pending_steps, pending_calls
        if not pending_steps and not content:
            return
        steps = _attach_results(pending_calls, pending_steps)
        items.append(
            {
                "id": final_id,
                "role": "assistant",
                "content": content,
                "steps": steps,
            }
        )
        pending_steps = []
        pending_calls = []

    for message in messages:
        if message.role == "user":
            if pending_calls or pending_steps:
                flush_if_needed(f"partial-{message.id}", "")
            items.append(
                {
                    "id": message.id,
                    "role": "user",
                    "content": message.content or "",
                    "steps": [],
                }
            )
            continue
        if message.role == "assistant" and message.tool_calls:
            if message.content:
                pending_steps.append({"type": "note", "text": message.content})
            pending_calls.extend(message.tool_calls)
            continue
        if message.role == "tool":
            pending_steps.append(
                {
                    "type": "tool_result",
                    "id": message.tool_call_id,
                    "name": message.tool_name,
                    "content": message.content or "",
                    "artifact": message.artifact or {},
                }
            )
            continue
        if message.role == "assistant":
            flush_if_needed(message.id, message.content or "")
    if pending_calls or pending_steps:
        flush_if_needed("partial", "")
    return items


def _attach_results(calls: list[ToolCall], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results_by_id = {
        step.get("id"): step for step in steps if step.get("type") == "tool_result" and step.get("id")
    }
    notes = [step for step in steps if step.get("type") == "note"]
    rendered: list[dict[str, Any]] = []
    for note in notes:
        rendered.append({"type": "note", "text": note.get("text") or ""})
    consumed: set[str] = set()
    for call in calls:
        result = results_by_id.get(call.id)
        if result:
            consumed.add(call.id)
        artifact = (result or {}).get("artifact") or {}
        content = (result or {}).get("content") or ""
        rendered.append(
            {
                "type": "tool",
                "id": call.id,
                "name": call.name,
                "arguments": call.arguments,
                "ok": bool(artifact.get("ok", bool(result))),
                "content": content,
                "image_url": artifact.get("image_url"),
            }
        )
    for step in steps:
        if step.get("type") == "tool_result" and step.get("id") not in consumed:
            artifact = step.get("artifact") or {}
            rendered.append(
                {
                    "type": "tool",
                    "id": step.get("id"),
                    "name": step.get("name"),
                    "arguments": {},
                    "ok": True,
                    "content": step.get("content") or "",
                    "image_url": artifact.get("image_url"),
                }
            )
    return rendered


def _conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=row["id"],
        title=row["title"],
        model_id=row["model_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message(row: sqlite3.Row) -> StoredMessage:
    tool_calls = None
    if row["tool_calls_json"]:
        raw_calls = json.loads(row["tool_calls_json"])
        tool_calls = [
            ToolCall(id=item["id"], name=item["name"], arguments=item.get("arguments") or {})
            for item in raw_calls
        ]
    artifact = json.loads(row["artifact_json"]) if row["artifact_json"] else None
    return StoredMessage(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        tool_calls=tool_calls,
        tool_call_id=row["tool_call_id"],
        tool_name=row["tool_name"],
        artifact=artifact,
        created_at=row["created_at"],
    )
