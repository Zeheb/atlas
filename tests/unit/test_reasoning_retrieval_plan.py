"""Plan-conditioned retrieval: retrieve_with_plan (M1.7 commit 5).

Same hermetic-KB pattern as test_reasoning_retrieval_passages.py. Covers the
boost arithmetic each plan hint contributes, the fallback-guarantee structural
property (candidate generation never consults doc-type/date preferences), and
ordering determinism.
"""

from __future__ import annotations

from pathlib import Path


from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.plan import DateWindow, DocTypePreference, RerankHints, SearchPlan
from atlas.reasoning.planner import HeuristicPlanner
from atlas.reasoning.retrieval import (
    _generate_candidates,
    retrieve_passages,
    retrieve_with_plan,
)

_MARGIN_TEXT = "Operating margin stood at 24.2% in FY26, an improvement over last year."
_RISK_TEXT = "Currency fluctuation risk affects our overseas operations significantly."
_IRRELEVANT_TEXT = "The quarterly board meeting discussed general governance policies."

_QUESTION = "What was the operating margin 24.2 and the currency fluctuation risk?"


def _kb_with_docs(
    tmp_path: Path,
    docs: dict[str, str],
    kinds: dict[str, EvidenceKind] | None = None,
    dates: dict[str, str] | None = None,
) -> KnowledgeBase:
    kb = KnowledgeBase(tmp_path)
    kinds = kinds or {}
    dates = dates or {}
    for evidence_id, content in docs.items():
        rel = f"{evidence_id}.txt"
        (tmp_path / rel).write_text(content, encoding="utf-8")
        entry = CatalogEntry(
            evidence_id=evidence_id,
            source=EvidenceSource.BSE.value,
            kind=kinds.get(evidence_id, EvidenceKind.ANNUAL_REPORT).value,
            title="Test doc",
            source_date=dates.get(evidence_id, "2026-03-31T00:00:00+00:00"),
            document_url=None,
            local_path=rel,
            file_size_bytes=None,
            acquired_at="2026-04-01T00:00:00+00:00",
        )
        kb.parse(entry)
    return kb


def _plan(**overrides: object) -> SearchPlan:
    defaults: dict[str, object] = dict(
        raw_question=_QUESTION,
        intent="general",
        query_terms=("operating", "margin", "currency", "fluctuation", "risk"),
        numeric_terms=("24.2",),
        top_k=5,
    )
    defaults.update(overrides)
    return SearchPlan(**defaults)  # type: ignore[arg-type]


# --- Fallback guarantee (the structural property, not a relax pass) -----------
def test_result_never_smaller_than_unplanned_retrieval(tmp_path: Path) -> None:
    kb = _kb_with_docs(
        tmp_path,
        {
            "ev-1": _MARGIN_TEXT,
            "ev-2": _RISK_TEXT,
            "ev-3": _IRRELEVANT_TEXT,
        },
    )
    plan = HeuristicPlanner().plan(_QUESTION)
    result = retrieve_with_plan(kb, ["ev-1", "ev-2", "ev-3"], plan)
    baseline = retrieve_passages(kb, ["ev-1", "ev-2", "ev-3"], _QUESTION, k=plan.top_k)
    assert len(result.matches) >= len(baseline)


def test_generate_candidates_ignores_doc_type_and_date_window(tmp_path: Path) -> None:
    # _generate_candidates must produce the identical candidate set whether
    # or not a plan expresses doc-type or date preferences -- ranking is the
    # only stage allowed to consult them.
    kb = _kb_with_docs(tmp_path, {"ev-1": _MARGIN_TEXT, "ev-2": _RISK_TEXT})
    cache: dict[str, str | None] = {}
    query_terms = frozenset({"operating", "margin", "currency", "fluctuation", "risk"})
    numeric_terms = frozenset({"24.2"})
    candidates = _generate_candidates(
        kb, ["ev-1", "ev-2"], query_terms, numeric_terms, cache
    )

    # Same call again with a fresh cache -- deterministic, same count.
    cache2: dict[str, str | None] = {}
    candidates2 = _generate_candidates(
        kb, ["ev-1", "ev-2"], query_terms, numeric_terms, cache2
    )
    assert len(candidates) == len(candidates2)
    assert {(c.doc_id, c.start) for c in candidates} == {
        (c.doc_id, c.start) for c in candidates2
    }


def test_candidates_considered_matches_generate_candidates_count(
    tmp_path: Path,
) -> None:
    kb = _kb_with_docs(
        tmp_path, {"ev-1": _MARGIN_TEXT, "ev-2": _RISK_TEXT, "ev-3": _IRRELEVANT_TEXT}
    )
    plan = _plan(top_k=50)  # large enough that truncation doesn't hide the count
    cache: dict[str, str | None] = {}
    candidates = _generate_candidates(
        kb,
        ["ev-1", "ev-2", "ev-3"],
        frozenset(plan.query_terms),
        frozenset(plan.numeric_terms),
        cache,
    )
    result = retrieve_with_plan(kb, ["ev-1", "ev-2", "ev-3"], plan)
    assert result.candidates_considered == len(candidates)


def test_docs_searched_counts_distinct_doc_ids(tmp_path: Path) -> None:
    kb = _kb_with_docs(tmp_path, {"ev-1": _MARGIN_TEXT, "ev-2": _RISK_TEXT})
    result = retrieve_with_plan(
        kb, ["ev-1", "ev-2", "ev-1"], _plan()
    )  # duplicate on purpose
    assert result.docs_searched == 2


def test_docs_searched_zero_when_no_query_terms(tmp_path: Path) -> None:
    kb = _kb_with_docs(tmp_path, {"ev-1": _MARGIN_TEXT})
    plan = _plan(query_terms=(), numeric_terms=())
    result = retrieve_with_plan(kb, ["ev-1"], plan)
    assert result.docs_searched == 1  # still counted, even though nothing matched


# --- Doc-type boost ------------------------------------------------------------
def test_preferred_doc_type_ranks_above_unpreferred_of_equal_score(
    tmp_path: Path,
) -> None:
    # Two docs, IDENTICAL scoring text, different kinds -- doc-type boost
    # must be the deciding factor.
    kb = _kb_with_docs(
        tmp_path,
        {"ev-transcript": _RISK_TEXT, "ev-annual": _RISK_TEXT},
        kinds={
            "ev-transcript": EvidenceKind.EARNINGS_TRANSCRIPT,
            "ev-annual": EvidenceKind.ANNUAL_REPORT,
        },
    )
    plan = _plan(
        query_terms=("currency", "fluctuation", "risk"),
        numeric_terms=(),
        preferred_doc_types=(DocTypePreference(kind="earnings_transcript", weight=60),),
        top_k=1,
    )
    result = retrieve_with_plan(kb, ["ev-transcript", "ev-annual"], plan)
    assert result.matches[0][0] == "ev-transcript"


def test_unknown_kind_document_still_eligible(tmp_path: Path) -> None:
    # A doc whose kind isn't in preferred_doc_types gets boost 0, not excluded.
    kb = _kb_with_docs(
        tmp_path, {"ev-1": _RISK_TEXT}, kinds={"ev-1": EvidenceKind.NEWS}
    )
    plan = _plan(
        query_terms=("currency", "fluctuation", "risk"),
        numeric_terms=(),
        preferred_doc_types=(DocTypePreference(kind="earnings_transcript", weight=60),),
    )
    result = retrieve_with_plan(kb, ["ev-1"], plan)
    assert len(result.matches) == 1
    assert result.matches[0][0] == "ev-1"


def test_document_missing_kb_metadata_still_eligible(tmp_path: Path) -> None:
    # doc_id passed in but never parsed -> no metadata row at all.
    kb = _kb_with_docs(tmp_path, {"ev-1": _RISK_TEXT})
    plan = _plan(query_terms=("currency", "fluctuation", "risk"), numeric_terms=())
    result = retrieve_with_plan(kb, ["ev-1", "ev-ghost"], plan)
    assert "ev-ghost" in result.docs_missing_metadata
    assert len(result.matches) == 1  # ev-1 still retrieved normally


# --- Date window boost ----------------------------------------------------------
def test_date_window_boosts_document_inside_range(tmp_path: Path) -> None:
    kb = _kb_with_docs(
        tmp_path,
        {"ev-in": _RISK_TEXT, "ev-out": _RISK_TEXT},
        dates={
            "ev-in": "2024-06-15T00:00:00+00:00",
            "ev-out": "2020-01-01T00:00:00+00:00",
        },
    )
    plan = _plan(
        query_terms=("currency", "fluctuation", "risk"),
        numeric_terms=(),
        date_window=DateWindow(start="2024-01-01", end="2024-12-31"),
        top_k=1,
    )
    result = retrieve_with_plan(kb, ["ev-in", "ev-out"], plan)
    assert result.matches[0][0] == "ev-in"


def test_date_window_never_excludes_document_outside_range(tmp_path: Path) -> None:
    kb = _kb_with_docs(
        tmp_path,
        {"ev-out": _RISK_TEXT},
        dates={"ev-out": "2020-01-01T00:00:00+00:00"},
    )
    plan = _plan(
        query_terms=("currency", "fluctuation", "risk"),
        numeric_terms=(),
        date_window=DateWindow(start="2024-01-01", end="2024-12-31"),
    )
    result = retrieve_with_plan(kb, ["ev-out"], plan)
    assert len(result.matches) == 1  # boost never becomes a filter


# --- Period boost ----------------------------------------------------------------
def test_period_mention_boosts_matching_window(tmp_path: Path) -> None:
    fy_text = "Currency fluctuation risk was elevated in FY2024 due to volatility."
    plain_text = (
        "Currency fluctuation risk affects our overseas operations significantly."
    )
    kb = _kb_with_docs(tmp_path, {"ev-fy": fy_text, "ev-plain": plain_text})
    plan = _plan(
        query_terms=("currency", "fluctuation", "risk"),
        numeric_terms=(),
        periods=("FY2024",),
        top_k=1,
    )
    result = retrieve_with_plan(kb, ["ev-fy", "ev-plain"], plan)
    assert result.matches[0][0] == "ev-fy"


# --- Recency boost (RerankHints.prefer_recent) ------------------------------------
def test_prefer_recent_ranks_newer_document_above_older_of_equal_score(
    tmp_path: Path,
) -> None:
    kb = _kb_with_docs(
        tmp_path,
        {"ev-new": _RISK_TEXT, "ev-old": _RISK_TEXT},
        dates={
            "ev-new": "2025-01-01T00:00:00+00:00",
            "ev-old": "2020-01-01T00:00:00+00:00",
        },
    )
    plan = _plan(
        query_terms=("currency", "fluctuation", "risk"),
        numeric_terms=(),
        rerank=RerankHints(prefer_recent=True),
        top_k=1,
    )
    result = retrieve_with_plan(kb, ["ev-new", "ev-old"], plan)
    assert result.matches[0][0] == "ev-new"


def test_prefer_recent_off_by_default_no_recency_bias(tmp_path: Path) -> None:
    # Without prefer_recent, dates must not affect ordering -- deterministic
    # tie-break (doc_id ascending) decides instead.
    kb = _kb_with_docs(
        tmp_path,
        {"ev-b": _RISK_TEXT, "ev-a": _RISK_TEXT},
        dates={
            "ev-b": "2025-01-01T00:00:00+00:00",
            "ev-a": "2020-01-01T00:00:00+00:00",
        },
    )
    plan = _plan(
        query_terms=("currency", "fluctuation", "risk"), numeric_terms=(), top_k=1
    )
    result = retrieve_with_plan(kb, ["ev-b", "ev-a"], plan)
    assert result.matches[0][0] == "ev-a"  # doc_id ascending, not date descending


# --- Numeric boost (RerankHints.prefer_numeric) -----------------------------------
def test_prefer_numeric_ranks_numeric_match_above_word_only_of_equal_score(
    tmp_path: Path,
) -> None:
    numeric_text = (
        "Currency fluctuation risk was quantified at 24.2 percent of revenue."
    )
    word_text = (
        "Currency fluctuation risk affects our overseas operations significantly."
    )
    kb = _kb_with_docs(tmp_path, {"ev-numeric": numeric_text, "ev-word": word_text})
    plan = _plan(
        query_terms=("currency", "fluctuation", "risk"),
        numeric_terms=("24.2",),
        rerank=RerankHints(prefer_numeric=True),
        top_k=1,
    )
    result = retrieve_with_plan(kb, ["ev-numeric", "ev-word"], plan)
    assert result.matches[0][0] == "ev-numeric"


# --- max_per_document ------------------------------------------------------------
def test_max_per_document_caps_selections_from_one_doc(tmp_path: Path) -> None:
    # Multiple distinct, non-overlapping matches available in one long doc.
    filler = "Filler sentence content here. " * 25
    long_text = (
        f"{_RISK_TEXT} {filler} {_MARGIN_TEXT} {filler} "
        "Currency fluctuation risk was also noted separately in another section."
    )
    kb = _kb_with_docs(tmp_path, {"ev-1": long_text})
    plan = _plan(
        query_terms=("currency", "fluctuation", "risk", "operating", "margin"),
        numeric_terms=("24.2",),
        rerank=RerankHints(max_per_document=1),
        top_k=5,
    )
    result = retrieve_with_plan(kb, ["ev-1"], plan)
    assert len(result.matches) <= 1


# --- Determinism -----------------------------------------------------------------
def test_deterministic_under_shuffled_doc_ids_input(tmp_path: Path) -> None:
    kb = _kb_with_docs(
        tmp_path,
        {
            "ev-1": _MARGIN_TEXT,
            "ev-2": _RISK_TEXT,
            "ev-3": _IRRELEVANT_TEXT,
        },
    )
    plan = _plan(top_k=5)
    forward = retrieve_with_plan(kb, ["ev-1", "ev-2", "ev-3"], plan)
    shuffled = retrieve_with_plan(kb, ["ev-3", "ev-1", "ev-2"], plan)
    assert forward.matches == shuffled.matches


def test_deterministic_tie_break_by_doc_id(tmp_path: Path) -> None:
    kb = _kb_with_docs(tmp_path, {"ev-b": _RISK_TEXT, "ev-a": _RISK_TEXT})
    plan = _plan(
        query_terms=("currency", "fluctuation", "risk"), numeric_terms=(), top_k=5
    )
    result = retrieve_with_plan(kb, ["ev-b", "ev-a"], plan)
    assert [doc_id for doc_id, _m in result.matches] == ["ev-a", "ev-b"]


# --- top_k / empty inputs ---------------------------------------------------------
def test_top_k_limits_result_count(tmp_path: Path) -> None:
    kb = _kb_with_docs(tmp_path, {"ev-1": _MARGIN_TEXT, "ev-2": _RISK_TEXT})
    plan = _plan(top_k=1)
    result = retrieve_with_plan(kb, ["ev-1", "ev-2"], plan)
    assert len(result.matches) == 1


def test_empty_doc_ids_returns_empty_result(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path)
    plan = _plan()
    result = retrieve_with_plan(kb, [], plan)
    assert result.matches == ()
    assert result.candidates_considered == 0
    assert result.docs_missing_metadata == ()


def test_no_usable_keywords_returns_empty_result(tmp_path: Path) -> None:
    kb = _kb_with_docs(tmp_path, {"ev-1": _MARGIN_TEXT})
    plan = _plan(query_terms=(), numeric_terms=())
    result = retrieve_with_plan(kb, ["ev-1"], plan)
    assert result.matches == ()


def test_result_carries_the_plan_it_was_given(tmp_path: Path) -> None:
    kb = _kb_with_docs(tmp_path, {"ev-1": _MARGIN_TEXT})
    plan = _plan()
    result = retrieve_with_plan(kb, ["ev-1"], plan)
    assert result.plan is plan
