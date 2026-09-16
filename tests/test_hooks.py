"""The WebSub callback endpoint.

This is the only route the public internet reaches, so these tests are really
about one question: can an unsigned request make the app publish something?
"""

from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kleos.config import Settings
from kleos.models import VideoRef
from kleos.web import hooks

SECRET = "test-secret"

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>VIDEO_ONE</yt:videoId>
    <yt:channelId>UC_one</yt:channelId>
    <title>Highlights</title>
    <published>2026-09-12T18:30:00+00:00</published>
  </entry>
</feed>"""


class SpyPipeline:
    def __init__(self) -> None:
        self.handled: list[VideoRef] = []

    async def handle(self, ref: VideoRef) -> tuple[()]:
        self.handled.append(ref)
        return ()


@pytest.fixture
def spy() -> SpyPipeline:
    return SpyPipeline()


@pytest.fixture
def client(spy: SpyPipeline) -> TestClient:
    app = FastAPI()
    app.include_router(hooks.router)
    app.state.settings = Settings()  # type: ignore[call-arg]
    app.state.pipeline = spy
    return TestClient(app)


def _sign(body: bytes, secret: str = SECRET) -> dict[str, str]:
    return {"X-Hub-Signature": "sha1=" + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()}


def test_verification_echoes_the_challenge(client: TestClient):
    response = client.get(
        "/websub/callback",
        params={"hub.challenge": "abc123", "hub.mode": "subscribe", "hub.topic": "t"},
    )
    assert response.status_code == 200
    assert response.text == "abc123"


def test_verification_without_a_challenge_is_rejected(client: TestClient):
    assert client.get("/websub/callback").status_code == 400


def test_a_correctly_signed_push_is_accepted(client: TestClient, spy: SpyPipeline):
    response = client.post("/websub/callback", content=FEED, headers=_sign(FEED))
    assert response.status_code == 204
    assert [ref.video_id for ref in spy.handled] == ["VIDEO_ONE"]


def test_an_unsigned_push_is_refused_and_publishes_nothing(client: TestClient, spy: SpyPipeline):
    response = client.post("/websub/callback", content=FEED)
    assert response.status_code == 403
    assert spy.handled == []


def test_a_wrongly_signed_push_is_refused_and_publishes_nothing(
    client: TestClient, spy: SpyPipeline
):
    response = client.post("/websub/callback", content=FEED, headers=_sign(FEED, "attacker-secret"))
    assert response.status_code == 403
    assert spy.handled == []


def test_a_tampered_body_is_refused(client: TestClient, spy: SpyPipeline):
    """Signature is over the body, so altered content must not validate."""
    headers = _sign(FEED)
    response = client.post("/websub/callback", content=FEED + b"<!--x-->", headers=headers)
    assert response.status_code == 403
    assert spy.handled == []


def test_a_signed_deletion_notice_is_acknowledged_and_ignored(client: TestClient, spy: SpyPipeline):
    body = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    response = client.post("/websub/callback", content=body, headers=_sign(body))
    assert response.status_code == 204
    assert spy.handled == []
