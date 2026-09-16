"""Publish a Reel to Instagram via the Content Publishing API.

Instagram is the awkward one. It will not accept a file upload - it takes a
publicly reachable URL and fetches the video itself. That is why the Cloudflare
Tunnel is load-bearing rather than a convenience: it serves the same file to
Meta that it serves the WebSub callback on.

Publishing is three steps: create a container, poll until Meta has finished
downloading and transcoding, then publish the container.

Requires an Instagram Professional (Business or Creator) account linked to the
Facebook Page, and instagram_content_publish on the token.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import httpx

from kleos.config import Settings
from kleos.models import LocalVideo, PublishResult
from kleos.publishers.base import summarise_error

logger = logging.getLogger(__name__)

NAME = "instagram"

# Meta downloads and transcodes asynchronously. Large files genuinely take
# minutes, and publishing before the container is FINISHED fails.
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 600


class InstagramPublisher:
    def __init__(self, settings: Settings, media_url_for: Callable[[LocalVideo], str]) -> None:
        """media_url_for maps a local file to a publicly reachable URL.

        Injected rather than imported so this module stays unaware of how the
        app exposes files, and so tests can hand it a stub.
        """
        self._settings = settings
        self._media_url_for = media_url_for

    @property
    def name(self) -> str:
        return NAME

    @property
    def enabled(self) -> bool:
        return (
            self._settings.instagram_enabled
            and bool(self._settings.instagram_user_id)
            and bool(self._settings.meta_access_token)
        )

    @property
    def max_duration_s(self) -> int:
        return self._settings.instagram_max_duration_s

    def _url(self, path: str) -> str:
        version = self._settings.meta_graph_version
        return f"https://graph.facebook.com/{version}/{self._settings.instagram_user_id}/{path}"

    async def publish(self, video: LocalVideo, caption: str) -> PublishResult:
        try:
            public_url = self._media_url_for(video)
            async with httpx.AsyncClient(timeout=120) as client:
                container_id = await self._create_container(client, public_url, caption)
                if container_id is None:
                    return PublishResult.failure(NAME, "container creation failed")

                ready, detail = await self._await_container(client, container_id)
                if not ready:
                    return PublishResult.failure(NAME, detail)

                return await self._publish_container(client, container_id, video.ref.video_id)
        except Exception as exc:  # noqa: BLE001 - publishers never raise
            return summarise_error(NAME, exc)

    async def _create_container(
        self, client: httpx.AsyncClient, public_url: str, caption: str
    ) -> str | None:
        response = await client.post(
            self._url("media"),
            data={
                "media_type": "REELS",
                "video_url": public_url,
                "caption": caption,
                "access_token": self._settings.meta_access_token,
            },
        )
        payload = response.json()
        if response.status_code != 200 or "id" not in payload:
            logger.error(
                "Instagram container creation failed: %s",
                payload.get("error", {}).get("message", response.text[:300]),
            )
            return None
        return str(payload["id"])

    async def _await_container(
        self, client: httpx.AsyncClient, container_id: str
    ) -> tuple[bool, str]:
        """Poll the container until Meta reports it ready, or we give up."""
        version = self._settings.meta_graph_version
        status_url = f"https://graph.facebook.com/{version}/{container_id}"
        deadline = asyncio.get_running_loop().time() + POLL_TIMEOUT_S

        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(POLL_INTERVAL_S)
            response = await client.get(
                status_url,
                params={
                    "fields": "status_code,status",
                    "access_token": self._settings.meta_access_token,
                },
            )
            payload = response.json()
            status = payload.get("status_code", "")
            if status == "FINISHED":
                return True, ""
            if status == "ERROR":
                detail = str(payload.get("status", "container processing error"))[:300]
                logger.error("Instagram container %s errored: %s", container_id, detail)
                return False, detail

        return False, f"container not ready after {POLL_TIMEOUT_S}s"

    async def _publish_container(
        self, client: httpx.AsyncClient, container_id: str, video_id: str
    ) -> PublishResult:
        response = await client.post(
            self._url("media_publish"),
            data={
                "creation_id": container_id,
                "access_token": self._settings.meta_access_token,
            },
        )
        payload = response.json()
        if response.status_code != 200 or "id" not in payload:
            message = payload.get("error", {}).get("message", response.text[:300])
            logger.error("Instagram publish failed for %s: %s", video_id, message)
            return PublishResult.failure(NAME, message)

        logger.info("Published %s to Instagram as %s", video_id, payload["id"])
        return PublishResult.success(NAME, str(payload["id"]))
