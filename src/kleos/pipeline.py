"""The orchestrator: one YouTube upload in, three published posts out.

Ordering matters here. Fetch happens once and is shared; trimming happens
per-platform because each has a different cap; publishing is sequential so a
rate-limit on one platform does not cascade into the others.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kleos import db
from kleos.config import Settings
from kleos.media import fetch, trim
from kleos.media.registry import MediaRegistry
from kleos.models import LocalVideo, PublishResult, VideoRef
from kleos.publishers.base import Publisher

logger = logging.getLogger(__name__)

KILL_SWITCH_KEY = "publish_enabled"


def build_caption(ref: VideoRef, suffix: str) -> str:
    """Caption is the original title plus a fixed suffix. No generation."""
    parts = [ref.title.strip(), suffix.strip()]
    return "\n\n".join(part for part in parts if part)


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        registry: MediaRegistry,
        publishers: tuple[Publisher, ...],
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._publishers = publishers
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def publish_enabled(self) -> bool:
        """Runtime kill switch, overridable from the UI without a restart."""
        stored = db.get_flag(self._settings.db_path, KILL_SWITCH_KEY)
        if stored:
            return stored == "true"
        return self._settings.publish_enabled

    def set_publish_enabled(self, enabled: bool) -> None:
        db.set_flag(self._settings.db_path, KILL_SWITCH_KEY, "true" if enabled else "false")

    def is_stale(self, ref: VideoRef, now: datetime | None = None) -> bool:
        """True if this upload is too old to be worth posting.

        Guards the catch-up poller: after the PC has been off overnight we want
        it to skip yesterday's highlights rather than flood the accounts.
        """
        cutoff = timedelta(minutes=self._settings.staleness_minutes)
        return (now or datetime.now(UTC)) - ref.published_at > cutoff

    async def handle(self, ref: VideoRef) -> tuple[PublishResult, ...]:
        """Process one video end to end. Never raises."""
        async with self._locks[ref.video_id]:
            return await self._handle_locked(ref)

    async def _handle_locked(self, ref: VideoRef) -> tuple[PublishResult, ...]:
        db.record_seen(self._settings.db_path, ref)

        if self.is_stale(ref):
            logger.info("Skipping %s - older than staleness cutoff", ref.video_id)
            return ()

        targets = self._pending_targets(ref.video_id)
        if not targets:
            logger.debug("Nothing to do for %s - already published everywhere", ref.video_id)
            return ()

        if not self.publish_enabled():
            logger.warning("Kill switch is on - not publishing %s", ref.video_id)
            return ()

        try:
            video = await fetch.fetch(ref, self._settings.work_dir)
        except Exception as exc:  # noqa: BLE001 - a fetch failure is per-video, not fatal
            logger.exception("Fetch failed for %s", ref.video_id)
            # yt-dlp leaves .part files and per-format fragments behind when a
            # download dies partway. Nothing else will ever clean them up.
            self._purge_work_files(ref.video_id)
            results = tuple(
                PublishResult.failure(target.name, f"fetch failed: {exc}"[:300])
                for target in targets
            )
            self._record_all(ref.video_id, results)
            return results

        try:
            return await self._publish_all(ref, video, targets)
        finally:
            self._purge_work_files(ref.video_id)

    def _pending_targets(self, video_id: str) -> tuple[Publisher, ...]:
        return tuple(
            publisher
            for publisher in self._publishers
            if publisher.enabled
            and not db.already_published(self._settings.db_path, video_id, publisher.name)
        )

    async def _publish_all(
        self,
        ref: VideoRef,
        video: LocalVideo,
        targets: tuple[Publisher, ...],
    ) -> tuple[PublishResult, ...]:
        caption = build_caption(ref, self._settings.caption_suffix)
        results: list[PublishResult] = []

        for publisher in targets:
            try:
                payload = await trim.trim_to(video, publisher.max_duration_s)
            except Exception as exc:  # noqa: BLE001 - one bad trim must not stop the rest
                logger.exception("Trim failed for %s on %s", ref.video_id, publisher.name)
                results.append(PublishResult.failure(publisher.name, f"trim failed: {exc}"[:300]))
                continue

            # Note: the file is NOT registered for public serving here. Only
            # Instagram needs a public URL, and it asks for one itself. Doing it
            # for every platform would expose files to the internet that nothing
            # is ever going to fetch.
            result = await publisher.publish(payload, caption)
            results.append(result)

        frozen = tuple(results)
        self._record_all(ref.video_id, frozen)
        return frozen

    def _record_all(self, video_id: str, results: tuple[PublishResult, ...]) -> None:
        for result in results:
            db.record_publication(self._settings.db_path, video_id, result)

    def _purge_work_files(self, prefix: str) -> None:
        """Remove the source, every trim derived from it, and any partial files.

        Source video is the bulk of disk use and none of it is worth keeping, so
        it goes as soon as the last platform is done with it. Tokens are revoked
        before the file is unlinked, so the public window closes first.

        The per-video lock is deliberately NOT evicted here. Dropping it while
        still holding it lets a later arrival create a fresh lock for the same
        video and run concurrently with a task already queued on the old one -
        both would read _pending_targets before either recorded a publication,
        and the video would be posted twice.
        """
        for path in sorted(self._settings.work_dir.glob(f"{prefix}*")):
            self._registry.revoke_path(path)
            self._unlink(path)

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)
