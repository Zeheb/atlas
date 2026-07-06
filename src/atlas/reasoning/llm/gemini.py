"""Google Gen AI adapter — implements ``LLMClient`` for the ``google_ai_studio``
transport.

Uses the official Google Gen AI SDK (``google-genai``), the same SDK and the
same ``genai.Client`` that supports BOTH the Gemini Developer API (Google AI
Studio: ``api_key=``) and Vertex AI (``vertexai=True, project=, location=``)
— per the provider-vs-adapter architecture amendment, one adapter class is
meant to serve both transports. ``google_ai_studio`` is implemented here;
``vertex_ai`` still raises ``NotImplementedError`` (it needs project/region/
ADC wiring and verification against a live Vertex project, out of scope for
this task) — ``from_settings`` already threads the ``provider`` distinction
through, so building it later touches only this file, not the factory.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from atlas.reasoning.llm.base import MissingAPIKeyError

if TYPE_CHECKING:
    from atlas.config.settings import Settings
    from atlas.reasoning.llm.base import LLMProvider


class GeminiClient:
    """``LLMClient`` adapter for the Google Gen AI SDK (google_ai_studio transport)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> None:
        # Imported lazily so importing this module never requires the SDK to
        # be present at call sites that only use FakeLLMClient.
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    @classmethod
    def from_settings(
        cls,
        settings: "Settings",
        *,
        provider: "LLMProvider",
        model: str | None = None,
    ) -> "GeminiClient":
        """Build from Settings, failing clearly when no key is configured.

        ``provider`` distinguishes which transport (google_ai_studio vs.
        vertex_ai) the caller wants, since one adapter class serves both;
        only google_ai_studio is implemented today. ``max_tokens``/
        ``temperature`` are read from the same Settings.llm_max_tokens/
        llm_temperature knobs the Anthropic adapter uses — one determinism
        policy (G7), shared across every provider, not reinvented per adapter.
        """
        if provider == "vertex_ai":
            raise NotImplementedError(
                "The vertex_ai transport is designed but not yet implemented "
                "(needs project/region/ADC wiring). Use google_ai_studio, "
                "which is implemented."
            )
        if not settings.gemini_api_key:
            raise MissingAPIKeyError(
                "No Gemini API key configured. Set ATLAS_GEMINI_API_KEY "
                "in your environment or .env file."
            )
        return cls(
            api_key=settings.gemini_api_key,
            model=model or settings.reasoning_model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )

    def complete(self, *, system: str, user: str) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=self._temperature,
                max_output_tokens=self._max_tokens,
            ),
        )
        return response.text or ""
