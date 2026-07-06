"""Gemini adapter — designed, not implemented.

One adapter class is expected to serve BOTH the ``google_ai_studio`` and
``vertex_ai`` transports: the real ``google-genai`` SDK supports both backends
behind one client, differing only in constructor kwargs (API key vs.
project/region/ADC), per the provider-vs-adapter architecture amendment.
Building the real implementation is out of scope for this refactor; this stub
exists so the factory's dispatch table has a concrete, importable target, and
so selecting a Gemini transport fails loudly and clearly rather than silently
or with an import error.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atlas.config.settings import Settings
    from atlas.reasoning.llm.base import LLMProvider


class GeminiClient:
    """Not yet implemented. Will serve the google_ai_studio and vertex_ai transports."""

    @classmethod
    def from_settings(
        cls,
        settings: "Settings",
        *,
        provider: "LLMProvider",
        model: str | None = None,
    ) -> "GeminiClient":
        """Always raises: the Gemini adapter is designed but not yet built.

        ``provider`` distinguishes which transport (google_ai_studio vs.
        vertex_ai) the caller wants, since one adapter class serves both.
        """
        raise NotImplementedError(
            f"The Gemini adapter ({provider!r} transport) is designed but not yet "
            "implemented. See the architecture note on provider vs. model adapter "
            "vs. model identity."
        )

    def complete(self, *, system: str, user: str) -> str:
        """Never reachable: from_settings always raises before an instance exists.

        Declared so GeminiClient genuinely satisfies the LLMClient Protocol at
        the type level, not just in prose.
        """
        raise NotImplementedError("GeminiClient is not yet implemented.")
