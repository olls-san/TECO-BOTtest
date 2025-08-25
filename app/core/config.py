"""
core/config.py
----------------

Application configuration module.

Defines strongly‑typed settings loaded from the environment using
``pydantic-settings``. These settings control timeouts, retry counts
and pagination limits for HTTP operations. Having a central place for
configuration makes it easier to adjust behaviour without touching the
business logic. The values provided here are sensible defaults but can
be overridden via environment variables at deployment time.
"""

from __future__ import annotations

from functools import lru_cache
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    The settings structure is flat and uses environment variables
    prefixed with ``APP_``.  For example, to override the default
    request timeout you can set ``APP_HTTP_TIMEOUT=15``.

    See :class:`pydantic_settings.BaseSettings` for details on how
    environment variables are mapped onto fields.
    """

    # HTTP client settings
    http_timeout: float = Field(10.0, description="Hard timeout for HTTP requests in seconds.")
    http_max_retries: int = Field(3, ge=0, description="Maximum number of retries for idempotent operations (GET).")
    http_backoff_factor: float = Field(0.5, description="Backoff factor for exponential retry delays.")

    # Pagination guards
    max_pages: int = Field(50, ge=1, description="Maximum number of pages to request when paginating.")
    max_items: int = Field(1000, ge=1, description="Maximum number of items to retrieve during pagination.")

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=None, case_sensitive=False)


@lru_cache()
def get_settings() -> Settings:
    """Return a cached instance of the application settings.

    Using a cache prevents expensive environment parsing on every call.
    The returned object is immutable and safe to share across threads.
    """
    return Settings()