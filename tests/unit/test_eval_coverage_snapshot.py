"""CoverageSnapshot embedded in run reports (M1.8.5 commit 6, ADR-0005).

The central acceptance criterion this file exists to prove: the snapshot in
a run report is BYTE-IDENTICAL to calling analyze_suite() directly on the
same cases -- one implementation, never two that could silently diverge.
"""

from __future__ import annotations

import dataclasses
import json

from atlas.benchmark.coverage import analyze_suite
from atlas.eval.cases import EvalCase
from atlas.eval.report import CoverageSnapshot, Report, build_coverage_snapshot
from atlas.eval.runner import RunnerError, RunOutcome, run_suite
from atlas.reasoning.contracts import GroundingContext, SubjectRef

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _cases() -> list[EvalCase]:
    return [
        EvalCase(
            id="t01",
            category="A",
            question="What are the key risk factors disclosed?",
            subject="TCS",
            expected_behavior="answer",
            rubric="r",
        ),
        EvalCase(
            id="t02",
            category="A",
            question="What was revenue in FY2024?",
            subject="TCS",
            expected_behavior="answer",
            rubric="r",
        ),
        EvalCase(
            id="t03",
            category="F",
            question="weakest assumption?",
            subject="TCS",
            expected_behavior="answer",
            rubric="thesis",
            requires=("thesis",),
        ),
    ]


class _FakeRunner:
    def run(self, case: EvalCase) -> RunOutcome:
        context = GroundingContext(
            subject_ref=SUBJECT, claims=(), evidence_index=frozenset()
        )
        return RunOutcome(context=context)  # retrieval-only-shaped: no result/answer


class _BrokenRunner:
    def run(self, case: EvalCase) -> RunOutcome:
        raise RunnerError("no profile")


# --- build_coverage_snapshot ---------------------------------------------------------
def test_snapshot_suite_matches_analyze_suite_directly() -> None:
    cases = _cases()
    snapshot = build_coverage_snapshot(cases)
    assert snapshot.suite == analyze_suite(cases)


def test_snapshot_fingerprint_is_deterministic() -> None:
    cases = _cases()
    a = build_coverage_snapshot(cases)
    b = build_coverage_snapshot(list(reversed(cases)))  # order must not matter
    assert a.suite_fingerprint == b.suite_fingerprint


def test_snapshot_fingerprint_changes_with_case_set() -> None:
    a = build_coverage_snapshot(_cases())
    b = build_coverage_snapshot(_cases()[:2])
    assert a.suite_fingerprint != b.suite_fingerprint


# --- run_suite embeds the identical snapshot ------------------------------------------
def test_run_suite_embeds_snapshot_matching_direct_analyze_suite() -> None:
    cases = _cases()
    report = run_suite(
        cases, _FakeRunner(), None, {"single_name"}, milestone="M0", model="fake"
    )
    assert report.coverage_snapshot is not None
    assert report.coverage_snapshot.suite == analyze_suite(cases)


def test_run_suite_snapshot_covers_full_suite_not_just_active_cases() -> None:
    # t03 requires "thesis" and is pending under {"single_name"} -- coverage
    # must still reflect the FULL suite, since it measures the benchmark
    # itself, not this run's active subset.
    cases = _cases()
    report = run_suite(
        cases, _FakeRunner(), None, {"single_name"}, milestone="M0", model="fake"
    )
    assert report.coverage_snapshot.suite.total_cases == 3


def test_run_suite_embeds_snapshot_even_when_runner_is_broken() -> None:
    report = run_suite(
        _cases()[:1],
        _BrokenRunner(),
        None,
        {"single_name"},
        milestone="M0",
        model="fake",
    )
    assert (
        report.coverage_snapshot is not None
    )  # coverage doesn't depend on execution succeeding


# --- JSON round-trip -------------------------------------------------------------------
def test_snapshot_survives_json_round_trip() -> None:
    cases = _cases()
    report = run_suite(
        cases, _FakeRunner(), None, {"single_name"}, milestone="M0", model="fake"
    )
    restored = Report.from_json(report.to_json())
    assert restored.coverage_snapshot == report.coverage_snapshot


def test_to_dict_snapshot_is_plain_json_serializable() -> None:
    cases = _cases()
    report = run_suite(
        cases, _FakeRunner(), None, {"single_name"}, milestone="M0", model="fake"
    )
    payload = report.to_dict()
    encoded = json.dumps(payload)  # must not raise
    decoded = json.loads(encoded)
    assert decoded["coverage_snapshot"]["suite"]["total_cases"] == 3


# --- Backward compatibility: an M1.8-era report (no coverage_snapshot key) -------------
def test_old_report_without_coverage_snapshot_key_still_loads() -> None:
    old_style = {
        "milestone": "M1.8",
        "created_at": "2026-01-01T00:00:00+00:00",
        "model": "fake",
        "capabilities": ["single_name"],
        "results": [{"case_id": "t01", "category": "A", "status": "active"}],
    }
    report = Report.from_dict(old_style)
    assert report.coverage_snapshot is None


def test_coverage_snapshot_type_is_a_frozen_dataclass() -> None:
    snapshot = build_coverage_snapshot(_cases())
    assert isinstance(snapshot, CoverageSnapshot)
    try:
        snapshot.suite_fingerprint = "x"  # type: ignore[misc]
        assert False, "should have raised"
    except dataclasses.FrozenInstanceError:
        pass
