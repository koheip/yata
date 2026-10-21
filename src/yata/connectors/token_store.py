"""Local token storage, one JSON file per connector under data/connectors/.

data/ is already gitignored. Tokens are never logged: callers pass the token
around as a value, not through log statements.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: float
    scope: str

    def to_json(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TokenSet:
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=float(data.get("expires_at") or 0),
            scope=data.get("scope") or "",
        )


class TokenStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, connector_id: str) -> Path:
        return self.directory / f"{connector_id}.json"

    def load(self, connector_id: str) -> TokenSet | None:
        path = self._path(connector_id)
        if not path.is_file():
            return None
        try:
            return TokenSet.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            return None

    def save(self, connector_id: str, token: TokenSet) -> None:
        path = self._path(connector_id)
        # mkstemp creates the file with 0600 permissions (POSIX) at creation
        # time, so there is no window where the token sits in a world/group
        # readable file before we get to restrict it.
        fd, tmp_name = tempfile.mkstemp(dir=self.directory, prefix=f".{connector_id}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(token.to_json()))
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        if sys.platform == "win32":
            self._restrict_to_current_user(path)

    @staticmethod
    def _restrict_to_current_user(path: Path) -> None:
        """Best effort: mode bits don't restrict an inherited ACL on Windows,
        so explicitly drop inheritance and grant full control to the current
        user only. Failures are swallowed; this is defense in depth."""
        user = os.environ.get("USERNAME")
        if not user:
            return
        domain = os.environ.get("USERDOMAIN")
        account = f"{domain}\\{user}" if domain else user
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{account}:F"],
                capture_output=True,
                check=False,
            )
        except OSError:
            pass

    def delete(self, connector_id: str) -> bool:
        path = self._path(connector_id)
        if not path.is_file():
            return False
        path.unlink()
        return True
