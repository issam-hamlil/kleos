"""Application entry point and wiring.

Run with:  uvicorn kleos.main:app --host 127.0.0.1 --port 8000

Everything is constructed once at startup and hung off app.state, so routes
reach their dependencies through the request rather than importing globals.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from kleos import db, scheduler
from kleos.config import Settings, get_settings
from kleos.media.registry import MediaRegistry
from kleos.media.trim import FFmpegError, require_ffmpeg
from kleos.models import LocalVideo
from kleos.pipeline import Pipeline
from kleos.publishers.base import Publisher
from kleos.publishers.facebook import FacebookPublisher
from kleos.publishers.instagram import InstagramPublisher
from kleos.publishers.x import XPublisher
from kleos.web import hooks, routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("kleos")


def build_publishers(settings: Settings, registry: MediaRegistry) -> tuple[Publisher, ...]:
    """Construct the publishers.

    Instagram needs a way to turn a local file into a public URL; it gets the
    registry's register method rather than the registry itself, so it cannot
    reach anything else.
    """

    def media_url_for(video: LocalVideo) -> str:
        return registry.register(video.path)

    return (
        FacebookPublisher(settings),
        InstagramPublisher(settings, media_url_for),
        XPublisher(settings),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    db.init_db(settings.db_path)

    try:
        require_ffmpeg()
    except FFmpegError as exc:
        # Not fatal: the status page should still come up so you can see why.
        logger.error("%s", exc)

    missing = settings.missing_credentials()
    if missing:
        logger.warning("Missing credentials: %s", ", ".join(missing))
    if not settings.channel_ids:
        logger.warning("No channels configured - set YOUTUBE_CHANNEL_IDS")

    registry = MediaRegistry(settings.public_base_url)
    publishers = build_publishers(settings, registry)
    pipeline = Pipeline(settings, registry, publishers)

    app.state.settings = settings
    app.state.registry = registry
    app.state.publishers = publishers
    app.state.pipeline = pipeline

    await scheduler.renew_subscriptions(settings)
    await scheduler.catch_up(settings, pipeline)
    running = scheduler.start_scheduler(settings, pipeline)

    logger.info("Kleos ready on %s", settings.public_base_url)
    try:
        yield
    finally:
        running.shutdown(wait=False)


app = FastAPI(title="Kleos", lifespan=lifespan)
app.include_router(hooks.router)
app.include_router(routes.router)
