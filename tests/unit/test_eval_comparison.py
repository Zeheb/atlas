"""ComparisonEngine (M1.8 commit 7, ADR-0004).

Pure functions over two persisted Reports, joined on case_id -- Option A from
the M1.8 design (no paired execution command). Every fixture here builds
Reports by hand rather than running real retrieval, so each metric's
arithmetic is independently checkable.
"""

from __future__ import annotations

from atlas.eval.comparison import (
    compare_retrieval,
    planner_attribution,
    ranking_change,
    retrieval_deltas,
    retrieval_quality_deltas,
    side_by_side,
)
from atlas.eval.report import (
    CaseResult,
    PlannerCaseMetrics,
    Report,
    RetrievalCaseMetrics,
    RetrievalQualityScore,
)


def _report(milestone: str, results: tuple[CaseResult, ...]) -> Report:
    return Report(
        milestone=milestone,
        created_at="2026-01-01T00:00:00+00:00",
        model="fake",
        capabilities=("single_name",),
        results=results,
    )


def _retrieval(
    selected: tuple[tuple[str, int, int], ...], **overrides: object
) -> RetrievalCaseMetrics:
    defaults: dict[str, object] = dict(
        candidates_considered=len(selected),
        docs_searched=3,
        selected=selected,
        doc_type_counts=(),
        metadata_coverage=1.0,
        boost_totals=(),
        boost_share=0.1,
    )
    defaults.update(overrides)
    return RetrievalCaseMetrics(**defaults)  # type: ignore[arg-type]


def _planner(intent: str, rules: tuple[str, ...]) -> PlannerCaseMetrics:
    return PlannerCaseMetrics(
        intent=intent, preferred_kinds=(), top_k=5, periods_found=(), rules_fired=rules
    )


def _case(case_id: str, **overrides: object) -> CaseResult:
    defaults: dict[str, object] = dict(case_id=case_id, category="A", status="active")
    defaults.update(overrides)
    return CaseResult(**defaults)  # type: ignore[arg-type]


# --- ranking_change ------------------------------------------------------------
def test_identical_selection_has_full_overlap_and_no_displacement() -> None:
    selected = (("ev-1", 10, 250), ("ev-2", 20, 150))
    baseline = _report("base", (_case("t01", retrieval_metrics=_retrieval(selected)),))
    candidate = _report("cand", (_case("t01", retrieval_metrics=_retrieval(selected)),))
    rc = ranking_change(baseline, candidate)
    assert rc["cases_compared"] == 1
    assert rc["mean_jaccard_overlap"] == 1.0
    assert rc["cases_with_changed_top1"] == 0
    assert rc["per_case"][0]["mean_rank_displacement"] == 0.0
    assert rc["per_case"][0]["churned_in"] == []
    assert rc["per_case"][0]["churned_out"] == []


def test_disjoint_selection_has_zero_overlap_and_changed_top1() -> None:
    baseline = _report(
        "base", (_case("t01", retrieval_metrics=_retrieval((("ev-1", 10, 250),))),)
    )
    candidate = _report(
        "cand", (_case("t01", retrieval_metrics=_retrieval((("ev-2", 20, 150),))),)
    )
    rc = ranking_change(baseline, candidate)
    assert rc["mean_jaccard_overlap"] == 0.0
    assert rc["cases_with_changed_top1"] == 1
    pc = rc["per_case"][0]
    assert pc["churned_in"] == [("ev-2", 20)]
    assert pc["churned_out"] == [("ev-1", 10)]
    assert pc["mean_rank_displacement"] is None  # no common items to displace


def test_reordering_without_membership_change_shows_displacement_not_churn() -> None:
    baseline = _report(
        "base",
        (
            _case(
                "t01",
                retrieval_metrics=_retrieval(
                    (("ev-1", 10, 250), ("ev-2", 20, 150)),
                ),
            ),
        ),
    )
    candidate = _report(
        "cand",
        (
            _case(
                "t01",
                retrieval_metrics=_retrieval(
                    (
                        ("ev-2", 20, 260),
                        ("ev-1", 10, 150),
                    ),  # same members, swapped order
                ),
            ),
        ),
    )
    rc = ranking_change(baseline, candidate)
    pc = rc["per_case"][0]
    assert pc["jaccard_overlap"] == 1.0  # same membership
    assert pc["churned_in"] == [] and pc["churned_out"] == []
    assert pc["mean_rank_displacement"] == 1.0  # each item moved one position
    assert pc["top1_changed"] is True  # rank 0 occupant changed


def test_both_empty_selection_is_vacuously_full_overlap() -> None:
    baseline = _report("base", (_case("t01", retrieval_metrics=_retrieval(())),))
    candidate = _report("cand", (_case("t01", retrieval_metrics=_retrieval(())),))
    rc = ranking_change(baseline, candidate)
    assert rc["mean_jaccard_overlap"] == 1.0
    assert rc["per_case"][0]["top1_changed"] is False


def test_case_missing_retrieval_metrics_on_either_side_excluded() -> None:
    baseline = _report("base", (_case("t01"),))  # no retrieval_metrics
    candidate = _report(
        "cand", (_case("t01", retrieval_metrics=_retrieval((("ev-1", 0, 100),))),)
    )
    rc = ranking_change(baseline, candidate)
    assert rc["cases_compared"] == 0
    assert rc["mean_jaccard_overlap"] is None


def test_case_absent_from_baseline_entirely_excluded() -> None:
    baseline = _report("base", ())
    candidate = _report(
        "cand", (_case("t01", retrieval_metrics=_retrieval((("ev-1", 0, 100),))),)
    )
    rc = ranking_change(baseline, candidate)
    assert rc["cases_compared"] == 0


# --- retrieval_deltas -----------------------------------------------------------
def test_retrieval_deltas_computes_expected_arithmetic() -> None:
    baseline = _report(
        "base",
        (
            _case(
                "t01",
                retrieval_metrics=_retrieval(
                    (("ev-1", 0, 100),),
                    candidates_considered=10,
                    metadata_coverage=0.5,
                    boost_share=0.1,
                ),
            ),
        ),
    )
    candidate = _report(
        "cand",
        (
            _case(
                "t01",
                retrieval_metrics=_retrieval(
                    (("ev-1", 0, 100),),
                    candidates_considered=20,
                    metadata_coverage=1.0,
                    boost_share=0.4,
                ),
            ),
        ),
    )
    deltas = retrieval_deltas(baseline, candidate)
    assert deltas["delta_mean_candidates_considered"] == 10.0
    assert deltas["delta_mean_metadata_coverage"] == 0.5
    assert deltas["delta_mean_boost_share"] == round(0.4 - 0.1, 3)


def test_retrieval_deltas_none_when_neither_report_has_retrieval_data() -> None:
    baseline = _report("base", (_case("t01"),))
    candidate = _report("cand", (_case("t01"),))
    deltas = retrieval_deltas(baseline, candidate)
    assert deltas["baseline"] is None
    assert deltas["candidate"] is None
    assert deltas["delta_mean_candidates_considered"] is None


# --- retrieval_quality_deltas (M1.8.5 / ADR-0005) -----------------------------------
def _quality(precision: float, recall: float, mrr: float) -> RetrievalQualityScore:
    return RetrievalQualityScore(
        precision_at_k=precision, recall_at_k=recall, mrr=mrr, forbidden_retrieved=()
    )


def test_retrieval_quality_deltas_computes_expected_arithmetic() -> None:
    baseline = _report(
        "base", (_case("t01", retrieval_quality=_quality(0.5, 0.5, 0.5)),)
    )
    candidate = _report(
        "cand", (_case("t01", retrieval_quality=_quality(1.0, 0.75, 1.0)),)
    )
    deltas = retrieval_quality_deltas(baseline, candidate)
    assert deltas["delta_mean_precision_at_k"] == 0.5
    assert deltas["delta_mean_recall_at_k"] == 0.25
    assert deltas["delta_mean_mrr"] == 0.5


def test_retrieval_quality_deltas_none_when_no_case_labelled() -> None:
    baseline = _report("base", (_case("t01"),))
    candidate = _report("cand", (_case("t01"),))
    deltas = retrieval_quality_deltas(baseline, candidate)
    assert deltas["baseline"] is None
    assert deltas["candidate"] is None
    assert deltas["delta_mean_precision_at_k"] is None


def test_compare_retrieval_includes_retrieval_quality_deltas() -> None:
    baseline = _report(
        "base", (_case("t01", retrieval_quality=_quality(0.5, 0.5, 0.5)),)
    )
    candidate = _report(
        "cand", (_case("t01", retrieval_quality=_quality(1.0, 1.0, 1.0)),)
    )
    result = compare_retrieval(baseline, candidate)
    assert "retrieval_quality_deltas" in result
    assert result["retrieval_quality_deltas"]["delta_mean_precision_at_k"] == 0.5


# --- planner_attribution ---------------------------------------------------------
def test_planner_attribution_by_intent_and_rule() -> None:
    baseline = _report(
        "base",
        (
            _case(
                "t01",
                correctness_pass=False,
                grounding_pass=True,
                planner_metrics=_planner("narrative", ("intent_keyword_match",)),
            ),
            _case(
                "t02",
                correctness_pass=True,
                grounding_pass=True,
                planner_metrics=_planner("general", ("intent_fallback",)),
            ),
        ),
    )
    candidate = _report(
        "cand",
        (
            _case(
                "t01",
                correctness_pass=True,
                grounding_pass=True,
                planner_metrics=_planner("narrative", ("intent_keyword_match",)),
            ),
            _case(
                "t02",
                correctness_pass=True,
                grounding_pass=True,
                planner_metrics=_planner("general", ("intent_fallback",)),
            ),
        ),
    )
    attribution = planner_attribution(baseline, candidate)
    assert attribution["by_intent"]["narrative"]["n_cases"] == 1
    assert attribution["by_intent"]["narrative"]["delta_correctness_pass_rate"] == 1.0
    assert attribution["by_intent"]["general"]["delta_correctness_pass_rate"] == 0.0
    assert (
        attribution["by_rule"]["intent_keyword_match"]["delta_correctness_pass_rate"]
        == 1.0
    )


def test_planner_attribution_excludes_cases_without_planner_metrics() -> None:
    baseline = _report("base", (_case("t01", correctness_pass=True),))
    candidate = _report(
        "cand", (_case("t01", correctness_pass=True),)
    )  # no planner_metrics
    attribution = planner_attribution(baseline, candidate)
    assert attribution["by_intent"] == {}
    assert attribution["by_rule"] == {}


# --- side_by_side -----------------------------------------------------------------
def test_side_by_side_carries_answer_text_and_scores() -> None:
    baseline = _report(
        "base",
        (
            _case(
                "t01",
                refused=False,
                correctness_pass=True,
                grounding_pass=True,
                answer_prose="Margins have been stable.",
                retrieval_metrics=_retrieval((("ev-1", 0, 100),)),
            ),
        ),
    )
    candidate = _report(
        "cand",
        (
            _case(
                "t01",
                refused=False,
                correctness_pass=True,
                grounding_pass=True,
                answer_prose="Margins improved due to cost discipline [ev-2].",
                retrieval_metrics=_retrieval((("ev-2", 0, 200),)),
            ),
        ),
    )
    rows = side_by_side(baseline, candidate)
    assert len(rows) == 1
    row = rows[0]
    assert row.case_id == "t01"
    assert row.baseline_answer == "Margins have been stable."
    assert row.candidate_answer == "Margins improved due to cost discipline [ev-2]."
    assert row.baseline_selected == (("ev-1", 0, 100),)
    assert row.candidate_selected == (("ev-2", 0, 200),)
    assert row.ranking_change is not None
    assert row.ranking_change["top1_changed"] is True


def test_side_by_side_skips_cases_absent_from_baseline() -> None:
    baseline = _report("base", ())
    candidate = _report("cand", (_case("t01"),))
    assert side_by_side(baseline, candidate) == ()


# --- compare_retrieval (the composed whole) ---------------------------------------
def test_compare_retrieval_composes_all_sections() -> None:
    baseline = _report(
        "base",
        (
            _case(
                "t01",
                correctness_pass=True,
                grounding_pass=True,
                refused=False,
                retrieval_metrics=_retrieval((("ev-1", 0, 100),)),
                planner_metrics=_planner("narrative", ("intent_keyword_match",)),
            ),
        ),
    )
    candidate = _report(
        "cand",
        (
            _case(
                "t01",
                correctness_pass=True,
                grounding_pass=True,
                refused=False,
                retrieval_metrics=_retrieval((("ev-2", 0, 200),)),
                planner_metrics=_planner("narrative", ("intent_keyword_match",)),
            ),
        ),
    )
    result = compare_retrieval(baseline, candidate)
    assert result["baseline"] == "base"
    assert result["candidate"] == "cand"
    assert "end_to_end" in result and "dimensions" in result["end_to_end"]
    assert result["ranking_change"]["cases_compared"] == 1
    assert result["retrieval_deltas"]["baseline"] is not None
    assert "by_intent" in result["planner_attribution"]
    assert len(result["side_by_side"]) == 1


def test_compare_retrieval_is_pure() -> None:
    baseline = _report(
        "base", (_case("t01", retrieval_metrics=_retrieval((("ev-1", 0, 100),))),)
    )
    candidate = _report(
        "cand", (_case("t01", retrieval_metrics=_retrieval((("ev-2", 0, 200),))),)
    )
    first = compare_retrieval(baseline, candidate)
    second = compare_retrieval(baseline, candidate)
    assert first == second
