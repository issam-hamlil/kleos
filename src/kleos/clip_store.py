"""Persistence for clips held for approval.

Status changes go through transition(), a compare-and-set on the current
status. That is the database-level guard against a clip being approved twice,
or approved after it was rejected or expired: only one UPDATE can match.

Every query is a literal string with ? placeholders. Column lists are written
out rather than interpolated so no SQL is ever assembled at runtime.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from kleos.db import connect
from kleos.models import Clip, ClipStatus, LocalVideo, VideoRef


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _row_to_clip(row: sqlite3.Row) -> Clip:
    ref = VideoRef(
        video_id=row["video_id"],
        channel_id=row["channel_id"],
        title=row["title"],
        published_at=datetime.fromisoformat(row["published_at"]),
    )
    platforms = tuple(name for name in row["platforms"].split(",") if name)
    decided = datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None
    return Clip(
        ref=ref,
        path=Path(row["path"]),
        duration_s=float(row["duration_s"]),
        status=ClipStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        platforms=platforms,
        decided_at=decided,
    )


def insert_pending(db_path: Path, video: LocalVideo, now: datetime | None = None) -> bool:
    """Queue a fetched video for review. False if the clip already exists."""
    ref = video.ref
    with connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO clips"
            " (video_id, channel_id, title, published_at, path, duration_s,"
            "  status, platforms, created_at, decided_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, '')",
            (
                ref.video_id,
                ref.channel_id,
                ref.title,
                _iso(ref.published_at),
                str(video.path),
                video.duration_s,
                ClipStatus.PENDING.value,
                _iso(now or datetime.now(UTC)),
            ),
        )
        return cursor.rowcount == 1


def get(db_path: Path, video_id: str) -> Clip | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT video_id, channel_id, title, published_at, path, duration_s,"
            "       status, platforms, created_at, decided_at"
            " FROM clips WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    return _row_to_clip(row) if row else None


def list_by_status(db_path: Path, status: ClipStatus, limit: int = 100) -> tuple[Clip, ...]:
    """Clips in one state, newest first."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT video_id, channel_id, title, published_at, path, duration_s,"
            "       status, platforms, created_at, decided_at"
            " FROM clips WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status.value, limit),
        ).fetchall()
    return tuple(_row_to_clip(row) for row in rows)


def pending_created_before(db_path: Path, cutoff: datetime) -> tuple[Clip, ...]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT video_id, channel_id, title, published_at, path, duration_s,"
            "       status, platforms, created_at, decided_at"
            " FROM clips WHERE status = ? AND created_at < ?",
            (ClipStatus.PENDING.value, _iso(cutoff)),
        ).fetchall()
    return tuple(_row_to_clip(row) for row in rows)


def transition(
    db_path: Path,
    video_id: str,
    expected: ClipStatus,
    target: ClipStatus,
    platforms: tuple[str, ...] = (),
    now: datetime | None = None,
) -> bool:
    """Move a clip from expected to target. False if it was not in expected."""
    with connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE clips SET status = ?, platforms = ?, decided_at = ?"
            " WHERE video_id = ? AND status = ?",
            (
                target.value,
                ",".join(platforms),
                _iso(now or datetime.now(UTC)),
                video_id,
                expected.value,
            ),
        )
        return cursor.rowcount == 1


def status_counts(db_path: Path) -> dict[str, int]:
    """Clip totals per status, with every status present even when zero."""
    with connect(db_path) as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM clips GROUP BY status").fetchall()
    found = {row["status"]: int(row["n"]) for row in rows}
    return {status.value: found.get(status.value, 0) for status in ClipStatus}


def decided(db_path: Path) -> tuple[Clip, ...]:
    """Clips an operator acted on - the basis for review-time analytics."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT video_id, channel_id, title, published_at, path, duration_s,"
            "       status, platforms, created_at, decided_at"
            " FROM clips WHERE status IN (?, ?)",
            (ClipStatus.APPROVED.value, ClipStatus.REJECTED.value),
        ).fetchall()
    return tuple(_row_to_clip(row) for row in rows)
