"""Short-lived, in-memory state for the loopback OAuth callback.

The `state` value is the CSRF check: whoever calls the callback has to present
the same opaque token we handed to Google. The PKCE code verifier rides along
so the callback can finish the exchange without a second round trip.
"""

from __future__ import annotations

import time
import uuid


class OAuthStateStore:
    def __init__(self, ttl_seconds: float = 600) -> None:
        self._ttl = ttl_seconds
        self._pending: dict[str, tuple[str, str, float]] = {}

    def open(self, connector_id: str, code_verifier: str) -> str:
        state = uuid.uuid4().hex
        self._pending[state] = (connector_id, code_verifier, time.time())
        return state

    def pop(self, state: str) -> tuple[str, str] | None:
        entry = self._pending.pop(state, None)
        if entry is None:
            return None
        connector_id, code_verifier, created_at = entry
        if time.time() - created_at > self._ttl:
            return None
        return connector_id, code_verifier
