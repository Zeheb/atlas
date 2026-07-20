"""OmniRouteClient at its canonical location.

Pure unit tests: ``requests.post`` is monkeypatched, so there is no live
OmniRoute dependency, no network, and no running server. Covers the HTTP call
shape (``POST {host}/messages``), settings wiring, optional API key, and
response/error handling.
"""
from __future__ import annotations

import pytest
import requests

from atlas.config.settings import Settings
from atlas.reasoning.llm.base import LLMClient
from atlas.reasoning.llm.omniroute import (
    OmniRouteClient,
    OmniRouteUnavailableError,
)
from atlas.reasoning.llm.factory import build_llm_client


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

    def __call__(self, url, *, json, headers=None, timeout):  # noqa: ANN001, ANN204 - test double
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self._response


def _patch_post(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> _PostRecorder:
    recorder = _PostRecorder(response)
    monkeypatch.setattr("atlas.reasoning.llm.omniroute.requests.post", recorder)
    return recorder


# --- Protocol / construction --------------------------------------------------
def test_omniroute_client_satisfies_llm_client_protocol() -> None:
    client = OmniRouteClient(base_url="http://localhost:20128", model="test_cc")
    assert isinstance(client, LLMClient)


def test_constructor_accepts_explicit_params() -> None:
    client = OmniRouteClient(
        base_url="http://h:1", model="m", api_key="k", max_tokens=10, temperature=0.9, timeout=5.0,
    )
    assert client._model == "m"
    assert client._api_key == "k"
    assert client._max_tokens == 10
    assert client._temperature == 0.9
    assert client._timeout == 5.0


def test_base_url_trailing_slash_is_stripped() -> None:
    client = OmniRouteClient(base_url="http://localhost:20128/", model="m")
    assert client._base_url == "http://localhost:20128"


# --- from_settings: optional key + shared reasoning_model/judge_model identity -
def test_from_settings_builds_without_api_key() -> None:
    client = OmniRouteClient.from_settings(Settings(_env_file=None))
    assert isinstance(client, LLMClient)
    assert client._api_key is None


def test_from_settings_builds_with_api_key(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_OMNIROUTE_API_KEY", "omni-key")
    client = OmniRouteClient.from_settings(Settings(_env_file=None))
    assert isinstance(client, LLMClient)
    assert client._api_key == "omni-key"


def test_from_settings_uses_default_base_url() -> None:
    client = OmniRouteClient.from_settings(Settings(_env_file=None))
    assert client._base_url == "http://localhost:20128"


def test_from_settings_defaults_model_to_reasoning_model(monkeypatch) -> None:
    # OmniRoute has no model namespace of its own: it reuses the shared
    # reasoning_model identity, exactly like the anthropic transport.
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "test_cc")
    client = OmniRouteClient.from_settings(Settings(_env_file=None))
    assert client._model == "test_cc"


def test_from_settings_reads_base_url_model_and_key_from_env(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_OMNIROUTE_BASE_URL", "http://custom-host:8080")
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "custom-omni-model")
    monkeypatch.setenv("ATLAS_OMNIROUTE_API_KEY", "custom-omni-key")
    client = OmniRouteClient.from_settings(Settings(_env_file=None))
    assert client._base_url == "http://custom-host:8080"
    assert client._model == "custom-omni-model"
    assert client._api_key == "custom-omni-key"


def test_from_settings_explicit_model_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "default-omni-model")
    client = OmniRouteClient.from_settings(Settings(_env_file=None), model="override-model")
    assert client._model == "override-model"


def test_from_settings_reads_max_tokens_and_temperature_from_shared_settings(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_LLM_MAX_TOKENS", "1234")
    monkeypatch.setenv("ATLAS_LLM_TEMPERATURE", "0.7")
    client = OmniRouteClient.from_settings(Settings(_env_file=None))
    assert client._max_tokens == 1234
    assert client._temperature == 0.7


def test_from_settings_default_max_tokens_and_temperature_match_parity() -> None:
    client = OmniRouteClient.from_settings(Settings(_env_file=None))
    assert client._max_tokens == 4096
    assert client._temperature == 0.0


# --- complete(): HTTP call shape, mocked transport ----------------------------
def test_complete_posts_to_messages_endpoint_with_correct_shape(monkeypatch) -> None:
    recorder = _patch_post(monkeypatch, _FakeResponse(json_data={
        "content": [{"type": "text", "text": "OmniRoute response."}]
    }))
    client = OmniRouteClient(
        base_url="http://localhost:20128", model="test_cc", api_key="test-key",
        max_tokens=2048, temperature=0.3, timeout=59.0,
    )
    result = client.complete(system="You are Atlas.", user="How are margins?")

    assert result == "OmniRoute response."
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["url"] == "http://localhost:20128/v1/messages"
    assert call["timeout"] == 59.0
    assert call["headers"] == {"X-API-Key": "test-key"}
    body = call["json"]
    assert body["model"] == "test_cc"
    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.3
    assert body["system"] == "You are Atlas."
    assert body["messages"] == [{"role": "user", "content": "How are margins?"}]


def test_complete_posts_without_api_key_header_when_not_set(monkeypatch) -> None:
    recorder = _patch_post(monkeypatch, _FakeResponse(json_data={
        "content": [{"type": "text", "text": "No key here."}]
    }))
    client = OmniRouteClient(
        base_url="http://localhost:20128", model="test_cc", max_tokens=2048, temperature=0.3,
    )
    client.complete(system="s", user="u")

    call = recorder.calls[0]
    assert "X-API-Key" not in call["headers"]


def test_complete_returns_empty_string_when_content_key_missing(monkeypatch) -> None:
    _patch_post(monkeypatch, _FakeResponse(json_data={}))
    client = OmniRouteClient(base_url="http://localhost:20128", model="m")
    assert client.complete(system="s", user="u") == ""


def test_complete_returns_empty_string_when_content_is_empty(monkeypatch) -> None:
    _patch_post(monkeypatch, _FakeResponse(json_data={"content": []}))
    client = OmniRouteClient(base_url="http://localhost:20128", model="m")
    assert client.complete(system="s", user="u") == ""


def test_complete_raises_on_http_error(monkeypatch) -> None:
    err = requests.exceptions.HTTPError("500 Server Error")
    _patch_post(monkeypatch, _FakeResponse(json_data={}, raise_exc=err))
    client = OmniRouteClient(base_url="http://localhost:20128", model="m")
    with pytest.raises(requests.exceptions.HTTPError):
        client.complete(system="s", user="u")


def test_complete_raises_friendly_error_when_server_unreachable(monkeypatch) -> None:
    def _raise_connection_error(url, *, json, headers, timeout):  # noqa: ANN001, ANN202 - test double
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr("atlas.reasoning.llm.omniroute.requests.post", _raise_connection_error)
    client = OmniRouteClient(base_url="http://localhost:20128", model="m")
    with pytest.raises(OmniRouteUnavailableError) as exc_info:
        client.complete(system="s", user="u")
    message = str(exc_info.value)
    assert "http://localhost:20128" in message  # the host, for debuggability
    assert "Is OmniRoute running?" in message  # actionable next step
    # Chained from the original for debuggers, hidden from the user's view.
    assert isinstance(exc_info.value.__cause__, requests.exceptions.ConnectionError)


def test_complete_uses_default_timeout_when_unset(monkeypatch) -> None:
    recorder = _patch_post(monkeypatch, _FakeResponse(json_data={
        "content": [{"type": "text", "text": "ok"}]
    }))
    client = OmniRouteClient(base_url="http://localhost:20128", model="m")
    client.complete(system="s", user="u")
    assert recorder.calls[0]["timeout"] >= 60.0


def test_factory_dispatches_to_omniroute_client(monkeypatch) -> None:
    # The factory threads the shared reasoning_model into the omniroute
    # transport — no provider-specific model setting.
    monkeypatch.setenv("ATLAS_LLM_PROVIDER", "omniroute")
    monkeypatch.setenv("ATLAS_REASONING_MODEL", "factory-model")
    client = build_llm_client(Settings(_env_file=None), role="reasoning")
    assert isinstance(client, OmniRouteClient)
    assert client._model == "factory-model"
