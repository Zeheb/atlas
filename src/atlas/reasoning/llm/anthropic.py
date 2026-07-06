"""Anthropic Messages API adapter — implements ``LLMClient`` for the
``anthropic`` transport.

This is the one thing in Atlas that knows the Anthropic SDK's request/response
shape. Everything above this module (reasoning, eval) depends only on the
``LLMClient`` Protocol.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from atlas.reasoning.llm.base import MissingAPIKeyError

if TYPE_CHECKING:
    from atlas.config.settings import Settings


class AnthropicClient:
    """``LLMClient`` adapter for the Anthropic Messages API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> None:
        # Imported lazily so importing this module never requires the SDK to be
        # present at call sites that only use FakeLLMClient.
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    @classmethod
    def from_settings(cls, settings: "Settings", *, model: str | None = None) -> "AnthropicClient":
        """Build from Settings, failing clearly when no key is configured.

        ``model`` — override the model id (defaults to settings.reasoning_model).
        Used by the eval harness to build the judge on its separately-pinned
        settings.judge_model. ``max_tokens``/``temperature`` are read from
        Settings (llm_max_tokens/llm_temperature) so the determinism floor
        (G7) is a stated, configurable policy rather than a hardcoded literal.
        """
        if not settings.anthropic_api_key:
            raise MissingAPIKeyError(
                "No Anthropic API key configured. Set ATLAS_ANTHROPIC_API_KEY "
                "in your environment or .env file."
            )
        return cls(
            api_key=settings.anthropic_api_key,
            model=model or settings.reasoning_model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )

    def complete(self, *, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        from anthropic.types import TextBlock

        parts = [block.text for block in response.content if isinstance(block, TextBlock)]
        return "".join(parts)
