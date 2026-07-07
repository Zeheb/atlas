"""Reasoning-related Settings fields (M0, commit 1).

The reasoning subsystem reads its Anthropic credentials and model id from the
same ATLAS_-prefixed Settings every other subsystem uses. These tests pin the
two guarantees M0 relies on:

  * the API key is *optional* — Settings() must construct without it, so that
    every non-reasoning command keeps working when no key is configured; and
  * both fields are overridable via the ATLAS_ environment prefix.
"""
from __future__ import annotations

from atlas.config.settings import Settings


def test_api_key_defaults_to_none_so_other_commands_still_construct() -> None:
    settings = Settings(_env_file=None)
    assert settings.anthropic_api_key is None


def test_reasoning_model_has_a_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.reasoning_model  # non-empty default


def test_fields_read_from_atlas_env_prefix(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test-123")
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "claude-test-model")
    settings = Settings(_env_file=None)
    assert settings.anthropic_api_key == "sk-test-123"
    assert settings.reasoning_model == "claude-test-model"


def test_judge_model_pinned_separately_from_reasoning_model(monkeypatch) -> None:
    # §12.6 amendment 1: upgrading the reasoning model must not move the judge.
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "claude-new-upgrade")
    settings = Settings(_env_file=None)
    assert settings.judge_model == "claude-sonnet-5"  # unchanged default
    monkeypatch.setenv("ATLAS_JUDGE_MODEL", "claude-judge-pin")
    assert Settings(_env_file=None).judge_model == "claude-judge-pin"


# --- Provider (transport) fields: provider vs. model adapter vs. model identity ---
def test_llm_provider_defaults_to_anthropic() -> None:
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "anthropic"


def test_reasoning_and_judge_provider_default_to_none_meaning_fall_back() -> None:
    settings = Settings(_env_file=None)
    assert settings.reasoning_provider is None
    assert settings.judge_provider is None


def test_provider_overrides_are_independent_like_judge_model(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_LLM_PROVIDER", "vertex_ai")
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "vertex_ai"
    assert settings.reasoning_provider is None  # still falls back, not auto-set
    monkeypatch.setenv("ATLAS_JUDGE_PROVIDER", "google_ai_studio")
    settings = Settings(_env_file=None)
    assert settings.judge_provider == "google_ai_studio"
    assert settings.reasoning_provider is None  # independent of judge_provider


def test_new_credential_and_transport_fields_default_to_none() -> None:
    settings = Settings(_env_file=None)
    assert settings.gemini_api_key is None
    assert settings.vertex_project is None
    assert settings.vertex_region is None


# --- ollama transport: local, keyless, its own model identity ----------------
def test_ollama_host_has_a_local_default_but_model_does_not() -> None:
    settings = Settings(_env_file=None)
    assert settings.ollama_host == "http://localhost:11434"
    # No default model on purpose: the right local model is machine-specific,
    # so it's required config rather than a tag the user may not have pulled.
    assert settings.ollama_model is None


def test_ollama_host_and_model_are_overridable(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_OLLAMA_HOST", "http://gpu-box:11434")
    monkeypatch.setenv("ATLAS_OLLAMA_MODEL", "qwen2.5:14b")
    settings = Settings(_env_file=None)
    assert settings.ollama_host == "http://gpu-box:11434"
    assert settings.ollama_model == "qwen2.5:14b"


def test_ollama_is_a_valid_provider_value(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_LLM_PROVIDER", "ollama")
    assert Settings(_env_file=None).llm_provider == "ollama"


def test_llm_max_tokens_and_temperature_defaults_match_prior_hardcoded_values() -> None:
    # These were previously hardcoded inside AnthropicClient; the defaults here
    # must reproduce that exact behavior (no functionality change).
    settings = Settings(_env_file=None)
    assert settings.llm_max_tokens == 4096
    assert settings.llm_temperature == 0.0


def test_llm_max_tokens_and_temperature_are_overridable(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_LLM_MAX_TOKENS", "2048")
    monkeypatch.setenv("ATLAS_LLM_TEMPERATURE", "0.5")
    settings = Settings(_env_file=None)
    assert settings.llm_max_tokens == 2048
    assert settings.llm_temperature == 0.5
