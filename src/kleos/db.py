"""SQLite persistence: what we have seen, and what we have already published.

Deliberately thin. The only state worth keeping is a dedupe ledger - if the
database is lost, the staleness cutoff stops the app reposting old history.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from kleos.models import PublishResult, VideoRef

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id      TEXT PRIMARY KEY,
    channel_id    TEXT NOT NULL,
    title         TEXT NOT NULL,
    published_at  TEXT NOT NULL,
    seen_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publications (
    video_id   TEXT NOT NULL,
    platform   TEXT NOT NULL,
    ok         INTEGER NOT NULL,
    remote_id  TEXT NOT NULL DEFAULT '',
    error      TEXT NOT NULL DEFAULT '',
    at         TEXT NOT NULL,
    PRIMARY KEY (video_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_publications_at ON publications(at DESC);

CREATE TABLE IF NOT EXISTS flags (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def record_seen(db_path: Path, ref: VideoRef) -> bool:
    """Register a video. True if this is the first time we have seen it.

    This is the concurrency guard: the hub sends duplicate pushes for the same
    upload, and they race on the primary key so that only one wins.
    """
    with connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO videos (video_id, channel_id, title, published_at, seen_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (ref.video_id, ref.channel_id, ref.title, ref.published_at.isoformat(), _now()),
        )
        return cursor.rowcount == 1


def already_published(db_path: Path, video_id: str, platform: str) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT ok FROM publications WHERE video_id = ? AND platform = ?",
            (video_id, platform),
        ).fetchone()
    return bool(row and row["ok"])


def record_publication(db_path: Path, video_id: str, result: PublishResult) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO publications (video_id, platform, ok, remote_id, error, at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(video_id, platform) DO UPDATE SET"
            "   ok=excluded.ok, remote_id=excluded.remote_id,"
            "   error=excluded.error, at=excluded.at",
            (video_id, result.platform, int(result.ok), result.remote_id, result.error, _now()),
        )


def recent_publications(db_path: Path, limit: int = 50) -> tuple[sqlite3.Row, ...]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT p.video_id, p.platform, p.ok, p.remote_id, p.error, p.at,"
            "       v.title, v.channel_id"
            " FROM publications p"
            " LEFT JOIN videos v ON v.video_id = p.video_id"
            " ORDER BY p.at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return tuple(rows)


def get_flag(db_path: Path, key: str, default: str = "") -> str:
    with connect(db_path) as conn:
        row = conn.execute("SELECT value FROM flags WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_flag(db_path: Path, key: str, value: str) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO flags (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
