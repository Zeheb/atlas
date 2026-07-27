"""Integration test for atlas.analysis.annual_report (v3.0) against real TCS data.

Uses FY2024 (Directors' Report naming) as the primary integration target.
Run with: pytest -m integration -v -s

Run with -s to see the full structured result printed to stdout.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.annual_report import analyze, summarize
from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit
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
def tcs_root(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found at repositories/TCS")
    pdf = _TCS_REPO / _AR_2024_PATH
    if not pdf.exists() or pdf.stat().st_size < 1_000_000:
        pytest.skip(f"Real annual report PDF not found or too small: {pdf}")
    return isolated_repo_factory(_TCS_REPO, evidence_ids=[_AR_2024_ID])


@pytest.fixture(scope="module")
def kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
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


@pytest.fixture(scope="module")
def result(kb: KnowledgeBase) -> AnalysisResult:
    return analyze(_AR_2024_ID, kb)


def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Contract checks
# ---------------------------------------------------------------------------


class TestAnalyzeContract:
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

    def test_char_count_substantial(
        self, result: AnalysisResult, kb: KnowledgeBase
    ) -> None:
        doc = kb.get(_AR_2024_ID)
        assert doc is not None
        assert doc.char_count is not None and doc.char_count >= 500_000

    def test_warnings_is_list(self, result: AnalysisResult) -> None:
        assert isinstance(result.warnings, list)

    def test_all_facts_have_confidence(self, result: AnalysisResult) -> None:
        for f in result.facts:
            assert f.confidence in ("high", "medium", "low")

    def test_all_facts_have_provenance_section(self, result: AnalysisResult) -> None:
        for f in result.facts:
            assert isinstance(f.provenance.section, str)
            assert len(f.provenance.section) > 0


# ---------------------------------------------------------------------------
# CSR spend
# ---------------------------------------------------------------------------


class TestCsrSpend:
    def test_csr_spend_fact_present(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        assert len(csr) == 1, f"Expected 1 CSR_SPEND fact; got {len(csr)}"

    def test_csr_spend_unit_is_crore_inr(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR spend fact not found")
        assert csr[0].unit == FactUnit.CRORE_INR

    def test_csr_spend_value_reasonable(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR spend fact not found")
        # FY2024: ₹813 crore — allow ±5 crore tolerance for text extraction
        assert isinstance(csr[0].value, (int, float))
        assert (
            800 <= float(csr[0].value) <= 830
        ), f"Expected FY2024 CSR spend ~813 crore; got {csr[0].value}"

    def test_csr_spend_confidence_high(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR spend fact not found")
        assert csr[0].confidence == "high"

    def test_csr_spend_period_is_fy2024(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR spend fact not found")
        assert csr[0].period == "2024-03-31"


# ---------------------------------------------------------------------------
# KAM titles
# ---------------------------------------------------------------------------


class TestKamTitles:
    def test_at_least_one_kam_title(self, result: AnalysisResult) -> None:
        kams = _facts(result, FactKind.AUDIT_KAM_TITLE)
        assert len(kams) >= 1, "Expected at least one KAM title"

    def test_kam_titles_are_strings(self, result: AnalysisResult) -> None:
        for f in _facts(result, FactKind.AUDIT_KAM_TITLE):
            assert isinstance(f.value, str) and len(f.value) >= 10

    def test_kam_titles_high_confidence(self, result: AnalysisResult) -> None:
        for f in _facts(result, FactKind.AUDIT_KAM_TITLE):
            assert f.confidence == "high"

    def test_revenue_recognition_in_kams(self, result: AnalysisResult) -> None:
        titles = [str(f.value) for f in _facts(result, FactKind.AUDIT_KAM_TITLE)]
        assert any(
            "Revenue recognition" in t or "revenue recognition" in t for t in titles
        ), f"Expected 'Revenue recognition' KAM; got: {titles}"


# ---------------------------------------------------------------------------
# Excerpts
# ---------------------------------------------------------------------------


class TestExcerpts:
    def test_key_audit_matters_excerpt_present(self, result: AnalysisResult) -> None:
        assert "key_audit_matters" in result.excerpts

    def test_key_audit_matters_non_empty(self, result: AnalysisResult) -> None:
        if "key_audit_matters" not in result.excerpts:
            pytest.skip("key_audit_matters excerpt not found")
        assert len(result.excerpts["key_audit_matters"]) >= 200

    def test_mda_excerpt_present(self, result: AnalysisResult) -> None:
        assert "mda" in result.excerpts, "Expected MDA excerpt"

    def test_boards_report_excerpt_present(self, result: AnalysisResult) -> None:
        # FY2024 uses "Directors' Report" — should still be found
        assert "boards_report" in result.excerpts


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------


class TestSummarizeAlias:
    def test_summarize_returns_same_result(self, kb: KnowledgeBase) -> None:
        result = summarize(_AR_2024_ID, kb)
        assert isinstance(result, AnalysisResult)
        assert result.evidence_id == _AR_2024_ID


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


class TestResultDemo:
    def test_print_structured_result(
        self,
        result: AnalysisResult,
        kb: KnowledgeBase,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Print the full structured result to stdout when run with -s."""

        def _trunc(text: str | None, limit: int = 300) -> str:
            if text is None:
                return "(not found)"
            return text[:limit].replace("\n", " ") + (
                "..." if len(text) > limit else ""
            )

        doc = kb.get(_AR_2024_ID)
        assert doc is not None

        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        kams = _facts(result, FactKind.AUDIT_KAM_TITLE)
        risks = _facts(result, FactKind.RISK_FACTOR)

        print("\n" + "=" * 70)
        print("ANNUAL REPORT ANALYSIS DEMO (FY2024)")
        print("=" * 70)
        print(f"Evidence ID      : {result.evidence_id}")
        print(f"Title            : {doc.title}")
        print(f"Source date      : {doc.source_date}")
        print(f"Char count       : {doc.char_count:,}")
        print(f"Analyzer version : {result.analyzer_version}")
        print(f"Confidence       : {result.confidence}")

        print("\n--- CSR SPEND ---")
        if csr:
            print(f"  INR {csr[0].value:.0f} crore  [period={csr[0].period}]")
        else:
            print("  (not found)")

        print("\n--- KEY AUDIT MATTERS ---")
        if kams:
            for f in kams:
                print(f"  • {f.value}")
        else:
            print("  (not found)")

        print("\n--- RISK FACTORS ---")
        if risks:
            for f in risks[:5]:
                print(f"  • {f.value}")
        else:
            print("  (not found)")

        print("\n--- MDA EXCERPT ---")
        print(_trunc(result.excerpts.get("mda")))

        if result.warnings:
            print("\n--- WARNINGS ---")
            for w in result.warnings:
                print(f"  ! {w}")

        print("=" * 70)

        # Soft assertion: CSR or KAM must be found to validate extraction.
        found = len(csr) + len(kams)
        assert found >= 1, "Expected at least one CSR or KAM fact to be extracted"
