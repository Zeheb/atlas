"""Retrieval quality metrics from gold labels (M1.8.5 commit 7, ADR-0005)."""
from __future__ import annotations

from atlas.benchmark.provenance import RetrievalLabel
from atlas.eval.report import RetrievalCaseMetrics
from atlas.eval.retrieval_quality import score_retrieval_quality


def _metrics(selected: tuple[tuple[str, int, int], ...]) -> RetrievalCaseMetrics:
    return RetrievalCaseMetrics(
        candidates_considered=len(selected), docs_searched=len({d for d, _c, _s in selected}) or 1,
        selected=selected, doc_type_counts=(), metadata_coverage=1.0,
        boost_totals=(), boost_share=0.1,
    )


# --- None propagation ----------------------------------------------------------------
def test_none_metrics_gives_none() -> None:
    assert score_retrieval_quality(None, RetrievalLabel(relevant_evidence_ids=("ev-1",))) is None


def test_none_label_gives_none() -> None:
    assert score_retrieval_quality(_metrics((("ev-1", 0, 100),)), None) is None


def test_both_none_gives_none() -> None:
    assert score_retrieval_quality(None, None) is None


# --- Kinds-only label: nothing id-computable except forbidden -----------------------
def test_kinds_only_label_gives_none_precision_recall_mrr() -> None:
    label = RetrievalLabel(relevant_kinds=("annual_report",))
    score = score_retrieval_quality(_metrics((("ev-1", 0, 100),)), label)
    assert score is not None
    assert score.precision_at_k is None
    assert score.recall_at_k is None
    assert score.mrr is None
    assert score.forbidden_retrieved == ()


def test_kinds_only_label_still_computes_forbidden() -> None:
    label = RetrievalLabel(relevant_kinds=("annual_report",), must_not_retrieve=("ev-bad",))
    score = score_retrieval_quality(_metrics((("ev-bad", 0, 100),)), label)
    assert score.forbidden_retrieved == ("ev-bad",)


# --- Nothing retrieved but relevant docs expected: zero, not None -------------------
def test_nothing_selected_with_relevant_ids_scores_zero() -> None:
    label = RetrievalLabel(relevant_evidence_ids=("ev-1",))
    score = score_retrieval_quality(_metrics(()), label)
    assert score.precision_at_k == 0.0
    assert score.recall_at_k == 0.0
    assert score.mrr == 0.0


# --- Perfect precision/recall/MRR ----------------------------------------------------
def test_perfect_match_scores_one_everywhere() -> None:
    label = RetrievalLabel(relevant_evidence_ids=("ev-1",))
    score = score_retrieval_quality(_metrics((("ev-1", 0, 100),)), label)
    assert score.precision_at_k == 1.0
    assert score.recall_at_k == 1.0
    assert score.mrr == 1.0


def test_relevant_doc_at_rank_two_gives_mrr_half() -> None:
    label = RetrievalLabel(relevant_evidence_ids=("ev-2",))
    score = score_retrieval_quality(
        _metrics((("ev-1", 0, 100), ("ev-2", 0, 90))), label,
    )
    assert score.mrr == 0.5


def test_relevant_doc_absent_from_selection_gives_zero_mrr() -> None:
    label = RetrievalLabel(relevant_evidence_ids=("ev-99",))
    score = score_retrieval_quality(_metrics((("ev-1", 0, 100),)), label)
    assert score.mrr == 0.0
    assert score.recall_at_k == 0.0


# --- Precision/recall arithmetic ------------------------------------------------------
def test_precision_counts_only_relevant_among_selected() -> None:
    label = RetrievalLabel(relevant_evidence_ids=("ev-1",))
    score = score_retrieval_quality(
        _metrics((("ev-1", 0, 100), ("ev-2", 0, 90), ("ev-3", 0, 80))), label,
    )
    assert score.precision_at_k == round(1 / 3, 3)


def test_recall_counts_relevant_ids_found_over_total_relevant() -> None:
    label = RetrievalLabel(relevant_evidence_ids=("ev-1", "ev-2", "ev-3"))
    score = score_retrieval_quality(_metrics((("ev-1", 0, 100),)), label)
    assert score.recall_at_k == round(1 / 3, 3)


def test_precision_and_recall_can_both_be_perfect_with_extra_relevant_not_needed() -> None:
    label = RetrievalLabel(relevant_evidence_ids=("ev-1", "ev-2"))
    score = score_retrieval_quality(
        _metrics((("ev-1", 0, 100), ("ev-2", 0, 90))), label,
    )
    assert score.precision_at_k == 1.0
    assert score.recall_at_k == 1.0


# --- Forbidden retrieval ---------------------------------------------------------------
def test_forbidden_retrieval_detected_alongside_normal_scoring() -> None:
    label = RetrievalLabel(relevant_evidence_ids=("ev-1",), must_not_retrieve=("ev-bad",))
    score = score_retrieval_quality(
        _metrics((("ev-1", 0, 100), ("ev-bad", 0, 50))), label,
    )
    assert score.forbidden_retrieved == ("ev-bad",)
    assert score.precision_at_k == 0.5  # ev-1 relevant, ev-bad not (in relevant_evidence_ids)


def test_no_forbidden_ids_selected_gives_empty_tuple() -> None:
    label = RetrievalLabel(relevant_evidence_ids=("ev-1",), must_not_retrieve=("ev-bad",))
    score = score_retrieval_quality(_metrics((("ev-1", 0, 100),)), label)
    assert score.forbidden_retrieved == ()
