"""Immutable value objects passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VideoRef:
    """A YouTube upload we have been told about, before any work is done on it."""

    video_id: str
    channel_id: str
    title: str
    published_at: datetime

    @property
    def watch_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True, slots=True)
class LocalVideo:
    """A fetched file on disk, plus what we know about it."""

    ref: VideoRef
    path: Path
    duration_s: float

    def with_path(self, path: Path, duration_s: float) -> LocalVideo:
        """Return a new LocalVideo pointing at a different file (e.g. a trim)."""
        return replace(self, path=path, duration_s=duration_s)


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Outcome of one publish attempt on one platform.

    Publishers return this instead of raising: one platform failing must never
    prevent the other two from being attempted.
    """

    platform: str
    ok: bool
    remote_id: str = ""
    error: str = ""

    @classmethod
    def success(cls, platform: str, remote_id: str) -> PublishResult:
        return cls(platform=platform, ok=True, remote_id=remote_id)

    @classmethod
    def failure(cls, platform: str, error: str) -> PublishResult:
        return cls(platform=platform, ok=False, error=error)
