"""Deterministic grounding + correctness scorers (eval commit 2)."""

from __future__ import annotations

from atlas.eval.cases import EvalCase
from atlas.eval.correctness import score_correctness
from atlas.eval.grounding import score_grounding
from atlas.reasoning.contracts import (
    Answer,
    Claim,
    EvidenceReference,
    Finding,
    GroundingContext,
    Question,
    ReasoningResult,
    SubjectRef,
)

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _context(ids: set[str]) -> GroundingContext:
    claims = [
        Claim(
            subject_ref=SUBJECT,
            statement=f"fact {i}",
            assertability="fact",
            confidence="high",
            evidence=[EvidenceReference(evidence_id=i)],
        )
        for i in ids
    ]
    return GroundingContext(
        subject_ref=SUBJECT, claims=claims, evidence_index=frozenset(ids)
    )


def _answered(citations: set[str]) -> ReasoningResult:
    claim = Claim(
        subject_ref=SUBJECT,
        statement="op margin",
        assertability="fact",
        confidence="high",
        evidence=[EvidenceReference(evidence_id=i) for i in citations],
    )
    finding = Finding(
        statement="durable",
        assertability="judgment",
        confidence="high",
        supporting_claims=[claim],
    )
    return ReasoningResult(
        question=Question(raw_text="q", subject_ref=SUBJECT),
        findings=[finding],
        overall_confidence="high",
        citations=frozenset(citations),
    )


def _refused() -> ReasoningResult:
    return ReasoningResult(
        question=Question(raw_text="q", subject_ref=SUBJECT),
        findings=(),
        overall_confidence="low",
        citations=frozenset(),
        refused=True,
        refusal_reason="no market data",
    )


# --- grounding ---------------------------------------------------------------
def test_grounding_passes_when_answer_cited_within_world() -> None:
    score = score_grounding(_answered({"ev-1"}), _context({"ev-1"}))
    assert score.passed, score.reasons


def test_grounding_flags_citation_outside_world() -> None:
    score = score_grounding(_answered({"ev-1"}), _context({"ev-2"}))
    assert not score.passed
    assert any("not in context" in r for r in score.reasons)


def test_grounding_passes_for_clean_refusal() -> None:
    assert score_grounding(_refused(), _context({"ev-1"})).passed


# --- correctness -------------------------------------------------------------
def _case(behavior: str, **kw) -> EvalCase:
    return EvalCase(
        id="c",
        category="X",
        question="q",
        subject="TCS",
        expected_behavior=behavior,
        rubric="",
        **kw,
    )  # type: ignore[arg-type]


def test_correctness_answer_expected_and_answered() -> None:
    ans = Answer(
        prose="margins durable [ev-1]", citations=(), overall_confidence="high"
    )
    assert score_correctness(_case("answer"), _answered({"ev-1"}), ans).passed


def test_correctness_refuse_expected_but_answered_fails() -> None:
    ans = Answer(prose="it is worth 100", citations=(), overall_confidence="high")
    score = score_correctness(_case("refuse"), _answered({"ev-1"}), ans)
    assert not score.passed


def test_correctness_refuse_expected_and_refused_passes() -> None:
    ans = Answer(
        prose="",
        citations=(),
        overall_confidence="low",
        refused=True,
        refusal_reason="no market data",
    )
    assert score_correctness(_case("refuse"), _refused(), ans).passed


def test_correctness_forbidden_substring_fails() -> None:
    # Behavioral expectation is met (answer/answered); only the forbidden
    # fabrication should trip the failure, isolating that check.
    ans = Answer(
        prose="Yes, management committed to a 30% target.",
        citations=(),
        overall_confidence="high",
    )
    case = _case("answer", must_not_contain=("committed to a 30%",))
    score = score_correctness(case, _answered({"ev-1"}), ans)
    assert not score.passed
    assert any("forbidden" in r for r in score.reasons)


# --- honest_negative (§12.6 amendment 5) --------------------------------------
def test_honest_negative_passes_on_clean_refusal() -> None:
    ans = Answer(
        prose="",
        citations=(),
        overall_confidence="low",
        refused=True,
        refusal_reason="no such promise in the evidence",
    )
    assert score_correctness(_case("honest_negative"), _refused(), ans).passed


def test_honest_negative_passes_on_honest_denial_answer() -> None:
    ans = Answer(
        prose="No such commitment appears anywhere in the evidence.",
        citations=(),
        overall_confidence="high",
    )
    assert score_correctness(_case("honest_negative"), _answered({"ev-1"}), ans).passed


def test_honest_negative_fails_only_on_fabrication() -> None:
    ans = Answer(
        prose="Yes — management committed to a 30% ROE target.",
        citations=(),
        overall_confidence="high",
    )
    case = _case("honest_negative", must_not_contain=("committed to a 30%",))
    score = score_correctness(case, _answered({"ev-1"}), ans)
    assert not score.passed
    assert all("forbidden" in r for r in score.reasons)  # ONLY the guard fires
