"""Subjective judge (eval commit 3). FakeLLMClient — no network."""
from __future__ import annotations

import json

import pytest

from atlas.eval.cases import EvalCase
from atlas.eval.judge import Judge, JudgeParseError
from atlas.reasoning.client import FakeLLMClient
from atlas.reasoning.contracts import Answer

CASE = EvalCase(id="c", category="D", question="Is management credible?",
                subject="TCS", expected_behavior="answer", rubric="marked judgment")
ANSWER = Answer(prose="Credible; guidance mostly met.", citations=(), overall_confidence="high")


def _judge(payload: dict) -> Judge:
    return Judge(FakeLLMClient(response=json.dumps(payload)))


def test_returns_scores_from_judge_output() -> None:
    verdict = _judge({"reasoning_quality": 4, "usefulness": 3, "notes": "solid"}).evaluate(
        CASE, ANSWER
    )
    assert verdict.reasoning_quality == 4
    assert verdict.usefulness == 3
    assert verdict.notes == "solid"


def test_scores_are_clamped_to_1_5() -> None:
    verdict = _judge({"reasoning_quality": 9, "usefulness": -2, "notes": ""}).evaluate(
        CASE, ANSWER
    )
    assert verdict.reasoning_quality == 5
    assert verdict.usefulness == 1


def test_unparseable_output_raises() -> None:
    with pytest.raises(JudgeParseError):
        Judge(FakeLLMClient(response="not json")).evaluate(CASE, ANSWER)


def test_prompt_includes_question_and_rubric() -> None:
    fake = FakeLLMClient(response=json.dumps({"reasoning_quality": 3, "usefulness": 3, "notes": ""}))
    Judge(fake).evaluate(CASE, ANSWER)
    _system, user = fake.calls[0]
    assert "Is management credible?" in user
    assert "marked judgment" in user
