"""The WebSub callback endpoint.

This is the only route the public internet is expected to hit, so it is the one
that has to be careful. Two rules:

1. Every POST body is verified against the shared secret before it is parsed.
   Without that, anyone who discovers the tunnel URL could hand us a forged
   Atom entry and make the app publish a video of their choosing.
2. We acknowledge immediately and do the work in the background. The hub
   retries on slow responses, and a download plus three uploads takes minutes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response

from kleos import websub
from kleos.config import Settings
from kleos.pipeline import Pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/websub", tags=["websub"])


@router.get("/callback")
async def verify_subscription(
    request: Request,
    challenge: str = Query("", alias="hub.challenge"),
    mode: str = Query("", alias="hub.mode"),
    topic: str = Query("", alias="hub.topic"),
) -> Response:
    """Hub verification handshake: echo the challenge back verbatim."""
    if not challenge:
        return Response(status_code=400, content="missing hub.challenge")
    logger.info("WebSub %s verified for %s", mode or "subscribe", topic)
    return Response(status_code=200, content=challenge, media_type="text/plain")


@router.post("/callback")
async def receive_push(request: Request, background: BackgroundTasks) -> Response:
    settings: Settings = request.app.state.settings
    pipeline: Pipeline = request.app.state.pipeline

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature")
    if not websub.verify_signature(settings.websub_secret, body, signature):
        logger.warning("Rejected WebSub push with bad or missing signature")
        return Response(status_code=403, content="invalid signature")

    refs = websub.parse_feed(body)
    for ref in refs:
        logger.info("Push received: %s (%s)", ref.video_id, ref.title[:80])
        background.add_task(pipeline.handle, ref)

    # 204 regardless of content: a deletion notice carries no entries, and
    # telling the hub we failed would only earn us a retry of the same payload.
    return Response(status_code=204)
