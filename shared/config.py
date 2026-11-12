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

    # ERPNext. The admin password is used only to create the integration user and its API key.
    # Every other script signs in with the API key (`make erp-api-keys` writes it to .env).
    erpnext_url: str = "http://localhost:8080"
    erpnext_admin_password: SecretStr | None = None
    erpnext_api_key: SecretStr | None = None
    erpnext_api_secret: SecretStr | None = None

    # Reporting database (Postgres). The pipeline and dbt write as the admin role; dashboards read
    # the marts schema as reporting_reader, which can't see or change anything else.
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "bluefield"
    postgres_user: str = "bluefield_admin"
    postgres_password: SecretStr | None = None
    reporting_reader_password: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Return cached settings. Call get_settings.cache_clear() after changing the environment."""
    return Settings()
