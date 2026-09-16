from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kleos.models import VideoRef


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings read the environment, so every test gets an isolated one."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://test.example.com")
    monkeypatch.setenv("WEBSUB_SECRET", "test-secret")
    monkeypatch.setenv("YOUTUBE_CHANNEL_IDS", "UC_one, UC_two")
    os.environ.pop("META_ACCESS_TOKEN", None)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    from kleos.db import init_db

    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def ref() -> VideoRef:
    return VideoRef(
        video_id="abc123",
        channel_id="UC_one",
        title="Match Highlights",
        published_at=datetime.now(UTC),
    )
