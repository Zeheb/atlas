"""Runner orchestration + report/compare (eval commit 4). Fakes — no network."""
from __future__ import annotations

import json

from atlas.eval.cases import EvalCase
from atlas.eval.judge import Judge
from atlas.eval.report import CaseResult, Report, aggregate, compare
from atlas.eval.runner import RunnerError, run_suite
from atlas.reasoning.client import FakeLLMClient
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


def _grounded() -> tuple[ReasoningResult, Answer, GroundingContext]:
    ref = EvidenceReference(evidence_id="ev-1")
    claim = Claim(subject_ref=SUBJECT, statement="op margin 24%", assertability="fact",
                  confidence="high", evidence=[ref])
    finding = Finding(statement="durable margins", assertability="judgment",
                      confidence="high", supporting_claims=[claim])
    result = ReasoningResult(question=Question(raw_text="q", subject_ref=SUBJECT),
                             findings=[finding], overall_confidence="high",
                             citations=frozenset({"ev-1"}))
    context = GroundingContext(subject_ref=SUBJECT, claims=[claim],
                               evidence_index=frozenset({"ev-1"}))
    answer = Answer(prose="Durable margins [ev-1]", citations=(ref,), overall_confidence="high")
    return result, answer, context


class _FakeRunner:
    def run(self, case: EvalCase):  # noqa: ANN201 - test double
        return _grounded()


class _BrokenRunner:
    def run(self, case: EvalCase):  # noqa: ANN201 - test double
        raise RunnerError("no profile")


def _cases() -> list[EvalCase]:
    return [
        EvalCase(id="t01", category="A", question="margins?", subject="TCS",
                 expected_behavior="answer", rubric="synthesize"),
        EvalCase(id="t29", category="F", question="weakest assumption?", subject="TCS",
                 expected_behavior="answer", rubric="thesis", requires=("thesis",)),
    ]


def _judge() -> Judge:
    return Judge(FakeLLMClient(response=json.dumps(
        {"reasoning_quality": 4, "usefulness": 4, "notes": "ok"})))


def test_run_suite_scores_active_and_marks_pending() -> None:
    report = run_suite(_cases(), _FakeRunner(), _judge(), {"single_name"},
                       milestone="M0", model="fake")
    by_id = {r.case_id: r for r in report.results}
    assert by_id["t29"].status == "pending"          # requires thesis (absent)
    active = by_id["t01"]
    assert active.status == "active"
    assert active.correctness_pass and active.grounding_pass
    assert active.reasoning_quality == 4 and active.usefulness == 4


def test_aggregates_reflect_scores_and_coverage() -> None:
    report = run_suite(_cases(), _FakeRunner(), _judge(), {"single_name"},
                       milestone="M0", model="fake")
    agg = aggregate(report.results)
    assert agg["coverage"] == 0.5                    # 1 of 2 active
    assert agg["correctness_pass_rate"] == 1.0
    assert agg["mean_reasoning_quality"] == 4.0


def test_broken_runner_records_error_without_aborting() -> None:
    report = run_suite(_cases()[:1], _BrokenRunner(), None, {"single_name"},
                       milestone="M0", model="fake")
    assert report.results[0].error == "no profile"


def test_report_json_roundtrips() -> None:
    report = run_suite(_cases(), _FakeRunner(), _judge(), {"single_name"},
                       milestone="M0", model="fake")
    restored = Report.from_json(report.to_json())
    assert restored.milestone == "M0"
    assert len(restored.results) == 2


def test_compare_shows_delta_and_newly_active() -> None:
    baseline = run_suite(_cases(), _FakeRunner(), _judge(), {"single_name"},
                         milestone="M0", model="fake")
    candidate = run_suite(_cases(), _FakeRunner(), _judge(), {"single_name", "thesis"},
                          milestone="M2", model="fake")
    diff = compare(baseline, candidate)
    assert diff["dimensions"]["coverage"]["delta"] == 0.5   # 0.5 -> 1.0
    assert "t29" in diff["newly_active"]
    assert diff["regressions"] == []
