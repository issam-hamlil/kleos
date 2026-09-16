"""Publish to X.

Two distinct APIs are involved: chunked media upload (INIT / APPEND / FINALIZE,
OAuth 1.0a user context), then the v2 tweet endpoint referencing the media id.
Video is processed asynchronously after FINALIZE, so STATUS must be polled
before the tweet will accept the media.

VERIFY BEFORE RELYING ON THIS: video upload support and monthly write caps on
X's free tier have moved between tiers repeatedly. Run scripts/check_x_video.py
against a short test clip before wiring this into the pipeline - it is the
cheapest way to find out whether the X half of this product exists.

Non-Premium accounts are capped near 140s of video, which is why
X_MAX_DURATION_S defaults low and the pipeline trims before calling publish.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from requests_oauthlib import OAuth1Session

from kleos.config import Settings
from kleos.models import LocalVideo, PublishResult
from kleos.publishers.base import summarise_error

logger = logging.getLogger(__name__)

NAME = "x"

UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
TWEET_URL = "https://api.x.com/2/tweets"
CHUNK_BYTES = 4 * 1024 * 1024
POLL_TIMEOUT_S = 300
TWEET_MAX_CHARS = 280


class XPublisher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def name(self) -> str:
        return NAME

    @property
    def enabled(self) -> bool:
        settings = self._settings
        return settings.x_enabled and all(
            (
                settings.x_api_key,
                settings.x_api_secret,
                settings.x_access_token,
                settings.x_access_token_secret,
            )
        )

    @property
    def max_duration_s(self) -> int:
        return self._settings.x_max_duration_s

    def _session(self) -> OAuth1Session:
        return OAuth1Session(
            self._settings.x_api_key,
            client_secret=self._settings.x_api_secret,
            resource_owner_key=self._settings.x_access_token,
            resource_owner_secret=self._settings.x_access_token_secret,
        )

    async def publish(self, video: LocalVideo, caption: str) -> PublishResult:
        try:
            text = caption[:TWEET_MAX_CHARS]
            return await asyncio.to_thread(self._publish_blocking, video.path, text)
        except Exception as exc:  # noqa: BLE001 - publishers never raise
            return summarise_error(NAME, exc)

    def _publish_blocking(self, path: Path, text: str) -> PublishResult:
        session = self._session()
        media_id = self._upload_media(session, path)
        if media_id is None:
            return PublishResult.failure(NAME, "media upload failed")

        if not self._await_processing(session, media_id):
            return PublishResult.failure(NAME, "media processing failed or timed out")

        response = session.post(
            TWEET_URL,
            json={"text": text, "media": {"media_ids": [media_id]}},
            timeout=60,
        )
        if response.status_code not in (200, 201):
            logger.error("X tweet rejected: %s %s", response.status_code, response.text[:300])
            return PublishResult.failure(NAME, response.text[:300])

        tweet_id = str(response.json().get("data", {}).get("id", ""))
        logger.info("Published to X as %s", tweet_id)
        return PublishResult.success(NAME, tweet_id)

    def _upload_media(self, session: OAuth1Session, path: Path) -> str | None:
        total_bytes = path.stat().st_size
        init = session.post(
            UPLOAD_URL,
            data={
                "command": "INIT",
                "total_bytes": str(total_bytes),
                "media_type": "video/mp4",
                "media_category": "tweet_video",
            },
            timeout=60,
        )
        if init.status_code not in (200, 201, 202):
            logger.error("X INIT failed: %s %s", init.status_code, init.text[:300])
            return None
        media_id = str(init.json()["media_id_string"])

        with path.open("rb") as handle:
            for index in range(0, (total_bytes + CHUNK_BYTES - 1) // CHUNK_BYTES):
                chunk = handle.read(CHUNK_BYTES)
                append = session.post(
                    UPLOAD_URL,
                    data={
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": str(index),
                    },
                    files={"media": chunk},
                    timeout=180,
                )
                if append.status_code not in (200, 201, 204):
                    logger.error(
                        "X APPEND segment %s failed: %s %s",
                        index,
                        append.status_code,
                        append.text[:200],
                    )
                    return None

        finalize = session.post(
            UPLOAD_URL,
            data={"command": "FINALIZE", "media_id": media_id},
            timeout=60,
        )
        if finalize.status_code not in (200, 201):
            logger.error("X FINALIZE failed: %s %s", finalize.status_code, finalize.text[:300])
            return None
        return media_id

    def _await_processing(self, session: OAuth1Session, media_id: str) -> bool:
        """Poll STATUS until X reports the video ready.

        X tells us how long to wait between checks; honour it rather than
        guessing, since polling too eagerly is itself rate-limited.
        """
        waited = 0
        while waited < POLL_TIMEOUT_S:
            status = session.get(
                UPLOAD_URL,
                params={"command": "STATUS", "media_id": media_id},
                timeout=60,
            )
            if status.status_code != 200:
                logger.error("X STATUS failed: %s %s", status.status_code, status.text[:200])
                return False

            info = status.json().get("processing_info")
            if info is None:
                return True

            state = info.get("state")
            if state == "succeeded":
                return True
            if state == "failed":
                logger.error("X media processing failed: %s", info.get("error"))
                return False

            delay = int(info.get("check_after_secs", 5))
            time.sleep(delay)
            waited += delay

        logger.error("X media %s still processing after %ss", media_id, POLL_TIMEOUT_S)
        return False
