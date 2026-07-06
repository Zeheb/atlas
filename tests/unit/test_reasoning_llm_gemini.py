"""GeminiClient — the google_ai_studio adapter (Google provider implementation).

Uses the real, installed google-genai SDK's import path but fakes
google.genai.Client itself so these are true unit tests: no network, no real
credentials, no live model call. vertex_ai remains a documented, tested
NotImplementedError — from_settings already threads the provider distinction
through, so implementing it later touches only this file.
"""
from __future__ import annotations

import pytest

from atlas.config.settings import Settings
from atlas.reasoning.llm.base import LLMClient, MissingAPIKeyError
from atlas.reasoning.llm.gemini import GeminiClient


class _FakeGenAIResponse:
    def __init__(self, text: str | None) -> None:
        self.text = text


class _FakeGenAIModels:
    def __init__(self, response_text: str | None) -> None:
        self.calls: list[dict] = []
        self._response_text = response_text

    def generate_content(self, *, model, contents, config):  # noqa: ANN001, ANN201 - test double
        self.calls.append({"model": model, "contents": contents, "config": config})
        return _FakeGenAIResponse(self._response_text)


class _FakeGenAIClient:
    """Stands in for google.genai.Client — no network, records call args."""

    last_instance: "_FakeGenAIClient | None" = None

    def __init__(self, *, api_key: str | None = None, **kwargs) -> None:  # noqa: ANN003
        self.api_key = api_key
        self.kwargs = kwargs
        self.models = _FakeGenAIModels(response_text="Operating margin has held near 24%.")
        _FakeGenAIClient.last_instance = self


@pytest.fixture(autouse=True)
def _patch_genai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("google.genai.Client", _FakeGenAIClient)


def test_gemini_client_satisfies_llm_client_protocol() -> None:
    client = GeminiClient(api_key="k", model="gemini-2.5-pro")
    assert isinstance(client, LLMClient)


# --- from_settings: google_ai_studio (implemented) ---------------------------
def test_from_settings_raises_missing_key_for_google_ai_studio_without_key() -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(MissingAPIKeyError, match="ATLAS_GEMINI_API_KEY"):
        GeminiClient.from_settings(settings, provider="google_ai_studio")


def test_from_settings_builds_with_key(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_GEMINI_API_KEY", "g-test-key")
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "gemini-2.5-pro")
    client = GeminiClient.from_settings(Settings(_env_file=None), provider="google_ai_studio")
    assert isinstance(client, LLMClient)
    assert client._model == "gemini-2.5-pro"


def test_from_settings_model_override_for_judge(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_GEMINI_API_KEY", "g-test-key")
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "gemini-reasoning")
    client = GeminiClient.from_settings(
        Settings(_env_file=None), provider="google_ai_studio", model="gemini-judge",
    )
    assert client._model == "gemini-judge"


def test_from_settings_reads_max_tokens_and_temperature_from_settings(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_GEMINI_API_KEY", "g-test-key")
    monkeypatch.setenv("ATLAS_LLM_MAX_TOKENS", "1234")
    monkeypatch.setenv("ATLAS_LLM_TEMPERATURE", "0.7")
    client = GeminiClient.from_settings(Settings(_env_file=None), provider="google_ai_studio")
    assert client._max_tokens == 1234
    assert client._temperature == 0.7


def test_from_settings_default_max_tokens_and_temperature_match_anthropic_parity(monkeypatch) -> None:
    # Same shared determinism policy (G7) as the Anthropic adapter — one
    # Settings-level knob, not reinvented per provider.
    monkeypatch.setenv("ATLAS_GEMINI_API_KEY", "g-test-key")
    client = GeminiClient.from_settings(Settings(_env_file=None), provider="google_ai_studio")
    assert client._max_tokens == 4096
    assert client._temperature == 0.0


def test_constructor_accepts_explicit_params() -> None:
    client = GeminiClient(api_key="k", model="m", max_tokens=10, temperature=0.9)
    assert client._max_tokens == 10
    assert client._temperature == 0.9


# --- from_settings: vertex_ai (still not implemented) -------------------------
def test_from_settings_vertex_ai_raises_not_implemented_regardless_of_key(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_GEMINI_API_KEY", "g-test-key")  # key present is irrelevant
    with pytest.raises(NotImplementedError, match="vertex_ai"):
        GeminiClient.from_settings(Settings(_env_file=None), provider="vertex_ai")


def test_from_settings_vertex_ai_raises_before_checking_for_a_key() -> None:
    settings = Settings(_env_file=None)  # no gemini_api_key at all
    with pytest.raises(NotImplementedError):  # NotImplementedError, not MissingAPIKeyError
        GeminiClient.from_settings(settings, provider="vertex_ai")


# --- complete(): real SDK call shape, faked transport -------------------------
def test_complete_calls_sdk_with_correct_shape() -> None:
    client = GeminiClient(api_key="k", model="gemini-2.5-pro", max_tokens=2048, temperature=0.3)
    result = client.complete(system="You are Atlas.", user="How are margins?")

    assert result == "Operating margin has held near 24%."
    fake = _FakeGenAIClient.last_instance
    assert fake is not None
    assert fake.api_key == "k"
    call = fake.models.calls[0]
    assert call["model"] == "gemini-2.5-pro"
    assert call["contents"] == "How are margins?"
    assert call["config"].system_instruction == "You are Atlas."
    assert call["config"].temperature == 0.3
    assert call["config"].max_output_tokens == 2048


def test_complete_returns_empty_string_when_response_text_is_none(monkeypatch) -> None:
    monkeypatch.setattr(
        "google.genai.Client",
        lambda **kw: type(
            "C", (), {"models": _FakeGenAIModels(response_text=None)},
        )(),
    )
    client = GeminiClient(api_key="k", model="m")
    assert client.complete(system="s", user="u") == ""


def test_llm_client_protocol_is_importable() -> None:
    assert LLMClient is not None
