"""In-memory confirmation broker.

The agent opens a request, the UI resolves it from another HTTP call, and the
loop waits on the same future. Desktop control can reuse this gate: a risky
tool sets its risk, and the loop asks before it runs.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol


class ConfirmationGate(Protocol):
    def open(self) -> str: ...

    async def wait(self, request_id: str, timeout: float) -> bool: ...

    def resolve(self, request_id: str, approved: bool) -> bool: ...


class InMemoryConfirmationGate:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[bool]] = {}

    def open(self) -> str:
        request_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        self._pending[request_id] = loop.create_future()
        return request_id

    async def wait(self, request_id: str, timeout: float) -> bool:
        future = self._pending.get(request_id)
        if future is None:
            return False
        try:
            return await asyncio.wait_for(future, timeout)
        except TimeoutError:
            return False
        finally:
            current = self._pending.get(request_id)
            if current is future:
                self._pending.pop(request_id, None)

    def resolve(self, request_id: str, approved: bool) -> bool:
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(approved)
        return True


class ScriptedGate:
    """Test double. Decisions are consumed in order."""

    def __init__(self, decisions: list[bool]):
        self._decisions = list(decisions)
        self.opened: list[str] = []

    def open(self) -> str:
        request_id = f"req-{len(self.opened) + 1}"
        self.opened.append(request_id)
        return request_id

    async def wait(self, request_id: str, timeout: float) -> bool:
        del request_id, timeout
        if not self._decisions:
            return False
        return self._decisions.pop(0)

    def resolve(self, request_id: str, approved: bool) -> bool:
        del request_id, approved
        return True
