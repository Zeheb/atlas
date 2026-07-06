"""Transport-agnostic seam at its canonical location (LLM-layer refactor,
commit 1). This proves atlas.reasoning.llm works standalone, independent of
the atlas.reasoning.client compatibility shim (which has its own,
untouched, pre-existing test file proving backward compatibility).
"""
from __future__ import annotations

from typing import get_args

from atlas.reasoning.llm.base import (
    FakeLLMClient,
    LLMClient,
    LLMProvider,
    MissingAPIKeyError,
)


def test_fake_client_returns_response_and_records_calls() -> None:
    fake = FakeLLMClient(response="hello")
    out = fake.complete(system="sys", user="usr")
    assert out == "hello"
    assert fake.calls == [("sys", "usr")]


def test_fake_client_satisfies_protocol() -> None:
    assert isinstance(FakeLLMClient(response="x"), LLMClient)


def test_missing_api_key_error_is_a_runtime_error() -> None:
    assert issubclass(MissingAPIKeyError, RuntimeError)


def test_llm_provider_names_transports_not_model_families() -> None:
    # Provider vs. model adapter vs. model identity: values must be transport
    # names. google_ai_studio and vertex_ai are two transports for one model
    # family (Gemini) — the exact gap the flat "gemini" name couldn't express.
    assert set(get_args(LLMProvider)) == {"anthropic", "google_ai_studio", "vertex_ai"}
