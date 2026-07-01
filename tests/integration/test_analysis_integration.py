"""Integration test for atlas.analysis.annual_report against real TCS data.

Requires the TCS annual report to be parsed into knowledge.db first.
Run with: pytest -m integration -v -s

The test also serves as a human-readable demo: run with -s to see the
structured result printed to stdout.
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.annual_report import summarize
from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind
from atlas.knowledge.base import KnowledgeBase

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"
_AR_2024_ID = "bse-news-a8be8b1d-ebc8-4ab7-8081-668fadaf6ecb"
_AR_2024_PATH = "annual_reports/a8be8b1d-ebc8-4ab7-8081-668fadaf6ecb.pdf"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tcs_root() -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found at repositories/TCS")
    pdf = _TCS_REPO / _AR_2024_PATH
    if not pdf.exists() or pdf.stat().st_size < 1_000_000:
        pytest.skip(f"Real annual report PDF not found or too small: {pdf}")
    return _TCS_REPO


@pytest.fixture(scope="module")
def kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    """KnowledgeBase pointing at TCS repo, with the AR 2024 pre-parsed.

    Scoped to module so the heavy PDF extraction runs only once per session.
    knowledge.db is cleaned up when the module finishes.
    """
    db = tcs_root / "knowledge.db"
    db.unlink(missing_ok=True)
    instance = KnowledgeBase(tcs_root)

    from atlas.acquisition.repository import Repository
    repo = Repository(tcs_root)
    entry = repo.get(_AR_2024_ID)
    if entry is None:
        pytest.skip(f"Catalog entry {_AR_2024_ID} not found")
    doc = instance.parse(entry)
    if doc.status != "ok":
        pytest.skip(f"PDF parsing failed: {doc.error}")

    yield instance
    db.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def result(kb: KnowledgeBase) -> AnalysisResult:
    return summarize(_AR_2024_ID, kb)


# Convenience: all facts of a given kind.
def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Basic contract checks
# ---------------------------------------------------------------------------


class TestSummarizeContract:
    def test_returns_analysis_result(self, result: AnalysisResult) -> None:
        assert isinstance(result, AnalysisResult)

    def test_evidence_id_matches(self, result: AnalysisResult) -> None:
        assert result.evidence_id == _AR_2024_ID

    def test_kind_is_annual_report(self, result: AnalysisResult) -> None:
        assert result.kind == "annual_report"

    def test_analyzer_version_present(self, result: AnalysisResult) -> None:
        from atlas.analysis.annual_report import ANALYZER_VERSION
        assert result.analyzer_version == ANALYZER_VERSION

    def test_confidence_is_valid(self, result: AnalysisResult) -> None:
        assert result.confidence in ("high", "medium", "low")

    def test_analyzed_at_is_utc(self, result: AnalysisResult) -> None:
        assert result.analyzed_at.tzinfo is not None

    def test_char_count_substantial(self, result: AnalysisResult, kb: KnowledgeBase) -> None:
        doc = kb.get(_AR_2024_ID)
        assert doc is not None
        assert doc.char_count >= 50_000

    def test_title_non_empty(self, result: AnalysisResult, kb: KnowledgeBase) -> None:
        doc = kb.get(_AR_2024_ID)
        assert doc is not None
        assert len(doc.title) > 0

    def test_source_date_non_empty(self, result: AnalysisResult, kb: KnowledgeBase) -> None:
        doc = kb.get(_AR_2024_ID)
        assert doc is not None
        assert len(doc.source_date) > 0


# ---------------------------------------------------------------------------
# Section content checks
# ---------------------------------------------------------------------------


class TestSectionExtraction:
    def test_management_commentary_found(self, result: AnalysisResult) -> None:
        assert "management_commentary" in result.excerpts, (
            "Expected to find management commentary / chairman letter"
        )

    def test_management_commentary_minimum_length(self, result: AnalysisResult) -> None:
        if "management_commentary" not in result.excerpts:
            pytest.skip("management_commentary not found — length check skipped")
        assert len(result.excerpts["management_commentary"]) >= 200

    def test_business_overview_found(self, result: AnalysisResult) -> None:
        assert "business_overview" in result.excerpts, (
            "Expected to find business overview section"
        )

    def test_capital_allocation_found(self, result: AnalysisResult) -> None:
        assert "capital_allocation" in result.excerpts, (
            "Expected to find capital allocation / dividend policy"
        )

    def test_segments_non_empty(self, result: AnalysisResult) -> None:
        segs = _facts(result, FactKind.SEGMENT_NAME)
        assert len(segs) >= 2, (
            f"Expected at least 2 business segments; got {[f.value for f in segs]}"
        )

    def test_segments_are_strings(self, result: AnalysisResult) -> None:
        for f in _facts(result, FactKind.SEGMENT_NAME):
            assert isinstance(f.value, str) and len(f.value) > 0

    def test_manufacturing_in_segments(self, result: AnalysisResult) -> None:
        values = [f.value for f in _facts(result, FactKind.SEGMENT_NAME)]
        assert any("Manufacturing" in str(v) for v in values), (
            f"Expected 'Manufacturing' in segments; got {values}"
        )

    def test_risks_non_empty(self, result: AnalysisResult) -> None:
        risks = _facts(result, FactKind.RISK_FACTOR)
        assert len(risks) >= 1, "Expected at least one risk factor"

    def test_warnings_is_list(self, result: AnalysisResult) -> None:
        assert isinstance(result.warnings, list)


# ---------------------------------------------------------------------------
# Fact structure checks
# ---------------------------------------------------------------------------


class TestFactStructure:
    def test_segment_facts_have_period(self, result: AnalysisResult) -> None:
        for f in _facts(result, FactKind.SEGMENT_NAME):
            assert f.period is not None
            assert f.period.startswith("20")

    def test_segment_facts_have_null_unit(self, result: AnalysisResult) -> None:
        for f in _facts(result, FactKind.SEGMENT_NAME):
            assert f.unit is None

    def test_all_facts_have_confidence(self, result: AnalysisResult) -> None:
        for f in result.facts:
            assert f.confidence in ("high", "medium", "low")

    def test_all_facts_have_provenance_section(self, result: AnalysisResult) -> None:
        for f in result.facts:
            assert isinstance(f.provenance.section, str)
            assert len(f.provenance.section) > 0


# ---------------------------------------------------------------------------
# Demo: print structured result for human review
# ---------------------------------------------------------------------------


class TestResultDemo:
    def test_print_structured_result(
        self, result: AnalysisResult, kb: KnowledgeBase, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Print the full structured result to stdout when run with -s."""

        def _trunc(text: str | None, limit: int = 500) -> str:
            if text is None:
                return "(not found)"
            return text[:limit].replace("\n", " ") + ("..." if len(text) > limit else "")

        doc = kb.get(_AR_2024_ID)
        assert doc is not None

        segs = _facts(result, FactKind.SEGMENT_NAME)
        risks = _facts(result, FactKind.RISK_FACTOR)

        print("\n" + "=" * 70)
        print("ANNUAL REPORT ANALYSIS DEMO")
        print("=" * 70)
        print(f"Evidence ID      : {result.evidence_id}")
        print(f"Title            : {doc.title}")
        print(f"Source date      : {doc.source_date}")
        print(f"Char count       : {doc.char_count:,}")
        print(f"Analyzer version : {result.analyzer_version}")
        print(f"Confidence       : {result.confidence}")
        print(f"Analyzed at      : {result.analyzed_at.isoformat()}")

        print("\n--- MANAGEMENT COMMENTARY ---")
        print(_trunc(result.excerpts.get("management_commentary")))

        print("\n--- BUSINESS OVERVIEW ---")
        print(_trunc(result.excerpts.get("business_overview")))

        print("\n--- BUSINESS SEGMENTS ---")
        if segs:
            for f in segs:
                print(f"  • {f.value}  [confidence={f.confidence}, period={f.period}]")
        else:
            print("  (not found)")

        print("\n--- CAPITAL ALLOCATION ---")
        print(_trunc(result.excerpts.get("capital_allocation")))

        print("\n--- RISK FACTORS ---")
        if risks:
            for f in risks:
                print(f"  • {f.value}")
        else:
            print("  (not found)")

        if result.warnings:
            print("\n--- WARNINGS ---")
            for w in result.warnings:
                print(f"  ! {w}")

        print("=" * 70)

        # Soft assertion: at least two key excerpts were found.
        found = sum(
            1
            for k in ("management_commentary", "business_overview", "capital_allocation")
            if k in result.excerpts
        )
        assert found >= 2, (
            "Expected at least 2 of management_commentary / business_overview / "
            f"capital_allocation in excerpts; got {found}"
        )
