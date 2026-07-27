"""OllamaClient — the local, keyless ``ollama`` transport adapter.

Pure unit tests: ``requests.post`` is monkeypatched, so there is no live
Ollama dependency, no network, and no running server. Covers the HTTP call
shape (``POST {host}/api/generate``, ``stream=false``), settings wiring, the
two deliberate divergences from the cloud adapters (keyless build + its own
``ollama_model`` identity), and response/error handling.
"""

from __future__ import annotations

import pytest
import requests

from atlas.config.settings import Settings
from atlas.reasoning.llm.base import LLMClient, LLMConfigurationError
from atlas.reasoning.llm.ollama import (
    MissingOllamaModelError,
    OllamaClient,
    OllamaUnavailableError,
)


class _FakeResponse:
    def __init__(self, *, json_data: dict, raise_exc: Exception | None = None) -> None:
        self._json = json_data
        self._raise_exc = raise_exc

    def raise_for_status(self) -> None:
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self) -> dict:
        return self._json


class _PostRecorder:
    """Stands in for requests.post — records call args, returns a canned response."""

    def __init__(self, response: _FakeResponse) -> None:
        self.calls: list[dict] = []
        self._response = response

    def __call__(self, url, *, json, timeout):  # noqa: ANN001, ANN204 - test double
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self._response


def _patch_post(
    monkeypatch: pytest.MonkeyPatch, response: _FakeResponse
) -> _PostRecorder:
    recorder = _PostRecorder(response)
    monkeypatch.setattr("atlas.reasoning.llm.ollama.requests.post", recorder)
    return recorder


# --- Protocol / construction --------------------------------------------------
def test_ollama_client_satisfies_llm_client_protocol() -> None:
    client = OllamaClient(host="http://localhost:11434", model="llama3.2")
    assert isinstance(client, LLMClient)


def test_constructor_accepts_explicit_params() -> None:
    client = OllamaClient(
        host="http://h:1",
        model="m",
        max_tokens=10,
        temperature=0.9,
        timeout=5.0,
    )
    assert client._model == "m"
    assert client._max_tokens == 10
    assert client._temperature == 0.9
    assert client._timeout == 5.0


def test_host_trailing_slash_is_stripped() -> None:
    client = OllamaClient(host="http://localhost:11434/", model="m")
    assert client._host == "http://localhost:11434"


# --- from_settings: keyless + its own model identity --------------------------
def test_from_settings_builds_without_any_key(monkeypatch) -> None:
    # Keyless transport: unlike the cloud adapters, a configured model with no
    # credential must build fine — Ollama needs no key.
    monkeypatch.setenv("ATLAS_OLLAMA_MODEL", "qwen3:8b")
    client = OllamaClient.from_settings(Settings(_env_file=None))
    assert isinstance(client, LLMClient)


def test_from_settings_uses_default_host(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_OLLAMA_MODEL", "qwen3:8b")
    client = OllamaClient.from_settings(Settings(_env_file=None))
    assert client._host == "http://localhost:11434"


def test_from_settings_raises_missing_model_when_unset() -> None:
    # No default model: an unset one must fail clearly at build time, not
    # silently pick a tag the user hasn't pulled.
    with pytest.raises(MissingOllamaModelError, match="ATLAS_OLLAMA_MODEL"):
        OllamaClient.from_settings(Settings(_env_file=None))


def test_missing_model_error_is_an_llm_configuration_error() -> None:
    # So the CLI's single build-time guard (except LLMConfigurationError)
    # catches it uniformly with missing-key and other config gaps.
    assert issubclass(MissingOllamaModelError, LLMConfigurationError)


def test_from_settings_reads_host_and_model_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_OLLAMA_HOST", "http://gpu-box:11434")
    monkeypatch.setenv("ATLAS_OLLAMA_MODEL", "qwen2.5:14b")
    client = OllamaClient.from_settings(Settings(_env_file=None))
    assert client._host == "http://gpu-box:11434"
    assert client._model == "qwen2.5:14b"


def test_from_settings_uses_ollama_model_not_cloud_reasoning_model(monkeypatch) -> None:
    # The key divergence: ollama_model is authoritative for this transport, so
    # a leftover cloud reasoning_model (the default is a Claude id) never leaks
    # in as an Ollama tag.
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("ATLAS_OLLAMA_MODEL", "llama3.2")
    client = OllamaClient.from_settings(Settings(_env_file=None))
    assert client._model == "llama3.2"


def test_from_settings_explicit_model_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_OLLAMA_MODEL", "llama3.2")
    client = OllamaClient.from_settings(Settings(_env_file=None), model="mistral")
    assert client._model == "mistral"


def test_from_settings_reads_max_tokens_and_temperature_from_shared_settings(
    monkeypatch,
) -> None:
    # Same shared determinism policy (G7) as the cloud adapters — one Settings
    # knob, not reinvented per provider.
    monkeypatch.setenv("ATLAS_OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("ATLAS_LLM_MAX_TOKENS", "1234")
    monkeypatch.setenv("ATLAS_LLM_TEMPERATURE", "0.7")
    client = OllamaClient.from_settings(Settings(_env_file=None))
    assert client._max_tokens == 1234
    assert client._temperature == 0.7


def test_from_settings_default_max_tokens_and_temperature_match_parity(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ATLAS_OLLAMA_MODEL", "qwen3:8b")
    client = OllamaClient.from_settings(Settings(_env_file=None))
    assert client._max_tokens == 4096
    assert client._temperature == 0.0


# --- complete(): HTTP call shape, mocked transport ----------------------------
def test_complete_posts_to_generate_endpoint_with_correct_shape(monkeypatch) -> None:
    recorder = _patch_post(
        monkeypatch, _FakeResponse(json_data={"response": "Margins ~24%."})
    )
    client = OllamaClient(
        host="http://localhost:11434",
        model="llama3.2",
        max_tokens=2048,
        temperature=0.3,
        timeout=99.0,
    )
    result = client.complete(system="You are Atlas.", user="How are margins?")

    assert result == "Margins ~24%."
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["url"] == "http://localhost:11434/api/generate"
    assert call["timeout"] == 99.0
    body = call["json"]
    assert body["model"] == "llama3.2"
    assert body["prompt"] == "How are margins?"
    assert body["system"] == "You are Atlas."
    assert body["stream"] is False
    assert body["options"] == {"temperature": 0.3, "num_predict": 2048}


def test_complete_returns_empty_string_when_response_key_missing(monkeypatch) -> None:
    _patch_post(monkeypatch, _FakeResponse(json_data={"done": True}))
    client = OllamaClient(host="http://localhost:11434", model="m")
    assert client.complete(system="s", user="u") == ""


def test_complete_returns_empty_string_when_response_is_null(monkeypatch) -> None:
    _patch_post(monkeypatch, _FakeResponse(json_data={"response": None}))
    client = OllamaClient(host="http://localhost:11434", model="m")
    assert client.complete(system="s", user="u") == ""


def test_complete_raises_on_http_error(monkeypatch) -> None:
    err = requests.exceptions.HTTPError("500 Server Error")
    _patch_post(monkeypatch, _FakeResponse(json_data={}, raise_exc=err))
    client = OllamaClient(host="http://localhost:11434", model="m")
    with pytest.raises(requests.exceptions.HTTPError):
        client.complete(system="s", user="u")


def test_complete_raises_friendly_error_when_server_unreachable(monkeypatch) -> None:
    # A raw ConnectionError becomes an OllamaUnavailableError with a "is it
    # running?" message the CLI prints instead of a traceback.
    def _raise_connection_error(
        url, *, json, timeout
    ):  # noqa: ANN001, ANN202 - test double
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(
        "atlas.reasoning.llm.ollama.requests.post", _raise_connection_error
    )
    client = OllamaClient(host="http://localhost:11434", model="m")
    with pytest.raises(OllamaUnavailableError) as exc_info:
        client.complete(system="s", user="u")
    message = str(exc_info.value)
    assert "http://localhost:11434" in message  # the host, for debuggability
    assert "ollama serve" in message  # actionable next step
    # Chained from the original for debuggers, hidden from the user's view.
    assert isinstance(exc_info.value.__cause__, requests.exceptions.ConnectionError)


def test_complete_uses_default_timeout_when_unset(monkeypatch) -> None:
    recorder = _patch_post(monkeypatch, _FakeResponse(json_data={"response": "ok"}))
    client = OllamaClient(host="http://localhost:11434", model="m")
    client.complete(system="s", user="u")
    # Local generation is slow; the default must be well above the general 30s
    # HTTP default so long completions aren't silently truncated.
    assert recorder.calls[0]["timeout"] >= 120.0
