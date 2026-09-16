"""The operator surface.

The media route gets the most attention: it is deliberately unauthenticated so
Meta's fetchers can reach it, which makes token scoping the only thing standing
between it and the work directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kleos import db
from kleos.config import Settings
from kleos.media.registry import MediaRegistry
from kleos.models import PublishResult, VideoRef
from kleos.pipeline import Pipeline
from kleos.web import routes


class StubPublisher:
    def __init__(self, name: str, enabled: bool, cap: int) -> None:
        self.name, self.enabled, self.max_duration_s = name, enabled, cap

    async def publish(self, video, caption):  # pragma: no cover - never called here
        raise AssertionError("not used")


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
def registry(settings: Settings) -> MediaRegistry:
    return MediaRegistry(settings.public_base_url)


@pytest.fixture
def client(settings: Settings, registry: MediaRegistry) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    app.state.settings = settings
    app.state.registry = registry
    app.state.publishers = (
        StubPublisher("facebook", True, 7200),
        StubPublisher("x", False, 140),
    )
    app.state.pipeline = Pipeline(settings, registry, ())
    return TestClient(app)


def test_health_endpoint_reports_ok(client: TestClient):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_dashboard_renders_with_no_history(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "Nothing published yet" in response.text


def test_dashboard_lists_publications(client: TestClient, settings: Settings):
    from datetime import UTC, datetime

    ref = VideoRef("vid1", "UC_one", "Team A 3-1 Team B", datetime.now(UTC))
    db.record_seen(settings.db_path, ref)
    db.record_publication(settings.db_path, "vid1", PublishResult.success("facebook", "fb_1"))
    response = client.get("/")
    assert "Team A 3-1 Team B" in response.text
    assert "fb_1" in response.text


def test_dashboard_shows_a_failure_reason(client: TestClient, settings: Settings):
    from datetime import UTC, datetime

    ref = VideoRef("vid1", "UC_one", "Highlights", datetime.now(UTC))
    db.record_seen(settings.db_path, ref)
    db.record_publication(settings.db_path, "vid1", PublishResult.failure("x", "rate limited"))
    assert "rate limited" in client.get("/").text


def test_dashboard_shows_disabled_platforms(client: TestClient):
    assert "x · 140s · off" in client.get("/").text


def test_kill_switch_toggles_off_then_on(client: TestClient):
    assert "ENABLED" in client.get("/").text

    client.post("/kill-switch", follow_redirects=False)
    assert "DISABLED" in client.get("/").text

    client.post("/kill-switch", follow_redirects=False)
    assert "ENABLED" in client.get("/").text


def test_kill_switch_redirects_back_to_the_dashboard(client: TestClient):
    response = client.post("/kill-switch", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_a_registered_file_is_served(client: TestClient, registry: MediaRegistry, settings):
    path = settings.work_dir / "clip.mp4"
    path.write_bytes(b"video-bytes")
    token = registry.register(path).rsplit("/", 1)[-1].removesuffix(".mp4")

    response = client.get(f"/media/{token}.mp4")
    assert response.status_code == 200
    assert response.content == b"video-bytes"
    assert response.headers["content-type"] == "video/mp4"


def test_an_unregistered_token_is_not_served(client: TestClient):
    assert client.get("/media/madeuptoken.mp4").status_code == 404


def test_a_revoked_token_stops_being_served(
    client: TestClient, registry: MediaRegistry, settings: Settings
):
    path = settings.work_dir / "clip.mp4"
    path.write_bytes(b"video-bytes")
    token = registry.register(path).rsplit("/", 1)[-1].removesuffix(".mp4")
    registry.revoke_path(path)
    assert client.get(f"/media/{token}.mp4").status_code == 404


@pytest.mark.parametrize("attempt", ["../../../etc/passwd", "..%2f..%2fsecret", "clip"])
def test_path_traversal_attempts_are_not_served(client: TestClient, attempt: str):
    """Paths come from the registry, never from the request."""
    assert client.get(f"/media/{attempt}.mp4").status_code == 404
