"""Transport-agnostic LLM seam.

``LLMClient`` is the only surface reasoning and eval depend on: text in, text
out. No module above this package imports a concrete adapter directly — see
``factory.py`` for the single place that selects one.

``LLMProvider`` names TRANSPORTS, not model families (architecture amendment —
provider vs. model adapter vs. model identity). ``google_ai_studio`` and
``vertex_ai`` both serve Gemini models and may share one adapter class;
aggregator transports (e.g. a future ``openrouter``/``groq``) serve many
unrelated model identities through one shared wire protocol. ``ollama`` is a
local, keyless transport whose model identity is its own setting
(``Settings.ollama_model``). Model identity for the cloud transports is a
free-form string (``Settings.reasoning_model`` / ``judge_model``), orthogonal
to this axis.
"""
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

LLMProvider = Literal["anthropic", "google_ai_studio", "vertex_ai", "ollama", "omniroute"]


class LLMConfigurationError(RuntimeError):
    """An LLM client cannot be built from the current configuration.

    The base for every *build-time* failure (missing credential, missing
    model, etc.) so a composition root can catch the whole class in one clause
    and print the message, without enumerating each transport's specifics.
    """


class MissingAPIKeyError(LLMConfigurationError):
    """Raised when a role's LLM client is built without its required credential."""


class LLMTransportError(RuntimeError):
    """A configured LLM transport could not be reached at call time.

    The runtime counterpart to LLMConfigurationError: the configuration is valid
    but the server isn't answering (not started, wrong host/port, network down).
    A composition root can catch this one class to print a friendly "is it
    running?" message for any transport — instead of a raw ConnectionError
    traceback — without enumerating each provider's specific error type.
    """


@runtime_checkable
class LLMClient(Protocol):
    """Text-in, text-out completion. The only LLM surface reasoning depends on."""

    def complete(self, *, system: str, user: str) -> str:
        """Return the model's text response to a system + user prompt."""
        ...


class FakeLLMClient:
    """Test double: returns a fixed response and records the prompts it received."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response
