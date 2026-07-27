"""OmniRoute adapter — implements ``LLMClient`` for the ``omniroute`` transport.

Talks to an external OmniRoute HTTP gateway at ``http://localhost:20128``
(or ``ATLAS_OMNIROUTE_BASE_URL``) using an Anthropic-compatible Messages API.
This is the one thing in Atlas that knows OmniRoute's request/response shape;
everything above it (reasoning, eval) depends only on the ``LLMClient`` Protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import requests

from atlas.reasoning.llm.base import LLMTransportError

if TYPE_CHECKING:
    from atlas.config.settings import Settings


# OmniRoute can be slower than cloud round-trips but faster than Ollama,
# so we'll use a slightly longer timeout than the default 30s.
_DEFAULT_TIMEOUT_SECONDS = 60.0


class OmniRouteUnavailableError(LLMTransportError):
    """Raised when the OmniRoute server can't be reached at ``complete()`` time."""


class OmniRouteClient:
    """``LLMClient`` adapter for the OmniRoute gateway (Anthropic-compatible Messages API)."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._timeout = timeout

    @classmethod
    def from_settings(
        cls, settings: "Settings", *, model: str | None = None
    ) -> "OmniRouteClient":
        """Build from Settings.

        Reuses Atlas's shared model identity exactly like ``AnthropicClient``:
        ``model`` defaults to ``settings.reasoning_model`` (the eval harness
        passes ``settings.judge_model`` for the judge role). For this transport
        that string is an OmniRoute model/combo name, e.g. ``"test_cc"``.
        ``max_tokens``/``temperature`` come from the shared Settings knobs so the
        determinism floor (G7) is one policy across every provider. The API key
        is optional (local dev needs none); an unreachable gateway surfaces from
        ``complete()`` as a transport error, not a build-time error.
        """
        return cls(
            base_url=settings.omniroute_base_url,
            model=model or settings.reasoning_model,
            api_key=settings.omniroute_api_key,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )

    def complete(self, *, system: str, user: str) -> str:
        headers = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        try:
            response = requests.post(
                f"{self._base_url}/v1/messages",
                json={
                    "model": self._model,
                    "max_tokens": self._max_tokens,
                    "temperature": self._temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                headers=headers,
                timeout=self._timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise OmniRouteUnavailableError(
                f"Couldn't connect to OmniRoute at {self._base_url}. "
                "Is OmniRoute running?"
            ) from exc
        response.raise_for_status()
        data = response.json()

        # Parse text blocks, mirroring AnthropicClient. Follow the sibling
        # adapters' "empty rather than None" contract: a well-formed reply always
        # carries "content", but guard its absence so complete() always returns str.
        parts = [
            block["text"]
            for block in data.get("content", [])
            if block["type"] == "text"
        ]
        return "".join(parts)
