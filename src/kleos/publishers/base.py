"""The contract every publisher implements.

Publishers never raise on a failed publish - they return a PublishResult. One
platform being down, rate-limited or rights-blocked must not stop the other two
from being attempted.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from kleos.models import LocalVideo, PublishResult

logger = logging.getLogger(__name__)


@runtime_checkable
class Publisher(Protocol):
    """A destination we can push one video to."""

    @property
    def name(self) -> str:
        """Stable identifier used as the dedupe key, e.g. 'facebook'."""
        ...

    @property
    def enabled(self) -> bool:
        """False when switched off in config or missing credentials."""
        ...

    @property
    def max_duration_s(self) -> int:
        """Hard duration cap. The pipeline trims to this before calling publish."""
        ...

    async def publish(self, video: LocalVideo, caption: str) -> PublishResult:
        """Upload and post. Returns a result; does not raise for API failures."""
        ...


def summarise_error(platform: str, exc: BaseException) -> PublishResult:
    """Turn an unexpected exception into a recorded failure.

    Deliberately truncated: API errors can carry long HTML bodies, and the full
    text is already in the log.
    """
    logger.exception("%s publish raised", platform)
    return PublishResult.failure(platform, f"{type(exc).__name__}: {exc}"[:500])
