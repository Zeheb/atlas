"""--judge-sample: evaluate only a selected subset of cases with the judge
(harness redesign, free-tier operation).

Deterministic scoring (correctness/grounding) must still run for every
active case regardless of sampling — only the LLM judge call is gated.

Sampling by count uses deterministic hash rank (sha256 of the case id), not
suite/file position: the acceptance suite is laid out in category blocks, so
"first N in file order" would concentrate a small sample inside a single
category. Hash rank is unbiased with respect to that layout while remaining
fully deterministic and reproducible.
"""

from __future__ import annotations

import hashlib
import json

from atlas.eval.cases import EvalCase
from atlas.eval.judge import Judge
from atlas.eval.report import CaseResult
from atlas.eval.runner import RunOutcome, resolve_judge_sample, run_suite
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
from atlas.reasoning.llm import FakeLLMClient

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _grounded() -> RunOutcome:
    ref = EvidenceReference(evidence_id="ev-1")
    claim = Claim(
        subject_ref=SUBJECT,
        statement="op margin 24%",
        assertability="fact",
        confidence="high",
        evidence=[ref],
    )
    finding = Finding(
        statement="durable margins",
        assertability="judgment",
        confidence="high",
        supporting_claims=[claim],
    )
    result = ReasoningResult(
        question=Question(raw_text="q", subject_ref=SUBJECT),
        findings=[finding],
        overall_confidence="high",
        citations=frozenset({"ev-1"}),
    )
    context = GroundingContext(
        subject_ref=SUBJECT, claims=[claim], evidence_index=frozenset({"ev-1"})
    )
    answer = Answer(
        prose="Durable margins [ev-1]", citations=(ref,), overall_confidence="high"
    )
    return RunOutcome(context=context, result=result, answer=answer)


class _FakeRunner:
    def run(self, case: EvalCase) -> RunOutcome:
        return _grounded()


def _cases(n: int) -> list[EvalCase]:
    return [
        EvalCase(
            id=f"t{i:02d}",
            category="A",
            question=f"q{i}",
            subject="TCS",
            expected_behavior="answer",
            rubric="synthesize",
        )
        for i in range(1, n + 1)
    ]


def _counting_judge() -> tuple[Judge, FakeLLMClient]:
    fake = FakeLLMClient(
        response=json.dumps(
            {"reasoning_quality": 4, "usefulness": 4, "evidence_use": 4, "notes": "ok"}
        )
    )
    return Judge(fake), fake


def _hash_rank(ids: list[str]) -> list[str]:
    return sorted(ids, key=lambda cid: hashlib.sha256(cid.encode("utf-8")).hexdigest())


# --- resolve_judge_sample (pure parsing) --------------------------------------


def test_none_value_means_judge_everything() -> None:
    assert resolve_judge_sample(None, ["t01", "t02"]) is None


def test_integer_value_selects_n_cases_by_hash_rank_not_file_order() -> None:
    ids = ["t01", "t02", "t03"]
    expected = frozenset(_hash_rank(ids)[:2])
    assert resolve_judge_sample("2", ids) == expected
    assert len(expected) == 2  # sanity: still selects exactly N


def test_hash_rank_sample_is_stable_across_calls() -> None:
    # Determinism: the same id set always yields the same sample, regardless
    # of the order the ids are passed in.
    ids = ["t01", "t02", "t03", "t04", "t05"]
    assert resolve_judge_sample("3", ids) == resolve_judge_sample(
        "3", list(reversed(ids))
    )


def test_hash_rank_sample_is_not_simply_the_first_n_in_input_order() -> None:
    # A regression guard for the specific bug being fixed: with enough ids,
    # hash rank essentially never coincides with plain input order.
    ids = [f"t{i:02d}" for i in range(1, 21)]
    assert resolve_judge_sample("10", ids) != frozenset(ids[:10])


def test_comma_separated_ids_select_exactly_those_cases() -> None:
    assert resolve_judge_sample("t01,t03", ["t01", "t02", "t03"]) == frozenset(
        {"t01", "t03"}
    )


# --- run_suite wiring ----------------------------------------------------------


def test_judge_sample_by_count_judges_only_the_hash_ranked_cases() -> None:
    judge, fake = _counting_judge()
    ids = [f"t{i:02d}" for i in range(1, 5)]
    sampled = _hash_rank(ids)[:2]
    report = run_suite(
        _cases(4),
        _FakeRunner(),
        judge,
        {"single_name"},
        milestone="M0",
        model="fake",
        judge_sample="2",
    )
    by_id = {r.case_id: r for r in report.results}
    for cid in ids:
        expected = 4 if cid in sampled else None
        assert by_id[cid].reasoning_quality == expected
    assert len(fake.calls) == 2  # judge invoked exactly twice, not four times


def test_judge_sample_by_id_judges_only_named_cases() -> None:
    judge, fake = _counting_judge()
    report = run_suite(
        _cases(4),
        _FakeRunner(),
        judge,
        {"single_name"},
        milestone="M0",
        model="fake",
        judge_sample="t01,t04",
    )
    by_id = {r.case_id: r for r in report.results}
    assert by_id["t01"].reasoning_quality == 4
    assert by_id["t04"].reasoning_quality == 4
    assert by_id["t02"].reasoning_quality is None
    assert by_id["t03"].reasoning_quality is None
    assert len(fake.calls) == 2


def test_unjudged_cases_still_get_deterministic_scoring() -> None:
    # Sampling gates only the judge — correctness/grounding must never be
    # skipped, since those are the deterministic dimensions the redesign
    # explicitly promises to leave unchanged.
    judge, _fake = _counting_judge()
    ids = ["t01", "t02"]
    unsampled_id = _hash_rank(ids)[1]  # the one NOT selected by judge_sample="1"
    report = run_suite(
        _cases(2),
        _FakeRunner(),
        judge,
        {"single_name"},
        milestone="M0",
        model="fake",
        judge_sample="1",
    )
    unjudged = next(r for r in report.results if r.case_id == unsampled_id)
    assert unjudged.reasoning_quality is None
    assert unjudged.correctness_pass is True
    assert unjudged.grounding_pass is True


def test_judge_sample_none_preserves_existing_behavior() -> None:
    judge, fake = _counting_judge()
    report = run_suite(
        _cases(3), _FakeRunner(), judge, {"single_name"}, milestone="M0", model="fake"
    )  # judge_sample omitted
    assert all(
        isinstance(r, CaseResult) and r.reasoning_quality == 4 for r in report.results
    )
    assert len(fake.calls) == 3
