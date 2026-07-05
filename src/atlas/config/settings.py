from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration.

    All values are read from environment variables prefixed with ATLAS_.
    A .env file is loaded automatically if present.
    Environment variables take precedence over .env file values.
    """

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    environment: Literal["development", "production"] = Field(
        default="development",
        description="Runtime environment.",
    )

    # --- Repository ---
    repository_base_path: Path = Field(
        default=Path("repositories"),
        description="Base directory for company repositories.",
    )

    # --- Logging (consumed by F-T3) ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="DEBUG",
        description="Minimum log level.",
    )
    log_file_path: Path = Field(
        default=Path("logs/atlas.log"),
        description="Path for the structured log file.",
    )

    # --- HTTP client (consumed by F-T4) ---
    http_timeout_seconds: int = Field(
        default=30,
        gt=0,
        description="Request timeout in seconds.",
    )
    http_max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum number of retry attempts.",
    )
    http_rate_limit_rps: float = Field(
        default=2.0,
        gt=0,
        description="Maximum requests per second per domain.",
    )

    # --- Reasoning / LLM (consumed by the reasoning subsystem, M0+) ---
    anthropic_api_key: str | None = Field(
        default=None,
        description=(
            "API key for the Anthropic reasoning client. Optional so non-reasoning "
            "commands run without it; the 'ask' command fails clearly when absent."
        ),
    )
    reasoning_model: str = Field(
        default="claude-sonnet-5",
        description="Model id used by the reasoning subsystem.",
    )
