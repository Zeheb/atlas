"""Compatibility shim — the LLM client seam moved to ``atlas.reasoning.llm``.

This module is deprecated and will be removed in the next commit (see the
architecture note on provider vs. model adapter vs. model identity). Import
from ``atlas.reasoning.llm`` instead. This re-export preserves every existing
call site unchanged for one transitional commit (strangler-fig migration).
"""
from __future__ import annotations

from atlas.reasoning.llm.anthropic import AnthropicClient
from atlas.reasoning.llm.base import FakeLLMClient, LLMClient, MissingAPIKeyError

__all__ = ["AnthropicClient", "FakeLLMClient", "LLMClient", "MissingAPIKeyError"]
