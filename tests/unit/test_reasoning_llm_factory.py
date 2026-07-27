"""build_llm_client — the only place in Atlas dispatching a transport name to
a concrete adapter (LLM-layer refactor, commit 1/2; Google provider).
"""

from __future__ import annotations

import pytest

from atlas.config.settings import Settings
from atlas.reasoning.llm.anthropic import AnthropicClient
from atlas.reasoning.llm.base import MissingAPIKeyError
from atlas.reasoning.llm.factory import build_llm_client
from atlas.reasoning.llm.gemini import GeminiClient
from atlas.reasoning.llm.ollama import OllamaClient


@pytest.fixture(autouse=True)
def _patch_genai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # google_ai_studio is now real (Google provider implementation); dispatch
    # tests that reach it must not touch the network. See
    # test_reasoning_llm_gemini.py for the SDK-call-shape tests themselves.
    monkeypatch.setattr("google.genai.Client", lambda **kw: object())


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, anthropic_api_key="sk-test", **overrides)


def test_default_provider_dispatches_to_anthropic() -> None:
    client = build_llm_client(_settings(), role="reasoning")
    assert isinstance(client, AnthropicClient)


def test_switching_llm_provider_to_google_ai_studio_dispatches_both_roles(
    monkeypatch,
) -> None:
    # Requirement 10: setting ATLAS_LLM_PROVIDER=google_ai_studio must require
    # no code changes anywhere else in Atlas — verified here at the exact seam
    # cli.py depends on (build_llm_client), for both roles, with no
    # per-role override needed.
    monkeypatch.setenv("ATLAS_LLM_PROVIDER", "google_ai_studio")
    monkeypatch.setenv("ATLAS_GEMINI_API_KEY", "g-test")
    settings = Settings(_env_file=None)
    assert isinstance(build_llm_client(settings, role="reasoning"), GeminiClient)
    assert isinstance(build_llm_client(settings, role="judge"), GeminiClient)


def test_judge_role_uses_judge_model_not_reasoning_model() -> None:
    settings = _settings(reasoning_model="claude-reasoning", judge_model="claude-judge")
    reasoning_client = build_llm_client(settings, role="reasoning")
    judge_client = build_llm_client(settings, role="judge")
    assert reasoning_client._model == "claude-reasoning"
    assert judge_client._model == "claude-judge"


def test_reasoning_provider_override_dispatches_to_gemini_client() -> None:
    # Goal 7: judge and reasoning must be able to run genuinely independent
    # implementations, not just independent models on the same transport.
    # google_ai_studio is real (Google provider implementation): this now
    # succeeds rather than raising, proving requirement 10 — switching
    # ATLAS_LLM_PROVIDER (or a per-role override) needs no code changes
    # anywhere else, including this factory.
    settings = _settings(reasoning_provider="google_ai_studio", gemini_api_key="g-test")
    reasoning_client = build_llm_client(settings, role="reasoning")
    assert isinstance(reasoning_client, GeminiClient)
    # Judge is untouched by the reasoning-only override — still Anthropic.
    judge_client = build_llm_client(settings, role="judge")
    assert isinstance(judge_client, AnthropicClient)


def test_reasoning_provider_google_ai_studio_without_key_raises_missing_key() -> None:
    settings = _settings(reasoning_provider="google_ai_studio")  # no gemini_api_key
    with pytest.raises(MissingAPIKeyError, match="ATLAS_GEMINI_API_KEY"):
        build_llm_client(settings, role="reasoning")


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


def test_provider_ollama_dispatches_to_ollama_client_for_both_roles() -> None:
    # Keyless: no credential needed to build (only a configured model).
    # Switching ATLAS_LLM_PROVIDER=ollama requires no code change beyond the
    # factory, for both roles.
    settings = _settings(llm_provider="ollama", ollama_model="qwen3:8b")
    assert isinstance(build_llm_client(settings, role="reasoning"), OllamaClient)
    assert isinstance(build_llm_client(settings, role="judge"), OllamaClient)


def test_ollama_dispatch_uses_ollama_model_not_cloud_role_model() -> None:
    # The factory must not thread reasoning_model/judge_model (cloud ids) into
    # the ollama transport — it reads ATLAS_OLLAMA_MODEL instead.
    settings = _settings(
        llm_provider="ollama",
        reasoning_model="claude-sonnet-5",
        judge_model="claude-judge",
        ollama_model="llama3.2",
    )
    assert build_llm_client(settings, role="reasoning")._model == "llama3.2"  # type: ignore[attr-defined]
    assert build_llm_client(settings, role="judge")._model == "llama3.2"  # type: ignore[attr-defined]


def test_reasoning_provider_override_to_ollama_leaves_judge_on_anthropic() -> None:
    settings = _settings(reasoning_provider="ollama", ollama_model="qwen3:8b")
    assert isinstance(build_llm_client(settings, role="reasoning"), OllamaClient)
    assert isinstance(build_llm_client(settings, role="judge"), AnthropicClient)


def test_ollama_without_model_raises_missing_model_at_build() -> None:
    from atlas.reasoning.llm.ollama import MissingOllamaModelError

    settings = _settings(llm_provider="ollama")  # no ollama_model
    with pytest.raises(MissingOllamaModelError, match="ATLAS_OLLAMA_MODEL"):
        build_llm_client(settings, role="reasoning")
