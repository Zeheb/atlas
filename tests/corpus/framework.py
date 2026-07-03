"""Evaluation framework for Atlas analyzers.

Measures extraction quality against a fixed expectation set using standard
information-retrieval metrics (precision, recall, F1).

Usage
-----
from tests.corpus.framework import ExpectedFact, evaluate
from atlas.analysis.base import FactKind, FactUnit

expected = [
    ExpectedFact(kind=FactKind.CREDIT_AGENCY, value="CRISIL ESG"),
    ExpectedFact(kind=FactKind.CREDIT_RATING, period="2025-04-18"),
]
eval_result = evaluate(expected, analyzer_result)
assert eval_result.recall == 1.0   # all expected facts found
assert eval_result.missing == 0
"""
from __future__ import annotations

from dataclasses import dataclass, field

from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit


@dataclass
class ExpectedFact:
    """A single expected fact used as a matching criterion.

    Each field set to a non-None value is treated as a required match condition.
    Fields left as None are wildcards (any value in that position matches).
    """

    kind: FactKind
    value: str | float | int | None = None   # None = match any value
    unit: FactUnit | None = None             # None = match any unit (incl. None)
    period: str | None = None               # None = match any period (incl. None)

    def matches(self, fact: AnalysisFact) -> bool:
        if fact.kind != self.kind:
            return False
        if self.value is not None and fact.value != self.value:
            return False
        if self.unit is not None and fact.unit != self.unit:
            return False
        if self.period is not None and fact.period != self.period:
            return False
        return True


@dataclass
class EvalResult:
    """Precision/recall summary for one analyzer run.

    true_positives  — expected facts that were found in result.facts
    missing         — expected facts absent from result.facts (false negatives)
    unexpected      — result.facts not matched to any expectation (false positives)
    warning_issues  — list of warning-related problems (e.g. unexpected warnings)
    """

    true_positives: int
    missing: int
    unexpected: int
    warning_issues: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.unexpected
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.missing
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def evaluate(
    expected: list[ExpectedFact],
    result: AnalysisResult,
    max_warnings: int = 0,
) -> EvalResult:
    """Match expected facts against extracted facts using greedy assignment.

    Each expected fact is matched against the first unmatched result.fact
    that satisfies all its conditions.  Once a fact is matched it is removed
    from the pool (no double-counting).

    The `unexpected` count is the number of extracted facts not claimed by any
    expectation.  This is not treated as an error by default — the corpus
    captures a *minimum* set of expected facts, not an exhaustive enumeration.
    """
    remaining = list(result.facts)
    tp = 0
    fn = 0

    for exp in expected:
        matched = False
        for i, fact in enumerate(remaining):
            if exp.matches(fact):
                tp += 1
                remaining.pop(i)
                matched = True
                break
        if not matched:
            fn += 1

    warning_issues: list[str] = []
    if len(result.warnings) > max_warnings:
        warning_issues.append(
            f"expected ≤{max_warnings} warnings, got {len(result.warnings)}: "
            + ", ".join(repr(w) for w in result.warnings)
        )

    return EvalResult(
        true_positives=tp,
        missing=fn,
        unexpected=len(remaining),
        warning_issues=warning_issues,
    )


def load_expected_facts(raw: list[dict]) -> list[ExpectedFact]:
    """Deserialise a list of expected-fact dicts from a JSON corpus file."""
    result = []
    for item in raw:
        kind = FactKind(item["kind"])
        unit_str = item.get("unit")
        unit = FactUnit(unit_str) if unit_str is not None else None
        result.append(ExpectedFact(
            kind=kind,
            value=item.get("value"),
            unit=unit,
            period=item.get("period"),
        ))
    return result
