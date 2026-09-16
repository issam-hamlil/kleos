"""Application configuration, loaded from environment or .env.

Every secret arrives through here. Nothing is hardcoded, and required values are
validated at import time so the app fails loudly at startup rather than silently
at the first publish attempt.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    public_base_url: str
    websub_secret: str
    youtube_channel_ids: str = ""

    staleness_minutes: int = 180
    publish_enabled: bool = True
    caption_suffix: str = ""

    data_dir: Path = PROJECT_ROOT / "data"
    work_dir: Path = PROJECT_ROOT / "work"

    meta_access_token: str = ""
    meta_graph_version: str = "v21.0"

    facebook_enabled: bool = True
    facebook_page_id: str = ""
    facebook_max_duration_s: int = 7200

    instagram_enabled: bool = True
    instagram_user_id: str = ""
    instagram_max_duration_s: int = 900

    x_enabled: bool = True
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""
    x_max_duration_s: int = 140

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def channel_ids(self) -> tuple[str, ...]:
        """Channel IDs as an immutable tuple, blanks discarded."""
        return tuple(c.strip() for c in self.youtube_channel_ids.split(",") if c.strip())

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kleos.db"

    def missing_credentials(self) -> tuple[str, ...]:
        """Names of credentials required by the platforms that are switched on.

        Returned rather than raised: a missing X token should not stop Facebook
        from publishing, so the caller decides how severe this is.
        """
        missing: list[str] = []
        needs_meta = self.facebook_enabled or self.instagram_enabled
        if needs_meta and not self.meta_access_token:
            missing.append("META_ACCESS_TOKEN")
        if self.facebook_enabled and not self.facebook_page_id:
            missing.append("FACEBOOK_PAGE_ID")
        if self.instagram_enabled and not self.instagram_user_id:
            missing.append("INSTAGRAM_USER_ID")
        if self.x_enabled:
            for name, value in (
                ("X_API_KEY", self.x_api_key),
                ("X_API_SECRET", self.x_api_secret),
                ("X_ACCESS_TOKEN", self.x_access_token),
                ("X_ACCESS_TOKEN_SECRET", self.x_access_token_secret),
            ):
                if not value:
                    missing.append(name)
        return tuple(missing)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[call-arg]
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    return settings
