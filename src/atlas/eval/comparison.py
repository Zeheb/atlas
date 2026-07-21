"""ComparisonEngine: baseline vs planned retrieval comparison (M1.8 commit 7,
ADR-0004).

Pure functions over two ALREADY-PERSISTED ``Report``s, joined on ``case_id``.
This is Option A from the M1.8 design (over a paired execution command):
each report is produced by an ordinary, independent ``atlas eval run``
invocation, and everything here composes ``report.py``'s existing
``aggregate``/``compare`` rather than replacing them. Nothing in this module
runs reasoning, retrieval, or an LLM -- it only reads two reports' already-
computed fields. A third/fourth retrieval strategy needs no new comparison
machinery: every function here already generalizes to any two reports.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from atlas.eval.report import CaseResult, PlannerCaseMetrics, Report, aggregate, compare


def _selected_keys(cr: CaseResult) -> tuple[tuple[str, int], ...]:
    """The ordered (doc_id, char_offset) keys of a case's selected passages,
    dropping the score (ranking-change metrics care about identity and
    order, not the score that produced it).
    """
    if cr.retrieval_metrics is None:
        return ()
    return tuple((doc_id, char_offset) for doc_id, char_offset, _score in cr.retrieval_metrics.selected)


def _ranking_change_for_case(base: CaseResult, cand: CaseResult) -> dict[str, Any] | None:
    """One case's ranking-change diagnostics, or None when either side has
    no retrieval metrics to compare (e.g. an inactive/pending case).
    """
    if base.retrieval_metrics is None or cand.retrieval_metrics is None:
        return None

    base_selected, cand_selected = _selected_keys(base), _selected_keys(cand)
    base_set, cand_set = set(base_selected), set(cand_selected)
    union = base_set | cand_set
    # Both empty is a vacuous "no change" (nothing selected either side),
    # not an undefined comparison -- reported as full overlap, not None.
    jaccard = len(base_set & cand_set) / len(union) if union else 1.0

    base_rank = {key: i for i, key in enumerate(base_selected)}
    cand_rank = {key: i for i, key in enumerate(cand_selected)}
    common = base_set & cand_set
    displacements = [abs(base_rank[k] - cand_rank[k]) for k in common]
    mean_displacement = round(sum(displacements) / len(displacements), 3) if displacements else None

    return {
        "case_id": base.case_id,
        "jaccard_overlap": round(jaccard, 3),
        "mean_rank_displacement": mean_displacement,
        "churned_in": sorted(cand_set - base_set),
        "churned_out": sorted(base_set - cand_set),
        "top1_changed": (base_selected[0] if base_selected else None) != (cand_selected[0] if cand_selected else None),
    }


def ranking_change(baseline: Report, candidate: Report) -> dict[str, Any]:
    """Suite-level ranking-change summary, joined on case_id."""
    base_by_id = {r.case_id: r for r in baseline.results}
    per_case: list[dict[str, Any]] = []
    for cand_r in candidate.results:
        base_r = base_by_id.get(cand_r.case_id)
        if base_r is None:
            continue
        rc = _ranking_change_for_case(base_r, cand_r)
        if rc is not None:
            per_case.append(rc)

    if not per_case:
        return {
            "cases_compared": 0, "mean_jaccard_overlap": None,
            "cases_with_changed_top1": 0, "fraction_changed_top1": None, "per_case": (),
        }
    jaccards = [c["jaccard_overlap"] for c in per_case]
    changed_top1 = sum(1 for c in per_case if c["top1_changed"])
    return {
        "cases_compared": len(per_case),
        "mean_jaccard_overlap": round(sum(jaccards) / len(jaccards), 3),
        "cases_with_changed_top1": changed_top1,
        "fraction_changed_top1": round(changed_top1 / len(per_case), 3),
        "per_case": tuple(per_case),
    }


def _delta(base: dict[str, Any] | None, cand: dict[str, Any] | None, key: str) -> float | None:
    if base is None or cand is None:
        return None
    b, c = base.get(key), cand.get(key)
    return round(c - b, 3) if isinstance(b, (int, float)) and isinstance(c, (int, float)) else None


def retrieval_deltas(baseline: Report, candidate: Report) -> dict[str, Any]:
    """Suite-level retrieval-metric deltas. Composes aggregate()'s existing
    "retrieval" sub-dict rather than recomputing anything.
    """
    base_agg = aggregate(baseline.results)["retrieval"]
    cand_agg = aggregate(candidate.results)["retrieval"]
    return {
        "baseline": base_agg,
        "candidate": cand_agg,
        "delta_mean_candidates_considered": _delta(base_agg, cand_agg, "mean_candidates_considered"),
        "delta_mean_metadata_coverage": _delta(base_agg, cand_agg, "mean_metadata_coverage"),
        "delta_mean_boost_share": _delta(base_agg, cand_agg, "mean_boost_share"),
    }


def retrieval_quality_deltas(baseline: Report, candidate: Report) -> dict[str, Any]:
    """Suite-level precision@k/recall@k/MRR deltas against gold labels
    (M1.8.5 / ADR-0005) -- what upgrades ``ranking_change``'s "the selection
    changed" into "the selection got better." Composes aggregate()'s
    "retrieval_quality" sub-dict; ``None`` on both sides when no case in
    either report carries a gold label.
    """
    base_agg = aggregate(baseline.results)["retrieval_quality"]
    cand_agg = aggregate(candidate.results)["retrieval_quality"]
    return {
        "baseline": base_agg,
        "candidate": cand_agg,
        "delta_mean_precision_at_k": _delta(base_agg, cand_agg, "mean_precision_at_k"),
        "delta_mean_recall_at_k": _delta(base_agg, cand_agg, "mean_recall_at_k"),
        "delta_mean_mrr": _delta(base_agg, cand_agg, "mean_mrr"),
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _bucket_delta(
    baseline: Report, candidate: Report, key_fn: Callable[[PlannerCaseMetrics], list[str]],
) -> dict[str, dict[str, Any]]:
    """Group candidate cases by key_fn(candidate.planner_metrics), join each
    to its baseline counterpart by case_id, and report the correctness/
    grounding pass-rate delta within each bucket. A case with no planner
    metrics, or no baseline counterpart, is excluded from every bucket.
    """
    base_by_id = {r.case_id: r for r in baseline.results}
    buckets: dict[str, list[tuple[CaseResult, CaseResult]]] = {}
    for cand_r in candidate.results:
        if cand_r.status != "active" or cand_r.planner_metrics is None:
            continue
        base_r = base_by_id.get(cand_r.case_id)
        if base_r is None or base_r.status != "active":
            continue
        for key in key_fn(cand_r.planner_metrics):
            buckets.setdefault(key, []).append((base_r, cand_r))

    out: dict[str, dict[str, Any]] = {}
    for key, pairs in sorted(buckets.items()):
        base_corr = [1.0 if b.correctness_pass else 0.0 for b, _c in pairs if b.correctness_pass is not None]
        cand_corr = [1.0 if c.correctness_pass else 0.0 for _b, c in pairs if c.correctness_pass is not None]
        base_grnd = [1.0 if b.grounding_pass else 0.0 for b, _c in pairs if b.grounding_pass is not None]
        cand_grnd = [1.0 if c.grounding_pass else 0.0 for _b, c in pairs if c.grounding_pass is not None]
        b_c, c_c = _mean(base_corr), _mean(cand_corr)
        b_g, c_g = _mean(base_grnd), _mean(cand_grnd)
        out[key] = {
            "n_cases": len(pairs),
            "delta_correctness_pass_rate": round(c_c - b_c, 3) if b_c is not None and c_c is not None else None,
            "delta_grounding_pass_rate": round(c_g - b_g, 3) if b_g is not None and c_g is not None else None,
        }
    return out


def planner_attribution(baseline: Report, candidate: Report) -> dict[str, Any]:
    """Outcome deltas bucketed by the CANDIDATE's intent and by each rule it
    fired -- answers "which planner decisions correlate with a changed
    outcome," the M1.8 objective stated directly.
    """
    return {
        "by_intent": _bucket_delta(baseline, candidate, lambda pm: [pm.intent]),
        "by_rule": _bucket_delta(baseline, candidate, lambda pm: list(pm.rules_fired)),
    }


@dataclass(frozen=True)
class CaseSideBySide:
    """One case's baseline-vs-candidate comparison, for the human read-through
    the milestone is for -- "did planning pull a better passage here, and
    which boost caused it?" Not used for scoring; presentation only.
    """

    case_id: str
    baseline_refused: bool | None
    candidate_refused: bool | None
    baseline_correctness_pass: bool | None
    candidate_correctness_pass: bool | None
    baseline_grounding_pass: bool | None
    candidate_grounding_pass: bool | None
    baseline_answer: str | None
    candidate_answer: str | None
    baseline_selected: tuple[tuple[str, int, int], ...]
    candidate_selected: tuple[tuple[str, int, int], ...]
    ranking_change: dict[str, Any] | None


def side_by_side(baseline: Report, candidate: Report) -> tuple[CaseSideBySide, ...]:
    base_by_id = {r.case_id: r for r in baseline.results}
    out: list[CaseSideBySide] = []
    for cand_r in candidate.results:
        base_r = base_by_id.get(cand_r.case_id)
        if base_r is None:
            continue
        out.append(CaseSideBySide(
            case_id=cand_r.case_id,
            baseline_refused=base_r.refused, candidate_refused=cand_r.refused,
            baseline_correctness_pass=base_r.correctness_pass,
            candidate_correctness_pass=cand_r.correctness_pass,
            baseline_grounding_pass=base_r.grounding_pass,
            candidate_grounding_pass=cand_r.grounding_pass,
            baseline_answer=base_r.answer_prose, candidate_answer=cand_r.answer_prose,
            baseline_selected=base_r.retrieval_metrics.selected if base_r.retrieval_metrics else (),
            candidate_selected=cand_r.retrieval_metrics.selected if cand_r.retrieval_metrics else (),
            ranking_change=_ranking_change_for_case(base_r, cand_r),
        ))
    return tuple(out)


def compare_retrieval(baseline: Report, candidate: Report) -> dict[str, Any]:
    """The full M1.8/M1.8.5 comparison: end-to-end deltas (via
    report.compare()), ranking change, retrieval deltas, retrieval-quality
    deltas (gold-label precision@k/recall@k/MRR, ADR-0005), planner
    attribution, and the per-case side-by-side -- everything the design's
    verification read-through needs, in one call.
    """
    return {
        "baseline": baseline.milestone,
        "candidate": candidate.milestone,
        "end_to_end": compare(baseline, candidate),
        "ranking_change": ranking_change(baseline, candidate),
        "retrieval_deltas": retrieval_deltas(baseline, candidate),
        "retrieval_quality_deltas": retrieval_quality_deltas(baseline, candidate),
        "planner_attribution": planner_attribution(baseline, candidate),
        "side_by_side": side_by_side(baseline, candidate),
    }
