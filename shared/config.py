"""Application settings read from environment variables (and an optional .env file).

Secrets and AI model names are never hardcoded. They come from the environment only.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings shared by every project in the portfolio."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["dev", "test", "demo"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # AI settings: no defaults on purpose, so a model name never lives in code.
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Return cached settings. Call get_settings.cache_clear() after changing the environment."""
    return Settings()
