"""Question-conditioned top-K passage retrieval (M1.5 commit 1, ADR-M1.5).

retrieve_passages is question-conditioned (query = the user's question) across
multiple documents, unlike find_excerpt/fetch_and_match (claim-conditioned,
single document). Same hermetic-KB pattern as M1's retrieval tests.
"""

from __future__ import annotations

from pathlib import Path

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.retrieval import retrieve_passages

_MARGIN_TEXT = "Operating margin stood at 24.2% in FY26, an improvement over last year."
_RISK_TEXT = "Currency fluctuation risk affects our overseas operations significantly."
_IRRELEVANT_TEXT = "The quarterly board meeting discussed general governance policies."

_QUESTION = "What was the operating margin 24.2 and the currency fluctuation risk?"


def _kb_with_docs(tmp_path: Path, docs: dict[str, str]) -> KnowledgeBase:
    kb = KnowledgeBase(tmp_path)
    for evidence_id, content in docs.items():
        rel = f"{evidence_id}.txt"
        (tmp_path / rel).write_text(content, encoding="utf-8")
        entry = CatalogEntry(
            evidence_id=evidence_id,
            source=EvidenceSource.BSE.value,
            kind=EvidenceKind.ANNUAL_REPORT.value,
            title="Test doc",
            source_date="2026-03-31T00:00:00+00:00",
            document_url=None,
            local_path=rel,
            file_size_bytes=None,
            acquired_at="2026-04-01T00:00:00+00:00",
        )
        kb.parse(entry)
    return kb


def test_returns_passages_from_multiple_docs_ranked_by_score(tmp_path: Path) -> None:
    kb = _kb_with_docs(
        tmp_path,
        {
            "ev-1": _MARGIN_TEXT,
            "ev-2": _RISK_TEXT,
            "ev-3": _IRRELEVANT_TEXT,
        },
    )
    results = retrieve_passages(kb, ["ev-1", "ev-2", "ev-3"], _QUESTION, k=5)
    doc_ids = [doc_id for doc_id, _match in results]
    assert doc_ids == [
        "ev-1",
        "ev-2",
    ]  # ev-1 (numeric match) outranks ev-2 (word-only); ev-3 excluded


def test_k_limits_result_count(tmp_path: Path) -> None:
    kb = _kb_with_docs(tmp_path, {"ev-1": _MARGIN_TEXT, "ev-2": _RISK_TEXT})
    results = retrieve_passages(kb, ["ev-1", "ev-2"], _QUESTION, k=1)
    assert len(results) == 1
    assert results[0][0] == "ev-1"  # highest score kept


def test_irrelevant_question_returns_empty() -> None:
    results = retrieve_passages(
        KnowledgeBase(Path(".")),
        ["ev-1"],
        "quantum entanglement spacecraft telemetry",
    )
    assert results == []


def test_empty_doc_ids_returns_empty(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path)
    assert retrieve_passages(kb, [], _QUESTION) == []


def test_overlapping_windows_in_same_doc_are_deduplicated(tmp_path: Path) -> None:
    filler_before = "Filler sentence content here. " * 25  # ~750 chars
    filler_after = "More filler sentence content. " * 25
    long_paragraph = filler_before + _RISK_TEXT + filler_after
    kb = _kb_with_docs(tmp_path, {"ev-1": long_paragraph})
    results = retrieve_passages(kb, ["ev-1"], "currency fluctuation risk", k=5)
    # Even though multiple overlapping windows may score the same phrase, only
    # one non-overlapping match per document survives (no near-duplicate slices).
    ev1_results = [m for doc_id, m in results if doc_id == "ev-1"]
    assert len(ev1_results) == 1


def test_reuses_content_cache_across_calls(tmp_path: Path) -> None:
    kb = _kb_with_docs(tmp_path, {"ev-1": _MARGIN_TEXT})
    cache: dict[str, str | None] = {}
    retrieve_passages(kb, ["ev-1"], _QUESTION, content_cache=cache)
    assert "ev-1" in cache

    def _boom(_eid: str) -> str | None:
        raise AssertionError(
            "get_content should not be called again — cache hit expected"
        )

    kb.get_content = _boom  # type: ignore[method-assign]
    results = retrieve_passages(kb, ["ev-1"], _QUESTION, content_cache=cache)
    assert results  # succeeded purely from cache, no new DB read


def test_deterministic_tie_break_by_doc_id(tmp_path: Path) -> None:
    # Two docs with IDENTICAL scoring content -> tie broken by doc_id ascending.
    kb = _kb_with_docs(tmp_path, {"ev-b": _RISK_TEXT, "ev-a": _RISK_TEXT})
    results = retrieve_passages(kb, ["ev-b", "ev-a"], "currency fluctuation risk", k=5)
    assert [doc_id for doc_id, _m in results] == ["ev-a", "ev-b"]


def test_result_excerpts_are_verbatim_substrings(tmp_path: Path) -> None:
    kb = _kb_with_docs(tmp_path, {"ev-1": _MARGIN_TEXT})
    results = retrieve_passages(kb, ["ev-1"], _QUESTION)
    assert results
    _doc_id, match = results[0]
    assert match.excerpt in _MARGIN_TEXT
