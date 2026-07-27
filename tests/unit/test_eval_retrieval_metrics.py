"""Retrieval/planner metrics on CaseResult/Report (M1.8 commit 6, ADR-0004).

Covers the pure builder functions (build_retrieval_metrics/build_planner_
metrics), the suite-level aggregates (dead-rule detection, intent/top_k
distributions, doc-type distribution, refusal_rate), and backward
compatibility: an M1.7-era report JSON with neither field must still load.
"""

from __future__ import annotations


from atlas.eval.report import (
    CaseResult,
    PlannerCaseMetrics,
    Report,
    RetrievalCaseMetrics,
    RetrievalQualityScore,
    aggregate,
    build_planner_metrics,
    build_retrieval_metrics,
)
from atlas.reasoning.plan import PlanningDecision, SearchPlan
from atlas.reasoning.planner import ALL_RULE_IDS
from atlas.reasoning.retrieval import RetrievalResult, ScoreBreakdown

SUBJECT_PLAN = SearchPlan(
    raw_question="What did management say about margins?",
    intent="narrative",
    query_terms=("management", "margins"),
    preferred_doc_types=(),
    top_k=5,
    periods=("FY2024",),
    decisions=(
        PlanningDecision(
            rule="intent_keyword_match", input="what did management", output="narrative"
        ),
        PlanningDecision(rule="period_extraction", input="q", output="FY2024"),
        PlanningDecision(rule="top_k_default", input="", output="5"),
    ),
)


def _breakdown(
    doc_id: str, char_offset: int, total: int, kind: str | None = "annual_report"
) -> ScoreBreakdown:
    return ScoreBreakdown(
        doc_id=doc_id,
        char_offset=char_offset,
        base=total // 100,
        doc_type=10,
        date_window=0,
        period=40,
        recency=0,
        numeric=0,
        total=total,
        kind=kind,
    )


# --- build_retrieval_metrics ------------------------------------------------------
def test_build_retrieval_metrics_none_when_no_retrieval() -> None:
    assert build_retrieval_metrics(None) is None


def test_build_retrieval_metrics_shape() -> None:
    retrieval = RetrievalResult(
        matches=(),
        plan=SUBJECT_PLAN,
        candidates_considered=7,
        docs_missing_metadata=("ev-ghost",),
        breakdowns=(
            _breakdown("ev-1", 10, 250),
            _breakdown("ev-2", 20, 150, kind="earnings_transcript"),
        ),
        docs_searched=4,
    )
    metrics = build_retrieval_metrics(retrieval)
    assert metrics is not None
    assert metrics.candidates_considered == 7
    assert metrics.docs_searched == 4
    assert metrics.selected == (("ev-1", 10, 250), ("ev-2", 20, 150))
    assert metrics.doc_type_counts == (("annual_report", 1), ("earnings_transcript", 1))
    assert metrics.metadata_coverage == round(1 - 1 / 4, 3)
    assert dict(metrics.boost_totals)["period"] == 80  # 40 + 40
    assert metrics.boost_share == round((10 + 40 + 10 + 40) / (250 + 150), 3)


def test_build_retrieval_metrics_no_selected_candidates() -> None:
    retrieval = RetrievalResult(
        matches=(),
        plan=SUBJECT_PLAN,
        candidates_considered=0,
        docs_missing_metadata=(),
        breakdowns=(),
        docs_searched=2,
    )
    metrics = build_retrieval_metrics(retrieval)
    assert metrics is not None
    assert metrics.selected == ()
    assert metrics.boost_share is None  # nothing selected -> no share to report
    assert metrics.metadata_coverage == 1.0  # nothing missing out of 2 searched


def test_build_retrieval_metrics_zero_docs_searched_gives_none_coverage() -> None:
    retrieval = RetrievalResult(
        matches=(),
        plan=SUBJECT_PLAN,
        candidates_considered=0,
        docs_missing_metadata=(),
        breakdowns=(),
        docs_searched=0,
    )
    metrics = build_retrieval_metrics(retrieval)
    assert metrics is not None
    assert metrics.metadata_coverage is None


def test_build_retrieval_metrics_unknown_kind_bucketed() -> None:
    retrieval = RetrievalResult(
        matches=(),
        plan=SUBJECT_PLAN,
        candidates_considered=1,
        docs_missing_metadata=(),
        breakdowns=(_breakdown("ev-1", 0, 100, kind=None),),
        docs_searched=1,
    )
    metrics = build_retrieval_metrics(retrieval)
    assert metrics is not None
    assert metrics.doc_type_counts == (("unknown", 1),)


# --- build_planner_metrics ---------------------------------------------------------
def test_build_planner_metrics_none_when_no_plan() -> None:
    assert build_planner_metrics(None) is None


def test_build_planner_metrics_shape() -> None:
    metrics = build_planner_metrics(SUBJECT_PLAN)
    assert metrics is not None
    assert metrics.intent == "narrative"
    assert metrics.top_k == 5
    assert metrics.periods_found == ("FY2024",)
    assert metrics.rules_fired == (
        "intent_keyword_match",
        "period_extraction",
        "top_k_default",
    )
    assert metrics.preferred_kinds == ()


# --- Suite-level aggregates: dead rules -------------------------------------------
def _case_with_planner(
    rules_fired: tuple[str, ...], intent: str = "narrative", top_k: int = 5
) -> CaseResult:
    return CaseResult(
        case_id="t01",
        category="A",
        status="active",
        planner_metrics=PlannerCaseMetrics(
            intent=intent,
            preferred_kinds=(),
            top_k=top_k,
            periods_found=(),
            rules_fired=rules_fired,
        ),
    )


def test_dead_rules_are_declared_rules_that_never_fired() -> None:
    fired_everywhere = ("intent_keyword_match", "top_k_default")
    results = (_case_with_planner(fired_everywhere),)
    agg = aggregate(results)
    assert agg["planner"] is not None
    assert set(agg["planner"]["dead_rules"]) == ALL_RULE_IDS - set(fired_everywhere)


def test_no_dead_rules_when_every_rule_fires() -> None:
    results = (_case_with_planner(tuple(sorted(ALL_RULE_IDS))),)
    agg = aggregate(results)
    assert agg["planner"]["dead_rules"] == []


def test_intent_and_top_k_distributions() -> None:
    results = (
        _case_with_planner(("intent_keyword_match",), intent="narrative", top_k=5),
        _case_with_planner(("intent_keyword_match",), intent="narrative", top_k=3),
        _case_with_planner(("intent_fallback",), intent="general", top_k=5),
    )
    agg = aggregate(results)
    assert agg["planner"]["intent_distribution"] == {"general": 1, "narrative": 2}
    assert agg["planner"]["top_k_distribution"] == {"3": 1, "5": 2}
    assert agg["planner"]["rule_fire_counts"]["intent_keyword_match"] == 2


def test_planner_aggregate_none_when_no_case_has_a_plan() -> None:
    results = (CaseResult(case_id="t01", category="A", status="active"),)
    agg = aggregate(results)
    assert agg["planner"] is None


# --- Suite-level aggregates: retrieval ----------------------------------------------
def _case_with_retrieval(
    candidates: int,
    coverage: float | None,
    boost_share: float | None,
    doc_type_counts: tuple[tuple[str, int], ...],
) -> CaseResult:
    return CaseResult(
        case_id="t01",
        category="A",
        status="active",
        retrieval_metrics=RetrievalCaseMetrics(
            candidates_considered=candidates,
            docs_searched=3,
            selected=(),
            doc_type_counts=doc_type_counts,
            metadata_coverage=coverage,
            boost_totals=(),
            boost_share=boost_share,
        ),
    )


def test_retrieval_aggregate_means_and_distribution() -> None:
    results = (
        _case_with_retrieval(10, 1.0, 0.2, (("annual_report", 2),)),
        _case_with_retrieval(20, 0.5, 0.4, (("earnings_transcript", 1),)),
    )
    agg = aggregate(results)
    r = agg["retrieval"]
    assert r["cases_with_retrieval"] == 2
    assert r["mean_candidates_considered"] == 15.0
    assert r["mean_metadata_coverage"] == 0.75
    assert r["mean_boost_share"] == 0.3
    assert r["doc_type_distribution"] == {"annual_report": 2, "earnings_transcript": 1}


def test_retrieval_aggregate_none_when_no_case_has_retrieval() -> None:
    results = (CaseResult(case_id="t01", category="A", status="active"),)
    agg = aggregate(results)
    assert agg["retrieval"] is None


# --- refusal_rate -------------------------------------------------------------------
def test_refusal_rate_computed_over_active_cases_with_a_definite_refused_value() -> (
    None
):
    results = (
        CaseResult(case_id="t01", category="A", status="active", refused=True),
        CaseResult(case_id="t02", category="A", status="active", refused=False),
        CaseResult(case_id="t03", category="A", status="active", refused=False),
    )
    agg = aggregate(results)
    assert agg["refusal_rate"] == round(1 / 3, 3)


def test_refusal_rate_none_when_no_case_has_a_definite_refused_value() -> None:
    results = (
        CaseResult(case_id="t01", category="A", status="active"),
    )  # retrieval-only case
    agg = aggregate(results)
    assert agg["refusal_rate"] is None


# --- Backward compatibility: old reports without these fields still load -----------
def test_old_report_json_without_new_fields_still_loads() -> None:
    old_style = {
        "milestone": "M0",
        "created_at": "2026-01-01T00:00:00+00:00",
        "model": "fake",
        "capabilities": ["single_name"],
        "results": [
            {
                "case_id": "t01",
                "category": "A",
                "status": "active",
                "refused": False,
                "correctness_pass": True,
                "grounding_pass": True,
            },
        ],
    }
    report = Report.from_dict(old_style)
    assert report.results[0].retrieval_metrics is None
    assert report.results[0].planner_metrics is None
    agg = aggregate(report.results)
    assert agg["planner"] is None
    assert agg["retrieval"] is None


def test_new_report_round_trips_nested_metrics_through_json() -> None:
    result = _case_with_planner(("intent_keyword_match",))
    result = CaseResult(
        **{
            **result.__dict__,
            "retrieval_metrics": _case_with_retrieval(
                5,
                1.0,
                0.1,
                (("annual_report", 1),),
            ).retrieval_metrics,
        }
    )
    report = Report(
        milestone="M1.8",
        created_at="2026-01-01T00:00:00+00:00",
        model="fake",
        capabilities=("single_name",),
        results=(result,),
    )
    restored = Report.from_json(report.to_json())
    assert restored.results[0].planner_metrics == result.planner_metrics
    assert restored.results[0].retrieval_metrics == result.retrieval_metrics


# --- retrieval_quality aggregate (M1.8.5 / ADR-0005) --------------------------------
def _case_with_quality(
    precision: float | None,
    recall: float | None,
    mrr: float | None,
    forbidden: tuple[str, ...] = (),
) -> CaseResult:
    return CaseResult(
        case_id="t01",
        category="A",
        status="active",
        retrieval_quality=RetrievalQualityScore(
            precision_at_k=precision,
            recall_at_k=recall,
            mrr=mrr,
            forbidden_retrieved=forbidden,
        ),
    )


def test_retrieval_quality_aggregate_means() -> None:
    results = (
        _case_with_quality(1.0, 1.0, 1.0),
        _case_with_quality(0.5, 0.5, 0.5),
    )
    agg = aggregate(results)
    rq = agg["retrieval_quality"]
    assert rq["labelled_cases"] == 2
    assert rq["mean_precision_at_k"] == 0.75
    assert rq["mean_recall_at_k"] == 0.75
    assert rq["mean_mrr"] == 0.75
    assert rq["cases_with_forbidden_retrieval"] == 0


def test_retrieval_quality_aggregate_counts_forbidden() -> None:
    results = (
        _case_with_quality(1.0, 1.0, 1.0, forbidden=("ev-bad",)),
        _case_with_quality(1.0, 1.0, 1.0),
    )
    agg = aggregate(results)
    assert agg["retrieval_quality"]["cases_with_forbidden_retrieval"] == 1


def test_retrieval_quality_aggregate_ignores_none_fields_in_means() -> None:
    # A kinds-only label produces None precision/recall/mrr -- must not
    # count as 0 in the mean, just excluded.
    results = (_case_with_quality(None, None, None),)
    agg = aggregate(results)
    rq = agg["retrieval_quality"]
    assert rq["labelled_cases"] == 1
    assert rq["mean_precision_at_k"] is None


def test_retrieval_quality_aggregate_none_when_no_case_labelled() -> None:
    results = (CaseResult(case_id="t01", category="A", status="active"),)
    agg = aggregate(results)
    assert agg["retrieval_quality"] is None


def test_retrieval_quality_round_trips_through_json() -> None:
    result = _case_with_quality(0.5, 0.75, 1.0, forbidden=("ev-bad",))
    report = Report(
        milestone="M1.8.5",
        created_at="2026-01-01T00:00:00+00:00",
        model="fake",
        capabilities=("single_name",),
        results=(result,),
    )
    restored = Report.from_json(report.to_json())
    assert restored.results[0].retrieval_quality == result.retrieval_quality


def test_old_report_without_retrieval_quality_key_still_loads() -> None:
    old_style = {
        "milestone": "M1.8",
        "created_at": "2026-01-01T00:00:00+00:00",
        "model": "fake",
        "capabilities": ["single_name"],
        "results": [{"case_id": "t01", "category": "A", "status": "active"}],
    }
    report = Report.from_dict(old_style)
    assert report.results[0].retrieval_quality is None
