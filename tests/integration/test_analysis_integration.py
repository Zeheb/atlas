"""Integration test for atlas.analysis.annual_report against real TCS data.

Requires the TCS annual report to be parsed into knowledge.db first.
Run with: pytest -m integration -v -s

The test also serves as a human-readable demo: run with -s to see the
structured summary printed to stdout.
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.annual_report import AnnualReportSummary, summarize
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
def summary(kb: KnowledgeBase) -> AnnualReportSummary:
    return summarize(_AR_2024_ID, kb)


# ---------------------------------------------------------------------------
# Basic contract checks
# ---------------------------------------------------------------------------


class TestSummarizeContract:
    def test_returns_annual_report_summary(self, summary: AnnualReportSummary) -> None:
        assert isinstance(summary, AnnualReportSummary)

    def test_evidence_id_matches(self, summary: AnnualReportSummary) -> None:
        assert summary.evidence_id == _AR_2024_ID

    def test_char_count_substantial(self, summary: AnnualReportSummary) -> None:
        assert summary.char_count >= 50_000

    def test_title_non_empty(self, summary: AnnualReportSummary) -> None:
        assert len(summary.title) > 0

    def test_source_date_non_empty(self, summary: AnnualReportSummary) -> None:
        assert len(summary.source_date) > 0


# ---------------------------------------------------------------------------
# Section content checks
# ---------------------------------------------------------------------------


class TestSectionExtraction:
    def test_management_commentary_found(self, summary: AnnualReportSummary) -> None:
        assert summary.management_commentary is not None, (
            "Expected to find management commentary / chairman letter"
        )

    def test_management_commentary_minimum_length(self, summary: AnnualReportSummary) -> None:
        if summary.management_commentary is None:
            pytest.skip("management_commentary not found — length check skipped")
        assert len(summary.management_commentary) >= 200

    def test_business_overview_found(self, summary: AnnualReportSummary) -> None:
        assert summary.business_overview is not None, (
            "Expected to find business overview section"
        )

    def test_capital_allocation_found(self, summary: AnnualReportSummary) -> None:
        assert summary.capital_allocation is not None, (
            "Expected to find capital allocation / dividend policy"
        )

    def test_segments_non_empty(self, summary: AnnualReportSummary) -> None:
        assert len(summary.segments) >= 2, (
            f"Expected at least 2 business segments; got {summary.segments}"
        )

    def test_segments_are_strings(self, summary: AnnualReportSummary) -> None:
        for s in summary.segments:
            assert isinstance(s, str) and len(s) > 0

    def test_manufacturing_in_segments(self, summary: AnnualReportSummary) -> None:
        assert any("Manufacturing" in s for s in summary.segments), (
            f"Expected 'Manufacturing' in segments; got {summary.segments}"
        )

    def test_no_yoy_changes_without_previous_id(self, summary: AnnualReportSummary) -> None:
        assert summary.year_on_year_changes == []


# ---------------------------------------------------------------------------
# Demo: print structured summary for human review
# ---------------------------------------------------------------------------


class TestSummaryDemo:
    def test_print_structured_summary(
        self, summary: AnnualReportSummary, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Print the full structured summary to stdout when run with -s."""

        def _trunc(text: str | None, limit: int = 500) -> str:
            if text is None:
                return "(not found)"
            return text[:limit].replace("\n", " ") + ("..." if len(text) > limit else "")

        print("\n" + "=" * 70)
        print("ANNUAL REPORT ANALYSIS DEMO")
        print("=" * 70)
        print(f"Evidence ID : {summary.evidence_id}")
        print(f"Title       : {summary.title}")
        print(f"Source date : {summary.source_date}")
        print(f"Char count  : {summary.char_count:,}")
        print(f"Extracted at: {summary.extracted_at.isoformat()}")

        print("\n--- MANAGEMENT COMMENTARY ---")
        print(_trunc(summary.management_commentary))

        print("\n--- BUSINESS OVERVIEW ---")
        print(_trunc(summary.business_overview))

        print("\n--- BUSINESS SEGMENTS ---")
        if summary.segments:
            for seg in summary.segments:
                print(f"  • {seg}")
        else:
            print("  (not found)")

        print("\n--- CAPITAL ALLOCATION ---")
        print(_trunc(summary.capital_allocation))

        print("\n--- MAJOR RISKS ---")
        if summary.major_risks:
            for risk in summary.major_risks:
                print(f"  • {risk}")
        else:
            print("  (not found)")

        print("\n--- YEAR-ON-YEAR CHANGES ---")
        if summary.year_on_year_changes:
            for change in summary.year_on_year_changes:
                print(f"  • {change}")
        else:
            print("  (no previous report provided)")

        print("=" * 70)

        # Soft assertion: at least one section was found.
        found = [
            f for f in [
                summary.management_commentary,
                summary.business_overview,
                summary.capital_allocation,
            ]
            if f is not None
        ]
        assert len(found) >= 2, (
            "Expected at least 2 of management_commentary / business_overview / "
            f"capital_allocation to be non-None; got {len(found)}"
        )
