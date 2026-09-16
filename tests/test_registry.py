"""Media registry.

This is what makes local files reachable by Meta's fetchers, so the important
properties are that tokens are unguessable, scoped, and expire.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from kleos.media.registry import MediaRegistry


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"not really video")
    return path


def test_registering_returns_a_url_on_the_public_origin(video: Path):
    registry = MediaRegistry("https://test.example.com")
    url = registry.register(video)
    assert url.startswith("https://test.example.com/media/")
    assert url.endswith(".mp4")


def test_a_trailing_slash_on_the_base_url_is_normalised(video: Path):
    registry = MediaRegistry("https://test.example.com/")
    assert "//media/" not in registry.register(video)


def test_a_registered_token_resolves_back_to_the_file(video: Path):
    registry = MediaRegistry("https://test.example.com")
    token = registry.register(video).rsplit("/", 1)[-1].removesuffix(".mp4")
    assert registry.resolve(token) == video


def test_an_unknown_token_resolves_to_nothing(video: Path):
    registry = MediaRegistry("https://test.example.com")
    registry.register(video)
    assert registry.resolve("not-a-real-token") is None


def test_each_registration_gets_a_distinct_token(video: Path):
    registry = MediaRegistry("https://test.example.com")
    assert registry.register(video) != registry.register(video)


def test_tokens_are_long_enough_to_be_unguessable(video: Path):
    registry = MediaRegistry("https://test.example.com")
    token = registry.register(video).rsplit("/", 1)[-1].removesuffix(".mp4")
    assert len(token) >= 32


def test_an_expired_token_stops_resolving(video: Path):
    registry = MediaRegistry("https://test.example.com", ttl_s=0)
    token = registry.register(video).rsplit("/", 1)[-1].removesuffix(".mp4")
    time.sleep(0.01)
    assert registry.resolve(token) is None


def test_a_token_for_a_deleted_file_resolves_to_nothing(video: Path):
    registry = MediaRegistry("https://test.example.com")
    token = registry.register(video).rsplit("/", 1)[-1].removesuffix(".mp4")
    video.unlink()
    assert registry.resolve(token) is None


def test_revoking_a_path_invalidates_every_token_for_it(video: Path):
    """Cleanup must close the public window, not just delete the file."""
    registry = MediaRegistry("https://test.example.com")
    tokens = [registry.register(video).rsplit("/", 1)[-1].removesuffix(".mp4") for _ in range(3)]
    registry.revoke_path(video)
    assert all(registry.resolve(token) is None for token in tokens)
