"""Approval mode: nothing leaves the building until an operator says so.

The properties that matter are negative ones - a clip is never published
without approval, never to a platform nobody chose, never twice, and never
after it was rejected or expired.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kleos import clip_store, db
from kleos import pipeline as pipeline_module
from kleos.models import ClipStatus, LocalVideo, VideoRef
from kleos.pipeline import ClipNotPendingError, PublishingDisabledError, UnknownPlatformError
from tests.fakes import RecordingPublisher, approval_settings, build_pipeline, make_ref, stub_fetch


@pytest.fixture
def settings(tmp_path: Path):
    return approval_settings(tmp_path)


@pytest.fixture
def fetches(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    return stub_fetch(monkeypatch)


def _later(settings) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=settings.pending_ttl_minutes + 1)


async def test_a_new_upload_is_queued_not_published(settings, fetches):
    fb = RecordingPublisher("facebook")
    assert await build_pipeline(settings, fb).handle(make_ref()) == ()
    clip = clip_store.get(settings.db_path, "vid1")
    assert clip is not None and clip.status is ClipStatus.PENDING
    assert fb.published == []


async def test_a_queued_clip_keeps_its_file_for_preview(settings, fetches):
    await build_pipeline(settings, RecordingPublisher("facebook")).handle(make_ref())
    assert (settings.work_dir / "vid1.mp4").exists()


async def test_a_repeat_push_does_not_fetch_again(settings, fetches):
    pipeline = build_pipeline(settings, RecordingPublisher("facebook"))
    await pipeline.handle(make_ref())
    await pipeline.handle(make_ref())
    assert fetches["fetch"] == 1


async def test_a_rejected_clip_is_never_requeued(settings, fetches):
    """The catch-up poller revisits recent uploads; a rejection must stick."""
    pipeline = build_pipeline(settings, RecordingPublisher("facebook"))
    await pipeline.handle(make_ref())
    await pipeline.reject("vid1")
    await pipeline.handle(make_ref())
    assert clip_store.get(settings.db_path, "vid1").status is ClipStatus.REJECTED
    assert fetches["fetch"] == 1


async def test_a_fetch_failure_queues_nothing_and_leaves_no_files(settings, monkeypatch):
    async def boom(ref: VideoRef, work_dir: Path) -> LocalVideo:
        (work_dir / f"{ref.video_id}.mp4.part").write_bytes(b"partial")
        raise RuntimeError("403")

    monkeypatch.setattr(pipeline_module.fetch, "fetch", boom)
    await build_pipeline(settings, RecordingPublisher("facebook")).handle(make_ref())
    assert clip_store.get(settings.db_path, "vid1") is None
    assert list(settings.work_dir.glob("*")) == []


async def test_approval_publishes_only_the_chosen_platforms(settings, fetches):
    fb, x = RecordingPublisher("facebook"), RecordingPublisher("x")
    pipeline = build_pipeline(settings, fb, x)
    await pipeline.handle(make_ref())
    results = await pipeline.approve("vid1", ["x"])
    assert [r.platform for r in results] == ["x"]
    assert fb.published == []
    assert len(x.published) == 1


async def test_approval_records_the_decision_and_deletes_the_file(settings, fetches):
    pipeline = build_pipeline(settings, RecordingPublisher("facebook"))
    await pipeline.handle(make_ref())
    await pipeline.approve("vid1", ["facebook"])
    clip = clip_store.get(settings.db_path, "vid1")
    assert clip.status is ClipStatus.APPROVED
    assert clip.platforms == ("facebook",)
    assert db.already_published(settings.db_path, "vid1", "facebook")
    assert list(settings.work_dir.glob("*")) == []


async def test_approving_twice_publishes_once(settings, fetches):
    fb = RecordingPublisher("facebook")
    pipeline = build_pipeline(settings, fb)
    await pipeline.handle(make_ref())
    await pipeline.approve("vid1", ["facebook"])
    with pytest.raises(ClipNotPendingError):
        await pipeline.approve("vid1", ["facebook"])
    assert len(fb.published) == 1


async def test_concurrent_approvals_publish_once(settings, fetches):
    """Two taps from the phone, or a tap plus a network retry, race on one clip."""
    fb = RecordingPublisher("facebook")
    pipeline = build_pipeline(settings, fb)
    await pipeline.handle(make_ref())
    outcomes = await asyncio.gather(
        pipeline.approve("vid1", ["facebook"]),
        pipeline.approve("vid1", ["facebook"]),
        return_exceptions=True,
    )
    assert sum(isinstance(o, ClipNotPendingError) for o in outcomes) == 1
    assert len(fb.published) == 1


async def test_duplicate_platform_names_publish_once(settings, fetches):
    fb = RecordingPublisher("facebook")
    pipeline = build_pipeline(settings, fb)
    await pipeline.handle(make_ref())
    await pipeline.approve("vid1", ["facebook", "facebook"])
    assert len(fb.published) == 1


@pytest.mark.parametrize("platforms", [[], ["tiktok"], ["x"]])
async def test_invalid_platform_choices_are_refused_and_leave_the_clip_pending(
    settings, fetches, platforms
):
    """Empty, unknown, and switched-off platforms are all refused."""
    pipeline = build_pipeline(
        settings, RecordingPublisher("facebook"), RecordingPublisher("x", enabled=False)
    )
    await pipeline.handle(make_ref())
    with pytest.raises(UnknownPlatformError):
        await pipeline.approve("vid1", platforms)
    assert clip_store.get(settings.db_path, "vid1").status is ClipStatus.PENDING


async def test_the_kill_switch_blocks_approval(settings, fetches):
    fb = RecordingPublisher("facebook")
    pipeline = build_pipeline(settings, fb)
    await pipeline.handle(make_ref())
    pipeline.set_publish_enabled(False)
    with pytest.raises(PublishingDisabledError):
        await pipeline.approve("vid1", ["facebook"])
    assert fb.published == []
    assert clip_store.get(settings.db_path, "vid1").status is ClipStatus.PENDING


async def test_approving_an_unknown_clip_is_refused(settings, fetches):
    pipeline = build_pipeline(settings, RecordingPublisher("facebook"))
    with pytest.raises(ClipNotPendingError):
        await pipeline.approve("nope", ["facebook"])


async def test_a_missing_source_file_is_reported_not_published(settings, fetches):
    fb = RecordingPublisher("facebook")
    pipeline = build_pipeline(settings, fb)
    await pipeline.handle(make_ref())
    (settings.work_dir / "vid1.mp4").unlink()
    results = await pipeline.approve("vid1", ["facebook"])
    assert [(r.ok, r.error) for r in results] == [(False, "source file missing")]
    assert fb.published == []


async def test_a_platform_failure_is_recorded_after_approval(settings, fetches):
    pipeline = build_pipeline(settings, RecordingPublisher("x", ok=False))
    await pipeline.handle(make_ref())
    results = await pipeline.approve("vid1", ["x"])
    assert [r.ok for r in results] == [False]
    assert db.publication_counts(settings.db_path) == {"x": {"published": 0, "failed": 1}}


async def test_rejection_deletes_the_file_and_publishes_nothing(settings, fetches):
    fb = RecordingPublisher("facebook")
    pipeline = build_pipeline(settings, fb)
    await pipeline.handle(make_ref())
    await pipeline.reject("vid1")
    assert clip_store.get(settings.db_path, "vid1").status is ClipStatus.REJECTED
    assert list(settings.work_dir.glob("*")) == []
    assert fb.published == []


async def test_a_rejected_clip_cannot_be_approved(settings, fetches):
    pipeline = build_pipeline(settings, RecordingPublisher("facebook"))
    await pipeline.handle(make_ref())
    await pipeline.reject("vid1")
    with pytest.raises(ClipNotPendingError):
        await pipeline.approve("vid1", ["facebook"])


async def test_rejecting_twice_is_refused(settings, fetches):
    pipeline = build_pipeline(settings, RecordingPublisher("facebook"))
    await pipeline.handle(make_ref())
    await pipeline.reject("vid1")
    with pytest.raises(ClipNotPendingError):
        await pipeline.reject("vid1")


async def test_unreviewed_clips_expire_and_are_deleted(settings, fetches):
    pipeline = build_pipeline(settings, RecordingPublisher("facebook"))
    await pipeline.handle(make_ref())
    assert await pipeline.expire_pending(now=_later(settings)) == 1
    assert clip_store.get(settings.db_path, "vid1").status is ClipStatus.EXPIRED
    assert list(settings.work_dir.glob("*")) == []


async def test_clips_inside_the_review_window_do_not_expire(settings, fetches):
    pipeline = build_pipeline(settings, RecordingPublisher("facebook"))
    await pipeline.handle(make_ref())
    assert await pipeline.expire_pending() == 0
    assert clip_store.get(settings.db_path, "vid1").status is ClipStatus.PENDING


async def test_an_expired_clip_cannot_be_approved(settings, fetches):
    pipeline = build_pipeline(settings, RecordingPublisher("facebook"))
    await pipeline.handle(make_ref())
    await pipeline.expire_pending(now=_later(settings))
    with pytest.raises(ClipNotPendingError):
        await pipeline.approve("vid1", ["facebook"])


async def test_available_publishers_exclude_disabled_ones(settings):
    pipeline = build_pipeline(
        settings, RecordingPublisher("facebook"), RecordingPublisher("x", enabled=False)
    )
    assert [p.name for p in pipeline.available_publishers()] == ["facebook"]
