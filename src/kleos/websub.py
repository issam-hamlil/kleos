"""YouTube push notifications over WebSub (PubSubHubbub).

YouTube publishes an Atom feed per channel and runs a hub that POSTs to us
within seconds of an upload. Subscriptions are leased, so they must be renewed
on a timer - see scheduler.py.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime

import httpx
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from kleos.models import VideoRef

logger = logging.getLogger(__name__)

HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"
TOPIC_TEMPLATE = "https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}"
LEASE_SECONDS = 432000  # 5 days - the longest lease the hub reliably honours.

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}


def topic_for(channel_id: str) -> str:
    return TOPIC_TEMPLATE.format(channel_id=channel_id)


async def subscribe(channel_id: str, callback_url: str, secret: str) -> bool:
    """Ask the hub to start (or renew) pushing this channel to us."""
    payload = {
        "hub.callback": callback_url,
        "hub.topic": topic_for(channel_id),
        "hub.verify": "async",
        "hub.mode": "subscribe",
        "hub.secret": secret,
        "hub.lease_seconds": str(LEASE_SECONDS),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(HUB_URL, data=payload)
    except httpx.HTTPError as exc:
        logger.error("WebSub subscribe failed for %s: %s", channel_id, exc)
        return False

    if response.status_code not in (202, 204):
        logger.error(
            "WebSub subscribe rejected for %s: %s %s",
            channel_id,
            response.status_code,
            response.text[:200],
        )
        return False
    logger.info("WebSub subscribe accepted for %s", channel_id)
    return True


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Check the hub's X-Hub-Signature against our shared secret.

    Without this the callback is an open endpoint: anyone who learns the tunnel
    URL could POST a forged Atom entry and make the app publish whatever they
    point it at. Compared in constant time.
    """
    if not header or "=" not in header:
        return False
    algorithm, _, provided = header.partition("=")
    digest_factory = getattr(hashlib, algorithm.lower().strip(), None)
    if digest_factory is None:
        logger.warning("Unknown X-Hub-Signature algorithm: %s", algorithm)
        return False
    expected = hmac.new(secret.encode(), body, digest_factory).hexdigest()
    return hmac.compare_digest(expected, provided.strip())


def parse_feed(body: bytes) -> tuple[VideoRef, ...]:
    """Extract video references from an Atom payload.

    Deletion notifications carry a deleted-entry element and no entry, so they
    parse to an empty tuple and the caller simply does nothing.
    """
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, DefusedXmlException) as exc:
        # DefusedXmlException covers entity-expansion and external-entity
        # attacks. The signature check upstream should mean we never see one,
        # but a parser is the wrong place to rely on that.
        logger.warning("Rejected WebSub payload: %s", exc)
        return ()

    refs: list[VideoRef] = []
    for entry in root.findall("atom:entry", _NS):
        video_id = entry.findtext("yt:videoId", default="", namespaces=_NS)
        channel_id = entry.findtext("yt:channelId", default="", namespaces=_NS)
        title = entry.findtext("atom:title", default="", namespaces=_NS) or ""
        published = entry.findtext("atom:published", default="", namespaces=_NS)
        if not video_id or not published:
            continue
        try:
            published_at = datetime.fromisoformat(published)
        except ValueError:
            logger.warning("Bad published timestamp on %s: %r", video_id, published)
            continue
        refs.append(
            VideoRef(
                video_id=video_id,
                channel_id=channel_id,
                title=title.strip(),
                published_at=published_at,
            )
        )
    return tuple(refs)


async def fetch_channel_feed(channel_id: str) -> tuple[VideoRef, ...]:
    """Pull a channel's Atom feed directly. Used by the catch-up poller."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(topic_for(channel_id))
    except httpx.HTTPError as exc:
        logger.error("Feed fetch failed for %s: %s", channel_id, exc)
        return ()

    if response.status_code != 200:
        logger.error("Feed fetch failed for %s: HTTP %s", channel_id, response.status_code)
        return ()
    return parse_feed(response.content)
