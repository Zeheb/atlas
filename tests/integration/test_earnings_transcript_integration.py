"""Integration tests for atlas.analysis.earnings_transcript.

Uses the three most recent real TCS earnings call transcripts:
  bse-news-7ff81737  Q4 & FY26 (quarter ended 2026-03-31)  — annual call
  bse-news-b60eabf7  Q2 FY26   (quarter ended 2025-09-30)  — mid-year call
  bse-news-4b68b72b  Q4 & FY25 (quarter ended 2025-03-31)  — annual call

Run with: pytest -m integration -v -s
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.earnings_transcript import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.knowledge.base import KnowledgeBase
from atlas.acquisition.repository import Repository

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

_ID_Q4_FY26 = "bse-news-7ff81737-8eeb-4f5a-afad-f5f79b216e83"  # 2026-04-14
_ID_Q2_FY26 = "bse-news-b60eabf7-2ff3-4f91-9aa6-20885f494608"  # 2025-10-15
_ID_Q4_FY25 = "bse-news-4b68b72b-6735-4e94-a1ea-5150aa11dac9"  # 2025-04-12

_ALL_IDS = [_ID_Q4_FY26, _ID_Q2_FY26, _ID_Q4_FY25]


@pytest.fixture(scope="module")
def tcs_root(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(_TCS_REPO, evidence_ids=_ALL_IDS)


@pytest.fixture(scope="module")
def kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(tcs_root)
    repo = Repository(tcs_root)
    for eid in _ALL_IDS:
        entry = repo.get(eid)
        if entry is not None:
            instance.parse(entry)
    yield instance


def _facts(result: AnalysisResult, kind: FactKind):
    return [f for f in result.facts if f.kind == kind]


def _skip_if_not_parsed(kb: KnowledgeBase, eid: str) -> None:
    entry = kb.get(eid)
    if entry is None or entry.status != "ok":
        pytest.skip(f"{eid[:16]}... not parsed")


# ---------------------------------------------------------------------------
# Q4 & Full Year FY26 (April 2026)
# ---------------------------------------------------------------------------

class TestQ4FY26:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_Q4_FY26)
        return analyze(_ID_Q4_FY26, kb)

    def test_returns_analysis_result(self, result):
        assert isinstance(result, AnalysisResult)

    def test_analyzer_version(self, result):
        assert result.analyzer_version == ANALYZER_VERSION

    def test_kind(self, result):
        assert result.kind == "earnings_transcript"

    def test_confidence_high(self, result):
        assert result.confidence == "high", (
            f"warnings={result.warnings}, facts={[f.kind.value for f in result.facts]}"
        )

    def test_period_end_march_2026(self, result):
        periods = _facts(result, FactKind.REPORT_PERIOD_END)
        assert periods
        assert periods[0].value == "2026-03-31"

    def test_both_period_types_emitted(self, result):
        pts = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        values = {f.value for f in pts}
        assert "quarterly" in values
        assert "annual" in values

    def test_quarterly_inr_revenue_present(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        inr_q = [f for f in revs if f.unit == FactUnit.CRORE_INR and f.provenance.section == "quarterly"]
        assert inr_q, "quarterly INR revenue not found"
        # TCS Q4 FY26: ₹70,698 crore
        assert inr_q[0].value == pytest.approx(70698.0, abs=50)

    def test_quarterly_usd_revenue_present(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        usd = [f for f in revs if f.unit == FactUnit.USD_BILLION]
        assert usd, "USD revenue not found"
        assert usd[0].value == pytest.approx(7.621, abs=0.1)

    def test_annual_inr_revenue_present(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        inr_a = [f for f in revs if f.unit == FactUnit.CRORE_INR and f.provenance.section == "annual"]
        assert inr_a, "annual INR revenue not found"
        # TCS FY26: ₹267,021 crore
        assert inr_a[0].value == pytest.approx(267021.0, abs=500)

    def test_tcv_present(self, result):
        tcv = _facts(result, FactKind.FINANCIAL_TCV)
        assert tcv, "TCV not found"
        # TCS Q4 FY26 TCV: $12 billion
        assert tcv[0].value == pytest.approx(12.0, abs=1.0)
        assert tcv[0].unit == FactUnit.USD_BILLION

    def test_quarterly_op_margin(self, result):
        margins = _facts(result, FactKind.FINANCIAL_OPERATING_MARGIN)
        q = [f for f in margins if f.provenance.section == "quarterly"]
        assert q, "quarterly operating margin not found"
        # TCS Q4 FY26: 25.3%
        assert q[0].value == pytest.approx(25.3, abs=0.5)
        assert q[0].unit == FactUnit.PERCENT

    def test_quarterly_net_margin(self, result):
        margins = _facts(result, FactKind.FINANCIAL_NET_MARGIN)
        q = [f for f in margins if f.provenance.section == "quarterly"]
        assert q, "quarterly net margin not found"
        # TCS Q4 FY26: 19.4%
        assert q[0].value == pytest.approx(19.4, abs=0.5)

    def test_ceo_commentary_excerpt(self, result):
        assert "ceo_commentary" in result.excerpts
        assert len(result.excerpts["ceo_commentary"]) > 200

    def test_cfo_commentary_excerpt(self, result):
        assert "cfo_commentary" in result.excerpts
        assert len(result.excerpts["cfo_commentary"]) > 200

    def test_all_facts_period_march_2026(self, result):
        for f in result.facts:
            assert f.period == "2026-03-31", f"{f.kind.value} period={f.period!r}"


# ---------------------------------------------------------------------------
# Q2 FY26 (October 2025) — mid-year, no annual facts
# ---------------------------------------------------------------------------

class TestQ2FY26:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_Q2_FY26)
        return analyze(_ID_Q2_FY26, kb)

    def test_confidence_high(self, result):
        assert result.confidence == "high"

    def test_period_end_sept_2025(self, result):
        periods = _facts(result, FactKind.REPORT_PERIOD_END)
        assert periods[0].value == "2025-09-30"

    def test_no_annual_period_type(self, result):
        pts = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        assert not any(f.value == "annual" for f in pts), (
            "mid-year call should not emit annual period type"
        )

    def test_quarterly_inr_revenue(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        inr_q = [f for f in revs if f.unit == FactUnit.CRORE_INR]
        assert inr_q
        # TCS Q2 FY26: ₹65,799 crore
        assert inr_q[0].value == pytest.approx(65799.0, abs=100)

    def test_tcv_10_billion(self, result):
        tcv = _facts(result, FactKind.FINANCIAL_TCV)
        assert tcv
        assert tcv[0].value == pytest.approx(10.0, abs=1.0)

    def test_op_margin_around_25(self, result):
        m = _facts(result, FactKind.FINANCIAL_OPERATING_MARGIN)
        assert m
        assert m[0].value == pytest.approx(25.2, abs=0.5)

    def test_net_margin_around_19(self, result):
        m = _facts(result, FactKind.FINANCIAL_NET_MARGIN)
        assert m
        assert m[0].value == pytest.approx(19.6, abs=0.5)


# ---------------------------------------------------------------------------
# Q4 FY25 (April 2025) — annual call
# ---------------------------------------------------------------------------

class TestQ4FY25:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_Q4_FY25)
        return analyze(_ID_Q4_FY25, kb)

    def test_period_end_march_2025(self, result):
        periods = _facts(result, FactKind.REPORT_PERIOD_END)
        assert periods[0].value == "2025-03-31"

    def test_both_period_types(self, result):
        pts = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        values = {f.value for f in pts}
        assert "quarterly" in values
        assert "annual" in values

    def test_quarterly_inr_revenue(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        inr_q = [f for f in revs if f.unit == FactUnit.CRORE_INR and f.provenance.section == "quarterly"]
        assert inr_q

    def test_confidence_not_low(self, result):
        assert result.confidence in ("medium", "high")


# ---------------------------------------------------------------------------
# Cross-document invariants
# ---------------------------------------------------------------------------

class TestCrossDocumentInvariants:
    @pytest.fixture(scope="class")
    def results(self, kb: KnowledgeBase) -> list[AnalysisResult]:
        out = []
        for eid in _ALL_IDS:
            _skip_if_not_parsed(kb, eid)
            out.append(analyze(eid, kb))
        return out

    def test_all_have_period_end(self, results):
        for r in results:
            periods = _facts(r, FactKind.REPORT_PERIOD_END)
            assert periods, f"{r.evidence_id} missing REPORT_PERIOD_END"

    def test_all_have_quarterly_inr_revenue(self, results):
        for r in results:
            revs = [f for f in r.facts
                    if f.kind == FactKind.FINANCIAL_REVENUE and f.unit == FactUnit.CRORE_INR]
            assert revs, f"{r.evidence_id} missing FINANCIAL_REVENUE (INR)"

    def test_all_have_operating_margin(self, results):
        for r in results:
            m = _facts(r, FactKind.FINANCIAL_OPERATING_MARGIN)
            assert m, f"{r.evidence_id} missing FINANCIAL_OPERATING_MARGIN"

    def test_all_have_net_margin(self, results):
        for r in results:
            m = _facts(r, FactKind.FINANCIAL_NET_MARGIN)
            assert m, f"{r.evidence_id} missing FINANCIAL_NET_MARGIN"

    def test_margins_are_percent_unit(self, results):
        for r in results:
            for f in r.facts:
                if f.kind in (FactKind.FINANCIAL_OPERATING_MARGIN, FactKind.FINANCIAL_NET_MARGIN):
                    assert f.unit == FactUnit.PERCENT

    def test_all_revenue_facts_have_period(self, results):
        for r in results:
            for f in _facts(r, FactKind.FINANCIAL_REVENUE):
                assert f.period is not None

    def test_tcv_unit_is_usd_billion(self, results):
        for r in results:
            for f in _facts(r, FactKind.FINANCIAL_TCV):
                assert f.unit == FactUnit.USD_BILLION

    def test_no_result_level_low_confidence(self, results):
        for r in results:
            assert r.confidence != "low", (
                f"{r.evidence_id}: confidence=low, warnings={r.warnings}"
            )
