"""Integration tests for atlas.analysis.financial_results against real TCS filings.

Run with: pytest -m integration -v -s

Validates against two real filings:
  Q2 FY2025 (quarterly, 6 columns)  — bse-news-373a3674-...
  Annual FY2026 (5 columns)         — bse-news-e4ffa3fc-...
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.financial_results import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit
from atlas.knowledge.base import KnowledgeBase

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

_Q2_ID = "bse-news-373a3674-df22-42d5-ac50-1d77941355cd"
_Q2_PATH = "financial_results/bse-news-373a3674-df22-42d5-ac50-1d77941355cd.pdf"

_ANN_ID = "bse-news-e4ffa3fc-e4f0-4da0-89fe-75d2f7b7b956"
_ANN_PATH = "financial_results/bse-news-e4ffa3fc-e4f0-4da0-89fe-75d2f7b7b956.pdf"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tcs_root(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(_TCS_REPO, evidence_ids=[_Q2_ID, _ANN_ID])


@pytest.fixture(scope="module")
def kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(tcs_root)
    from atlas.acquisition.repository import Repository
    repo = Repository(tcs_root)
    for eid in (_Q2_ID, _ANN_ID):
        entry = repo.get(eid)
        if entry is not None:
            instance.parse(entry)
    yield instance


@pytest.fixture(scope="module")
def q2_result(kb: KnowledgeBase) -> AnalysisResult:
    if kb.get(_Q2_ID) is None or kb.get(_Q2_ID).status != "ok":
        pytest.skip("Q2 FY2025 filing not parsed")
    return analyze(_Q2_ID, kb)


@pytest.fixture(scope="module")
def ann_result(kb: KnowledgeBase) -> AnalysisResult:
    if kb.get(_ANN_ID) is None or kb.get(_ANN_ID).status != "ok":
        pytest.skip("Annual FY2026 filing not parsed")
    return analyze(_ANN_ID, kb)


def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


def _con(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind
            and "consolidated" in f.provenance.section]


# ---------------------------------------------------------------------------
# Q2 FY2025 contract
# ---------------------------------------------------------------------------


class TestQ2Contract:
    def test_returns_analysis_result(self, q2_result: AnalysisResult) -> None:
        assert isinstance(q2_result, AnalysisResult)

    def test_evidence_id(self, q2_result: AnalysisResult) -> None:
        assert q2_result.evidence_id == _Q2_ID

    def test_analyzer_version(self, q2_result: AnalysisResult) -> None:
        assert q2_result.analyzer_version == ANALYZER_VERSION

    def test_confidence_high(self, q2_result: AnalysisResult) -> None:
        assert q2_result.confidence == "high"

    def test_no_warnings(self, q2_result: AnalysisResult) -> None:
        assert q2_result.warnings == []

    def test_period_end(self, q2_result: AnalysisResult) -> None:
        pe = _facts(q2_result, FactKind.REPORT_PERIOD_END)
        assert pe[0].value == "2024-09-30"

    def test_period_type_quarterly(self, q2_result: AnalysisResult) -> None:
        pt = _facts(q2_result, FactKind.REPORT_PERIOD_TYPE)
        assert pt[0].value == "quarterly"

    def test_consolidated_revenue(self, q2_result: AnalysisResult) -> None:
        rev = _con(q2_result, FactKind.FINANCIAL_REVENUE)
        assert len(rev) == 1
        assert rev[0].value == pytest.approx(64259.0)

    def test_consolidated_pat(self, q2_result: AnalysisResult) -> None:
        pat = _con(q2_result, FactKind.FINANCIAL_PAT)
        assert len(pat) == 1
        assert pat[0].value == pytest.approx(11955.0)

    def test_consolidated_pbt(self, q2_result: AnalysisResult) -> None:
        pbt = _con(q2_result, FactKind.FINANCIAL_PROFIT_BEFORE_TAX)
        assert pbt[0].value == pytest.approx(16032.0)

    def test_deferred_tax_negative(self, q2_result: AnalysisResult) -> None:
        dt = _con(q2_result, FactKind.FINANCIAL_DEFERRED_TAX)
        assert dt[0].value == pytest.approx(-1.0)

    def test_eps(self, q2_result: AnalysisResult) -> None:
        eps = _con(q2_result, FactKind.FINANCIAL_EPS_BASIC)
        assert eps[0].value == pytest.approx(32.92)

    def test_eps_unit_rupees(self, q2_result: AnalysisResult) -> None:
        eps = _con(q2_result, FactKind.FINANCIAL_EPS_BASIC)
        assert eps[0].unit == FactUnit.RUPEES

    def test_six_segments(self, q2_result: AnalysisResult) -> None:
        segs = _facts(q2_result, FactKind.SEGMENT_NAME)
        assert len(segs) == 6

    def test_bfsi_segment_revenue(self, q2_result: AnalysisResult) -> None:
        rev_facts = _facts(q2_result, FactKind.SEGMENT_REVENUE)
        assert rev_facts[0].value == pytest.approx(23785.0)

    def test_manufacturing_segment_revenue(self, q2_result: AnalysisResult) -> None:
        name_facts = _facts(q2_result, FactKind.SEGMENT_NAME)
        rev_facts = _facts(q2_result, FactKind.SEGMENT_REVENUE)
        mfg_idx = next(i for i, f in enumerate(name_facts) if "Manufacturing" in str(f.value))
        assert rev_facts[mfg_idx].value == pytest.approx(6310.0)

    def test_six_segment_ebit_facts(self, q2_result: AnalysisResult) -> None:
        ebit = _facts(q2_result, FactKind.SEGMENT_EBIT)
        assert len(ebit) == 6

    def test_bfsi_ebit(self, q2_result: AnalysisResult) -> None:
        ebit = _facts(q2_result, FactKind.SEGMENT_EBIT)
        assert ebit[0].value == pytest.approx(6345.0)

    def test_manufacturing_ebit(self, q2_result: AnalysisResult) -> None:
        ebit = _facts(q2_result, FactKind.SEGMENT_EBIT)
        assert any(f.value == pytest.approx(2063.0) for f in ebit)

    def test_consumer_business_ebit(self, q2_result: AnalysisResult) -> None:
        ebit = _facts(q2_result, FactKind.SEGMENT_EBIT)
        assert any(f.value == pytest.approx(2695.0) for f in ebit)

    def test_cmt_ebit(self, q2_result: AnalysisResult) -> None:
        ebit = _facts(q2_result, FactKind.SEGMENT_EBIT)
        assert any(f.value == pytest.approx(2357.0) for f in ebit)

    def test_lsh_ebit(self, q2_result: AnalysisResult) -> None:
        ebit = _facts(q2_result, FactKind.SEGMENT_EBIT)
        assert any(f.value == pytest.approx(1849.0) for f in ebit)

    def test_others_ebit(self, q2_result: AnalysisResult) -> None:
        ebit = _facts(q2_result, FactKind.SEGMENT_EBIT)
        assert any(f.value == pytest.approx(1422.0) for f in ebit)

    def test_dividend_amount(self, q2_result: AnalysisResult) -> None:
        dps = _facts(q2_result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert dps[0].value == pytest.approx(10.0)

    def test_dividend_type_interim(self, q2_result: AnalysisResult) -> None:
        types = _facts(q2_result, FactKind.CAPITAL_DIVIDEND_TYPE)
        assert types[0].value == "interim"

    def test_dividend_record_date(self, q2_result: AnalysisResult) -> None:
        rec = _facts(q2_result, FactKind.CAPITAL_DIVIDEND_RECORD_DATE)
        assert rec[0].value == "2024-10-18"

    def test_dividend_payment_date(self, q2_result: AnalysisResult) -> None:
        pay = _facts(q2_result, FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE)
        assert pay[0].value == "2024-11-05"

    def test_audit_opinion_unmodified(self, q2_result: AnalysisResult) -> None:
        op = _facts(q2_result, FactKind.AUDIT_OPINION)
        assert op[0].value == "unmodified"

    def test_audit_firm_bsr(self, q2_result: AnalysisResult) -> None:
        firm = _facts(q2_result, FactKind.AUDIT_FIRM)
        assert "B S R" in str(firm[0].value)

    def test_consolidated_pl_excerpt(self, q2_result: AnalysisResult) -> None:
        assert "consolidated_pl_table" in q2_result.excerpts

    def test_standalone_pl_excerpt(self, q2_result: AnalysisResult) -> None:
        assert "standalone_pl_table" in q2_result.excerpts

    def test_all_facts_have_provenance(self, q2_result: AnalysisResult) -> None:
        for f in q2_result.facts:
            assert isinstance(f.provenance.section, str) and f.provenance.section


# ---------------------------------------------------------------------------
# Annual FY2026 contract
# ---------------------------------------------------------------------------


class TestAnnualContract:
    def test_period_type_annual(self, ann_result: AnalysisResult) -> None:
        pt = _facts(ann_result, FactKind.REPORT_PERIOD_TYPE)
        assert pt[0].value == "annual"

    def test_period_end(self, ann_result: AnalysisResult) -> None:
        pe = _facts(ann_result, FactKind.REPORT_PERIOD_END)
        assert pe[0].value == "2026-03-31"

    def test_full_year_revenue(self, ann_result: AnalysisResult) -> None:
        """Col 3 = full year 267,021 crore, not Q4 70,698."""
        rev = _con(ann_result, FactKind.FINANCIAL_REVENUE)
        assert rev[0].value == pytest.approx(267021.0)

    def test_full_year_pbt(self, ann_result: AnalysisResult) -> None:
        pbt = _con(ann_result, FactKind.FINANCIAL_PROFIT_BEFORE_TAX)
        assert pbt[0].value == pytest.approx(65487.0)

    def test_full_year_eps(self, ann_result: AnalysisResult) -> None:
        eps = _con(ann_result, FactKind.FINANCIAL_EPS_BASIC)
        assert eps[0].value == pytest.approx(135.70)

    def test_final_dividend(self, ann_result: AnalysisResult) -> None:
        dps = _facts(ann_result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert any(f.value == pytest.approx(31.0) for f in dps)

    def test_exceptional_items_emitted(self, ann_result: AnalysisResult) -> None:
        exc = _con(ann_result, FactKind.EXCEPTIONAL_AMOUNT)
        assert len(exc) >= 2

    def test_segment_warning_on_annual(self, ann_result: AnalysisResult) -> None:
        """Annual PDF layout prevents segment alignment — exactly one warning expected."""
        seg_warnings = [w for w in ann_result.warnings if "annual PDF layout" in w or "Segment" in w.lower()]
        assert len(seg_warnings) == 1

    def test_confidence_high(self, ann_result: AnalysisResult) -> None:
        assert ann_result.confidence == "high"

    def test_cash_and_equivalents(self, ann_result: AnalysisResult) -> None:
        cash = _facts(ann_result, FactKind.FINANCIAL_CASH_AND_EQUIVALENTS)
        assert len(cash) == 1
        assert cash[0].value == pytest.approx(6417.0)

    def test_total_equity(self, ann_result: AnalysisResult) -> None:
        eq = _facts(ann_result, FactKind.FINANCIAL_TOTAL_EQUITY)
        assert len(eq) == 1
        assert eq[0].value == pytest.approx(107240.0)

    def test_no_total_debt_for_tcs(self, ann_result: AnalysisResult) -> None:
        debt = _facts(ann_result, FactKind.FINANCIAL_TOTAL_DEBT)
        assert debt == []

    def test_operating_cash_flow(self, ann_result: AnalysisResult) -> None:
        cfo = _facts(ann_result, FactKind.FINANCIAL_OPERATING_CASH_FLOW)
        assert len(cfo) == 1
        assert cfo[0].value == pytest.approx(52094.0)

    def test_capex(self, ann_result: AnalysisResult) -> None:
        capex = _facts(ann_result, FactKind.FINANCIAL_CAPEX)
        assert len(capex) == 1
        assert capex[0].value == pytest.approx(3670.0)

    def test_capex_is_positive(self, ann_result: AnalysisResult) -> None:
        capex = _facts(ann_result, FactKind.FINANCIAL_CAPEX)
        assert capex[0].value > 0


# ---------------------------------------------------------------------------
# Demo: print full structured output
# ---------------------------------------------------------------------------


class TestDemo:
    def test_print_q2_result(
        self, q2_result: AnalysisResult, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = q2_result
        print("\n" + "=" * 70)
        print("FINANCIAL RESULTS ANALYSIS DEMO — Q2 FY2025 (CONSOLIDATED)")
        print("=" * 70)
        print(f"Evidence ID : {result.evidence_id}")
        print(f"Confidence  : {result.confidence}")
        print(f"Total facts : {len(result.facts)}")

        print("\n--- P&L ---")
        for kind in (
            FactKind.FINANCIAL_REVENUE,
            FactKind.FINANCIAL_EMPLOYEE_COST,
            FactKind.FINANCIAL_PROFIT_BEFORE_TAX,
            FactKind.FINANCIAL_PAT,
            FactKind.FINANCIAL_EPS_BASIC,
        ):
            for f in _con(result, kind):
                unit = f.unit.value if f.unit else ""
                print(f"  {kind.value}: {f.value} {unit}")

        print("\n--- SEGMENTS ---")
        names = _facts(result, FactKind.SEGMENT_NAME)
        revs = _facts(result, FactKind.SEGMENT_REVENUE)
        for n, r in zip(names, revs):
            print(f"  {n.value}: {r.value} crore")

        print("\n--- CAPITAL ALLOCATION ---")
        for kind in (FactKind.CAPITAL_DIVIDEND_PER_SHARE, FactKind.CAPITAL_DIVIDEND_TYPE,
                     FactKind.CAPITAL_DIVIDEND_RECORD_DATE, FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE):
            for f in _facts(result, kind):
                print(f"  {kind.value}: {f.value}")

        print("=" * 70)
        assert result.confidence == "high"
