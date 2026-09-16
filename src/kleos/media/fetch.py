"""Fetching source video via yt-dlp.

Kept behind a narrow function so the rest of the pipeline never imports yt-dlp
directly - if the source ever changes, only this module moves.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from yt_dlp import YoutubeDL

from kleos.models import LocalVideo, VideoRef

logger = logging.getLogger(__name__)

# Cap at 1080p MP4. Larger gains nothing on a phone feed and costs upload time.
_FORMAT = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best"


class FetchError(RuntimeError):
    """Raised when the source video could not be retrieved."""


def _download_blocking(ref: VideoRef, work_dir: Path) -> LocalVideo:
    target = work_dir / ref.video_id
    options = {
        "format": _FORMAT,
        "outtmpl": f"{target}.%(ext)s",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
    }
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(ref.watch_url, download=True)
        if info is None:
            raise FetchError(f"yt-dlp returned no metadata for {ref.video_id}")
        path = Path(downloader.prepare_filename(info)).with_suffix(".mp4")

    if not path.exists():
        raise FetchError(f"Expected output missing after download: {path}")

    duration = float(info.get("duration") or 0.0)
    logger.info("Fetched %s (%.0fs, %.1f MB)", ref.video_id, duration, path.stat().st_size / 1e6)
    return LocalVideo(ref=ref, path=path, duration_s=duration)


async def fetch(ref: VideoRef, work_dir: Path) -> LocalVideo:
    """Download a video to work_dir. Runs the blocking yt-dlp call off the loop."""
    work_dir.mkdir(parents=True, exist_ok=True)
    return await asyncio.to_thread(_download_blocking, ref, work_dir)
