"""AnthropicClient at its canonical location (LLM-layer refactor, commit 1/2).

Covers the incremental new behavior — temperature/max_tokens now read from
Settings rather than hardcoded — plus from_settings' existing contract
(previously covered by tests/unit/test_reasoning_client.py, deleted in
commit 2 once the atlas.reasoning.client shim it exercised was removed;
this file's coverage fully supersedes it).
"""
from __future__ import annotations

import pytest

from atlas.config.settings import Settings
from atlas.reasoning.llm.anthropic import AnthropicClient
from atlas.reasoning.llm.base import LLMClient, MissingAPIKeyError


def test_from_settings_raises_clear_error_without_key() -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(MissingAPIKeyError):
        AnthropicClient.from_settings(settings)


def test_from_settings_builds_with_key(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test-abc")
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "claude-test")
    client = AnthropicClient.from_settings(Settings(_env_file=None))
    assert isinstance(client, LLMClient)
    assert client._model == "claude-test"


def test_from_settings_model_override_for_judge(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test-abc")
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "claude-reasoning")
    client = AnthropicClient.from_settings(Settings(_env_file=None), model="claude-judge")
    assert client._model == "claude-judge"


# --- New in this refactor: temperature/max_tokens promoted from hardcoded ----
def test_from_settings_reads_max_tokens_and_temperature_from_settings(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test-abc")
    monkeypatch.setenv("ATLAS_LLM_MAX_TOKENS", "1234")
    monkeypatch.setenv("ATLAS_LLM_TEMPERATURE", "0.7")
    client = AnthropicClient.from_settings(Settings(_env_file=None))
    assert client._max_tokens == 1234
    assert client._temperature == 0.7


def test_from_settings_default_max_tokens_and_temperature_match_prior_hardcoded(monkeypatch) -> None:
    # No functionality change: these must equal what was previously hardcoded
    # inline (max_tokens=4096, temperature=0) inside AnthropicClient.
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test-abc")
    client = AnthropicClient.from_settings(Settings(_env_file=None))
    assert client._max_tokens == 4096
    assert client._temperature == 0.0


def test_constructor_accepts_explicit_temperature_and_max_tokens() -> None:
    client = AnthropicClient(api_key="k", model="m", max_tokens=10, temperature=0.9)
    assert client._max_tokens == 10
    assert client._temperature == 0.9
