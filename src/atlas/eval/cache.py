"""Persistent LLM-response cache for free-tier evaluation.

Caches at the LLMClient boundary: any (system, user) completion is memoized
by (model, generation fingerprint, prompt_hash, context_hash), so an unchanged
case never re-invokes the LLM across separate `atlas eval run` invocations.
This is a pure decorator over LLMClient — it does not know or care whether it
wraps the reasoning client or the judge client, and Atlas's reasoning code
(ask.py, prompt.py) and judge.py's prompt-building are completely unaware it
exists. Deterministic scoring (correctness/grounding) never sees the cache at
all: it always scores whatever ReasoningResult/Answer comes back, cached or
not, identically — so "keep deterministic scoring unchanged" holds by
construction, not by care taken.

Key naming follows the spec literally: prompt_hash = hash(system prompt),
context_hash = hash(user prompt) — the user prompt is the fully-rendered
turn, which already embeds both the question and the evidence context
(build_user_prompt / Judge._prompt both bake the question in). A cache hit
therefore requires an identical model, an identical generation fingerprint
(temperature/max_tokens — the client-level settings a bare (system, user)
pair can't otherwise reveal, so a drift there can't silently produce a false
hit), an identical system prompt, AND an identical rendered context+question
— provably no false hits. "question" is additionally extracted (best-effort)
and stored as a plain, human-readable label on each entry for auditability;
it is not itself part of the lookup key, since context_hash already
determines it uniquely.

CACHE_VERSION guards the cache FILE's own on-disk schema (distinct from
prompt/context evolution, which content-hashing already invalidates
automatically with no version bump needed): a mismatched or missing version
is treated as a cold cache rather than an attempt to interpret
possibly-incompatible entries.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atlas.reasoning.llm import LLMClient

CACHE_VERSION = 1

_QUESTION_RE = re.compile(r"QUESTION:\s*(.+)")
_LABEL_MAX_CHARS = 200


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract_question_label(user: str) -> str:
    """Best-effort human-readable label for a cache entry.

    Not part of the lookup key — purely so a human reading the cache file
    can tell which question an entry belongs to without decoding a hash.
    Both build_user_prompt (reasoning) and Judge._prompt (judging) render a
    "QUESTION: ..." line, so this works for either without reasoning
    needing to know the cache exists.
    """
    match = _QUESTION_RE.search(user)
    label = match.group(1).strip() if match else user.strip()
    return label[:_LABEL_MAX_CHARS]


class EvalCache:
    """JSON-backed cache: (model, fingerprint, prompt_hash, context_hash) ->
    raw response.

    Loaded eagerly at construction. Writes are write-through (put() persists
    immediately) rather than buffered until a final save(), so a run
    interrupted partway through free-tier quota still keeps every case it
    completed before the interrupt — the scenario this cache exists for.
    save() remains available and is safe to call redundantly (e.g. once more
    at the end of a run for clarity).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.hits = 0
        self.misses = 0
        self._entries: dict[str, dict[str, str]] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if raw.get("cache_version") == CACHE_VERSION:
                    self._entries = raw.get("entries", {})
                # else: unversioned or incompatible file -> start cold rather
                # than risk misinterpreting entries written under a different
                # on-disk schema.
            except json.JSONDecodeError, OSError:
                self._entries = {}

    @staticmethod
    def make_key(
        model: str, fingerprint: str, prompt_hash: str, context_hash: str
    ) -> str:
        return f"{model}::{fingerprint}::{prompt_hash}::{context_hash}"

    def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        self.hits += 1
        return entry["response"]

    def put(
        self,
        key: str,
        *,
        model: str,
        fingerprint: str,
        prompt_hash: str,
        context_hash: str,
        question: str,
        response: str,
    ) -> None:
        self._entries[key] = {
            "model": model,
            "fingerprint": fingerprint,
            "prompt_hash": prompt_hash,
            "context_hash": context_hash,
            "question": question,
            "response": response,
        }
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"cache_version": CACHE_VERSION, "entries": self._entries}, indent=2
            ),
            encoding="utf-8",
        )

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}


class CachingLLMClient:
    """LLMClient decorator: memoizes complete(system, user) in a shared,
    persistent EvalCache, keyed by (model, fingerprint, sha256(system),
    sha256(user)).

    Constructed once per run (not per case) and reused for every case's
    complete() call — it derives everything it needs (including a
    human-readable question label) from the system/user text it receives,
    so no per-case wiring is required from the caller. ``fingerprint`` should
    encode any generation-affecting setting not visible in system/user text
    (e.g. temperature, max_tokens), so a future drift in those settings can't
    silently produce a false cache hit.
    """

    def __init__(
        self,
        inner: "LLMClient",
        cache: EvalCache,
        *,
        model: str,
        fingerprint: str = "",
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._model = model
        self._fingerprint = fingerprint

    def complete(self, *, system: str, user: str) -> str:
        prompt_hash = _hash(system)
        context_hash = _hash(user)
        key = EvalCache.make_key(
            self._model, self._fingerprint, prompt_hash, context_hash
        )

        cached = self._cache.get(key)
        if cached is not None:
            return cached

        response = self._inner.complete(system=system, user=user)
        self._cache.put(
            key,
            model=self._model,
            fingerprint=self._fingerprint,
            prompt_hash=prompt_hash,
            context_hash=context_hash,
            question=_extract_question_label(user),
            response=response,
        )
        return response
