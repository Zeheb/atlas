"""to_answer(context=...) drill-to-source + format_answer(show_evidence=...)
(M1 commit 4). M0's test_reasoning_render.py (to_answer() with no context)
is untouched and still passes, confirming the default path is unchanged.
"""
from __future__ import annotations

from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    Finding,
    GroundingContext,
    Question,
    ReasoningResult,
    SubjectRef,
)
from atlas.reasoning.render import format_answer, to_answer

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _result_and_context(*, with_excerpt: bool) -> tuple[ReasoningResult, GroundingContext]:
    ref = EvidenceReference(
        evidence_id="ev-1",
        excerpt="Operating margin stood at 24.2% in FY26." if with_excerpt else None,
        section="Financial Highlights" if with_excerpt else None,
    )
    claim = Claim(
        subject_ref=SUBJECT, statement="op margin 24.2%", assertability="fact",
        confidence="high", evidence=[ref],
    )
    finding = Finding(
        statement="Margins have been durable near 24%.",
        assertability="judgment", confidence="high", supporting_claims=[claim],
    )
    result = ReasoningResult(
        question=Question(raw_text="margins?", subject_ref=SUBJECT),
        findings=[finding], overall_confidence="high", citations=frozenset({"ev-1"}),
    )
    context = GroundingContext(subject_ref=SUBJECT, claims=[claim], evidence_index=frozenset({"ev-1"}))
    return result, context


def test_to_answer_without_context_is_m0_equivalent() -> None:
    result, _context = _result_and_context(with_excerpt=True)
    answer = to_answer(result)  # no context passed
    assert answer.citations[0].excerpt is None  # bare, exactly like M0


def test_to_answer_with_context_carries_excerpt() -> None:
    result, context = _result_and_context(with_excerpt=True)
    answer = to_answer(result, context=context)
    assert answer.citations[0].excerpt == "Operating margin stood at 24.2% in FY26."
    assert answer.citations[0].section == "Financial Highlights"


def test_to_answer_with_context_but_no_excerpt_stays_bare() -> None:
    result, context = _result_and_context(with_excerpt=False)
    answer = to_answer(result, context=context)
    assert answer.citations[0].excerpt is None


def test_format_answer_show_evidence_prints_excerpt() -> None:
    result, context = _result_and_context(with_excerpt=True)
    answer = to_answer(result, context=context)
    text = format_answer(answer, show_evidence=True)
    assert "Operating margin stood at 24.2% in FY26." in text
    assert "Financial Highlights" in text


def test_format_answer_show_evidence_declares_missing_excerpt() -> None:
    result, context = _result_and_context(with_excerpt=False)
    answer = to_answer(result, context=context)
    text = format_answer(answer, show_evidence=True)
    assert "no excerpt retrieved" in text


def test_format_answer_default_does_not_print_excerpt() -> None:
    result, context = _result_and_context(with_excerpt=True)
    answer = to_answer(result, context=context)
    text = format_answer(answer)  # show_evidence defaults False
    assert "Operating margin stood at 24.2%" not in text
