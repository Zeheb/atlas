"""Provider-agnostic LLM layer for the reasoning subsystem.

Public API: ``LLMClient`` (the Protocol), ``FakeLLMClient`` (test double),
``MissingAPIKeyError``, ``LLMProvider`` (the transport type alias), and
``build_llm_client`` (the factory — the only place selecting a concrete
adapter). Concrete adapters (``AnthropicClient``, ``GeminiClient``) are
importable from their own modules for tests that need to construct one
explicitly; production code should go through ``build_llm_client``.
"""
from __future__ import annotations

from atlas.reasoning.llm.base import (
    FakeLLMClient,
    LLMClient,
    LLMProvider,
    MissingAPIKeyError,
)
from atlas.reasoning.llm.factory import build_llm_client

__all__ = [
    "FakeLLMClient",
    "LLMClient",
    "LLMProvider",
    "MissingAPIKeyError",
    "build_llm_client",
]
