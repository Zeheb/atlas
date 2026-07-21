"""CoverageAnalyzer (M1.8.5 commit 3, ADR-0005).

analyze_suite is pure (no I/O beyond the real plan_retrieval); analyze_corpus
needs a real KnowledgeBase, so those tests build one via the same hermetic
pattern used throughout tests/unit/test_reasoning_retrieval_plan.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.benchmark.coverage import (
    _MIN_CASES_PER_SLOT,
    _REDUNDANCY_THRESHOLD,
    _normalized_entropy,
    analyze,
    analyze_corpus,
    analyze_suite,
)
from atlas.benchmark.taxonomy import ALL_SCENARIO_IDS
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.planner import ALL_RULE_IDS


@dataclass(frozen=True)
class _Case:
    """A minimal CaseLike -- proves the Protocol is structural, not nominal."""
    id: str
    category: str
    question: str
    subject: str = "TCS"
    scenario: str | None = None
    difficulty: str | None = None


# --- _normalized_entropy -----------------------------------------------------------
def test_entropy_zero_when_all_in_one_slot() -> None:
    assert _normalized_entropy({"a": 10}, vocab_size=4) == 0.0


def test_entropy_near_one_when_evenly_spread_across_full_vocab() -> None:
    e = _normalized_entropy({"a": 1, "b": 1, "c": 1, "d": 1}, vocab_size=4)
    assert e == 1.0


def test_entropy_lower_when_vocab_has_unused_slots() -> None:
    even_full = _normalized_entropy({"a": 5, "b": 5}, vocab_size=2)
    even_partial = _normalized_entropy({"a": 5, "b": 5}, vocab_size=9)
    assert even_partial < even_full  # same distribution, bigger unused vocab


def test_entropy_zero_for_empty_counts() -> None:
    assert _normalized_entropy({}, vocab_size=9) == 0.0


# --- analyze_suite: intent/rule floors -----------------------------------------------
def test_missing_intent_detected() -> None:
    cases = [_Case(id="c1", category="A", question="What is the weather today?")]
    cov = analyze_suite(cases)
    assert "esg" in cov.intent.missing


def test_intent_floor_marks_underrepresented_below_three() -> None:
    cases = [
        _Case(id="c1", category="A", question="What are the key risk factors disclosed?"),
        _Case(id="c2", category="A", question="What is the weather today?"),
    ]
    cov = analyze_suite(cases)
    assert "risk" in cov.intent.underrepresented  # 1 case, floor is 3
    assert "risk" not in cov.intent.missing  # not zero either


def test_intent_meets_floor_at_exactly_three_cases() -> None:
    cases = [
        _Case(id=f"c{i}", category="A", question="What are the key risk factors disclosed?")
        for i in range(_MIN_CASES_PER_SLOT)
    ]
    cov = analyze_suite(cases)
    assert "risk" not in cov.intent.underrepresented
    assert "risk" not in cov.intent.missing


def test_dead_rule_detected_when_no_case_triggers_it() -> None:
    cases = [_Case(id="c1", category="A", question="What is the weather today?")]
    cov = analyze_suite(cases)
    assert "period_extraction" in cov.rule.missing
    assert "top_k_narrow_specific_metric" in cov.rule.missing


def test_period_extraction_rule_fires_when_a_case_uses_a_fiscal_period() -> None:
    cases = [_Case(id="c1", category="A", question="What was revenue in FY2024?")]
    cov = analyze_suite(cases)
    assert cov.rule.counts[[k for k, _ in cov.rule.counts].index("period_extraction")][1] == 1


# --- scenario / difficulty / subject / general share -------------------------------
def test_scenario_coverage_only_counts_declared_tags() -> None:
    cases = [
        _Case(id="c1", category="A", question="q1", scenario="temporal"),
        _Case(id="c2", category="A", question="q2", scenario=None),
    ]
    cov = analyze_suite(cases)
    counts = dict(cov.scenario.counts)
    assert counts["temporal"] == 1
    assert set(ALL_SCENARIO_IDS) - {"temporal"} <= set(cov.scenario.missing)


def test_general_intent_share_computed_correctly() -> None:
    cases = [
        _Case(id="c1", category="A", question="What is the weather today?"),  # general
        _Case(id="c2", category="A", question="What is the weather like?"),  # general
        _Case(id="c3", category="A", question="What are the key risk factors disclosed?"),  # risk
    ]
    cov = analyze_suite(cases)
    assert cov.general_intent_share == round(2 / 3, 3)


def test_max_subject_share_flags_single_subject_dominance() -> None:
    cases = [_Case(id=f"c{i}", category="A", question="q", subject="TCS") for i in range(5)]
    cov = analyze_suite(cases)
    assert cov.max_subject_share == 1.0


def test_max_subject_share_with_balanced_subjects() -> None:
    cases = [
        _Case(id="c1", category="A", question="q", subject="TCS"),
        _Case(id="c2", category="A", question="q", subject="SBIN"),
    ]
    cov = analyze_suite(cases)
    assert cov.max_subject_share == 0.5


def test_empty_suite_does_not_crash() -> None:
    cov = analyze_suite([])
    assert cov.total_cases == 0
    assert cov.general_intent_share == 0.0
    assert cov.max_subject_share == 0.0


# --- redundancy ----------------------------------------------------------------------
def test_identical_questions_flagged_as_near_duplicates() -> None:
    cases = [
        _Case(id="c1", category="A", question="What are the key risk factors disclosed this year?"),
        _Case(id="c2", category="A", question="What are the key risk factors disclosed this year?"),
    ]
    cov = analyze_suite(cases)
    assert len(cov.redundancy.near_duplicate_pairs) == 1
    a, b, score = cov.redundancy.near_duplicate_pairs[0]
    assert {a, b} == {"c1", "c2"}
    assert score > _REDUNDANCY_THRESHOLD


def test_dissimilar_questions_not_flagged() -> None:
    cases = [
        _Case(id="c1", category="A", question="What are the key risk factors disclosed?"),
        _Case(id="c2", category="A", question="Did management deliver on the growth target?"),
    ]
    cov = analyze_suite(cases)
    assert cov.redundancy.near_duplicate_pairs == ()


# --- analyze_corpus (real KnowledgeBase) --------------------------------------------
def _seed_kb(tmp_path: Path, subject: str, kind: EvidenceKind, source_field: str) -> None:
    root = tmp_path / subject
    profile = CompanyProfile(
        company_id=subject,
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
        )]),
    )
    CompanyStore(root / "profile.json", subject).save(profile)
    rel = "ev-1.txt"
    (root / rel).write_text("Operating margin stood at 24.2%.", encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1", source=EvidenceSource.BSE.value, kind=kind.value,
        title="Test filing", source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(root).parse(entry)


def test_analyze_corpus_reports_retrievable_kinds_per_subject(tmp_path: Path) -> None:
    _seed_kb(tmp_path, "TCS", EvidenceKind.EARNINGS_TRANSCRIPT, "ev-1")
    cov = analyze_corpus(tmp_path, ["TCS"])
    kinds_by_subject = dict(cov.retrievable_kinds_by_subject)
    assert kinds_by_subject["TCS"] == ("earnings_transcript",)


def test_analyze_corpus_flags_declared_but_unretrievable_kinds(tmp_path: Path) -> None:
    # Only annual_report is ever retrievable -- everything else _INTENT_DOC_TYPES
    # declares (financial_results, brsr, agm_notice, dividend, ...) is dead.
    _seed_kb(tmp_path, "TCS", EvidenceKind.ANNUAL_REPORT, "ev-1")
    cov = analyze_corpus(tmp_path, ["TCS"])
    assert "financial_results" in cov.structurally_dead_doc_types
    assert "annual_report" not in cov.structurally_dead_doc_types


def test_analyze_corpus_handles_missing_subject_gracefully(tmp_path: Path) -> None:
    cov = analyze_corpus(tmp_path, ["NONEXISTENT"])
    kinds_by_subject = dict(cov.retrievable_kinds_by_subject)
    assert kinds_by_subject["NONEXISTENT"] == ()


# --- analyze() composition -----------------------------------------------------------
def test_analyze_without_repo_root_gives_no_corpus_section() -> None:
    result = analyze([_Case(id="c1", category="A", question="q")])
    assert result.corpus is None
    assert result.suite.total_cases == 1


def test_analyze_with_repo_root_includes_corpus_section(tmp_path: Path) -> None:
    _seed_kb(tmp_path, "TCS", EvidenceKind.ANNUAL_REPORT, "ev-1")
    result = analyze([_Case(id="c1", category="A", question="q")], repo_root=tmp_path, subjects=["TCS"])
    assert result.corpus is not None
    assert dict(result.corpus.retrievable_kinds_by_subject)["TCS"] == ("annual_report",)


# --- ALL_RULE_IDS consistency (regression guard) --------------------------------------
def test_rule_dimension_uses_the_real_all_rule_ids() -> None:
    cov = analyze_suite([_Case(id="c1", category="A", question="q")])
    assert {k for k, _v in cov.rule.counts} == ALL_RULE_IDS
