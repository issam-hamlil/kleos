"""Background timers: subscription renewal and the catch-up poller.

Two jobs, for two different failure modes.

Renewal exists because WebSub leases expire - miss a renewal and the pushes stop
silently, which is the worst kind of outage.

Catch-up exists because this runs on a desktop that may sleep. Pushes that
arrive while the machine is down are gone for good, so on startup and on a
timer we reconcile against each channel's feed. The staleness cutoff in the
pipeline stops that reconciliation from posting anything old.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from kleos import websub
from kleos.config import Settings
from kleos.pipeline import Pipeline

logger = logging.getLogger(__name__)

RENEWAL_HOURS = 24
CATCH_UP_MINUTES = 15


def callback_url(settings: Settings) -> str:
    return f"{settings.public_base_url}/websub/callback"


async def renew_subscriptions(settings: Settings) -> None:
    """Re-subscribe every channel. The hub treats this as idempotent."""
    if not settings.channel_ids:
        logger.warning("No YOUTUBE_CHANNEL_IDS configured - nothing to subscribe to")
        return

    url = callback_url(settings)
    results = await asyncio.gather(
        *(
            websub.subscribe(channel_id, url, settings.websub_secret)
            for channel_id in settings.channel_ids
        )
    )
    logger.info("Renewed %s/%s WebSub subscriptions", sum(results), len(results))


async def catch_up(settings: Settings, pipeline: Pipeline) -> None:
    """Reconcile against channel feeds for anything the push missed."""
    for channel_id in settings.channel_ids:
        for ref in await websub.fetch_channel_feed(channel_id):
            if pipeline.is_stale(ref):
                continue
            try:
                await pipeline.handle(ref)
            except Exception:  # noqa: BLE001 - one bad video must not kill the timer
                logger.exception("Catch-up failed for %s", ref.video_id)


def start_scheduler(settings: Settings, pipeline: Pipeline) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        renew_subscriptions,
        "interval",
        hours=RENEWAL_HOURS,
        args=[settings],
        id="renew_subscriptions",
        max_instances=1,
    )
    scheduler.add_job(
        catch_up,
        "interval",
        minutes=CATCH_UP_MINUTES,
        args=[settings, pipeline],
        id="catch_up",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started: renewal every %sh, catch-up every %sm",
        RENEWAL_HOURS,
        CATCH_UP_MINUTES,
    )
    return scheduler
