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
    #
    # Provider fields name TRANSPORTS, not model families (architecture
    # amendment: provider vs. model adapter vs. model identity).
    # google_ai_studio and vertex_ai both serve Gemini models and may share
    # one adapter; this Literal is duplicated (not imported) from
    # atlas.reasoning.llm.base.LLMProvider deliberately — config is a
    # foundational module and must not depend on a domain subsystem package.
    # Keep the two literals' values in sync by hand.
    llm_provider: Literal["anthropic", "google_ai_studio", "vertex_ai", "ollama", "omniroute"] = Field(
        default="anthropic",
        description="Default transport for both the reasoning and judge roles.",
    )
    reasoning_provider: Literal["anthropic", "google_ai_studio", "vertex_ai", "ollama", "omniroute"] | None = Field(
        default=None,
        description="Transport override for the reasoning role; falls back to llm_provider.",
    )
    judge_provider: Literal["anthropic", "google_ai_studio", "vertex_ai", "ollama", "omniroute"] | None = Field(
        default=None,
        description=(
            "Transport override for the judge role; falls back to llm_provider. "
            "Independent of reasoning_provider so judge and reasoning can run on "
            "genuinely different implementations (blueprint §12.6, amendment 1)."
        ),
    )

    anthropic_api_key: str | None = Field(
        default=None,
        description=(
            "API key for the anthropic transport. Optional so non-reasoning "
            "commands run without it; the 'ask' command fails clearly when absent."
        ),
    )
    gemini_api_key: str | None = Field(
        default=None,
        description=(
            "API key for the google_ai_studio transport. Optional so non-Gemini "
            "commands run without it; building a Gemini client fails clearly "
            "when absent."
        ),
    )
    vertex_project: str | None = Field(
        default=None,
        description=(
            "GCP project id for the vertex_ai transport. Config surface only — "
            "the Gemini adapter is designed but not yet implemented."
        ),
    )
    vertex_region: str | None = Field(
        default=None,
        description=(
            "GCP region for the vertex_ai transport. Config surface only — "
            "the Gemini adapter is designed but not yet implemented."
        ),
    )

    # The ollama transport is local and keyless: the host URL is its
    # connection config (no API key), and its model identity is its own
    # setting rather than reasoning_model/judge_model — local Ollama tags
    # (e.g. "llama3.2") are a distinct namespace from cloud model ids.
    ollama_host: str = Field(
        default="http://localhost:11434",
        description="Base URL of the Ollama server for the ollama transport.",
    )
    ollama_model: str | None = Field(
        default=None,
        description=(
            "Model tag for the ollama transport (e.g. 'qwen3:8b'). No default: "
            "the right local model is task- and machine-specific, so building "
            "the ollama client fails clearly when it's unset rather than "
            "defaulting to a tag the user may not have pulled. Distinct from "
            "reasoning_model/judge_model, which name cloud model ids."
        ),
    )

    # The omniroute transport is a cloud-style aggregator gateway: connection
    # config only, no model namespace of its own. Its model identity is the
    # shared reasoning_model/judge_model (a free-form string that, for this
    # transport, holds an OmniRoute model/combo name like "test_cc") — the same
    # way the anthropic transport reads reasoning_model. Contrast ollama, whose
    # local tags are a genuinely distinct namespace and so carry ollama_model.
    omniroute_base_url: str = Field(
        default="http://localhost:20128",
        description="Base URL of the OmniRoute gateway for the omniroute transport.",
    )
    omniroute_api_key: str | None = Field(
        default=None,
        description="API key for the omniroute transport. Optional so local development doesn't require it.",
    )

    reasoning_model: str = Field(
        default="claude-sonnet-5",
        description="Model id used by the reasoning subsystem.",
    )
    judge_model: str = Field(
        default="claude-sonnet-5",
        description=(
            "Model id used by the evaluation judge. Pinned separately from "
            "reasoning_model so upgrading the system under test never changes "
            "the measuring instrument (blueprint §12.6, amendment 1)."
        ),
    )

    llm_max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Max output tokens for LLM completions.",
    )
    llm_temperature: float = Field(
        default=0.0,
        ge=0,
        description="Sampling temperature for LLM completions (determinism floor; G7).",
    )
