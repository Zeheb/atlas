"""Provider selection — the ONLY place in Atlas mapping a transport name to a
concrete ``LLMClient`` adapter.

Reasoning and eval never see a provider name or a concrete adapter class; they
call ``build_llm_client(settings, role=...)`` and receive an ``LLMClient``.
Dispatch is many-to-one (multiple providers may share one adapter class), per
the provider-vs-adapter architecture amendment — not a 1:1 provider→class map.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from atlas.reasoning.llm.anthropic import AnthropicClient
from atlas.reasoning.llm.base import LLMClient, LLMProvider
from atlas.reasoning.llm.gemini import GeminiClient
from atlas.reasoning.llm.ollama import OllamaClient

if TYPE_CHECKING:
    from atlas.config.settings import Settings

Role = Literal["reasoning", "judge"]


def build_llm_client(settings: "Settings", *, role: Role) -> LLMClient:
    """Build the LLMClient for *role*.

    Role-specific provider/model overrides (reasoning_provider/judge_provider,
    reasoning_model/judge_model) fall back to the shared llm_provider default
    when unset — the same independent-by-default pattern already used for
    judge_model vs. reasoning_model, extended to the provider (transport) axis
    so judge and reasoning can each receive a genuinely independent
    implementation, not just an independent model on the same transport.
    """
    provider: LLMProvider = (
        settings.judge_provider if role == "judge" else settings.reasoning_provider
    ) or settings.llm_provider
    model = settings.judge_model if role == "judge" else settings.reasoning_model

    if provider == "anthropic":
        return AnthropicClient.from_settings(settings, model=model)
    if provider in ("google_ai_studio", "vertex_ai"):
        return GeminiClient.from_settings(settings, provider=provider, model=model)
    if provider == "ollama":
        # Deliberately not threading the cloud role model (reasoning_model/
        # judge_model): those default to cloud ids like "claude-sonnet-5",
        # which are meaningless as Ollama tags. This transport reads its own
        # ATLAS_OLLAMA_MODEL instead (see OllamaClient.from_settings).
        return OllamaClient.from_settings(settings)

    raise ValueError(f"Unknown LLM provider: {provider!r}")
