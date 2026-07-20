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
    LLMConfigurationError,
    LLMProvider,
    LLMTransportError,
    MissingAPIKeyError,
)
from atlas.reasoning.llm.factory import build_llm_client
from atlas.reasoning.llm.ollama import MissingOllamaModelError, OllamaUnavailableError
from atlas.reasoning.llm.omniroute import OmniRouteUnavailableError

__all__ = [
    "FakeLLMClient",
    "LLMClient",
    "LLMConfigurationError",
    "LLMProvider",
    "LLMTransportError",
    "MissingAPIKeyError",
    "MissingOllamaModelError",
    "OllamaUnavailableError",
    "OmniRouteUnavailableError",
    "build_llm_client",
]
