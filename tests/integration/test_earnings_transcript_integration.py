"""Integration tests for atlas.analysis.earnings_transcript (v2.0) against
real filings from all three reference companies.

Uses one real Q4/full-year transcript per company, chosen to exercise a
different speaker structure and sector:

  TCS         bse-news-7ff81737-...  Q4 & FY26 (April 14, 2026) — CEO/COO/
              CFO/CHRO structure, explicit no-guidance policy
  Tata Steel  bse-news-ee68c4f0-...  4QFY2026 & FY2026 (May 20, 2026) — CEO
              & MD / ED & CFO structure, one continuous narrative covering
              quarter + full year + balance sheet, explicit capex guidance
  SBI         bse-news-95273449-...  Q4FY26 Analyst Meet (May 15, 2026) —
              Chairman + four Managing Directors, no CEO/CFO at all,
              explicit NIM guidance. Real transcripts for SBI were found
              mis-catalogued as investor_presentation during this redesign's
              filing survey and reclassified — see project memory.

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
_TATASTEEL_REPO = _PROJECT_ROOT / "repositories" / "TATASTEEL"
_SBIN_REPO = _PROJECT_ROOT / "repositories" / "SBIN"

_TCS_ID = "bse-news-7ff81737-8eeb-4f5a-afad-f5f79b216e83"
_TATASTEEL_ID = "bse-news-ee68c4f0-4ad5-4e68-a453-7ac611317316"
_SBIN_ID = "bse-news-95273449-bfc3-407f-98ca-a2793fb883f4"


def _facts(result: AnalysisResult, kind: FactKind):
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# TCS — Q4 & FY26
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tcs_root(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(_TCS_REPO, evidence_ids=[_TCS_ID])


@pytest.fixture(scope="module")
def tcs_kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(tcs_root)
    entry = Repository(tcs_root).get(_TCS_ID)
    if entry is not None:
        instance.parse(entry)
    yield instance


@pytest.fixture(scope="module")
def tcs_result(tcs_kb: KnowledgeBase) -> AnalysisResult:
    doc = tcs_kb.get(_TCS_ID)
    if doc is None or doc.status != "ok":
        pytest.skip(f"{_TCS_ID[:16]}... not parsed")
    return analyze(_TCS_ID, tcs_kb)


class TestTCSQ4FY26:
    def test_returns_analysis_result(self, tcs_result: AnalysisResult):
        assert isinstance(tcs_result, AnalysisResult)

    def test_analyzer_version(self, tcs_result: AnalysisResult):
        assert tcs_result.analyzer_version == ANALYZER_VERSION

    def test_confidence_high(self, tcs_result: AnalysisResult):
        assert tcs_result.confidence == "high"

    def test_period_annual(self, tcs_result: AnalysisResult):
        assert _facts(tcs_result, FactKind.REPORT_PERIOD_END)[0].value == "2026-03-31"
        assert _facts(tcs_result, FactKind.REPORT_PERIOD_TYPE)[0].value == "annual"

    def test_quarterly_revenue(self, tcs_result: AnalysisResult):
        inr = [f for f in _facts(tcs_result, FactKind.FINANCIAL_REVENUE)
               if f.unit == FactUnit.CRORE_INR and f.provenance.section == "quarterly"]
        assert inr and inr[0].value == 70698.0

    def test_annual_revenue(self, tcs_result: AnalysisResult):
        inr = [f for f in _facts(tcs_result, FactKind.FINANCIAL_REVENUE)
               if f.unit == FactUnit.CRORE_INR and f.provenance.section == "annual"]
        assert inr and inr[0].value == 267021.0

    def test_usd_revenue(self, tcs_result: AnalysisResult):
        usd = [f for f in _facts(tcs_result, FactKind.FINANCIAL_REVENUE) if f.unit == FactUnit.USD_BILLION]
        assert usd and usd[0].value == 7.621

    def test_operating_margin(self, tcs_result: AnalysisResult):
        facts = _facts(tcs_result, FactKind.FINANCIAL_OPERATING_MARGIN)
        assert facts and facts[0].value == 25.3

    def test_net_margin(self, tcs_result: AnalysisResult):
        facts = _facts(tcs_result, FactKind.FINANCIAL_NET_MARGIN)
        assert facts and facts[0].value == 19.4

    def test_tcv(self, tcs_result: AnalysisResult):
        facts = _facts(tcs_result, FactKind.FINANCIAL_TCV)
        assert facts and facts[0].value == 12.0

    def test_headcount(self, tcs_result: AnalysisResult):
        facts = _facts(tcs_result, FactKind.ESG_WORKFORCE_HEADCOUNT)
        assert facts and facts[0].value == 584519.0

    def test_female_pct(self, tcs_result: AnalysisResult):
        facts = _facts(tcs_result, FactKind.ESG_WORKFORCE_FEMALE_PCT)
        assert facts and facts[0].value == 35.2

    def test_all_facts_have_provenance_section(self, tcs_result: AnalysisResult):
        for f in tcs_result.facts:
            assert f.provenance.section, f"fact {f.kind} missing provenance section"


# ---------------------------------------------------------------------------
# Tata Steel — 4QFY2026 & FY2026
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tata_root(isolated_repo_factory) -> Path:
    if not _TATASTEEL_REPO.exists():
        pytest.skip("TATASTEEL repository not found")
    return isolated_repo_factory(_TATASTEEL_REPO, evidence_ids=[_TATASTEEL_ID])


@pytest.fixture(scope="module")
def tata_kb(tata_root: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(tata_root)
    entry = Repository(tata_root).get(_TATASTEEL_ID)
    if entry is not None:
        instance.parse(entry)
    yield instance


@pytest.fixture(scope="module")
def tata_result(tata_kb: KnowledgeBase) -> AnalysisResult:
    doc = tata_kb.get(_TATASTEEL_ID)
    if doc is None or doc.status != "ok":
        pytest.skip(f"{_TATASTEEL_ID[:16]}... not parsed")
    return analyze(_TATASTEEL_ID, tata_kb)


class TestTataSteelQ4FY2026:
    def test_returns_analysis_result(self, tata_result: AnalysisResult):
        assert isinstance(tata_result, AnalysisResult)

    def test_confidence_high(self, tata_result: AnalysisResult):
        assert tata_result.confidence == "high"

    def test_period_annual(self, tata_result: AnalysisResult):
        assert _facts(tata_result, FactKind.REPORT_PERIOD_END)[0].value == "2026-03-31"
        assert _facts(tata_result, FactKind.REPORT_PERIOD_TYPE)[0].value == "annual"

    def test_quarterly_revenue(self, tata_result: AnalysisResult):
        # Regression: v1.0 anchored purely on the "₹" glyph and would have
        # found nothing at all — Tata Steel's CFO uses the "Rs" text marker.
        facts = _facts(tata_result, FactKind.FINANCIAL_REVENUE)
        assert facts and facts[0].value == 63270.0

    def test_margin_is_headline_not_segment_detail(self, tata_result: AnalysisResult):
        # Regression: the CFO states an unrelated annual India-segment
        # EBITDA margin (24%) well before the true quarterly headline
        # figure (16%) that immediately follows the revenue figure — the
        # nearer-to-revenue mention must win.
        facts = _facts(tata_result, FactKind.FINANCIAL_OPERATING_MARGIN)
        assert facts and facts[0].value == 16.0

    def test_guidance_extracted(self, tata_result: AnalysisResult):
        # Tata Steel gives explicit FY2027 capex guidance, unlike TCS which
        # states a policy of no numeric guidance at all.
        facts = _facts(tata_result, FactKind.STRATEGY_GUIDANCE)
        assert facts

    def test_no_tcv(self, tata_result: AnalysisResult):
        # TCV is an IT-services concept — correctly absent for a steel co.
        assert _facts(tata_result, FactKind.FINANCIAL_TCV) == []

    def test_all_facts_have_provenance_section(self, tata_result: AnalysisResult):
        for f in tata_result.facts:
            assert f.provenance.section, f"fact {f.kind} missing provenance section"


# ---------------------------------------------------------------------------
# SBI — Q4FY26 Analyst Meet
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sbin_root(isolated_repo_factory) -> Path:
    if not _SBIN_REPO.exists():
        pytest.skip("SBIN repository not found")
    return isolated_repo_factory(_SBIN_REPO, evidence_ids=[_SBIN_ID])


@pytest.fixture(scope="module")
def sbin_kb(sbin_root: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(sbin_root)
    entry = Repository(sbin_root).get(_SBIN_ID)
    if entry is not None:
        instance.parse(entry)
    yield instance


@pytest.fixture(scope="module")
def sbin_result(sbin_kb: KnowledgeBase) -> AnalysisResult:
    doc = sbin_kb.get(_SBIN_ID)
    if doc is None or doc.status != "ok":
        pytest.skip(f"{_SBIN_ID[:16]}... not parsed")
    return analyze(_SBIN_ID, sbin_kb)


class TestSBIQ4FY26:
    def test_returns_analysis_result(self, sbin_result: AnalysisResult):
        assert isinstance(sbin_result, AnalysisResult)

    def test_period_quarterly(self, sbin_result: AnalysisResult):
        # SBI's cover letter never says "quarter ended <date>" in the
        # phrase-matched form — this exercises the "QN FYyy" label fallback.
        assert _facts(sbin_result, FactKind.REPORT_PERIOD_END)[0].value == "2026-03-31"
        assert _facts(sbin_result, FactKind.REPORT_PERIOD_TYPE)[0].value == "quarterly"

    def test_guidance_extracted_despite_no_ceo_or_cfo(self, sbin_result: AnalysisResult):
        # SBI has no CEO or CFO at all — a Chairman delivers all headline
        # commentary directly. Fact extraction is content-window-bound, not
        # speaker-gated, so this must still succeed.
        facts = _facts(sbin_result, FactKind.STRATEGY_GUIDANCE)
        assert facts
        assert any("NIM" in f.value for f in facts)

    def test_no_revenue_no_false_positive(self, sbin_result: AnalysisResult):
        # A bank's Chairman states Net Profit, not "revenue" — must not be
        # forced into a false match against unrelated figures.
        assert _facts(sbin_result, FactKind.FINANCIAL_REVENUE) == []

    def test_no_tcv(self, sbin_result: AnalysisResult):
        assert _facts(sbin_result, FactKind.FINANCIAL_TCV) == []

    def test_all_facts_have_provenance_section(self, sbin_result: AnalysisResult):
        for f in sbin_result.facts:
            assert f.provenance.section, f"fact {f.kind} missing provenance section"
