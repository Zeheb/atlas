"""Diff between two remembered views of the SAME question (M-P2.7, Q23).

VALIDATION/COMPARISON ONLY -- no persistence, same discipline as
``staleness.py``. This module never imports ``research.memory``: it operates
on two already-loaded ``Thesis`` objects, so the store can change its
persistence format without this module's tests noticing, and this module
cannot accidentally grow into a stateful cache. The CLI is the one place that
composes ``ThesisStore`` lookup with this comparison, the same way it already
composes ``ThesisStore`` with ``staleness.check_staleness``.

Versioning itself already exists in ``ThesisStore`` (multiple distinct
``view_id``s per question are appended, never overwritten -- see
``thesis.compute_view_id``'s own docstring). The gap this module closes is
comparison: nothing previously answered "what changed between what I thought
then and what I think now."

Findings are matched by PRESENTATION-normalized statement text only --
lowercase, punctuation stripped, whitespace collapsed. No stemming, synonym
expansion, fuzzy matching, or semantic similarity: two statements that differ
in wording are ADDED/REMOVED, never merged as "the same finding reworded."
This is the same normalization discipline as ``query.engine.risk_recurrence``
(M-P2.6), applied here to thesis findings instead of risk factors.

Under-emit: comparing two theses that answer DIFFERENT questions would
misattribute an apparent "change" to what is really just a different
question, so ``diff_theses`` refuses (returns ``None``) rather than guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from atlas.research.thesis import Thesis

_RE_DIFF_PUNCT = re.compile(r"[^\w\s]")
_RE_DIFF_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Presentation-only normalization: lowercase, strip punctuation, collapse
    whitespace. Deliberately no stemming/synonyms/fuzzy matching -- the same
    discipline as ``query.engine._normalize_risk_text`` (M-P2.6)."""
    lowered = text.lower()
    no_punct = _RE_DIFF_PUNCT.sub(" ", lowered)
    return _RE_DIFF_WS.sub(" ", no_punct).strip()


@dataclass(frozen=True)
class ChangedFinding:
    """A finding present in both theses, under the same normalized statement,
    whose confidence differs."""

    statement: str          # verbatim statement from the NEWER thesis
    older_confidence: str
    newer_confidence: str


@dataclass(frozen=True)
class ThesisDiff:
    """The result of comparing two Thesis versions of the same question.

    ``added``/``removed`` hold verbatim statements (from the newer/older
    thesis respectively) that have no presentation-normalized match on the
    other side. ``changed`` holds findings matched by normalized statement
    whose confidence differs. Findings matched with identical statement AND
    identical confidence are UNCHANGED and are counted but not itemized --
    the diff reports what changed, not what stayed the same.
    """

    question: str
    older_view_id: str
    newer_view_id: str
    older_as_of: str
    newer_as_of: str
    older_overall_confidence: str
    newer_overall_confidence: str
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[ChangedFinding, ...]
    unchanged_count: int


def diff_theses(older: Thesis, newer: Thesis) -> ThesisDiff | None:
    """Compare *older* against *newer*. Returns ``None`` if their questions do
    not match under presentation normalization -- comparing answers to two
    different questions is refused, not guessed at (under-emit).

    "older"/"newer" are the caller's labels, not inferred from ``as_of``: the
    diff is directional by construction (added = in newer, not older; removed
    = in older, not newer), so reversing the two arguments inverts added/
    removed, exactly as a caller comparing in the other direction would expect.
    """
    if _normalize(older.question) != _normalize(newer.question):
        return None

    older_by_key = {_normalize(f.statement): f for f in older.result.findings}
    newer_by_key = {_normalize(f.statement): f for f in newer.result.findings}

    added: list[str] = [
        f.statement for key, f in newer_by_key.items() if key not in older_by_key
    ]
    removed: list[str] = [
        f.statement for key, f in older_by_key.items() if key not in newer_by_key
    ]
    changed: list[ChangedFinding] = []
    unchanged_count = 0
    for key, newer_f in newer_by_key.items():
        older_f = older_by_key.get(key)
        if older_f is None:
            continue
        if older_f.confidence == newer_f.confidence:
            unchanged_count += 1
        else:
            changed.append(ChangedFinding(
                statement=newer_f.statement,
                older_confidence=older_f.confidence,
                newer_confidence=newer_f.confidence,
            ))

    return ThesisDiff(
        question=newer.question,
        older_view_id=older.view_id,
        newer_view_id=newer.view_id,
        older_as_of=older.as_of,
        newer_as_of=newer.as_of,
        older_overall_confidence=older.result.overall_confidence,
        newer_overall_confidence=newer.result.overall_confidence,
        added=tuple(added),
        removed=tuple(removed),
        changed=tuple(changed),
        unchanged_count=unchanged_count,
    )
