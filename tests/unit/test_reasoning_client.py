"""LLMClient seam (M0 commit 4). No network — FakeLLMClient and construction only."""
from __future__ import annotations

import pytest

from atlas.config.settings import Settings
from atlas.reasoning.client import (
    AnthropicClient,
    FakeLLMClient,
    LLMClient,
    MissingAPIKeyError,
)


def test_fake_client_returns_response_and_records_calls() -> None:
    fake = FakeLLMClient(response="hello")
    out = fake.complete(system="sys", user="usr")
    assert out == "hello"
    assert fake.calls == [("sys", "usr")]


def test_fake_client_satisfies_protocol() -> None:
    assert isinstance(FakeLLMClient(response="x"), LLMClient)


def test_from_settings_raises_clear_error_without_key() -> None:
    settings = Settings(_env_file=None)  # no key
    with pytest.raises(MissingAPIKeyError):
        AnthropicClient.from_settings(settings)


def test_from_settings_builds_with_key(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test-abc")
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "claude-test")
    client = AnthropicClient.from_settings(Settings(_env_file=None))
    assert isinstance(client, LLMClient)
    assert client._model == "claude-test"
