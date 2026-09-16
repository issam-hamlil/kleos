"""Subscription renewal and the catch-up poller.

Both exist for failure modes rather than features: leases expire silently, and a
desktop sleeps. The behaviour worth pinning down is that neither one can post
something stale.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from kleos import db, scheduler, websub
from kleos.config import Settings
from kleos.media.registry import MediaRegistry
from kleos.models import VideoRef
from kleos.pipeline import Pipeline

HUB = "https://pubsubhubbub.appspot.com/subscribe"
FEED_URL = "https://www.youtube.com/xml/feeds/videos.xml"


def _feed(video_id: str, published: datetime) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <yt:videoId>{video_id}</yt:videoId>
    <yt:channelId>UC_one</yt:channelId>
    <title>Highlights</title>
    <published>{published.isoformat()}</published>
  </entry>
</feed>""".encode()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    built = Settings()  # type: ignore[call-arg]
    built.data_dir = tmp_path / "data"
    built.work_dir = tmp_path / "work"
    built.data_dir.mkdir(parents=True)
    built.work_dir.mkdir(parents=True)
    db.init_db(built.db_path)
    return built


class SpyPipeline(Pipeline):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, MediaRegistry(settings.public_base_url), ())
        self.handled: list[VideoRef] = []

    async def handle(self, ref: VideoRef):
        self.handled.append(ref)
        return ()


# --- subscribing -----------------------------------------------------------


@respx.mock
async def test_subscribe_accepts_a_202(settings: Settings):
    route = respx.post(HUB).mock(return_value=httpx.Response(202))
    assert await websub.subscribe("UC_one", "https://cb.example.com", "secret") is True
    assert route.called


@respx.mock
async def test_subscribe_sends_the_secret_and_topic(settings: Settings):
    route = respx.post(HUB).mock(return_value=httpx.Response(202))
    await websub.subscribe("UC_one", "https://cb.example.com", "secret")
    body = route.calls[0].request.content.decode()
    assert "hub.secret=secret" in body
    assert "UC_one" in body


@respx.mock
async def test_subscribe_reports_a_rejection(settings: Settings):
    respx.post(HUB).mock(return_value=httpx.Response(400, text="nope"))
    assert await websub.subscribe("UC_one", "https://cb.example.com", "secret") is False


@respx.mock
async def test_subscribe_survives_a_network_error(settings: Settings):
    respx.post(HUB).mock(side_effect=httpx.ConnectError("down"))
    assert await websub.subscribe("UC_one", "https://cb.example.com", "secret") is False


@respx.mock
async def test_renewal_subscribes_every_configured_channel(settings: Settings):
    route = respx.post(HUB).mock(return_value=httpx.Response(202))
    await scheduler.renew_subscriptions(settings)
    assert route.call_count == len(settings.channel_ids) == 2


def test_callback_url_is_built_from_the_public_origin(settings: Settings):
    assert scheduler.callback_url(settings) == "https://test.example.com/websub/callback"


# --- fetching feeds --------------------------------------------------------


@respx.mock
async def test_fetch_channel_feed_parses_entries():
    respx.get(url__startswith=FEED_URL).mock(
        return_value=httpx.Response(200, content=_feed("VID_1", datetime.now(UTC)))
    )
    refs = await websub.fetch_channel_feed("UC_one")
    assert [r.video_id for r in refs] == ["VID_1"]


@respx.mock
async def test_fetch_channel_feed_returns_empty_on_http_error():
    respx.get(url__startswith=FEED_URL).mock(return_value=httpx.Response(404))
    assert await websub.fetch_channel_feed("UC_one") == ()


@respx.mock
async def test_fetch_channel_feed_returns_empty_on_network_error():
    respx.get(url__startswith=FEED_URL).mock(side_effect=httpx.ConnectError("down"))
    assert await websub.fetch_channel_feed("UC_one") == ()


# --- catch-up --------------------------------------------------------------


@respx.mock
async def test_catch_up_handles_a_fresh_video(settings: Settings):
    respx.get(url__startswith=FEED_URL).mock(
        return_value=httpx.Response(200, content=_feed("VID_1", datetime.now(UTC)))
    )
    spy = SpyPipeline(settings)
    await scheduler.catch_up(settings, spy)
    assert [r.video_id for r in spy.handled] == ["VID_1", "VID_1"]  # one per channel


@respx.mock
async def test_catch_up_ignores_stale_videos(settings: Settings):
    """After the PC has been off overnight, yesterday's highlights stay unposted."""
    old = datetime.now(UTC) - timedelta(days=1)
    respx.get(url__startswith=FEED_URL).mock(
        return_value=httpx.Response(200, content=_feed("VID_OLD", old))
    )
    spy = SpyPipeline(settings)
    await scheduler.catch_up(settings, spy)
    assert spy.handled == []


@respx.mock
async def test_catch_up_continues_after_one_video_fails(settings: Settings):
    respx.get(url__startswith=FEED_URL).mock(
        return_value=httpx.Response(200, content=_feed("VID_1", datetime.now(UTC)))
    )

    class Exploding(SpyPipeline):
        async def handle(self, ref: VideoRef):
            self.handled.append(ref)
            raise RuntimeError("boom")

    spy = Exploding(settings)
    await scheduler.catch_up(settings, spy)  # must not raise
    assert len(spy.handled) == 2


async def test_scheduler_registers_both_jobs(settings: Settings):
    spy = SpyPipeline(settings)
    running = scheduler.start_scheduler(settings, spy)
    try:
        assert {job.id for job in running.get_jobs()} == {"renew_subscriptions", "catch_up"}
    finally:
        running.shutdown(wait=False)
