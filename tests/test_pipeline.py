"""Pipeline guards.

The tests here cover the decisions the pipeline makes *before* it touches the
network, which are exactly the ones that stop it posting something it should
not have.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kleos.config import Settings
from kleos.media.registry import MediaRegistry
from kleos.models import LocalVideo, PublishResult, VideoRef
from kleos.pipeline import Pipeline, build_caption


class FakePublisher:
    """Records what it was asked to publish instead of calling an API."""

    def __init__(self, name: str, *, enabled: bool = True, cap: int = 140) -> None:
        self._name = name
        self._enabled = enabled
        self._cap = cap
        self.calls: list[tuple[Path, str]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def max_duration_s(self) -> int:
        return self._cap

    async def publish(self, video: LocalVideo, caption: str) -> PublishResult:
        self.calls.append((video.path, caption))
        return PublishResult.success(self._name, f"{self._name}_1")


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("STALENESS_MINUTES", "180")
    built = Settings()  # type: ignore[call-arg]
    return replace_paths(built, tmp_path)


def replace_paths(settings: Settings, tmp_path: Path) -> Settings:
    settings.data_dir = tmp_path / "data"
    settings.work_dir = tmp_path / "work"
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    from kleos.db import init_db

    init_db(settings.db_path)
    return settings


@pytest.fixture
def pipeline(settings: Settings) -> Pipeline:
    registry = MediaRegistry(settings.public_base_url)
    return Pipeline(settings, registry, (FakePublisher("fake"),))


def test_caption_is_the_title_when_there_is_no_suffix(ref: VideoRef):
    assert build_caption(ref, "") == "Match Highlights"


def test_caption_appends_the_suffix(ref: VideoRef):
    assert build_caption(ref, "#football") == "Match Highlights\n\n#football"


def test_caption_ignores_a_whitespace_only_suffix(ref: VideoRef):
    assert build_caption(ref, "   ") == "Match Highlights"


def test_a_fresh_upload_is_not_stale(pipeline: Pipeline, ref: VideoRef):
    assert pipeline.is_stale(ref) is False


def test_an_old_upload_is_stale(pipeline: Pipeline, ref: VideoRef):
    old = replace(ref, published_at=datetime.now(UTC) - timedelta(hours=4))
    assert pipeline.is_stale(old) is True


def test_staleness_boundary_is_respected(pipeline: Pipeline, ref: VideoRef):
    just_inside = replace(ref, published_at=datetime.now(UTC) - timedelta(minutes=179))
    assert pipeline.is_stale(just_inside) is False


async def test_a_stale_video_is_never_published(pipeline: Pipeline, ref: VideoRef):
    """The catch-up poller must not flood accounts after the PC wakes up."""
    old = replace(ref, published_at=datetime.now(UTC) - timedelta(days=1))
    assert await pipeline.handle(old) == ()


async def test_the_kill_switch_prevents_publishing(pipeline: Pipeline, ref: VideoRef):
    pipeline.set_publish_enabled(False)
    assert pipeline.publish_enabled() is False
    assert await pipeline.handle(ref) == ()


def test_the_kill_switch_survives_a_restart(settings: Settings, pipeline: Pipeline):
    pipeline.set_publish_enabled(False)
    reloaded = Pipeline(settings, MediaRegistry(settings.public_base_url), ())
    assert reloaded.publish_enabled() is False


def test_publishing_defaults_to_enabled(pipeline: Pipeline):
    assert pipeline.publish_enabled() is True
