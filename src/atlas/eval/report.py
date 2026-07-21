"""Machine-readable evaluation reports and milestone comparison.

A Report captures per-case results across the four dimensions plus provenance
(milestone, model, git commit), and computes per-dimension aggregates. compare()
diffs two reports so we can answer, after each milestone: did the dimensions
improve, did coverage grow, and did anything regress?

M1.8 (ADR-0004) adds two OPTIONAL nested metric objects to CaseResult --
``retrieval_metrics`` and ``planner_metrics`` -- populated whenever the
runner produced a ``RetrievalResult``/``SearchPlan`` (see ``eval/runner.py``'s
``RunOutcome``). Both default to ``None``, and ``Report.from_dict`` reads them
via ``.get()``, so an M1.7-era report with neither field still loads exactly
as before (backward compatible by construction, not by special-casing).

M1.8.5 (ADR-0005) adds one more OPTIONAL field to ``Report`` itself:
``coverage_snapshot``, a ``CoverageSnapshot`` -- exactly
``benchmark.coverage.analyze_suite()``'s output for the suite this run used,
plus a fingerprint of which case ids produced it. This is BENCHMARK coverage
(does the suite exercise every planner intent/rule/scenario), not run-result
coverage -- ``atlas eval coverage`` computes the identical thing via the
identical function, so a report never carries a second, possibly-diverging
notion of "coverage." Also defaults to ``None`` and reads via ``.get()``, so
an M1.8-era report without it still loads.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

from atlas.benchmark.coverage import (
    DimensionCoverage,
    RedundancyReport,
    SuiteCoverage,
    analyze_suite,
)
from atlas.reasoning.planner import ALL_RULE_IDS

if TYPE_CHECKING:
    from atlas.benchmark.coverage import CaseLike
    from atlas.reasoning.plan import SearchPlan
    from atlas.reasoning.retrieval import RetrievalResult

Status = Literal["active", "pending"]


@dataclass(frozen=True)
class RetrievalCaseMetrics:
    """One case's retrieval diagnostics (M1.8 / ADR-0004) -- built from a
    ``RetrievalResult`` by ``build_retrieval_metrics``, never constructed by
    hand in production code. No LLM involved in producing any of these.
    """

    candidates_considered: int
    docs_searched: int
    selected: tuple[tuple[str, int, int], ...]  # (doc_id, char_offset, total_score)
    doc_type_counts: tuple[tuple[str, int], ...]  # (kind, count) over selected, sorted by kind
    metadata_coverage: float | None  # 1 - missing/searched; None when docs_searched == 0
    boost_totals: tuple[tuple[str, int], ...]  # (boost_name, summed value) over selected
    boost_share: float | None  # fraction of summed score from boosts; None when nothing selected


@dataclass(frozen=True)
class PlannerCaseMetrics:
    """One case's planner diagnostics (M1.8 / ADR-0004) -- built from a
    ``SearchPlan`` by ``build_planner_metrics``.
    """

    intent: str
    preferred_kinds: tuple[str, ...]
    top_k: int
    periods_found: tuple[str, ...]
    rules_fired: tuple[str, ...]


def build_retrieval_metrics(retrieval: "RetrievalResult | None") -> RetrievalCaseMetrics | None:
    """Derive per-case retrieval metrics from a RetrievalResult. Pure, no LLM,
    no I/O -- every input is already in memory on the RunOutcome.
    """
    if retrieval is None:
        return None

    selected = tuple((b.doc_id, b.char_offset, b.total) for b in retrieval.breakdowns)

    doc_type_counter: dict[str, int] = {}
    boost_totals_acc = {"doc_type": 0, "date_window": 0, "period": 0, "recency": 0, "numeric": 0}
    boost_sum = 0
    total_sum = 0
    for b in retrieval.breakdowns:
        doc_type_counter[b.kind or "unknown"] = doc_type_counter.get(b.kind or "unknown", 0) + 1
        boost_totals_acc["doc_type"] += b.doc_type
        boost_totals_acc["date_window"] += b.date_window
        boost_totals_acc["period"] += b.period
        boost_totals_acc["recency"] += b.recency
        boost_totals_acc["numeric"] += b.numeric
        boost_sum += b.doc_type + b.date_window + b.period + b.recency + b.numeric
        total_sum += b.total

    metadata_coverage = (
        1.0 - (len(retrieval.docs_missing_metadata) / retrieval.docs_searched)
        if retrieval.docs_searched > 0 else None
    )
    boost_share = round(boost_sum / total_sum, 3) if total_sum > 0 else None

    return RetrievalCaseMetrics(
        candidates_considered=retrieval.candidates_considered,
        docs_searched=retrieval.docs_searched,
        selected=selected,
        doc_type_counts=tuple(sorted(doc_type_counter.items())),
        metadata_coverage=(round(metadata_coverage, 3) if metadata_coverage is not None else None),
        boost_totals=tuple(sorted(boost_totals_acc.items())),
        boost_share=boost_share,
    )


def build_planner_metrics(plan: "SearchPlan | None") -> PlannerCaseMetrics | None:
    """Derive per-case planner metrics from a SearchPlan. Pure, no LLM."""
    if plan is None:
        return None
    return PlannerCaseMetrics(
        intent=plan.intent,
        preferred_kinds=tuple(p.kind for p in plan.preferred_doc_types),
        top_k=plan.top_k,
        periods_found=plan.periods,
        rules_fired=tuple(d.rule for d in plan.decisions),
    )


def _retrieval_metrics_from_dict(d: dict[str, Any] | None) -> RetrievalCaseMetrics | None:
    if d is None:
        return None
    return RetrievalCaseMetrics(
        candidates_considered=d["candidates_considered"],
        docs_searched=d.get("docs_searched", 0),
        selected=tuple(tuple(x) for x in d.get("selected", ())),
        doc_type_counts=tuple(tuple(x) for x in d.get("doc_type_counts", ())),
        metadata_coverage=d.get("metadata_coverage"),
        boost_totals=tuple(tuple(x) for x in d.get("boost_totals", ())),
        boost_share=d.get("boost_share"),
    )


def _planner_metrics_from_dict(d: dict[str, Any] | None) -> PlannerCaseMetrics | None:
    if d is None:
        return None
    return PlannerCaseMetrics(
        intent=d["intent"],
        preferred_kinds=tuple(d.get("preferred_kinds", ())),
        top_k=d["top_k"],
        periods_found=tuple(d.get("periods_found", ())),
        rules_fired=tuple(d.get("rules_fired", ())),
    )


@dataclass(frozen=True)
class CoverageSnapshot:
    """Benchmark coverage AT THE TIME OF THIS RUN (M1.8.5 / ADR-0005) --
    exactly ``analyze_suite()``'s output for the suite this run used, plus a
    fingerprint of which case ids produced it. Embedded in ``Report`` so a
    run's provenance includes not just the model/git commit but also which
    benchmark gaps existed when it ran.
    """

    suite_fingerprint: str
    suite: SuiteCoverage


def build_coverage_snapshot(cases: Sequence["CaseLike"]) -> CoverageSnapshot:
    """The ONE place a Report acquires its coverage snapshot -- calls
    ``analyze_suite`` directly, never a second implementation (ADR-0005).
    """
    fingerprint = hashlib.sha256(
        ",".join(sorted(c.id for c in cases)).encode("utf-8")
    ).hexdigest()
    return CoverageSnapshot(suite_fingerprint=fingerprint, suite=analyze_suite(cases))


def _dimension_coverage_from_dict(d: dict[str, Any]) -> DimensionCoverage:
    return DimensionCoverage(
        counts=tuple(tuple(x) for x in d["counts"]),
        missing=tuple(d["missing"]),
        underrepresented=tuple(d["underrepresented"]),
        entropy=d["entropy"],
    )


def _redundancy_report_from_dict(d: dict[str, Any]) -> RedundancyReport:
    return RedundancyReport(
        near_duplicate_pairs=tuple(tuple(x) for x in d["near_duplicate_pairs"]),
        threshold=d["threshold"],
    )


def _suite_coverage_from_dict(d: dict[str, Any]) -> SuiteCoverage:
    return SuiteCoverage(
        total_cases=d["total_cases"],
        intent=_dimension_coverage_from_dict(d["intent"]),
        rule=_dimension_coverage_from_dict(d["rule"]),
        scenario=_dimension_coverage_from_dict(d["scenario"]),
        subject_counts=tuple(tuple(x) for x in d["subject_counts"]),
        difficulty_counts=tuple(tuple(x) for x in d["difficulty_counts"]),
        general_intent_share=d["general_intent_share"],
        max_subject_share=d["max_subject_share"],
        redundancy=_redundancy_report_from_dict(d["redundancy"]),
    )


def _coverage_snapshot_from_dict(d: dict[str, Any] | None) -> CoverageSnapshot | None:
    if d is None:
        return None
    return CoverageSnapshot(
        suite_fingerprint=d["suite_fingerprint"],
        suite=_suite_coverage_from_dict(d["suite"]),
    )


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    status: Status
    refused: bool | None = None
    correctness_pass: bool | None = None
    correctness_reasons: tuple[str, ...] = ()
    grounding_pass: bool | None = None
    grounding_reasons: tuple[str, ...] = ()
    reasoning_quality: int | None = None
    usefulness: int | None = None
    # §12.6 amendment 3: judged completeness against the available evidence,
    # plus the free deterministic proxy (distinct evidence documents cited).
    evidence_use: int | None = None
    distinct_docs_cited: int | None = None
    judge_notes: str = ""
    error: str | None = None
    # M1.8 (ADR-0004): both None unless the runner produced retrieval/planner
    # diagnostics (RunOutcome.retrieval / .plan). Retrieval-only mode
    # populates these with no LLM involved at all.
    retrieval_metrics: RetrievalCaseMetrics | None = None
    planner_metrics: PlannerCaseMetrics | None = None
    # M1.8 (ADR-0004): the answer's prose (or "[REFUSED] <reason>", matching
    # judge.py's own formatting convention), kept ONLY for the comparison
    # engine's human side-by-side read-through -- no dimension is scored from
    # it. None when no answer was produced (--retrieval-only mode, or error).
    answer_prose: str | None = None


@dataclass(frozen=True)
class Report:
    milestone: str
    created_at: str
    model: str
    capabilities: tuple[str, ...]
    results: tuple[CaseResult, ...]
    git_commit: str | None = None
    # Judge model recorded separately from the reasoning model: the instrument
    # is pinned independently of the system under test (§12.6 amendment 1).
    judge_model: str | None = None
    # Free-tier operation: LLM-call cache hit/miss counts for this run, when
    # caching was enabled. Optional and additive — absent in older reports,
    # which from_dict() reads as None, so report compatibility is preserved.
    cache_hits: int | None = None
    cache_misses: int | None = None
    # M1.8.5 (ADR-0005): benchmark coverage AT THE TIME OF THIS RUN. None for
    # any report built before this field existed, or if the caller chose not
    # to compute one -- from_dict() reads it via .get(), so an M1.8-era
    # report still loads exactly as before.
    coverage_snapshot: CoverageSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "milestone": self.milestone,
            "created_at": self.created_at,
            "model": self.model,
            "judge_model": self.judge_model,
            "git_commit": self.git_commit,
            "capabilities": list(self.capabilities),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "coverage_snapshot": asdict(self.coverage_snapshot) if self.coverage_snapshot else None,
            "aggregates": aggregate(self.results),
            "results": [asdict(r) for r in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Report":
        results = tuple(
            CaseResult(
                case_id=r["case_id"], category=r["category"], status=r["status"],
                refused=r.get("refused"),
                correctness_pass=r.get("correctness_pass"),
                correctness_reasons=tuple(r.get("correctness_reasons", ())),
                grounding_pass=r.get("grounding_pass"),
                grounding_reasons=tuple(r.get("grounding_reasons", ())),
                reasoning_quality=r.get("reasoning_quality"),
                usefulness=r.get("usefulness"),
                evidence_use=r.get("evidence_use"),
                distinct_docs_cited=r.get("distinct_docs_cited"),
                judge_notes=r.get("judge_notes", ""),
                error=r.get("error"),
                retrieval_metrics=_retrieval_metrics_from_dict(r.get("retrieval_metrics")),
                planner_metrics=_planner_metrics_from_dict(r.get("planner_metrics")),
                answer_prose=r.get("answer_prose"),
            )
            for r in d["results"]
        )
        return cls(
            milestone=d["milestone"], created_at=d["created_at"], model=d["model"],
            capabilities=tuple(d.get("capabilities", ())), results=results,
            git_commit=d.get("git_commit"), judge_model=d.get("judge_model"),
            cache_hits=d.get("cache_hits"), cache_misses=d.get("cache_misses"),
            coverage_snapshot=_coverage_snapshot_from_dict(d.get("coverage_snapshot")),
        )

    @classmethod
    def from_json(cls, text: str) -> "Report":
        return cls.from_dict(json.loads(text))


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _aggregate_planner(active: list[CaseResult]) -> dict[str, Any] | None:
    """Suite-level planner aggregates (M1.8 / ADR-0004): intent distribution,
    rule firing counts, top_k distribution, and DEAD RULES -- declared
    PlanningDecision rules that never fired across the suite. Dead rules are
    the highest-value signal for "which planner decisions create value": a
    rule that never fires cannot have created any effect worth keeping.
    Returns None when no case in this report carries planner metrics at all
    (e.g. an older report, or a run with no strategy/capability active).
    """
    with_planner = [r.planner_metrics for r in active if r.planner_metrics is not None]
    if not with_planner:
        return None

    intent_counts: dict[str, int] = {}
    rule_counts: dict[str, int] = {}
    top_k_counts: dict[str, int] = {}
    for pm in with_planner:
        intent_counts[pm.intent] = intent_counts.get(pm.intent, 0) + 1
        key = str(pm.top_k)
        top_k_counts[key] = top_k_counts.get(key, 0) + 1
        for rule in pm.rules_fired:
            rule_counts[rule] = rule_counts.get(rule, 0) + 1

    dead_rules = sorted(ALL_RULE_IDS - frozenset(rule_counts))
    return {
        "cases_with_plan": len(with_planner),
        "intent_distribution": dict(sorted(intent_counts.items())),
        "rule_fire_counts": dict(sorted(rule_counts.items())),
        "top_k_distribution": dict(sorted(top_k_counts.items())),
        "dead_rules": dead_rules,
    }


def _aggregate_retrieval(active: list[CaseResult]) -> dict[str, Any] | None:
    """Suite-level retrieval aggregates (M1.8 / ADR-0004). None when no case
    in this report carries retrieval metrics.
    """
    with_retrieval = [r.retrieval_metrics for r in active if r.retrieval_metrics is not None]
    if not with_retrieval:
        return None

    candidates = [float(m.candidates_considered) for m in with_retrieval]
    coverage = [m.metadata_coverage for m in with_retrieval if m.metadata_coverage is not None]
    boost_share = [m.boost_share for m in with_retrieval if m.boost_share is not None]
    doc_type_totals: dict[str, int] = {}
    for m in with_retrieval:
        for kind, count in m.doc_type_counts:
            doc_type_totals[kind] = doc_type_totals.get(kind, 0) + count

    return {
        "cases_with_retrieval": len(with_retrieval),
        "mean_candidates_considered": _mean(candidates),
        "mean_metadata_coverage": _mean(coverage),
        "mean_boost_share": _mean(boost_share),
        "doc_type_distribution": dict(sorted(doc_type_totals.items())),
    }


def aggregate(results: tuple[CaseResult, ...]) -> dict[str, Any]:
    """Per-dimension aggregates. Pending cases count only toward coverage."""
    active = [r for r in results if r.status == "active"]
    correctness = [r.correctness_pass for r in active if r.correctness_pass is not None]
    grounding = [r.grounding_pass for r in active if r.grounding_pass is not None]
    quality = [r.reasoning_quality for r in active if r.reasoning_quality is not None]
    useful = [r.usefulness for r in active if r.usefulness is not None]
    ev_use = [r.evidence_use for r in active if r.evidence_use is not None]
    docs = [r.distinct_docs_cited for r in active if r.distinct_docs_cited is not None]
    refused = [r.refused for r in active if r.refused is not None]
    return {
        "total_cases": len(results),
        "active_cases": len(active),
        "coverage": round(len(active) / len(results), 3) if results else 0.0,
        "correctness_pass_rate": _mean([1.0 if p else 0.0 for p in correctness]),
        "grounding_pass_rate": _mean([1.0 if p else 0.0 for p in grounding]),
        "mean_reasoning_quality": _mean([float(q) for q in quality]),
        "mean_usefulness": _mean([float(u) for u in useful]),
        "mean_evidence_use": _mean([float(e) for e in ev_use]),
        "mean_distinct_docs_cited": _mean([float(d) for d in docs]),
        # M1.8 (ADR-0004): None when no case has a definite refused/answered
        # outcome yet (e.g. every case errored) -- consistent with every
        # other rate above, which is also None rather than 0.0 when empty.
        "refusal_rate": _mean([1.0 if r else 0.0 for r in refused]),
        "errors": sum(1 for r in active if r.error),
        "planner": _aggregate_planner(active),
        "retrieval": _aggregate_retrieval(active),
    }


def compare(baseline: Report, candidate: Report) -> dict[str, Any]:
    """Diff two reports: per-dimension deltas, regressions, newly-active cases."""
    base_agg, cand_agg = aggregate(baseline.results), aggregate(candidate.results)
    dims = [
        "coverage", "correctness_pass_rate", "grounding_pass_rate",
        "mean_reasoning_quality", "mean_usefulness", "mean_evidence_use",
        "refusal_rate",  # M1.8 (ADR-0004)
    ]
    deltas: dict[str, Any] = {}
    for d in dims:
        b, c = base_agg.get(d), cand_agg.get(d)
        deltas[d] = {
            "baseline": b, "candidate": c,
            "delta": round(c - b, 3) if isinstance(b, (int, float)) and isinstance(c, (int, float)) else None,
        }

    base_by_id = {r.case_id: r for r in baseline.results}
    regressions: list[str] = []
    newly_active: list[str] = []
    for r in candidate.results:
        b = base_by_id.get(r.case_id)
        if b is None:
            continue
        if b.status == "pending" and r.status == "active":
            newly_active.append(r.case_id)
        if b.status == "active" and r.status == "active":
            if b.correctness_pass and not r.correctness_pass:
                regressions.append(f"{r.case_id}: correctness")
            if b.grounding_pass and not r.grounding_pass:
                regressions.append(f"{r.case_id}: grounding")

    return {
        "baseline": baseline.milestone,
        "candidate": candidate.milestone,
        "dimensions": deltas,
        "regressions": regressions,
        "newly_active": newly_active,
    }
