"""Duration probing and trimming via FFmpeg.

Trims use stream copy (-c copy), so a cut costs roughly a second regardless of
video length: nothing is re-encoded and no quality is lost. The tradeoff is that
FFmpeg can only cut at a keyframe, so the result may be a second or two under
the requested limit. That is the correct tradeoff for a hard platform cap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from kleos.models import LocalVideo

logger = logging.getLogger(__name__)

# Trim slightly inside the limit: keyframe cuts land on a boundary, and
# platforms reject a video that is even fractionally over.
SAFETY_MARGIN_S = 2.0


class FFmpegError(RuntimeError):
    """Raised when FFmpeg or FFprobe is unavailable or fails."""


def require_ffmpeg() -> None:
    """Fail at startup rather than at the first publish."""
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise FFmpegError(f"{binary} not found on PATH - install FFmpeg and restart")


async def _run(*args: str) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return process.returncode or 0, stdout, stderr


async def probe_duration(path: Path) -> float:
    """Read a file's duration in seconds."""
    code, stdout, stderr = await _run(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    )
    if code != 0:
        raise FFmpegError(f"ffprobe failed on {path.name}: {stderr.decode(errors='replace')[:200]}")
    try:
        return float(json.loads(stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise FFmpegError(f"Could not read duration from ffprobe output: {exc}") from exc


async def trim_to(video: LocalVideo, max_duration_s: int) -> LocalVideo:
    """Return a copy of the video no longer than max_duration_s.

    If it already fits, the original is returned untouched - no file is written
    and no work is done.
    """
    if video.duration_s <= max_duration_s:
        return video

    target_s = max(1.0, max_duration_s - SAFETY_MARGIN_S)
    output = video.path.with_name(f"{video.path.stem}.{max_duration_s}s.mp4")

    code, _, stderr = await _run(
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        "0",
        "-i",
        str(video.path),
        "-t",
        f"{target_s:.2f}",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    )
    if code != 0 or not output.exists():
        raise FFmpegError(f"ffmpeg trim failed: {stderr.decode(errors='replace')[:300]}")

    actual = await probe_duration(output)
    if actual > max_duration_s:
        # Stream copy cuts on keyframes, so a long GOP can overshoot the target
        # even with the safety margin. Worth knowing about: the platform will
        # reject the upload, and the fix is a larger SAFETY_MARGIN_S.
        logger.warning(
            "Trim of %s overshot the cap: %.1fs > %ss - platform will likely reject it",
            video.ref.video_id,
            actual,
            max_duration_s,
        )
    logger.info(
        "Trimmed %s from %.0fs to %.0fs (cap %ss)",
        video.ref.video_id,
        video.duration_s,
        actual,
        max_duration_s,
    )
    return video.with_path(output, actual)
