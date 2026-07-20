"""Ollama adapter — implements ``LLMClient`` for the ``ollama`` transport.

Talks to a local (or self-hosted) Ollama server over its HTTP API
(``POST {host}/api/generate`` with ``stream=false``) rather than shelling out
to the ``ollama`` CLI. This is the one thing in Atlas that knows Ollama's
request/response shape; everything above it (reasoning, eval) depends only on
the ``LLMClient`` Protocol.

Two deliberate divergences from the cloud adapters, both intrinsic to the
transport rather than stylistic:

* **Keyless.** Ollama runs locally and takes no API key, so there is no
  ``MissingAPIKeyError`` path. The credential-equivalent is the host URL,
  which carries a default (``http://localhost:11434``); a misconfigured or
  unreachable host surfaces as a transport error from ``complete()``, not a
  build-time credential error.
* **Its own model setting.** ``ATLAS_OLLAMA_MODEL`` is the model identity for
  this transport, not ``reasoning_model``/``judge_model``. Those default to
  *cloud* model ids (e.g. ``claude-sonnet-5``); local Ollama tags (e.g.
  ``llama3.2``) are a distinct namespace, so threading the cloud identity in
  would be actively wrong. See the factory for where this is wired.

``max_tokens``/``temperature`` are still read from the shared
``Settings.llm_max_tokens``/``llm_temperature`` knobs, so the determinism
floor (G7) is one policy across every provider rather than reinvented here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import requests

from atlas.reasoning.llm.base import LLMConfigurationError, LLMTransportError

if TYPE_CHECKING:
    from atlas.config.settings import Settings

# Local model generation is far slower than a cloud round-trip and easily
# exceeds the general 30s HTTP default, so this transport carries its own
# generous timeout rather than reusing Settings.http_timeout_seconds.
_DEFAULT_TIMEOUT_SECONDS = 120.0


class MissingOllamaModelError(LLMConfigurationError):
    """Raised when the ollama transport is selected but no model is configured.

    Deliberately has no default: Atlas is an investment-reasoning engine, and
    the models you'd actually run locally for it (qwen3, gemma3, mistral-small,
    deepseek-r1, ...) vary by machine. Silently defaulting to some tag would
    just yield "model X not found" from a server that's working fine, which
    reads as "Atlas is broken." Better to say plainly what to set.
    """


class OllamaUnavailableError(LLMTransportError):
    """Raised when the Ollama server can't be reached at ``complete()`` time.

    A *runtime* error, not a configuration one: the host is validly configured
    but nothing is listening (server not started, wrong host/port).
    """


class OllamaClient:
    """``LLMClient`` adapter for the Ollama HTTP API (``/api/generate``)."""

    def __init__(
        self,
        *,
        host: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        # rstrip so a host configured with a trailing slash doesn't produce a
        # double-slashed request path.
        self._host = host.rstrip("/")
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._timeout = timeout

    @classmethod
    def from_settings(cls, settings: "Settings", *, model: str | None = None) -> "OllamaClient":
        """Build from Settings.

        Unlike the cloud adapters, this reads the transport-specific
        ``ollama_model`` (``ATLAS_OLLAMA_MODEL``) rather than the cloud
        ``reasoning_model``/``judge_model`` identity — the caller may still
        pass an explicit ``model`` to override it. There is no default model
        (see ``MissingOllamaModelError``); an unset one fails clearly at build
        time. No API-key check: Ollama is keyless, so an unreachable host
        surfaces from ``complete()`` as a transport error instead.
        """
        resolved = model or settings.ollama_model
        if not resolved:
            raise MissingOllamaModelError(
                "No Ollama model configured. Set ATLAS_OLLAMA_MODEL in your "
                "environment or .env file, e.g.\n\n"
                "    ATLAS_OLLAMA_MODEL=qwen3:8b\n\n"
                "(any tag you've pulled with `ollama pull <model>`)."
            )
        return cls(
            host=settings.ollama_host,
            model=resolved,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )

    def complete(self, *, system: str, user: str) -> str:
        try:
            response = requests.post(
                f"{self._host}/api/generate",
                json={
                    "model": self._model,
                    "prompt": user,
                    "system": system,
                    "stream": False,
                    "options": {
                        "temperature": self._temperature,
                        "num_predict": self._max_tokens,
                    },
                },
                timeout=self._timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailableError(
                f"Couldn't connect to Ollama at {self._host}.\n\n"
                "Is Ollama running? Try:\n\n"
                "    ollama serve\n\n"
                "or start the Ollama desktop application."
            ) from exc
        response.raise_for_status()
        data = response.json()
        # Mirror the Gemini adapter's "empty rather than None" contract: a
        # well-formed non-streaming reply always carries "response", but guard
        # against its absence so complete() always returns a str.
        return str(data.get("response") or "")
