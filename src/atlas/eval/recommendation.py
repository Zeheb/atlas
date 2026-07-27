"""Advisory recommendation verdict for enabling retrieval planning by default
(M1.8 commit 8, ADR-0004).

Phase 1 (this milestone): compute the thresholds below automatically and
emit a recommendation. This NEVER fails a command -- ``recommend()`` returns
a value, it never raises for a bad verdict, and no CLI command exits non-zero
because of it. Enforcement is a distinct Phase 2, gated on the recommendation
matching the human enable/hold decision across >=3 evaluation runs on
distinct git commits, with no threshold firing spuriously (see ADR-0004).

Every threshold below is EXPLICITLY UNVALIDATED. M1.8's purpose is learning
whether these metrics predict retrieval quality at all; enforcing a
threshold derived from the same data used to validate it would be circular.
Treat the numbers as a starting hypothesis, not policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from atlas.eval.comparison import ranking_change
from atlas.eval.report import Report, aggregate

Verdict = Literal["SAFE_TO_ENABLE", "NOT_READY", "INSUFFICIENT_DATA"]

# Thresholds -- see module docstring: proposed, not validated.
_MIN_ACTIVE_CASES_WITH_ANSWERS = 20
_MAX_REFUSAL_RATE_INCREASE = 0.02
_MIN_CHANGED_SELECTION_FRACTION = 0.20


@dataclass(frozen=True)
class Recommendation:
    """The verdict plus the record of every criterion checked to reach it --
    printed and persisted, never enforced (Phase 1 / ADR-0004).
    """

    verdict: Verdict
    reasons: tuple[str, ...]
    criteria: dict[str, Any]


def _agg_delta(
    base_agg: dict[str, Any], cand_agg: dict[str, Any], key: str
) -> float | None:
    b, c = base_agg.get(key), cand_agg.get(key)
    return (
        round(c - b, 3)
        if isinstance(b, (int, float)) and isinstance(c, (int, float))
        else None
    )


def _grounding_regressions(baseline: Report, candidate: Report) -> list[str]:
    """Case ids grounded under baseline that fail grounding under candidate --
    a hard criterion (grounding is a product guarantee, G1/G10), not a
    weighted signal like the others.
    """
    base_by_id = {r.case_id: r for r in baseline.results}
    regressions: list[str] = []
    for c in candidate.results:
        b = base_by_id.get(c.case_id)
        if b is None or b.status != "active" or c.status != "active":
            continue
        if b.grounding_pass and not c.grounding_pass:
            regressions.append(c.case_id)
    return sorted(regressions)


def _fraction_changed_selection(rc: dict[str, Any]) -> float | None:
    """Fraction of compared cases whose selected-passage SET differs at all
    (jaccard < 1) -- a broader signal than ranking_change's own
    ``fraction_changed_top1``, since a plan can matter without moving rank 1.
    """
    per_case = rc.get("per_case", ())
    if not per_case:
        return None
    changed = sum(1 for c in per_case if c["jaccard_overlap"] < 1.0)
    return round(changed / len(per_case), 3)


def recommend(baseline: Report, candidate: Report) -> Recommendation:
    """Compute the Phase 1 advisory verdict for enabling retrieval planning
    by default, comparing *candidate* (planned) against *baseline*.
    """
    active_with_answers = sum(
        1
        for r in candidate.results
        if r.status == "active" and r.correctness_pass is not None
    )
    if active_with_answers < _MIN_ACTIVE_CASES_WITH_ANSWERS:
        return Recommendation(
            verdict="INSUFFICIENT_DATA",
            reasons=(
                f"only {active_with_answers} active case(s) with answers "
                f"(need >= {_MIN_ACTIVE_CASES_WITH_ANSWERS}); rerun with --with-answers "
                "on a larger suite -- retrieval metrics alone cannot judge answer quality.",
            ),
            criteria={"active_cases_with_answers": active_with_answers},
        )

    base_agg, cand_agg = aggregate(baseline.results), aggregate(candidate.results)
    grounding_regressions = _grounding_regressions(baseline, candidate)
    correctness_delta = _agg_delta(base_agg, cand_agg, "correctness_pass_rate")
    refusal_delta = _agg_delta(base_agg, cand_agg, "refusal_rate")
    evidence_use_delta = _agg_delta(base_agg, cand_agg, "mean_evidence_use")
    usefulness_delta = _agg_delta(base_agg, cand_agg, "mean_usefulness")
    changed_fraction = _fraction_changed_selection(ranking_change(baseline, candidate))

    criteria: dict[str, Any] = {
        "active_cases_with_answers": active_with_answers,
        "grounding_regressions": grounding_regressions,
        "correctness_pass_rate_delta": correctness_delta,
        "refusal_rate_delta": refusal_delta,
        "mean_evidence_use_delta": evidence_use_delta,
        "mean_usefulness_delta": usefulness_delta,
        "fraction_changed_selection": changed_fraction,
    }

    reasons: list[str] = []
    ok = True

    if grounding_regressions:
        ok = False
        reasons.append(
            f"grounding regressed on {len(grounding_regressions)} case(s): {grounding_regressions}"
        )
    else:
        reasons.append("no grounding regressions")

    if correctness_delta is None or correctness_delta < 0:
        ok = False
        reasons.append(
            f"correctness_pass_rate delta is {correctness_delta} (need >= 0)"
        )
    else:
        reasons.append(f"correctness_pass_rate delta {correctness_delta} >= 0")

    if refusal_delta is not None and refusal_delta > _MAX_REFUSAL_RATE_INCREASE:
        ok = False
        reasons.append(
            f"refusal_rate delta {refusal_delta} exceeds +{_MAX_REFUSAL_RATE_INCREASE}"
        )
    else:
        reasons.append(
            f"refusal_rate delta {refusal_delta} within +{_MAX_REFUSAL_RATE_INCREASE}"
        )

    evidence_or_usefulness_ok = (
        evidence_use_delta is not None and evidence_use_delta >= 0
    ) or (usefulness_delta is not None and usefulness_delta >= 0)
    if not evidence_or_usefulness_ok:
        ok = False
        reasons.append(
            f"neither mean_evidence_use delta ({evidence_use_delta}) nor "
            f"mean_usefulness delta ({usefulness_delta}) is >= 0"
        )
    else:
        reasons.append("mean_evidence_use or mean_usefulness delta is >= 0")

    if changed_fraction is None or changed_fraction < _MIN_CHANGED_SELECTION_FRACTION:
        ok = False
        reasons.append(
            f"only {changed_fraction} of cases show a changed passage selection "
            f"(need >= {_MIN_CHANGED_SELECTION_FRACTION}) -- planning has no measurable effect"
        )
    else:
        reasons.append(f"{changed_fraction} of cases show a changed passage selection")

    return Recommendation(
        verdict=("SAFE_TO_ENABLE" if ok else "NOT_READY"),
        reasons=tuple(reasons),
        criteria=criteria,
    )
