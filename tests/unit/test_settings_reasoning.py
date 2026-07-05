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
