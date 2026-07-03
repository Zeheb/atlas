"""Comprehensive integration tests for atlas.analysis.annual_report against all TCS annual reports.

Tests all three available annual reports (FY2026, FY2025, FY2024) to verify:
- Section detection works across different naming conventions (Board's Report / Directors' Report)
- CSR spend extraction succeeds across different PDF generations
- KAM title extraction works against real auditor's report text
- Unicode apostrophe (U+2019) handling works in production

Run with: pytest -m integration tests/integration/test_annual_report_integration.py -v -s

Expected values (from targeted document research):
  FY2026: CSR ₹1,009 crore, KAM: Revenue recognition
  FY2025: CSR ₹949 crore,  KAM: Revenue recognition
  FY2024: CSR ₹813 crore,  KAM: Revenue recognition
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.annual_report import analyze
from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit
from atlas.knowledge.base import KnowledgeBase

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

_EID_FY2026 = "bse-news-6e49b04e-0256-4d93-b50e-a91ee2773bf2"
_EID_FY2025 = "bse-news-5f265e1c-6312-4556-b208-749bfa2caf8f"
_EID_FY2024 = "bse-news-a8be8b1d-ebc8-4ab7-8081-668fadaf6ecb"

_ANNUAL_REPORT_EIDS = [_EID_FY2026, _EID_FY2025, _EID_FY2024]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skip_if_not_parsed(kb: KnowledgeBase, eid: str) -> None:
    doc = kb.get(eid)
    if doc is None:
        pytest.skip(f"Document not in knowledge base: {eid}")
    if doc.status != "ok":
        pytest.skip(f"Document not successfully parsed: {eid} status={doc.status!r}")
    if not doc.char_count or doc.char_count < 500_000:
        pytest.skip(f"Document too small (char_count={doc.char_count}): {eid}")


def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Module-scoped fixture — pre-parse all three reports once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def kb(isolated_repo_factory) -> Generator[KnowledgeBase, None, None]:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found at repositories/TCS")

    tcs_root = isolated_repo_factory(_TCS_REPO, evidence_ids=_ANNUAL_REPORT_EIDS)
    instance = KnowledgeBase(tcs_root)

    from atlas.acquisition.repository import Repository
    repo = Repository(tcs_root)

    parsed_count = 0
    for eid in _ANNUAL_REPORT_EIDS:
        entry = repo.get(eid)
        if entry is None:
            continue
        # Skip entries with no local file
        if not entry.local_path:
            continue
        pdf = tcs_root / entry.local_path
        if not pdf.exists() or pdf.stat().st_size < 1_000_000:
            continue
        doc = instance.parse(entry)
        if doc.status == "ok":
            parsed_count += 1

    if parsed_count == 0:
        pytest.skip("No annual report PDFs found — skipping integration tests")

    yield instance


# ---------------------------------------------------------------------------
# FY2026 tests — "Board's Report" with Unicode apostrophe
# ---------------------------------------------------------------------------


class TestFY2026:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _EID_FY2026)
        return analyze(_EID_FY2026, kb)

    def test_returns_analysis_result(self, result: AnalysisResult) -> None:
        assert isinstance(result, AnalysisResult)

    def test_evidence_id(self, result: AnalysisResult) -> None:
        assert result.evidence_id == _EID_FY2026

    def test_confidence_not_low(self, result: AnalysisResult) -> None:
        assert result.confidence in ("high", "medium"), (
            f"Expected high/medium confidence for FY2026; warnings: {result.warnings}"
        )

    def test_csr_spend_found(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        assert len(csr) == 1, f"Expected 1 CSR fact; got {len(csr)}"

    def test_csr_spend_value(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR fact not found")
        # FY2026 mandatory disclosure: ₹1,009 crore (amount spent on CSR Projects)
        assert 990 <= float(csr[0].value) <= 1030, (
            f"Expected FY2026 CSR ~1009 crore; got {csr[0].value}"
        )

    def test_csr_unit(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR fact not found")
        assert csr[0].unit == FactUnit.CRORE_INR

    def test_csr_period(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR fact not found")
        assert csr[0].period == "2026-03-31"

    def test_kam_titles_found(self, result: AnalysisResult) -> None:
        kams = _facts(result, FactKind.AUDIT_KAM_TITLE)
        assert len(kams) >= 1, f"Expected KAM titles; got none. Warnings: {result.warnings}"

    def test_revenue_recognition_kam(self, result: AnalysisResult) -> None:
        titles = [str(f.value) for f in _facts(result, FactKind.AUDIT_KAM_TITLE)]
        assert any("Revenue recognition" in t or "revenue recognition" in t for t in titles), (
            f"Expected Revenue recognition KAM; got: {titles}"
        )

    def test_boards_report_excerpt(self, result: AnalysisResult) -> None:
        assert "boards_report" in result.excerpts, (
            "Board's Report section not found in FY2026 (uses Unicode apostrophe U+2019)"
        )

    def test_mda_excerpt(self, result: AnalysisResult) -> None:
        assert "mda" in result.excerpts

    def test_auditor_excerpt(self, result: AnalysisResult) -> None:
        assert "key_audit_matters" in result.excerpts


# ---------------------------------------------------------------------------
# FY2025 tests
# ---------------------------------------------------------------------------


class TestFY2025:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _EID_FY2025)
        return analyze(_EID_FY2025, kb)

    def test_returns_analysis_result(self, result: AnalysisResult) -> None:
        assert isinstance(result, AnalysisResult)

    def test_evidence_id(self, result: AnalysisResult) -> None:
        assert result.evidence_id == _EID_FY2025

    def test_csr_spend_found(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        assert len(csr) == 1, f"Expected 1 CSR fact; got {len(csr)}"

    def test_csr_spend_value(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR fact not found")
        # FY2025 mandatory disclosure: ₹949 crore
        assert 930 <= float(csr[0].value) <= 970, (
            f"Expected FY2025 CSR ~949 crore; got {csr[0].value}"
        )

    def test_csr_period(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR fact not found")
        assert csr[0].period == "2025-03-31"

    def test_kam_titles_found(self, result: AnalysisResult) -> None:
        kams = _facts(result, FactKind.AUDIT_KAM_TITLE)
        assert len(kams) >= 1

    def test_revenue_recognition_kam(self, result: AnalysisResult) -> None:
        titles = [str(f.value) for f in _facts(result, FactKind.AUDIT_KAM_TITLE)]
        assert any("Revenue recognition" in t or "revenue recognition" in t for t in titles), (
            f"Expected Revenue recognition KAM; got: {titles}"
        )


# ---------------------------------------------------------------------------
# FY2024 tests — uses "Directors' Report" (different naming)
# ---------------------------------------------------------------------------


class TestFY2024:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _EID_FY2024)
        return analyze(_EID_FY2024, kb)

    def test_returns_analysis_result(self, result: AnalysisResult) -> None:
        assert isinstance(result, AnalysisResult)

    def test_evidence_id(self, result: AnalysisResult) -> None:
        assert result.evidence_id == _EID_FY2024

    def test_directors_report_detected(self, result: AnalysisResult) -> None:
        # FY2024 uses "Directors' Report" not "Board's Report"
        # Both aliases map to the "boards_report" excerpt key
        assert "boards_report" in result.excerpts, (
            "Expected Directors' Report to be found as 'boards_report' excerpt"
        )

    def test_csr_spend_found(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        assert len(csr) == 1, f"Expected 1 CSR fact; got {len(csr)}"

    def test_csr_spend_value(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR fact not found")
        # FY2024 mandatory disclosure: ₹813 crore
        assert 800 <= float(csr[0].value) <= 830, (
            f"Expected FY2024 CSR ~813 crore; got {csr[0].value}"
        )

    def test_csr_period(self, result: AnalysisResult) -> None:
        csr = _facts(result, FactKind.ESG_CSR_SPEND)
        if not csr:
            pytest.skip("CSR fact not found")
        assert csr[0].period == "2024-03-31"

    def test_kam_titles_found(self, result: AnalysisResult) -> None:
        kams = _facts(result, FactKind.AUDIT_KAM_TITLE)
        assert len(kams) >= 1

    def test_revenue_recognition_kam(self, result: AnalysisResult) -> None:
        titles = [str(f.value) for f in _facts(result, FactKind.AUDIT_KAM_TITLE)]
        assert any("Revenue recognition" in t or "revenue recognition" in t for t in titles), (
            f"Expected Revenue recognition KAM; got: {titles}"
        )

    def test_mda_excerpt_found(self, result: AnalysisResult) -> None:
        assert "mda" in result.excerpts


# ---------------------------------------------------------------------------
# Cross-year consistency
# ---------------------------------------------------------------------------


class TestCrossYearConsistency:
    """Validate that CSR spend is monotonically increasing across years."""

    def test_csr_spend_increases_across_years(self, kb: KnowledgeBase) -> None:
        values: dict[str, float] = {}
        for eid, label in [(_EID_FY2024, "FY2024"), (_EID_FY2025, "FY2025"), (_EID_FY2026, "FY2026")]:
            doc = kb.get(eid)
            if doc is None or doc.status != "ok":
                continue
            try:
                r = analyze(eid, kb)
            except Exception:
                continue
            csr = [f for f in r.facts if f.kind == FactKind.ESG_CSR_SPEND]
            if csr:
                values[label] = float(csr[0].value)

        if len(values) < 2:
            pytest.skip("Fewer than 2 years parsed — cannot check cross-year consistency")

        years = ["FY2024", "FY2025", "FY2026"]
        present = [y for y in years if y in values]
        for i in range(len(present) - 1):
            assert values[present[i]] < values[present[i + 1]], (
                f"Expected CSR to increase: {present[i]}={values[present[i]]} "
                f"< {present[i+1]}={values[present[i+1]]}"
            )

    def test_kam_period_matches_source_year(self, kb: KnowledgeBase) -> None:
        expected = {
            _EID_FY2026: "2026-03-31",
            _EID_FY2025: "2025-03-31",
            _EID_FY2024: "2024-03-31",
        }
        for eid, expected_period in expected.items():
            doc = kb.get(eid)
            if doc is None or doc.status != "ok":
                continue
            try:
                r = analyze(eid, kb)
            except Exception:
                continue
            for f in r.facts:
                if f.kind == FactKind.AUDIT_KAM_TITLE:
                    assert f.period == expected_period, (
                        f"{eid}: expected KAM period {expected_period}; got {f.period}"
                    )
