"""Publish to a Facebook Page via the Graph API.

Facebook is the most forgiving of the three: it accepts a direct file upload and
allows long videos, so no trim is normally needed.

Requires pages_manage_posts and pages_read_engagement on a Page access token.
While the Meta app is in Development Mode this works without App Review for any
user holding a role on the app - which, for a single-operator tool, is you.
"""

from __future__ import annotations

import logging

import httpx

from kleos.config import Settings
from kleos.models import LocalVideo, PublishResult
from kleos.publishers.base import summarise_error

logger = logging.getLogger(__name__)

NAME = "facebook"
UPLOAD_TIMEOUT_S = 600


class FacebookPublisher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return NAME

    @property
    def enabled(self) -> bool:
        return (
            self._settings.facebook_enabled
            and bool(self._settings.facebook_page_id)
            and bool(self._settings.meta_access_token)
        )

    @property
    def max_duration_s(self) -> int:
        return self._settings.facebook_max_duration_s

    @property
    def _endpoint(self) -> str:
        version = self._settings.meta_graph_version
        return f"https://graph.facebook.com/{version}/{self._settings.facebook_page_id}/videos"

    async def publish(self, video: LocalVideo, caption: str) -> PublishResult:
        try:
            with video.path.open("rb") as handle:
                files = {"source": (video.path.name, handle, "video/mp4")}
                data = {
                    "description": caption,
                    "access_token": self._settings.meta_access_token,
                }
                async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT_S) as client:
                    response = await client.post(self._endpoint, data=data, files=files)

            payload = response.json()
            if response.status_code != 200 or "id" not in payload:
                message = payload.get("error", {}).get("message", response.text[:300])
                logger.error("Facebook rejected %s: %s", video.ref.video_id, message)
                return PublishResult.failure(NAME, message)

            logger.info("Published %s to Facebook as %s", video.ref.video_id, payload["id"])
            return PublishResult.success(NAME, str(payload["id"]))
        except Exception as exc:  # noqa: BLE001 - publishers never raise
            return summarise_error(NAME, exc)
