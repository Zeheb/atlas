"""ReasoningResult -> Answer rendering (§10 C9, M0 commit 6)."""
from __future__ import annotations

from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    Finding,
    Question,
    ReasoningResult,
    SubjectRef,
)
from atlas.reasoning.render import format_answer, to_answer

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")


def _result(refused: bool = False) -> ReasoningResult:
    if refused:
        return ReasoningResult(
            question=Question(raw_text="what is it worth?", subject_ref=SUBJECT),
            findings=(), overall_confidence="low", citations=frozenset(),
            refused=True, refusal_reason="No market price data in Atlas.",
        )
    claim = Claim(
        subject_ref=SUBJECT, statement="op margin 24.2%", assertability="fact",
        confidence="high", evidence=[EvidenceReference(evidence_id="ev-1")],
    )
    finding = Finding(
        statement="Margins have been durable near 24%.",
        assertability="judgment", confidence="high", supporting_claims=[claim],
    )
    return ReasoningResult(
        question=Question(raw_text="margins?", subject_ref=SUBJECT),
        findings=[finding], overall_confidence="high",
        citations=frozenset({"ev-1"}),
    )


def test_answer_splits_fact_and_judgment_and_keeps_citations() -> None:
    answer = to_answer(_result())
    assert not answer.refused
    assert answer.judgment_lines == ("Margins have been durable near 24%.",)
    assert [r.evidence_id for r in answer.citations] == ["ev-1"]


def test_answer_citations_are_subset_of_result_citations() -> None:
    result = _result()
    answer = to_answer(result)
    assert {r.evidence_id for r in answer.citations} <= result.citations


def test_refused_result_renders_reason_and_no_citations() -> None:
    answer = to_answer(_result(refused=True))
    assert answer.refused
    assert answer.citations == ()
    text = format_answer(answer)
    assert "cannot answer" in text.lower()
    assert "market price" in text


def test_format_answer_shows_judgment_tag_and_sources() -> None:
    text = format_answer(to_answer(_result()))
    assert "JUDGMENT" in text
    assert "Sources:" in text
    assert "ev-1" in text
