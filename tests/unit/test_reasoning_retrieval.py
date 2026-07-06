"""Deterministic retrieval: find_excerpt + fetch_and_match (M1 commit 1).

find_excerpt is pure (no KB); fetch_and_match wraps a real, hermetic
KnowledgeBase built via its public .parse() API (mirrors the pattern in
test_knowledge_base.py) since this worktree has no real knowledge.db.
"""
from __future__ import annotations

from pathlib import Path

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.retrieval import _MAX_CONTENT_CHARS, fetch_and_match, find_excerpt

_ANNUAL_REPORT_TEXT = """
Business Overview

Tata Consultancy Services is a global IT services company.

Financial Highlights

Operating margin for the year stood at 24.2%, driven by continued cost
discipline and favourable currency movements across major markets. Revenue
grew 12% year on year.

Risk Factors

The company faces currency fluctuation risk given its global operations.
"""


def _kb_with_content(tmp_path: Path, evidence_id: str, content: str) -> KnowledgeBase:
    rel = "doc.txt"
    (tmp_path / rel).write_text(content, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id=evidence_id, source=EvidenceSource.BSE.value,
        kind=EvidenceKind.ANNUAL_REPORT.value, title="Test AR",
        source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
    )
    kb = KnowledgeBase(tmp_path)
    kb.parse(entry)
    return kb


# --- find_excerpt (pure) ------------------------------------------------------
def test_finds_excerpt_via_numeric_match() -> None:
    match = find_excerpt(_ANNUAL_REPORT_TEXT, "operating margin 24.2")
    assert match is not None
    assert "24.2" in match.excerpt


def test_excerpt_is_verbatim_substring_of_content() -> None:
    match = find_excerpt(_ANNUAL_REPORT_TEXT, "operating margin 24.2")
    assert match is not None
    assert match.excerpt in _ANNUAL_REPORT_TEXT
    assert _ANNUAL_REPORT_TEXT[match.char_offset : match.char_offset + len(match.excerpt)] == match.excerpt


def test_irrelevant_query_returns_none() -> None:
    assert find_excerpt(_ANNUAL_REPORT_TEXT, "quantum entanglement spacecraft") is None


def test_single_generic_word_alone_is_not_enough() -> None:
    # "the" is a stopword and "company" alone is one generic word: below the
    # >=2-word / any-numeric accept bar.
    assert find_excerpt(_ANNUAL_REPORT_TEXT, "company") is None


def test_two_distinct_words_can_match_without_a_number() -> None:
    match = find_excerpt(_ANNUAL_REPORT_TEXT, "currency fluctuation risk")
    assert match is not None
    assert "currency" in match.excerpt.lower()


def test_section_guess_finds_preceding_heading() -> None:
    match = find_excerpt(_ANNUAL_REPORT_TEXT, "operating margin 24.2")
    assert match is not None
    assert match.section == "Financial Highlights"


def test_empty_content_returns_none() -> None:
    assert find_excerpt("", "operating margin") is None


def test_oversized_content_returns_none() -> None:
    huge = "x " * (_MAX_CONTENT_CHARS // 2 + 10)
    assert find_excerpt(huge, "operating margin 24.2") is None


def test_relevance_is_high_for_numeric_match_medium_otherwise() -> None:
    numeric = find_excerpt(_ANNUAL_REPORT_TEXT, "operating margin 24.2")
    words_only = find_excerpt(_ANNUAL_REPORT_TEXT, "currency fluctuation risk")
    assert numeric is not None and numeric.relevance == "high"
    assert words_only is not None and words_only.relevance == "medium"


# --- fetch_and_match (KB-backed, hermetic) -----------------------------------
def test_fetch_and_match_finds_excerpt_from_real_kb(tmp_path: Path) -> None:
    kb = _kb_with_content(tmp_path, "ev-1", _ANNUAL_REPORT_TEXT)
    match = fetch_and_match(kb, "ev-1", "operating margin 24.2", content_cache={})
    assert match is not None
    assert "24.2" in match.excerpt


def test_fetch_and_match_unknown_id_returns_none(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path)
    assert fetch_and_match(kb, "ev-missing", "anything relevant here", content_cache={}) is None


def test_fetch_and_match_reuses_cache_across_calls(tmp_path: Path) -> None:
    kb = _kb_with_content(tmp_path, "ev-1", _ANNUAL_REPORT_TEXT)
    cache: dict[str, str | None] = {}
    fetch_and_match(kb, "ev-1", "operating margin 24.2", content_cache=cache)
    assert "ev-1" in cache

    def _boom(_eid: str) -> str | None:
        raise AssertionError("get_content should not be called again — cache miss")

    kb.get_content = _boom  # type: ignore[method-assign]
    # Second call for the same id must not touch get_content again.
    match = fetch_and_match(kb, "ev-1", "revenue grew 12", content_cache=cache)
    assert match is not None
