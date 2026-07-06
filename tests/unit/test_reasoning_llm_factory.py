"""build_llm_client — the only place in Atlas dispatching a transport name to
a concrete adapter (LLM-layer refactor, commit 1).
"""
from __future__ import annotations

import pytest

from atlas.config.settings import Settings
from atlas.reasoning.llm.anthropic import AnthropicClient
from atlas.reasoning.llm.factory import build_llm_client


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, anthropic_api_key="sk-test", **overrides)


def test_default_provider_dispatches_to_anthropic() -> None:
    client = build_llm_client(_settings(), role="reasoning")
    assert isinstance(client, AnthropicClient)


def test_judge_role_uses_judge_model_not_reasoning_model() -> None:
    settings = _settings(reasoning_model="claude-reasoning", judge_model="claude-judge")
    reasoning_client = build_llm_client(settings, role="reasoning")
    judge_client = build_llm_client(settings, role="judge")
    assert reasoning_client._model == "claude-reasoning"
    assert judge_client._model == "claude-judge"


def test_reasoning_provider_override_takes_a_gemini_transport() -> None:
    # Goal 7: judge and reasoning must be able to run genuinely independent
    # implementations, not just independent models on the same transport.
    settings = _settings(reasoning_provider="google_ai_studio")
    with pytest.raises(NotImplementedError, match="google_ai_studio"):
        build_llm_client(settings, role="reasoning")
    # Judge is untouched by the reasoning-only override — still Anthropic.
    judge_client = build_llm_client(settings, role="judge")
    assert isinstance(judge_client, AnthropicClient)


def test_judge_provider_override_is_independent_of_reasoning_provider() -> None:
    settings = _settings(judge_provider="vertex_ai")
    reasoning_client = build_llm_client(settings, role="reasoning")
    assert isinstance(reasoning_client, AnthropicClient)
    with pytest.raises(NotImplementedError, match="vertex_ai"):
        build_llm_client(settings, role="judge")


def test_llm_provider_default_applies_to_both_roles_when_no_override() -> None:
    settings = _settings(llm_provider="vertex_ai")
    with pytest.raises(NotImplementedError):
        build_llm_client(settings, role="reasoning")
    with pytest.raises(NotImplementedError):
        build_llm_client(settings, role="judge")


def test_unknown_provider_raises_clear_value_error() -> None:
    settings = _settings()
    settings.llm_provider = "not-a-real-provider"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        build_llm_client(settings, role="reasoning")
