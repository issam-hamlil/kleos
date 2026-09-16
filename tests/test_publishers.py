"""Publisher behaviour against mocked platform APIs.

The contract being tested is the one the pipeline depends on: a publisher
reports failure, it does not raise. A platform being down, rate-limited or
rights-blocked must leave the other two unaffected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from kleos.config import Settings
from kleos.models import LocalVideo, VideoRef
from kleos.publishers.facebook import FacebookPublisher
from kleos.publishers.instagram import InstagramPublisher
from kleos.publishers.x import XPublisher

GRAPH = "https://graph.facebook.com/v21.0"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("META_ACCESS_TOKEN", "token123")
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "page123")
    monkeypatch.setenv("INSTAGRAM_USER_ID", "ig123")
    monkeypatch.setenv("X_API_KEY", "k")
    monkeypatch.setenv("X_API_SECRET", "s")
    monkeypatch.setenv("X_ACCESS_TOKEN", "t")
    monkeypatch.setenv("X_ACCESS_TOKEN_SECRET", "ts")
    return Settings()  # type: ignore[call-arg]


@pytest.fixture
def video(tmp_path: Path) -> LocalVideo:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake video bytes")
    ref = VideoRef(
        video_id="vid1",
        channel_id="UC_one",
        title="Highlights",
        published_at=datetime.now(UTC),
    )
    return LocalVideo(ref=ref, path=path, duration_s=120.0)


# --- Facebook --------------------------------------------------------------


@respx.mock
async def test_facebook_reports_success_with_the_post_id(settings: Settings, video: LocalVideo):
    respx.post(f"{GRAPH}/page123/videos").mock(
        return_value=httpx.Response(200, json={"id": "fb_post_1"})
    )
    result = await FacebookPublisher(settings).publish(video, "caption")
    assert result.ok is True
    assert result.remote_id == "fb_post_1"
    assert result.platform == "facebook"


@respx.mock
async def test_facebook_reports_an_api_error_without_raising(settings: Settings, video: LocalVideo):
    respx.post(f"{GRAPH}/page123/videos").mock(
        return_value=httpx.Response(400, json={"error": {"message": "Copyright match"}})
    )
    result = await FacebookPublisher(settings).publish(video, "caption")
    assert result.ok is False
    assert "Copyright match" in result.error


@respx.mock
async def test_facebook_survives_a_network_failure(settings: Settings, video: LocalVideo):
    respx.post(f"{GRAPH}/page123/videos").mock(side_effect=httpx.ConnectError("down"))
    result = await FacebookPublisher(settings).publish(video, "caption")
    assert result.ok is False
    assert result.platform == "facebook"


def test_facebook_is_disabled_without_a_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FACEBOOK_PAGE_ID", "page123")
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    assert FacebookPublisher(Settings()).enabled is False  # type: ignore[call-arg]


def test_facebook_is_disabled_when_switched_off(settings: Settings, monkeypatch):
    monkeypatch.setenv("FACEBOOK_ENABLED", "false")
    assert FacebookPublisher(Settings()).enabled is False  # type: ignore[call-arg]


# --- Instagram -------------------------------------------------------------


def _instagram(settings: Settings) -> InstagramPublisher:
    return InstagramPublisher(
        settings, lambda video: f"https://test.example.com/media/{video.ref.video_id}.mp4"
    )


@respx.mock
async def test_instagram_creates_polls_then_publishes(settings: Settings, video: LocalVideo):
    respx.post(f"{GRAPH}/ig123/media").mock(
        return_value=httpx.Response(200, json={"id": "container_1"})
    )
    respx.get(f"{GRAPH}/container_1").mock(
        return_value=httpx.Response(200, json={"status_code": "FINISHED"})
    )
    respx.post(f"{GRAPH}/ig123/media_publish").mock(
        return_value=httpx.Response(200, json={"id": "ig_post_1"})
    )
    result = await _instagram(settings).publish(video, "caption")
    assert result.ok is True
    assert result.remote_id == "ig_post_1"


@respx.mock
async def test_instagram_reports_a_container_error(settings: Settings, video: LocalVideo):
    """Meta reports rights blocks at the container stage, not at creation."""
    respx.post(f"{GRAPH}/ig123/media").mock(
        return_value=httpx.Response(200, json={"id": "container_1"})
    )
    respx.get(f"{GRAPH}/container_1").mock(
        return_value=httpx.Response(200, json={"status_code": "ERROR", "status": "rights block"})
    )
    result = await _instagram(settings).publish(video, "caption")
    assert result.ok is False
    assert "rights block" in result.error


@respx.mock
async def test_instagram_reports_a_rejected_container(settings: Settings, video: LocalVideo):
    respx.post(f"{GRAPH}/ig123/media").mock(
        return_value=httpx.Response(400, json={"error": {"message": "bad url"}})
    )
    result = await _instagram(settings).publish(video, "caption")
    assert result.ok is False
    assert result.error == "container creation failed"


def test_instagram_is_disabled_without_a_user_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("META_ACCESS_TOKEN", "token123")
    monkeypatch.delenv("INSTAGRAM_USER_ID", raising=False)
    assert _instagram(Settings()).enabled is False  # type: ignore[call-arg]


# --- X ---------------------------------------------------------------------


def test_x_is_enabled_with_all_four_credentials(settings: Settings):
    assert XPublisher(settings).enabled is True


def test_x_is_disabled_when_any_credential_is_missing(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("X_ACCESS_TOKEN_SECRET", raising=False)
    assert XPublisher(Settings()).enabled is False  # type: ignore[call-arg]


async def test_x_reports_failure_instead_of_raising(
    settings: Settings, video: LocalVideo, monkeypatch: pytest.MonkeyPatch
):
    publisher = XPublisher(settings)
    monkeypatch.setattr(
        publisher, "_publish_blocking", lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    result = await publisher.publish(video, "caption")
    assert result.ok is False
    assert "boom" in result.error


async def test_x_truncates_captions_to_the_tweet_limit(
    settings: Settings, video: LocalVideo, monkeypatch: pytest.MonkeyPatch
):
    captured: list[str] = []
    publisher = XPublisher(settings)

    def fake(path, text):
        captured.append(text)
        from kleos.models import PublishResult

        return PublishResult.success("x", "1")

    monkeypatch.setattr(publisher, "_publish_blocking", fake)
    await publisher.publish(video, "x" * 400)
    assert len(captured[0]) == 280


@pytest.mark.parametrize("cap_env,expected", [("140", 140), ("600", 600)])
def test_x_duration_cap_comes_from_config(
    monkeypatch: pytest.MonkeyPatch, cap_env: str, expected: int
):
    monkeypatch.setenv("X_MAX_DURATION_S", cap_env)
    assert XPublisher(Settings()).max_duration_s == expected  # type: ignore[call-arg]
