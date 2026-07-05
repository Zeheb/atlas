"""LLM client seam for the reasoning subsystem (M0 commit 4).

The reasoning code depends only on the ``LLMClient`` Protocol — text in, text
out — so every module above it is unit-testable with ``FakeLLMClient`` and no
network. ``AnthropicClient`` is the one production implementation; swapping the
model or provider never touches reasoning logic.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from atlas.config.settings import Settings


class MissingAPIKeyError(RuntimeError):
    """Raised when reasoning is invoked without an Anthropic API key configured."""


@runtime_checkable
class LLMClient(Protocol):
    """Text-in, text-out completion. The only LLM surface reasoning depends on."""

    def complete(self, *, system: str, user: str) -> str:
        """Return the model's text response to a system + user prompt."""
        ...


class AnthropicClient:
    """Production ``LLMClient`` backed by the Anthropic API (temperature 0)."""

    def __init__(self, *, api_key: str, model: str, max_tokens: int = 4096) -> None:
        # Imported lazily so importing this module never requires the SDK to be
        # present at call sites that only use FakeLLMClient.
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    @classmethod
    def from_settings(cls, settings: "Settings") -> "AnthropicClient":
        """Build from Settings, failing clearly when no key is configured (§9.4)."""
        if not settings.anthropic_api_key:
            raise MissingAPIKeyError(
                "No Anthropic API key configured. Set ATLAS_ANTHROPIC_API_KEY "
                "in your environment or .env file."
            )
        return cls(api_key=settings.anthropic_api_key, model=settings.reasoning_model)

    def complete(self, *, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=0,  # determinism floor (G7); true G7 arrives with M4
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        from anthropic.types import TextBlock

        parts = [block.text for block in response.content if isinstance(block, TextBlock)]
        return "".join(parts)


class FakeLLMClient:
    """Test double: returns a fixed response and records the prompts it received."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response
