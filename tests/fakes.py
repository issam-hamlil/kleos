"""Shared fakes for the approval-mode suites."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from kleos import db
from kleos import pipeline as pipeline_module
from kleos.config import Settings
from kleos.media.registry import MediaRegistry
from kleos.models import LocalVideo, PublishResult, VideoRef
from kleos.pipeline import Pipeline

API_TOKEN = "t" * 32


class RecordingPublisher:
    def __init__(self, name: str, *, enabled: bool = True, ok: bool = True) -> None:
        self._name, self._enabled, self._ok = name, enabled, ok
        self.published: list[Path] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def max_duration_s(self) -> int:
        return 7200

    async def publish(self, video: LocalVideo, caption: str) -> PublishResult:
        self.published.append(video.path)
        if self._ok:
            return PublishResult.success(self._name, f"{self._name}_1")
        return PublishResult.failure(self._name, "api said no")


def approval_settings(tmp_path: Path) -> Settings:
    built = Settings()  # type: ignore[call-arg]
    built.approval_required = True
    built.kleos_api_token = API_TOKEN
    built.pending_ttl_minutes = 60
    built.data_dir = tmp_path / "data"
    built.work_dir = tmp_path / "work"
    built.data_dir.mkdir(parents=True)
    built.work_dir.mkdir(parents=True)
    db.init_db(built.db_path)
    return built


def make_ref(video_id: str = "vid1") -> VideoRef:
    return VideoRef(
        video_id=video_id,
        channel_id="UC_one",
        title="Highlights",
        published_at=datetime.now(UTC),
    )


def build_pipeline(settings: Settings, *publishers: RecordingPublisher) -> Pipeline:
    return Pipeline(settings, MediaRegistry(settings.public_base_url), tuple(publishers))


def stub_fetch(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Replace fetch with one that writes a real file; trim passes through."""
    calls = {"fetch": 0}

    async def fake_fetch(ref: VideoRef, work_dir: Path) -> LocalVideo:
        calls["fetch"] += 1
        path = work_dir / f"{ref.video_id}.mp4"
        path.write_bytes(b"fake video")
        return LocalVideo(ref=ref, path=path, duration_s=90.0)

    async def fake_trim(video: LocalVideo, cap: int) -> LocalVideo:
        return video

    monkeypatch.setattr(pipeline_module.fetch, "fetch", fake_fetch)
    monkeypatch.setattr(pipeline_module.trim, "trim_to", fake_trim)
    return calls
