"""End-to-end orchestration with the network stubbed out.

Fetch and trim are replaced; everything else is real. These cover the sequencing
guarantees: fetch once, publish to each enabled platform, record every outcome,
and leave no video files behind.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kleos import db
from kleos import pipeline as pipeline_module
from kleos.config import Settings
from kleos.media.registry import MediaRegistry
from kleos.models import LocalVideo, PublishResult, VideoRef
from kleos.pipeline import Pipeline


class RecordingPublisher:
    def __init__(self, name: str, *, enabled: bool = True, cap: int = 140, ok: bool = True):
        self._name, self._enabled, self._cap, self._ok = name, enabled, cap, ok
        self.captions: list[str] = []

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
        self.captions.append(caption)
        if self._ok:
            return PublishResult.success(self._name, f"{self._name}_1")
        return PublishResult.failure(self._name, "api said no")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    built = Settings()  # type: ignore[call-arg]
    built.data_dir = tmp_path / "data"
    built.work_dir = tmp_path / "work"
    built.data_dir.mkdir(parents=True)
    built.work_dir.mkdir(parents=True)
    db.init_db(built.db_path)
    return built


@pytest.fixture
def ref() -> VideoRef:
    return VideoRef(
        video_id="vid1",
        channel_id="UC_one",
        title="Highlights",
        published_at=datetime.now(UTC),
    )


@pytest.fixture
def stub_media(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    """Replace fetch with a real file on disk; leave trim to pass it through."""
    calls = {"fetch": 0}

    async def fake_fetch(ref: VideoRef, work_dir: Path) -> LocalVideo:
        calls["fetch"] += 1
        path = work_dir / f"{ref.video_id}.mp4"
        path.write_bytes(b"fake video")
        return LocalVideo(ref=ref, path=path, duration_s=100.0)

    async def fake_trim(video: LocalVideo, cap: int) -> LocalVideo:
        return video

    monkeypatch.setattr(pipeline_module.fetch, "fetch", fake_fetch)
    monkeypatch.setattr(pipeline_module.trim, "trim_to", fake_trim)
    return calls


def _pipeline(settings: Settings, *publishers) -> Pipeline:
    return Pipeline(settings, MediaRegistry(settings.public_base_url), tuple(publishers))


async def test_publishes_to_every_enabled_platform(settings, ref, stub_media):
    fb, ig = RecordingPublisher("facebook"), RecordingPublisher("instagram")
    results = await _pipeline(settings, fb, ig).handle(ref)
    assert {r.platform for r in results} == {"facebook", "instagram"}
    assert all(r.ok for r in results)


async def test_skips_disabled_platforms(settings, ref, stub_media):
    fb = RecordingPublisher("facebook")
    off = RecordingPublisher("x", enabled=False)
    results = await _pipeline(settings, fb, off).handle(ref)
    assert [r.platform for r in results] == ["facebook"]
    assert off.captions == []


async def test_fetches_once_for_all_platforms(settings, ref, stub_media):
    await _pipeline(
        settings, RecordingPublisher("facebook"), RecordingPublisher("instagram")
    ).handle(ref)
    assert stub_media["fetch"] == 1


async def test_records_every_outcome(settings, ref, stub_media):
    await _pipeline(settings, RecordingPublisher("facebook")).handle(ref)
    assert db.already_published(settings.db_path, "vid1", "facebook") is True


async def test_a_failure_on_one_platform_does_not_stop_the_others(settings, ref, stub_media):
    bad = RecordingPublisher("x", ok=False)
    good = RecordingPublisher("facebook")
    results = await _pipeline(settings, bad, good).handle(ref)
    assert {r.platform: r.ok for r in results} == {"x": False, "facebook": True}


async def test_a_failed_platform_is_retried_on_the_next_run(settings, ref, stub_media):
    bad = RecordingPublisher("x", ok=False)
    await _pipeline(settings, bad).handle(ref)
    good = RecordingPublisher("x")
    results = await _pipeline(settings, good).handle(ref)
    assert [r.ok for r in results] == [True]


async def test_an_already_published_platform_is_not_published_again(settings, ref, stub_media):
    """The guard against double-posting, which is what gets accounts flagged."""
    first = RecordingPublisher("facebook")
    await _pipeline(settings, first).handle(ref)
    second = RecordingPublisher("facebook")
    assert await _pipeline(settings, second).handle(ref) == ()
    assert second.captions == []


async def test_source_files_are_deleted_after_publishing(settings, ref, stub_media):
    await _pipeline(settings, RecordingPublisher("facebook")).handle(ref)
    assert list(settings.work_dir.glob("*")) == []


async def test_the_caption_is_the_youtube_title(settings, ref, stub_media):
    fb = RecordingPublisher("facebook")
    await _pipeline(settings, fb).handle(ref)
    assert fb.captions == ["Highlights"]


async def test_a_fetch_failure_is_recorded_as_a_failure_per_platform(settings, ref, monkeypatch):
    async def boom(ref: VideoRef, work_dir: Path) -> LocalVideo:
        raise RuntimeError("410 gone")

    monkeypatch.setattr(pipeline_module.fetch, "fetch", boom)
    results = await _pipeline(settings, RecordingPublisher("facebook")).handle(ref)
    assert [r.ok for r in results] == [False]
    assert "410 gone" in results[0].error


async def test_a_trim_failure_skips_only_that_platform(settings, ref, stub_media, monkeypatch):
    async def selective_trim(video: LocalVideo, cap: int) -> LocalVideo:
        if cap == 140:
            raise RuntimeError("keyframe error")
        return video

    monkeypatch.setattr(pipeline_module.trim, "trim_to", selective_trim)
    results = await _pipeline(
        settings,
        RecordingPublisher("x", cap=140),
        RecordingPublisher("facebook", cap=7200),
    ).handle(ref)
    assert {r.platform: r.ok for r in results} == {"x": False, "facebook": True}


async def test_a_stale_video_is_never_fetched(settings, ref, stub_media):
    old = replace(ref, published_at=datetime(2020, 1, 1, tzinfo=UTC))
    assert await _pipeline(settings, RecordingPublisher("facebook")).handle(old) == ()
    assert stub_media["fetch"] == 0


# --- regression guards -----------------------------------------------------


async def test_concurrent_pushes_for_one_video_publish_it_once(settings, ref, stub_media):
    """The hub sends duplicate pushes for the same upload."""
    fb = RecordingPublisher("facebook")
    pipeline = _pipeline(settings, fb)
    await asyncio.gather(pipeline.handle(ref), pipeline.handle(ref))
    assert len(fb.captions) == 1


async def test_the_per_video_lock_is_not_evicted_after_handling(settings, ref, stub_media):
    """Regression: evicting a lock while holding it allows a double-post.

    A later push would build a *second* lock for the same video and run
    alongside a task already queued on the first. Both would read pending
    targets before either recorded a publication, and the clip would go out
    twice - which is precisely the pattern that gets accounts flagged.
    """
    pipeline = _pipeline(settings, RecordingPublisher("facebook"))
    lock_before = pipeline._locks[ref.video_id]
    await pipeline.handle(ref)
    assert pipeline._locks[ref.video_id] is lock_before


async def test_files_are_not_exposed_publicly_for_platforms_that_upload_directly(
    settings, ref, stub_media
):
    """Only Instagram fetches over HTTP; nothing else should be made reachable."""

    class CountingRegistry(MediaRegistry):
        def __init__(self, base_url: str) -> None:
            super().__init__(base_url)
            self.registered: list[Path] = []

        def register(self, path: Path) -> str:
            self.registered.append(path)
            return super().register(path)

    registry = CountingRegistry(settings.public_base_url)
    pipeline = Pipeline(settings, registry, (RecordingPublisher("facebook"),))
    await pipeline.handle(ref)
    assert registry.registered == []


async def test_partial_downloads_are_removed_when_fetch_fails(settings, ref, monkeypatch):
    """yt-dlp leaves .part fragments behind; nothing else would ever clear them."""

    async def boom(ref: VideoRef, work_dir: Path) -> LocalVideo:
        (work_dir / f"{ref.video_id}.mp4.part").write_bytes(b"partial")
        raise RuntimeError("connection reset")

    monkeypatch.setattr(pipeline_module.fetch, "fetch", boom)
    await _pipeline(settings, RecordingPublisher("facebook")).handle(ref)
    assert list(settings.work_dir.glob("*")) == []
