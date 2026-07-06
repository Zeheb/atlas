"""Deterministic CORRECTNESS scorer.

Checks behavioral expectations from the acceptance case: did Atlas refuse when it
should (and answer when it should), and did it avoid forbidden fabrications /
include a required fact. Pure function; no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass

from atlas.eval.cases import EvalCase
from atlas.reasoning.contracts import Answer, ReasoningResult


@dataclass(frozen=True)
class CorrectnessScore:
    passed: bool
    reasons: tuple[str, ...]


def _text(answer: Answer) -> str:
    return f"{answer.prose}\n{answer.refusal_reason or ''}".lower()


def score_correctness(
    case: EvalCase, result: ReasoningResult, answer: Answer
) -> CorrectnessScore:
    reasons: list[str] = []
    expected = case.expected_behavior

    # Behavioral expectation: refused-vs-answered must match.
    # "honest_negative" (§12.6 amendment 5): EITHER a clean refusal OR an
    # honest negative answer is acceptable — no behavioral mismatch possible;
    # the fabrication guards below are the teeth.
    if expected == "refuse" and not result.refused:
        reasons.append("expected a refusal but Atlas answered")
    if expected == "answer" and result.refused:
        reasons.append(f"expected an answer but Atlas refused: {result.refusal_reason}")

    text = _text(answer)

    # Forbidden fabrications must not appear (checked on all branches).
    for banned in case.must_not_contain:
        if banned.lower() in text:
            reasons.append(f"contains forbidden text: {banned!r}")

    # A required fact must appear when the case answered (non-refuse classes).
    if expected != "refuse" and not result.refused and case.must_contain_any:
        if not any(want.lower() in text for want in case.must_contain_any):
            reasons.append(f"missing any of required text: {list(case.must_contain_any)}")

    return CorrectnessScore(passed=not reasons, reasons=tuple(reasons))
