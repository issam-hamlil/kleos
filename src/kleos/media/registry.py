"""Short-lived public URLs for local files.

Instagram fetches video over HTTP rather than accepting an upload, so files have
to be reachable from the internet for the duration of a publish. Rather than
exposing the work directory, each file gets an unguessable token that expires.

Tokens are held in memory: a restart invalidates them, which is correct - an
in-flight publish would have failed anyway.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

DEFAULT_TTL_S = 3600


@dataclass(frozen=True, slots=True)
class _Entry:
    path: Path
    expires_at: float


class MediaRegistry:
    def __init__(self, base_url: str, ttl_s: int = DEFAULT_TTL_S) -> None:
        self._base_url = base_url.rstrip("/")
        self._ttl_s = ttl_s
        self._entries: dict[str, _Entry] = {}
        self._lock = Lock()

    def register(self, path: Path) -> str:
        """Expose a file and return its public URL."""
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._purge_locked()
            self._entries[token] = _Entry(path=path, expires_at=time.time() + self._ttl_s)
        return f"{self._base_url}/media/{token}.mp4"

    def resolve(self, token: str) -> Path | None:
        """Look up a token. Returns None if unknown, expired, or gone from disk."""
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            if entry.expires_at < time.time():
                del self._entries[token]
                return None
        return entry.path if entry.path.exists() else None

    def revoke_path(self, path: Path) -> None:
        """Drop every token pointing at a file, once we are done with it."""
        with self._lock:
            stale = [token for token, entry in self._entries.items() if entry.path == path]
            for token in stale:
                del self._entries[token]

    def _purge_locked(self) -> None:
        now = time.time()
        expired = [token for token, entry in self._entries.items() if entry.expires_at < now]
        for token in expired:
            del self._entries[token]
