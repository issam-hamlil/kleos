"""Dedupe ledger behaviour.

These are the guarantees that stop the app double-posting, which is the failure
mode most likely to get an account flagged.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from kleos.db import (
    already_published,
    get_flag,
    recent_publications,
    record_publication,
    record_seen,
    set_flag,
)
from kleos.models import PublishResult, VideoRef


def test_first_sighting_of_a_video_returns_true(db_path: Path, ref: VideoRef):
    assert record_seen(db_path, ref) is True


def test_second_sighting_of_the_same_video_returns_false(db_path: Path, ref: VideoRef):
    record_seen(db_path, ref)
    assert record_seen(db_path, ref) is False


def test_a_different_video_is_still_a_first_sighting(db_path: Path, ref: VideoRef):
    record_seen(db_path, ref)
    assert record_seen(db_path, replace(ref, video_id="other")) is True


def test_unpublished_video_is_not_marked_published(db_path: Path, ref: VideoRef):
    assert already_published(db_path, ref.video_id, "facebook") is False


def test_successful_publish_is_recorded(db_path: Path, ref: VideoRef):
    record_seen(db_path, ref)
    record_publication(db_path, ref.video_id, PublishResult.success("facebook", "fb_1"))
    assert already_published(db_path, ref.video_id, "facebook") is True


def test_failed_publish_does_not_count_as_published(db_path: Path, ref: VideoRef):
    """A failure must stay retryable - otherwise one API blip loses the post."""
    record_seen(db_path, ref)
    record_publication(db_path, ref.video_id, PublishResult.failure("x", "rate limited"))
    assert already_published(db_path, ref.video_id, "x") is False


def test_a_retry_after_failure_overwrites_the_failure(db_path: Path, ref: VideoRef):
    record_seen(db_path, ref)
    record_publication(db_path, ref.video_id, PublishResult.failure("x", "rate limited"))
    record_publication(db_path, ref.video_id, PublishResult.success("x", "tweet_1"))
    assert already_published(db_path, ref.video_id, "x") is True


def test_platforms_are_tracked_independently(db_path: Path, ref: VideoRef):
    record_seen(db_path, ref)
    record_publication(db_path, ref.video_id, PublishResult.success("facebook", "fb_1"))
    assert already_published(db_path, ref.video_id, "instagram") is False


def test_recent_publications_are_newest_first(db_path: Path, ref: VideoRef):
    record_seen(db_path, ref)
    record_publication(db_path, ref.video_id, PublishResult.success("facebook", "fb_1"))
    record_publication(db_path, ref.video_id, PublishResult.success("x", "tweet_1"))
    rows = recent_publications(db_path)
    assert len(rows) == 2
    assert rows[0]["title"] == ref.title


def test_flags_round_trip(db_path: Path):
    assert get_flag(db_path, "publish_enabled", "unset") == "unset"
    set_flag(db_path, "publish_enabled", "false")
    assert get_flag(db_path, "publish_enabled") == "false"
    set_flag(db_path, "publish_enabled", "true")
    assert get_flag(db_path, "publish_enabled") == "true"
