"""Advisory recommendation verdict (M1.8 commit 8, ADR-0004).

Every scenario here is deliberately explicit about which threshold it is
testing, mirroring the design's own explicit unvalidated thresholds. The
central invariant across the whole file: recommend() always returns a value
and NEVER raises -- there is no command this can cause to exit non-zero.
"""
from __future__ import annotations

from atlas.eval.recommendation import (
    _MIN_ACTIVE_CASES_WITH_ANSWERS,
    _MIN_CHANGED_SELECTION_FRACTION,
    recommend,
)
from atlas.eval.report import CaseResult, PlannerCaseMetrics, Report, RetrievalCaseMetrics


def _report(milestone: str, results: tuple[CaseResult, ...]) -> Report:
    return Report(
        milestone=milestone, created_at="2026-01-01T00:00:00+00:00", model="fake",
        capabilities=("single_name",), results=results,
    )


def _retrieval(selected: tuple[tuple[str, int, int], ...]) -> RetrievalCaseMetrics:
    return RetrievalCaseMetrics(
        candidates_considered=len(selected), docs_searched=3, selected=selected,
        doc_type_counts=(), metadata_coverage=1.0, boost_totals=(), boost_share=0.1,
    )


def _healthy_case(case_id: str, selected: tuple[tuple[str, int, int], ...], **overrides: object) -> CaseResult:
    defaults: dict[str, object] = dict(
        case_id=case_id, category="A", status="active",
        refused=False, correctness_pass=True, grounding_pass=True,
        reasoning_quality=4, usefulness=4, evidence_use=4,
        retrieval_metrics=_retrieval(selected),
        planner_metrics=PlannerCaseMetrics(
            intent="narrative", preferred_kinds=(), top_k=5, periods_found=(),
            rules_fired=("intent_keyword_match",),
        ),
    )
    defaults.update(overrides)
    return CaseResult(**defaults)  # type: ignore[arg-type]


def _n_cases(n: int, *, changed_fraction: float) -> tuple[Report, Report]:
    """n cases, `changed_fraction` of which get a genuinely different
    selected-passage set between baseline and candidate.
    """
    n_changed = round(n * changed_fraction)
    baseline_cases = []
    candidate_cases = []
    for i in range(n):
        cid = f"t{i:02d}"
        baseline_cases.append(_healthy_case(cid, (("ev-1", 0, 100),)))
        if i < n_changed:
            candidate_cases.append(_healthy_case(cid, (("ev-2", 0, 200),)))  # disjoint set
        else:
            candidate_cases.append(_healthy_case(cid, (("ev-1", 0, 100),)))  # identical set
    return _report("base", tuple(baseline_cases)), _report("cand", tuple(candidate_cases))


# --- INSUFFICIENT_DATA -----------------------------------------------------------
def test_insufficient_data_below_minimum_active_cases_with_answers() -> None:
    baseline, candidate = _n_cases(_MIN_ACTIVE_CASES_WITH_ANSWERS - 1, changed_fraction=1.0)
    rec = recommend(baseline, candidate)
    assert rec.verdict == "INSUFFICIENT_DATA"
    assert rec.criteria["active_cases_with_answers"] == _MIN_ACTIVE_CASES_WITH_ANSWERS - 1


def test_insufficient_data_for_retrieval_only_report() -> None:
    # --retrieval-only mode: correctness_pass is always None (no LLM call).
    cases = tuple(
        CaseResult(case_id=f"t{i:02d}", category="A", status="active") for i in range(30)
    )
    baseline, candidate = _report("base", cases), _report("cand", cases)
    rec = recommend(baseline, candidate)
    assert rec.verdict == "INSUFFICIENT_DATA"


# --- SAFE_TO_ENABLE ----------------------------------------------------------------
def test_safe_to_enable_when_every_criterion_passes() -> None:
    baseline, candidate = _n_cases(_MIN_ACTIVE_CASES_WITH_ANSWERS, changed_fraction=1.0)
    rec = recommend(baseline, candidate)
    assert rec.verdict == "SAFE_TO_ENABLE"
    assert rec.criteria["grounding_regressions"] == []
    assert rec.criteria["fraction_changed_selection"] == 1.0


# --- NOT_READY: each criterion individually --------------------------------------
def test_not_ready_on_grounding_regression() -> None:
    baseline, candidate = _n_cases(_MIN_ACTIVE_CASES_WITH_ANSWERS, changed_fraction=1.0)
    # Regress exactly one case's grounding on the candidate side.
    regressed = CaseResult(**{**candidate.results[0].__dict__, "grounding_pass": False})
    candidate = _report("cand", (regressed,) + candidate.results[1:])
    rec = recommend(baseline, candidate)
    assert rec.verdict == "NOT_READY"
    assert regressed.case_id in rec.criteria["grounding_regressions"]


def test_not_ready_on_negative_correctness_delta() -> None:
    baseline, candidate = _n_cases(_MIN_ACTIVE_CASES_WITH_ANSWERS, changed_fraction=1.0)
    worsened = CaseResult(**{**candidate.results[0].__dict__, "correctness_pass": False, "grounding_pass": True})
    candidate = _report("cand", (worsened,) + candidate.results[1:])
    rec = recommend(baseline, candidate)
    assert rec.verdict == "NOT_READY"
    assert rec.criteria["correctness_pass_rate_delta"] is not None
    assert rec.criteria["correctness_pass_rate_delta"] < 0


def test_not_ready_on_refusal_rate_spike() -> None:
    baseline, candidate = _n_cases(_MIN_ACTIVE_CASES_WITH_ANSWERS, changed_fraction=1.0)
    # Push several cases to refused=True on the candidate side to exceed +0.02.
    new_results = list(candidate.results)
    for i in range(5):
        new_results[i] = CaseResult(**{**new_results[i].__dict__, "refused": True})
    candidate = _report("cand", tuple(new_results))
    rec = recommend(baseline, candidate)
    assert rec.verdict == "NOT_READY"
    assert rec.criteria["refusal_rate_delta"] > 0.02


def test_not_ready_when_no_measurable_effect() -> None:
    # Every criterion else passes, but the plan changed NOTHING.
    baseline, candidate = _n_cases(_MIN_ACTIVE_CASES_WITH_ANSWERS, changed_fraction=0.0)
    rec = recommend(baseline, candidate)
    assert rec.verdict == "NOT_READY"
    assert rec.criteria["fraction_changed_selection"] == 0.0


def test_not_ready_right_at_the_changed_fraction_boundary() -> None:
    baseline, candidate = _n_cases(
        _MIN_ACTIVE_CASES_WITH_ANSWERS, changed_fraction=_MIN_CHANGED_SELECTION_FRACTION,
    )
    rec = recommend(baseline, candidate)
    assert rec.verdict == "SAFE_TO_ENABLE"  # >= threshold passes, not just >


# --- Never raises, never signals failure via exception -----------------------------
def test_recommend_never_raises_on_empty_reports() -> None:
    empty = _report("empty", ())
    rec = recommend(empty, empty)  # must not raise
    assert rec.verdict == "INSUFFICIENT_DATA"


def test_recommend_is_pure() -> None:
    baseline, candidate = _n_cases(_MIN_ACTIVE_CASES_WITH_ANSWERS, changed_fraction=0.5)
    first = recommend(baseline, candidate)
    second = recommend(baseline, candidate)
    assert first == second
