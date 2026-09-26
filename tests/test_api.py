"""The mobile API.

This router is reachable from the internet, so the first half of this file is
about one question: can anything get through without the token? The second half
covers the review flow the Android app drives.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kleos.web import api
from tests.fakes import (
    API_TOKEN,
    RecordingPublisher,
    approval_settings,
    build_pipeline,
    make_ref,
    stub_fetch,
)

AUTH = {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.fixture
def settings(tmp_path: Path):
    return approval_settings(tmp_path)


@pytest.fixture
def publishers():
    return (RecordingPublisher("facebook"), RecordingPublisher("x"))


@pytest.fixture
def pipeline(settings, publishers, monkeypatch: pytest.MonkeyPatch):
    stub_fetch(monkeypatch)
    return build_pipeline(settings, *publishers)


@pytest.fixture
def client(settings, pipeline) -> TestClient:
    app = FastAPI()
    app.state.settings = settings
    app.state.pipeline = pipeline
    api.install(app)
    return TestClient(app)


async def _queue(pipeline, video_id: str = "vid1") -> None:
    await pipeline.handle(make_ref(video_id))


# --- auth boundary -----------------------------------------------------------

ROUTES = [
    ("get", "/api/pending"),
    ("get", "/api/platforms"),
    ("get", "/api/analytics"),
    ("get", "/api/history"),
    ("get", "/api/clips/vid1"),
    ("get", "/api/clips/vid1/stream"),
    ("post", "/api/clips/vid1/approve"),
    ("post", "/api/clips/vid1/reject"),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_route_refuses_a_missing_token(client: TestClient, method: str, path: str):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json() == {"success": False, "data": None, "error": "invalid or missing token"}


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_route_refuses_a_wrong_token(client: TestClient, method: str, path: str):
    response = getattr(client, method)(path, headers={"Authorization": "Bearer " + "x" * 32})
    assert response.status_code == 401


@pytest.mark.parametrize("header", [API_TOKEN, f"Basic {API_TOKEN}", f"Bearer {API_TOKEN}x"])
def test_malformed_authorization_headers_are_refused(client: TestClient, header: str):
    assert client.get("/api/pending", headers={"Authorization": header}).status_code == 401


def test_an_unset_token_disables_the_api_entirely(client: TestClient, settings):
    """Fail closed: forgetting to configure auth must not leave the API open."""
    settings.kleos_api_token = ""
    response = client.get("/api/pending", headers={"Authorization": "Bearer "})
    assert response.status_code == 503


def test_a_too_short_token_disables_the_api(client: TestClient, settings):
    settings.kleos_api_token = "short"
    response = client.get("/api/pending", headers={"Authorization": "Bearer short"})
    assert response.status_code == 503


def test_a_401_tells_the_client_how_to_authenticate(client: TestClient):
    assert client.get("/api/pending").headers["www-authenticate"] == "Bearer"


# --- review flow -------------------------------------------------------------


def test_platforms_lists_only_enabled_publishers(client: TestClient):
    body = client.get("/api/platforms", headers=AUTH).json()
    assert body["success"] is True
    assert [p["name"] for p in body["data"]] == ["facebook", "x"]


async def test_pending_lists_queued_clips_with_expiry(client: TestClient, pipeline):
    await _queue(pipeline)
    body = client.get("/api/pending", headers=AUTH).json()
    [clip] = body["data"]
    assert clip["video_id"] == "vid1"
    assert clip["status"] == "pending"
    assert clip["expires_at"] > clip["created_at"]
    assert clip["watch_url"] == "https://www.youtube.com/watch?v=vid1"


def test_pending_is_empty_when_nothing_is_queued(client: TestClient):
    assert client.get("/api/pending", headers=AUTH).json()["data"] == []


async def test_clip_detail_returns_the_clip(client: TestClient, pipeline):
    await _queue(pipeline)
    assert client.get("/api/clips/vid1", headers=AUTH).json()["data"]["title"] == "Highlights"


def test_clip_detail_404s_for_an_unknown_clip(client: TestClient):
    response = client.get("/api/clips/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_stream_serves_the_pending_clip(client: TestClient, pipeline):
    await _queue(pipeline)
    response = client.get("/api/clips/vid1/stream", headers=AUTH)
    assert response.status_code == 200
    assert response.content == b"fake video"
    assert response.headers["content-type"] == "video/mp4"


async def test_stream_supports_range_requests_for_seeking(client: TestClient, pipeline):
    await _queue(pipeline)
    response = client.get("/api/clips/vid1/stream", headers={**AUTH, "Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"fake"


async def test_stream_is_gone_once_the_clip_is_decided(client: TestClient, pipeline):
    await _queue(pipeline)
    await pipeline.reject("vid1")
    assert client.get("/api/clips/vid1/stream", headers=AUTH).status_code == 404


@pytest.mark.parametrize("bad_id", ["..%2F..%2Fetc", "a b", "x" * 65])
def test_malformed_video_ids_are_refused(client: TestClient, bad_id: str):
    response = client.get(f"/api/clips/{bad_id}/stream", headers=AUTH)
    assert response.status_code in (404, 422)


async def test_approve_publishes_to_the_chosen_platforms(client: TestClient, pipeline, publishers):
    await _queue(pipeline)
    response = client.post(
        "/api/clips/vid1/approve", json={"platforms": ["facebook"]}, headers=AUTH
    )
    assert response.status_code == 200
    results = response.json()["data"]["results"]
    assert results == [{"platform": "facebook", "ok": True, "remote_id": "facebook_1", "error": ""}]
    assert publishers[1].published == []


async def test_a_second_approve_is_a_conflict(client: TestClient, pipeline):
    await _queue(pipeline)
    client.post("/api/clips/vid1/approve", json={"platforms": ["facebook"]}, headers=AUTH)
    response = client.post(
        "/api/clips/vid1/approve", json={"platforms": ["facebook"]}, headers=AUTH
    )
    assert response.status_code == 409


async def test_approve_rejects_an_unknown_platform(client: TestClient, pipeline):
    await _queue(pipeline)
    response = client.post("/api/clips/vid1/approve", json={"platforms": ["tiktok"]}, headers=AUTH)
    assert response.status_code == 400
    assert "tiktok" in response.json()["error"]


async def test_approve_requires_at_least_one_platform(client: TestClient, pipeline):
    await _queue(pipeline)
    response = client.post("/api/clips/vid1/approve", json={"platforms": []}, headers=AUTH)
    assert response.status_code == 422
    assert response.json() == {"success": False, "data": None, "error": "invalid request"}


async def test_approve_is_locked_while_the_kill_switch_is_on(client: TestClient, pipeline):
    await _queue(pipeline)
    pipeline.set_publish_enabled(False)
    response = client.post(
        "/api/clips/vid1/approve", json={"platforms": ["facebook"]}, headers=AUTH
    )
    assert response.status_code == 423


async def test_reject_removes_the_clip_from_the_queue(client: TestClient, pipeline):
    await _queue(pipeline)
    response = client.post("/api/clips/vid1/reject", headers=AUTH)
    assert response.json()["data"] == {"video_id": "vid1", "status": "rejected"}
    assert client.get("/api/pending", headers=AUTH).json()["data"] == []


def test_rejecting_an_unknown_clip_is_a_conflict(client: TestClient):
    assert client.post("/api/clips/nope/reject", headers=AUTH).status_code == 409


def test_analytics_is_empty_before_any_activity(client: TestClient):
    data = client.get("/api/analytics", headers=AUTH).json()["data"]
    assert data["clips"] == {"pending": 0, "approved": 0, "rejected": 0, "expired": 0}
    assert data["approval_rate"] is None
    assert data["avg_review_minutes"] is None
    assert data["platforms"] == {}
    assert data["publishing_enabled"] is True


async def test_analytics_reflects_decisions_and_publish_outcomes(client: TestClient, pipeline):
    await _queue(pipeline, "vid1")
    await _queue(pipeline, "vid2")
    await _queue(pipeline, "vid3")
    await pipeline.approve("vid1", ["facebook", "x"])
    await pipeline.reject("vid2")
    data = client.get("/api/analytics", headers=AUTH).json()["data"]
    assert data["clips"] == {"pending": 1, "approved": 1, "rejected": 1, "expired": 0}
    assert data["approval_rate"] == 0.5
    assert data["avg_review_minutes"] >= 0
    assert data["platforms"] == {
        "facebook": {"published": 1, "failed": 0},
        "x": {"published": 1, "failed": 0},
    }


async def test_history_lists_publications_with_titles(client: TestClient, pipeline):
    await _queue(pipeline)
    await pipeline.approve("vid1", ["x"])
    [entry] = client.get("/api/history", headers=AUTH).json()["data"]
    assert entry["platform"] == "x"
    assert entry["ok"] is True


def test_history_limit_is_bounded(client: TestClient):
    assert client.get("/api/history?limit=10000", headers=AUTH).status_code == 422


def test_non_api_errors_keep_the_default_shape():
    """The envelope applies to /api only; the dashboard and hooks are unaffected."""
    app = FastAPI()
    api.install(app)
    response = TestClient(app).get("/not-a-route")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
