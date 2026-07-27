"""Subjective judge (eval commit 3; freeze amendments 2-4, §12.6).
FakeLLMClient — no network."""

from __future__ import annotations

import json

import pytest

from atlas.eval.cases import EvalCase
from atlas.eval.judge import Judge, JudgeParseError
from atlas.reasoning.contracts import (
    Answer,
    Claim,
    EvidenceReference,
    GroundingContext,
    SubjectRef,
)
from atlas.reasoning.llm import FakeLLMClient

CASE = EvalCase(
    id="c",
    category="D",
    question="Is management credible?",
    subject="TCS",
    expected_behavior="answer",
    rubric="marked judgment",
)
ANSWER = Answer(
    prose="Credible; guidance mostly met.", citations=(), overall_confidence="high"
)

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _context() -> GroundingContext:
    claim = Claim(
        subject_ref=SUBJECT,
        statement="financial_roe = 42.6 (period 2022-03-31)",
        assertability="fact",
        confidence="high",
        evidence=[EvidenceReference(evidence_id="ev-roe")],
    )
    return GroundingContext(
        subject_ref=SUBJECT, claims=[claim], evidence_index=frozenset({"ev-roe"})
    )


def _judge(payload: dict) -> Judge:
    return Judge(FakeLLMClient(response=json.dumps(payload)))


def test_returns_scores_from_judge_output() -> None:
    verdict = _judge(
        {"reasoning_quality": 4, "usefulness": 3, "evidence_use": 5, "notes": "solid"}
    ).evaluate(CASE, ANSWER)
    assert verdict.reasoning_quality == 4
    assert verdict.usefulness == 3
    assert verdict.evidence_use == 5
    assert verdict.notes == "solid"


def test_scores_are_clamped_to_1_5() -> None:
    verdict = _judge(
        {"reasoning_quality": 9, "usefulness": -2, "evidence_use": 0, "notes": ""}
    ).evaluate(CASE, ANSWER)
    assert verdict.reasoning_quality == 5
    assert verdict.usefulness == 1
    assert verdict.evidence_use == 1


def test_unparseable_output_raises() -> None:
    with pytest.raises(JudgeParseError):
        Judge(FakeLLMClient(response="not json")).evaluate(CASE, ANSWER)


def test_prompt_includes_question_and_rubric() -> None:
    fake = FakeLLMClient(
        response=json.dumps(
            {"reasoning_quality": 3, "usefulness": 3, "evidence_use": 3, "notes": ""}
        )
    )
    Judge(fake).evaluate(CASE, ANSWER)
    _system, user = fake.calls[0]
    assert "Is management credible?" in user
    assert "marked judgment" in user


# --- Amendment 2: judge receives the available evidence -----------------------
def test_context_claims_are_rendered_into_prompt() -> None:
    fake = FakeLLMClient(
        response=json.dumps(
            {"reasoning_quality": 3, "usefulness": 3, "evidence_use": 3, "notes": ""}
        )
    )
    Judge(fake).evaluate(CASE, ANSWER, _context())
    _system, user = fake.calls[0]
    assert "AVAILABLE EVIDENCE" in user
    assert "financial_roe = 42.6" in user
    assert "ev-roe" in user


def test_no_context_omits_evidence_block() -> None:
    fake = FakeLLMClient(
        response=json.dumps(
            {"reasoning_quality": 3, "usefulness": 3, "evidence_use": 3, "notes": ""}
        )
    )
    Judge(fake).evaluate(CASE, ANSWER)  # context omitted
    _system, user = fake.calls[0]
    assert "AVAILABLE EVIDENCE" not in user


# --- Amendment 4: refused answers are judged too ------------------------------
def test_refused_answer_is_rendered_with_refused_marker() -> None:
    refused = Answer(
        prose="",
        citations=(),
        overall_confidence="low",
        refused=True,
        refusal_reason="No market price data in Atlas.",
    )
    fake = FakeLLMClient(
        response=json.dumps(
            {
                "reasoning_quality": 5,
                "usefulness": 4,
                "evidence_use": 5,
                "notes": "clean refusal",
            }
        )
    )
    verdict = Judge(fake).evaluate(CASE, refused, _context())
    _system, user = fake.calls[0]
    assert "[REFUSED] No market price data in Atlas." in user
    assert verdict.reasoning_quality == 5
