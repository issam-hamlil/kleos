"""Trim decisions.

The FFmpeg invocation itself is not mocked - what matters here is the decision
made before it: a video that already fits must not be touched at all, since
rewriting it would cost time and gain nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from kleos.media import trim
from kleos.media.trim import FFmpegError, require_ffmpeg, trim_to
from kleos.models import LocalVideo, VideoRef


def _video(tmp_path: Path, duration_s: float) -> LocalVideo:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake")
    ref = VideoRef(
        video_id="vid1",
        channel_id="UC_one",
        title="Highlights",
        published_at=datetime.now(UTC),
    )
    return LocalVideo(ref=ref, path=path, duration_s=duration_s)


async def test_a_video_under_the_cap_is_returned_untouched(tmp_path: Path):
    video = _video(tmp_path, duration_s=100.0)
    assert await trim_to(video, 140) is video


async def test_a_video_exactly_at_the_cap_is_returned_untouched(tmp_path: Path):
    video = _video(tmp_path, duration_s=140.0)
    assert await trim_to(video, 140) is video


async def test_an_oversized_video_triggers_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    captured: list[tuple[str, ...]] = []

    async def fake_run(*args: str):
        captured.append(args)
        # Create the file ffmpeg would have produced.
        Path(args[-1]).write_bytes(b"trimmed")
        return 0, b"", b""

    async def fake_probe(path: Path) -> float:
        return 138.0

    monkeypatch.setattr(trim, "_run", fake_run)
    monkeypatch.setattr(trim, "probe_duration", fake_probe)

    video = _video(tmp_path, duration_s=300.0)
    result = await trim_to(video, 140)

    assert result is not video
    assert result.duration_s == 138.0
    assert "-c" in captured[0] and "copy" in captured[0], "must use stream copy, not re-encode"


async def test_the_trim_target_stays_inside_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Keyframe cuts land on a boundary, so aim under the limit, never over."""
    captured: list[tuple[str, ...]] = []

    async def fake_run(*args: str):
        captured.append(args)
        Path(args[-1]).write_bytes(b"trimmed")
        return 0, b"", b""

    monkeypatch.setattr(trim, "_run", fake_run)
    monkeypatch.setattr(trim, "probe_duration", lambda path: _async(138.0))

    await trim_to(_video(tmp_path, duration_s=300.0), 140)

    target = float(captured[0][captured[0].index("-t") + 1])
    assert target < 140


async def test_a_failing_ffmpeg_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    async def fake_run(*args: str):
        return 1, b"", b"codec not supported"

    monkeypatch.setattr(trim, "_run", fake_run)
    with pytest.raises(FFmpegError, match="trim failed"):
        await trim_to(_video(tmp_path, duration_s=300.0), 140)


def test_require_ffmpeg_passes_when_binaries_are_present(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(trim.shutil, "which", lambda name: f"/usr/bin/{name}")
    require_ffmpeg()


def test_require_ffmpeg_raises_when_a_binary_is_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(trim.shutil, "which", lambda name: None)
    with pytest.raises(FFmpegError, match="ffmpeg not found"):
        require_ffmpeg()


async def _async(value: float) -> float:
    return value
