"""Deterministic raw-text retrieval (M1 commit 1; M1.5 commit 1 adds
question-conditioned top-K passages).

Finds a verbatim excerpt in a document's extracted text that supports a given
statement, using keyword overlap — no embeddings, no vector store (none exist
in the architecture; this stays a reproducible, auditable lexical match, the
same "deterministic floor" philosophy as the rest of Atlas). This is the
*grounding validator* named in the M1 milestone: a match is accepted only when
it clears a confidence bar, so a weak/incidental overlap never masquerades as
verbatim support (Faithfulness / G10).

``RetrievalMatch`` is an internal implementation detail, not a §10 contract
type — it never crosses the reasoning package boundary; ``context.py`` turns an
accepted match into an ordinary ``EvidenceReference``.

M1.5 (ADR-M1.5): ``find_excerpt`` is *claim*-conditioned (query = a claim's own
statement) — it answers "does this document support this fact I already have?"
``retrieve_passages`` is *question*-conditioned (query = the user's question)
across several candidate documents — it answers "which passages, across what
Atlas already holds, actually bear on what's being asked?" Same deterministic
scoring floor; different query source and cardinality (one best match vs top-K
across documents).

M1.7 (retrieval planning): ``retrieve_with_plan`` adds a THIRD mode, plan-
conditioned — query terms, doc-type preferences, and period/date hints all
come from a ``SearchPlan`` (``plan.py``) rather than a bare question string.
``retrieve_passages`` is untouched (same function, same behavior, same
tests) — it stays the M1.5 code path for callers that never build a plan.

``retrieve_with_plan`` is split into two stages on purpose:

  * ``_generate_candidates`` applies the UNCHANGED accept bar
    (``_clears_accept_bar``) and never looks at ``preferred_doc_types`` or
    ``date_window`` — its output set is provably identical to what
    ``retrieve_passages`` would consider for the same doc_ids/query terms.
    This is what makes the M1.7 fallback guarantee ("a plan can never return
    fewer results than an unplanned query") structural rather than a relax
    pass: ranking cannot remove a candidate, only reorder and truncate.
  * ``_rank_and_select`` applies every plan-derived boost (doc-type, recency,
    period, date-window, numeric) purely additively on top of the same
    ``matched_words + 2*matched_numbers`` base score, then dedups/truncates
    to ``top_k`` exactly as ``retrieve_passages`` already does.

Swapping in a real reranking model later replaces ``_rank_and_select`` alone.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from atlas.knowledge.base import KnowledgeBase, ParsedDocument
from atlas.reasoning.contracts import ConfidenceLevel
from atlas.reasoning.plan import SearchPlan
from atlas.reasoning.text import _TOKEN_RE, keywords as _keywords, tokenize as _tokenize

# Defensive bound: skip retrieval entirely for pathologically large documents
# rather than risk slow tokenization/scanning.
_MAX_CONTENT_CHARS = 2_000_000

_WINDOW_CHARS_DEFAULT = 240
# A paragraph longer than this is re-chunked into overlapping slices so a
# single match doesn't drag in an entire mega-section.
_MAX_PARAGRAPH_CHARS = 900
_SLIDE_STRIDE = 450


@dataclass(frozen=True)
class RetrievalMatch:
    """One accepted excerpt match. Internal — not a §10 contract type."""

    excerpt: str
    char_offset: int
    section: str | None
    relevance: ConfidenceLevel


def _windows(content: str) -> list[tuple[int, str]]:
    """Split *content* into (start_offset, text) windows to score independently."""
    out: list[tuple[int, str]] = []
    pos = 0
    for para in re.split(r"\n\s*\n", content):
        start = content.index(para, pos) if para else pos
        pos = start + len(para)
        if not para.strip():
            continue
        if len(para) <= _MAX_PARAGRAPH_CHARS:
            out.append((start, para))
            continue
        # Re-chunk an oversized paragraph into overlapping slices.
        for local in range(0, len(para), _SLIDE_STRIDE):
            chunk = para[local : local + _MAX_PARAGRAPH_CHARS]
            if chunk.strip():
                out.append((start + local, chunk))
    return out


def _guess_section(content: str, char_offset: int) -> str | None:
    """Best-effort nearest-preceding short line that looks like a heading."""
    lookback_start = max(0, char_offset - 500)
    preceding = content[lookback_start:char_offset]
    for line in reversed(preceding.splitlines()):
        stripped = line.strip()
        if not stripped or len(stripped) > 80:
            continue
        if stripped.endswith((".", ",", ";")):
            continue
        return stripped
    return None


def _trim_excerpt(window_text: str, keyword_pos: int, window_chars: int) -> str:
    half = window_chars // 2
    start = max(0, keyword_pos - half)
    end = min(len(window_text), keyword_pos + half)
    # Snap outward to whitespace so we never cut mid-word.
    while start > 0 and not window_text[start - 1].isspace():
        start -= 1
    while end < len(window_text) and not window_text[end].isspace():
        end += 1
    return window_text[start:end].strip()


# Accept bar shared by find_excerpt and retrieve_passages: >=2 distinct word
# matches, OR any numeric match (numbers are rare/high-precision signals for
# financial claims).
def _clears_accept_bar(matched_words: int, matched_numbers: int) -> bool:
    return matched_words >= 2 or matched_numbers >= 1


def _finalize_match(
    content: str, start: int, text: str, all_keywords: set[str],
    window_chars: int, has_numeric: bool,
) -> RetrievalMatch:
    """Trim *text* around its first matched keyword and locate it in *content*."""
    tokens_with_pos = [
        (m.start(), m.group().lower()) for m in _TOKEN_RE.finditer(text)
    ]
    anchor = next((pos for pos, tok in tokens_with_pos if tok in all_keywords), 0)

    excerpt = _trim_excerpt(text, anchor, window_chars)
    char_offset = content.index(excerpt, max(0, start - 50)) if excerpt else start
    if char_offset == -1:
        # Extremely defensive fallback; should not happen since excerpt is a
        # substring of `text`, which is itself a substring of `content`.
        char_offset = start

    return RetrievalMatch(
        excerpt=excerpt,
        char_offset=char_offset,
        section=_guess_section(content, char_offset),
        relevance="high" if has_numeric else "medium",
    )


def find_excerpt(
    content: str, query: str, *, window_chars: int = _WINDOW_CHARS_DEFAULT
) -> RetrievalMatch | None:
    """Find the best verbatim excerpt in *content* supporting *query*.

    Returns None when no window clears the confidence bar — declaring "no
    confident match" rather than returning a weak, misleading excerpt (G5).
    """
    if not content or len(content) > _MAX_CONTENT_CHARS:
        return None
    q_words, q_numbers = _keywords(query)
    if not q_words and not q_numbers:
        return None

    best: tuple[int, int, int, str] | None = None  # (score, start, has_numeric, text)
    for start, text in _windows(content):
        w_words, w_numbers = _keywords(text)
        matched_words = len(q_words & w_words)
        matched_numbers = len(q_numbers & w_numbers)
        if not _clears_accept_bar(matched_words, matched_numbers):
            continue
        score = matched_words + 2 * matched_numbers
        if best is None or score > best[0]:
            best = (score, start, matched_numbers, text)

    if best is None:
        return None
    _score, start, has_numeric, text = best
    return _finalize_match(content, start, text, q_words | q_numbers, window_chars, bool(has_numeric))


def retrieve_passages(
    kb: KnowledgeBase,
    doc_ids: Iterable[str],
    question: str,
    *,
    k: int = 5,
    content_cache: dict[str, str | None] | None = None,
    window_chars: int = _WINDOW_CHARS_DEFAULT,
) -> list[tuple[str, RetrievalMatch]]:
    """Top-K passages across *doc_ids* matching *question*'s keywords.

    Question-conditioned (ADR-M1.5), unlike ``find_excerpt``/``fetch_and_match``
    which are claim-conditioned. Same deterministic accept bar and windowing;
    generalizes "keep the single best window" to "keep the best K, one per
    non-overlapping span, across documents" — no embeddings, no index.

    Deterministic tie-break: (score desc, doc_id asc, char_offset asc), so the
    result is reproducible regardless of dict/set iteration order.

    Returns [] when *question* yields no usable keywords or no window clears
    the accept bar — declaring "nothing relevant found" rather than guessing.
    """
    cache: dict[str, str | None] = content_cache if content_cache is not None else {}
    q_words, q_numbers = _keywords(question)
    if not q_words and not q_numbers:
        return []

    # (score, doc_id, start, text, has_numeric)
    candidates: list[tuple[int, str, int, str, bool]] = []
    for doc_id in sorted(set(doc_ids)):
        if doc_id not in cache:
            cache[doc_id] = kb.get_content(doc_id)
        content = cache[doc_id]
        if not content or len(content) > _MAX_CONTENT_CHARS:
            continue
        for start, text in _windows(content):
            w_words, w_numbers = _keywords(text)
            matched_words = len(q_words & w_words)
            matched_numbers = len(q_numbers & w_numbers)
            if not _clears_accept_bar(matched_words, matched_numbers):
                continue
            score = matched_words + 2 * matched_numbers
            candidates.append((score, doc_id, start, text, matched_numbers > 0))

    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    all_keywords = q_words | q_numbers
    selected: list[tuple[int, str, int, str, bool]] = []
    for cand in candidates:
        _score, doc_id, start, text, _has_numeric = cand
        end = start + len(text)
        # Skip windows that overlap an already-selected, higher-ranked window
        # from the SAME document — avoids near-duplicate slices dominating
        # top-K (a simple deterministic dedup, not a ranking heuristic).
        overlaps = any(
            s_doc == doc_id and not (end <= s_start or start >= s_start + len(s_text))
            for _s, s_doc, s_start, s_text, _n in selected
        )
        if overlaps:
            continue
        selected.append(cand)
        if len(selected) >= k:
            break

    results: list[tuple[str, RetrievalMatch]] = []
    for _score, doc_id, start, text, has_numeric in selected:
        content = cache[doc_id]
        assert content is not None  # guaranteed: doc_id only entered candidates if content is set
        match = _finalize_match(content, start, text, all_keywords, window_chars, has_numeric)
        results.append((doc_id, match))
    return results


# ---------------------------------------------------------------------------
# M1.7: plan-conditioned retrieval
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RetrievalResult:
    """Matches plus the diagnostics needed to verify how they were chosen.

    Internal, like ``RetrievalMatch`` — not a §10 contract type. Capped at
    these four fields on purpose: an observability seam, not a scratch pad.
    """

    matches: tuple[tuple[str, RetrievalMatch], ...]
    plan: SearchPlan
    candidates_considered: int
    docs_missing_metadata: tuple[str, ...]


@dataclass(frozen=True)
class _Candidate:
    """One window that cleared the accept bar. Plan-independent — the same
    shape whether or not a SearchPlan is in play.
    """

    doc_id: str
    start: int
    text: str
    matched_words: int
    matched_numbers: int


def _generate_candidates(
    kb: KnowledgeBase,
    doc_ids: Iterable[str],
    query_terms: frozenset[str],
    numeric_terms: frozenset[str],
    content_cache: dict[str, str | None],
) -> list[_Candidate]:
    """Apply the UNCHANGED accept bar across every window of every doc_id.

    Deliberately consults nothing from a SearchPlan beyond its query/numeric
    terms — see the module docstring for why that is what makes the fallback
    guarantee structural rather than a relax pass.
    """
    candidates: list[_Candidate] = []
    for doc_id in sorted(set(doc_ids)):
        if doc_id not in content_cache:
            content_cache[doc_id] = kb.get_content(doc_id)
        content = content_cache[doc_id]
        if not content or len(content) > _MAX_CONTENT_CHARS:
            continue
        for start, text in _windows(content):
            w_words, w_numbers = _keywords(text)
            matched_words = len(query_terms & w_words)
            matched_numbers = len(numeric_terms & w_numbers)
            if not _clears_accept_bar(matched_words, matched_numbers):
                continue
            candidates.append(_Candidate(doc_id, start, text, matched_words, matched_numbers))
    return candidates


def _doc_type_boost(doc: ParsedDocument | None, plan: SearchPlan) -> int:
    if doc is None:
        return 0
    for pref in plan.preferred_doc_types:
        if pref.kind == doc.kind:
            return pref.weight
    return 0


def _date_prefix(source_date: str) -> str | None:
    """Best-effort YYYY-MM-DD prefix, lexically comparable to a DateWindow
    bound. Returns None rather than raising on a malformed/short string —
    a date-based boost simply doesn't fire, it never crashes retrieval.
    """
    return source_date[:10] if source_date and len(source_date) >= 10 else None


def _recency_ranks(doc_ids: Iterable[str], metadata: dict[str, ParsedDocument]) -> dict[str, int]:
    """Rank *doc_ids* by source_date descending (0 = most recent).

    Docs with no metadata or an unparseable date sort last — a missing
    signal degrades to "no boost," never to an error or a crash.
    """
    dated: list[tuple[str, str]] = []
    undated: list[str] = []
    for doc_id in doc_ids:
        doc = metadata.get(doc_id)
        prefix = _date_prefix(doc.source_date) if doc is not None else None
        (dated.append((doc_id, prefix)) if prefix is not None else undated.append(doc_id))
    dated.sort(key=lambda pair: pair[1], reverse=True)
    ranks: dict[str, int] = {doc_id: rank for rank, (doc_id, _date) in enumerate(dated)}
    base = len(dated)
    for offset, doc_id in enumerate(undated):
        ranks[doc_id] = base + offset
    return ranks


def _date_window_boost(doc: ParsedDocument | None, plan: SearchPlan) -> int:
    if plan.date_window is None or doc is None:
        return 0
    prefix = _date_prefix(doc.source_date)
    if prefix is None:
        return 0
    if plan.date_window.start is not None and prefix < plan.date_window.start:
        return 0
    if plan.date_window.end is not None and prefix > plan.date_window.end:
        return 0
    return 25


def _period_boost(text: str, plan: SearchPlan) -> int:
    if not plan.periods:
        return 0
    # Whitespace-insensitive substring match: a plan period like "Q3FY2024"
    # should still hit prose rendered as "Q3 FY2024" or "Q3-FY2024". A bonus
    # signal only (additive), so a miss here never excludes a candidate.
    normalized_text = re.sub(r"\s+", "", text).lower()
    for period in plan.periods:
        if re.sub(r"\s+", "", period).lower() in normalized_text:
            return 40
    return 0


def _rank_and_select(
    candidates: list[_Candidate],
    plan: SearchPlan,
    metadata: dict[str, ParsedDocument],
) -> list[_Candidate]:
    """Score every candidate with plan-derived boosts, then dedup/truncate to
    ``plan.top_k`` — the same same-document-overlap dedup ``retrieve_passages``
    uses, plus ``rerank.max_per_document`` when the plan sets it.

    Purely additive on top of the unchanged base score: ranking can reorder
    and truncate ``candidates`` but never grows or shrinks the set it was
    given (that already happened in ``_generate_candidates``).
    """
    recency_ranks = _recency_ranks((c.doc_id for c in candidates), metadata) if plan.rerank.prefer_recent else {}

    scored: list[tuple[int, str, int, _Candidate]] = []
    for cand in candidates:
        doc = metadata.get(cand.doc_id)
        base = cand.matched_words + 2 * cand.matched_numbers
        score = base * 100
        score += _doc_type_boost(doc, plan)
        score += _date_window_boost(doc, plan)
        score += _period_boost(cand.text, plan)
        if plan.rerank.prefer_recent:
            rank = recency_ranks.get(cand.doc_id, len(recency_ranks))
            score += max(0, 30 - 3 * rank)
        if plan.rerank.prefer_numeric and cand.matched_numbers > 0:
            score += 20
        scored.append((score, cand.doc_id, cand.start, cand))

    scored.sort(key=lambda s: (-s[0], s[1], s[2]))

    per_doc_count: dict[str, int] = {}
    selected: list[_Candidate] = []
    for _score, doc_id, start, cand in scored:
        end = start + len(cand.text)
        overlaps = any(
            s.doc_id == doc_id and not (end <= s.start or start >= s.start + len(s.text))
            for s in selected
        )
        if overlaps:
            continue
        if plan.rerank.max_per_document is not None:
            if per_doc_count.get(doc_id, 0) >= plan.rerank.max_per_document:
                continue
        selected.append(cand)
        per_doc_count[doc_id] = per_doc_count.get(doc_id, 0) + 1
        if len(selected) >= plan.top_k:
            break
    return selected


def retrieve_with_plan(
    kb: KnowledgeBase,
    doc_ids: Iterable[str],
    plan: SearchPlan,
    *,
    content_cache: dict[str, str | None] | None = None,
    window_chars: int = _WINDOW_CHARS_DEFAULT,
) -> RetrievalResult:
    """Plan-conditioned counterpart to ``retrieve_passages`` (M1.7).

    Candidate generation applies the identical accept bar ``retrieve_passages``
    uses — see the module docstring for why that makes this call's result set
    a superset-or-equal of ``retrieve_passages``'s for the same ``top_k``.
    Only ranking differs, driven by ``plan``'s doc-type/date/period/rerank
    hints, all additive boosts.

    One ``KnowledgeBase.get_many()`` call fetches metadata for every distinct
    doc_id — a single round trip regardless of how many boosts consult it.
    """
    cache: dict[str, str | None] = content_cache if content_cache is not None else {}
    query_terms = frozenset(plan.query_terms)
    numeric_terms = frozenset(plan.numeric_terms)

    unique_doc_ids = sorted(set(doc_ids))
    metadata = kb.get_many(unique_doc_ids)
    docs_missing_metadata = tuple(d for d in unique_doc_ids if d not in metadata)

    if not query_terms and not numeric_terms:
        return RetrievalResult((), plan, 0, docs_missing_metadata)

    candidates = _generate_candidates(kb, unique_doc_ids, query_terms, numeric_terms, cache)
    selected = _rank_and_select(candidates, plan, metadata)

    all_keywords = query_terms | numeric_terms
    results: list[tuple[str, RetrievalMatch]] = []
    for cand in selected:
        content = cache[cand.doc_id]
        assert content is not None  # guaranteed: doc_id only entered candidates if content is set
        match = _finalize_match(
            content, cand.start, cand.text, all_keywords, window_chars, cand.matched_numbers > 0,
        )
        results.append((cand.doc_id, match))

    return RetrievalResult(tuple(results), plan, len(candidates), docs_missing_metadata)


def fetch_and_match(
    kb: KnowledgeBase,
    evidence_id: str,
    query: str,
    *,
    content_cache: dict[str, str | None],
    window_chars: int = _WINDOW_CHARS_DEFAULT,
) -> RetrievalMatch | None:
    """Fetch *evidence_id*'s content (cached across calls) and find an excerpt."""
    if evidence_id not in content_cache:
        content_cache[evidence_id] = kb.get_content(evidence_id)
    content = content_cache[evidence_id]
    if content is None:
        return None
    return find_excerpt(content, query, window_chars=window_chars)
