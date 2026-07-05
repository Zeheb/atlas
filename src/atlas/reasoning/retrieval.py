"""Deterministic raw-text retrieval (M1 commit 1).

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
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.contracts import ConfidenceLevel

# Defensive bound: skip retrieval entirely for pathologically large documents
# rather than risk slow tokenization/scanning.
_MAX_CONTENT_CHARS = 2_000_000

_WINDOW_CHARS_DEFAULT = 240
# A paragraph longer than this is re-chunked into overlapping slices so a
# single match doesn't drag in an entire mega-section.
_MAX_PARAGRAPH_CHARS = 900
_SLIDE_STRIDE = 450

_TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?")

_STOPWORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "is",
    "are", "was", "were", "be", "been", "being", "has", "have", "had", "this",
    "that", "these", "those", "with", "as", "by", "from", "it", "its", "their",
    "they", "which", "what", "how", "does", "do", "did", "will", "would",
    "can", "could", "about", "over", "under", "than", "then", "if", "not",
    "no", "yes", "you", "your", "we", "our", "i", "he", "she", "them", "his",
    "her", "there", "here", "such", "any", "all", "so", "but", "also",
})


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _keywords(text: str) -> tuple[set[str], set[str]]:
    """Return (word_keywords, numeric_keywords) from *text*, stopwords dropped."""
    words: set[str] = set()
    numbers: set[str] = set()
    for tok in _tokenize(text):
        if tok[0].isdigit():
            numbers.add(tok)
        elif tok not in _STOPWORDS and len(tok) >= 3:
            words.add(tok)
    return words, numbers


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
        score = matched_words + 2 * matched_numbers
        # Accept bar: >=2 distinct word matches, OR any numeric match (numbers
        # are rare/high-precision signals for financial claims).
        if matched_words < 2 and matched_numbers < 1:
            continue
        if best is None or score > best[0]:
            best = (score, start, matched_numbers, text)

    if best is None:
        return None
    _score, start, has_numeric, text = best

    # Anchor the trim on the first matched keyword's position in the window.
    all_keywords = q_words | q_numbers
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
