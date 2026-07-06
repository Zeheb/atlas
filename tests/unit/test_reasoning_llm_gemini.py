"""GeminiClient stub (LLM-layer refactor, commit 1).

Designed, not implemented: proves the seam accepts a second model family
without touching anything above it, and fails loudly/clearly rather than
silently or with an ImportError, for BOTH transports it is meant to serve.
"""
from __future__ import annotations

import pytest

from atlas.config.settings import Settings
from atlas.reasoning.llm.base import LLMClient
from atlas.reasoning.llm.gemini import GeminiClient


def test_gemini_client_satisfies_llm_client_protocol_structurally() -> None:
    # Never constructible via from_settings, but must genuinely conform to
    # the Protocol at the type level (mypy caught this — complete() must exist).
    assert hasattr(GeminiClient, "complete")


@pytest.mark.parametrize("provider", ["google_ai_studio", "vertex_ai"])
def test_from_settings_raises_not_implemented_for_both_transports(provider) -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(NotImplementedError, match=provider):
        GeminiClient.from_settings(settings, provider=provider)


def test_complete_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        GeminiClient.complete(GeminiClient.__new__(GeminiClient), system="s", user="u")


def test_llm_client_import_still_works_alongside_gemini_stub() -> None:
    # Sanity: importing the stub module doesn't require any Gemini SDK.
    assert LLMClient is not None
