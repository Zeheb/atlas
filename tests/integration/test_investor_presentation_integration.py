"""Integration tests for atlas.analysis.investor_presentation (v2.0) against
real filings from all three reference companies.

Uses one real filing per company, chosen to exercise a different document
shape and sector:

  TCS         bse-news-d4482add-...  Analyst Day 2025 — genuine slide deck
              (December 17, 2025)
  Tata Steel  bse-news-2cf3f833-...  Q4/FY2026 results — press-release-style
              filing with a management-quote block (May 15, 2026)
  SBI         bse-news-f64f0315-...  Q2 FY2025 analyst presentation — genuine
              slide deck with a banking KPI table (November 8, 2024)

Run with: pytest -m integration -v -s
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.investor_presentation import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.knowledge.base import KnowledgeBase
from atlas.acquisition.repository import Repository

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"
_TATASTEEL_REPO = _PROJECT_ROOT / "repositories" / "TATASTEEL"
_SBIN_REPO = _PROJECT_ROOT / "repositories" / "SBIN"

_ANALYST_DAY_ID = "bse-news-d4482add-0416-449e-babc-d6e5aeefe1ab"
_TATASTEEL_ID = "bse-news-2cf3f833-00a2-44d6-b16e-7eb9376f6519"
_SBIN_ID = "bse-news-f64f0315-c651-4902-83d6-6a64cf4716be"


def _facts(result: AnalysisResult, kind: FactKind):
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# TCS — Analyst Day 2025 (genuine slide deck)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tcs_root(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(_TCS_REPO, evidence_ids=[_ANALYST_DAY_ID])


@pytest.fixture(scope="module")
def tcs_kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(tcs_root)
    entry = Repository(tcs_root).get(_ANALYST_DAY_ID)
    if entry is not None:
        instance.parse(entry)
    yield instance


@pytest.fixture(scope="module")
def tcs_result(tcs_kb: KnowledgeBase) -> AnalysisResult:
    doc = tcs_kb.get(_ANALYST_DAY_ID)
    if doc is None or doc.status != "ok":
        pytest.skip(f"{_ANALYST_DAY_ID[:16]}... not parsed")
    return analyze(_ANALYST_DAY_ID, tcs_kb)


class TestTCSAnalystDay2025:
    def test_returns_analysis_result(self, tcs_result: AnalysisResult):
        assert isinstance(tcs_result, AnalysisResult)

    def test_kind(self, tcs_result: AnalysisResult):
        assert tcs_result.kind == "investor_presentation"

    def test_analyzer_version(self, tcs_result: AnalysisResult):
        assert tcs_result.analyzer_version == ANALYZER_VERSION

    def test_confidence_high(self, tcs_result: AnalysisResult):
        assert tcs_result.confidence == "high"

    # -- STRATEGY_ASPIRATION --------------------------------------------------

    def test_aspiration_extracted(self, tcs_result: AnalysisResult):
        facts = _facts(tcs_result, FactKind.STRATEGY_ASPIRATION)
        assert len(facts) == 1
        assert "largest" in facts[0].value

    def test_aspiration_not_truncated_by_recurring_header(
        self, tcs_result: AnalysisResult
    ):
        # The real deck repeats this sentence before every slide's own
        # "Our Aspiration" heading — must not bleed into the capture.
        facts = _facts(tcs_result, FactKind.STRATEGY_ASPIRATION)
        assert "Our Aspiration" not in facts[0].value

    def test_aspiration_no_newlines(self, tcs_result: AnalysisResult):
        assert "\n" not in _facts(tcs_result, FactKind.STRATEGY_ASPIRATION)[0].value

    # -- SEGMENT_NAME + SEGMENT_GROWTH_PCT ------------------------------------

    def test_service_line_growth_extracted(self, tcs_result: AnalysisResult):
        growths = _facts(tcs_result, FactKind.SEGMENT_GROWTH_PCT)
        assert len(growths) >= 4

    def test_ai_services_growth_present(self, tcs_result: AnalysisResult):
        names = {f.value for f in _facts(tcs_result, FactKind.SEGMENT_NAME)}
        assert "AI Services" in names

    def test_segment_growth_units_percent(self, tcs_result: AnalysisResult):
        for f in _facts(tcs_result, FactKind.SEGMENT_GROWTH_PCT):
            assert f.unit == FactUnit.PERCENT

    # -- FINANCIAL_ROE — clean multi-year bar-chart block ---------------------

    def test_five_roe_years_extracted(self, tcs_result: AnalysisResult):
        facts = _facts(tcs_result, FactKind.FINANCIAL_ROE)
        assert len(facts) == 5, f"expected 5 ROE years, got {len(facts)}"

    def test_roe_fy2021(self, tcs_result: AnalysisResult):
        fy21 = next(
            f
            for f in _facts(tcs_result, FactKind.FINANCIAL_ROE)
            if f.period == "2021-03-31"
        )
        assert fy21.value == pytest.approx(38.2)

    def test_roe_fy2025(self, tcs_result: AnalysisResult):
        fy25 = next(
            f
            for f in _facts(tcs_result, FactKind.FINANCIAL_ROE)
            if f.period == "2025-03-31"
        )
        assert fy25.value == pytest.approx(51.2)

    def test_peer_average_not_in_roe(self, tcs_result: AnalysisResult):
        assert 23.6 not in [f.value for f in _facts(tcs_result, FactKind.FINANCIAL_ROE)]

    # -- FINANCIAL_FCF — interleaved-layout bar-chart block -------------------

    def test_five_fcf_years_extracted(self, tcs_result: AnalysisResult):
        facts = _facts(tcs_result, FactKind.FINANCIAL_FCF)
        assert len(facts) == 5, f"expected 5 FCF years, got {len(facts)}"

    def test_fcf_fy2021(self, tcs_result: AnalysisResult):
        # Regression: the real PDF interleaves "FY 2021, 30664" as an
        # adjacent pair, then groups the remaining 4 years and values
        # separately — an off-by-one year/value pairing bug produced
        # 31424 here (FY2022's real value) before the FIFO-pairing fix.
        fy21 = next(
            f
            for f in _facts(tcs_result, FactKind.FINANCIAL_FCF)
            if f.period == "2021-03-31"
        )
        assert fy21.value == 30664

    def test_fcf_fy2025(self, tcs_result: AnalysisResult):
        fy25 = next(
            f
            for f in _facts(tcs_result, FactKind.FINANCIAL_FCF)
            if f.period == "2025-03-31"
        )
        assert fy25.value == 44962

    def test_fcf_units_crore_inr(self, tcs_result: AnalysisResult):
        for f in _facts(tcs_result, FactKind.FINANCIAL_FCF):
            assert f.unit == FactUnit.CRORE_INR

    # -- STRATEGY_CSAT --------------------------------------------------------

    def test_csat_extracted(self, tcs_result: AnalysisResult):
        facts = _facts(tcs_result, FactKind.STRATEGY_CSAT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(94.18)

    def test_csat_period_h1_fy26(self, tcs_result: AnalysisResult):
        assert _facts(tcs_result, FactKind.STRATEGY_CSAT)[0].period == "2025-09-30"

    # -- Cross-sector concepts absent for TCS ---------------------------------

    def test_no_banking_ratios(self, tcs_result: AnalysisResult):
        assert _facts(tcs_result, FactKind.FINANCIAL_NET_INTEREST_MARGIN) == []

    def test_no_production_volume(self, tcs_result: AnalysisResult):
        assert _facts(tcs_result, FactKind.FINANCIAL_PRODUCTION_VOLUME) == []

    # -- Provenance -------------------------------------------------------------

    def test_all_facts_have_provenance_section(self, tcs_result: AnalysisResult):
        for f in tcs_result.facts:
            assert f.provenance.section, f"fact {f.kind} missing provenance section"

    def test_source_date_dec_2025(self, tcs_result: AnalysisResult):
        assert tcs_result.source_date.year == 2025
        assert tcs_result.source_date.month == 12


# ---------------------------------------------------------------------------
# Tata Steel — Q4/FY2026 results presentation (press-release-style filing)
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

    # -- Period: Q4-bundled-with-annual filing must resolve to annual --------

    def test_period_end(self, tata_result: AnalysisResult):
        facts = _facts(tata_result, FactKind.REPORT_PERIOD_END)
        assert facts[0].value == "2026-03-31"

    def test_period_type_annual(self, tata_result: AnalysisResult):
        facts = _facts(tata_result, FactKind.REPORT_PERIOD_TYPE)
        assert facts[0].value == "annual"

    # -- FINANCIAL_FCF — inline sentence, not the ambiguous "Capital
    #    Allocation" prose heading's capex figure ------------------------------

    def test_fcf_extracted_correct_value(self, tata_result: AnalysisResult):
        facts = _facts(tata_result, FactKind.FINANCIAL_FCF)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(10738.0)

    def test_fcf_not_confused_with_capex(self, tata_result: AnalysisResult):
        # Regression: "Capital Allocation" heading precedes unrelated prose
        # bullets here (unlike TCS's clean chart) — a capex figure of
        # 14,026 sits nearby and must not be captured as FCF.
        values = [f.value for f in _facts(tata_result, FactKind.FINANCIAL_FCF)]
        assert 14026.0 not in values

    def test_fcf_period(self, tata_result: AnalysisResult):
        assert _facts(tata_result, FactKind.FINANCIAL_FCF)[0].period == "2026-03-31"

    # -- Physical operating volume (steel-specific concept) -------------------

    def test_production_volume_extracted(self, tata_result: AnalysisResult):
        facts = _facts(tata_result, FactKind.FINANCIAL_PRODUCTION_VOLUME)
        assert len(facts) == 1
        assert facts[0].unit == FactUnit.MILLION_TONNES

    def test_delivery_volume_extracted(self, tata_result: AnalysisResult):
        facts = _facts(tata_result, FactKind.FINANCIAL_DELIVERY_VOLUME)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(6.19)

    # -- STRATEGY_GUIDANCE ------------------------------------------------------

    def test_at_least_one_guidance_fact(self, tata_result: AnalysisResult):
        assert _facts(tata_result, FactKind.STRATEGY_GUIDANCE)

    # -- Management commentary excerpt ------------------------------------------

    def test_management_commentary_excerpt_present(self, tata_result: AnalysisResult):
        assert "management_commentary" in tata_result.excerpts
        assert "Narendran" in tata_result.excerpts["management_commentary"]

    # -- Cross-sector concepts absent for a steel company ----------------------

    def test_no_banking_ratios(self, tata_result: AnalysisResult):
        assert _facts(tata_result, FactKind.FINANCIAL_NET_INTEREST_MARGIN) == []

    def test_no_csat(self, tata_result: AnalysisResult):
        assert _facts(tata_result, FactKind.STRATEGY_CSAT) == []

    def test_all_facts_have_provenance_section(self, tata_result: AnalysisResult):
        for f in tata_result.facts:
            assert f.provenance.section, f"fact {f.kind} missing provenance section"


# ---------------------------------------------------------------------------
# SBI — Q2 FY2025 analyst presentation (genuine slide deck, banking KPIs)
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


class TestSBIQ2FY2025:
    def test_returns_analysis_result(self, sbin_result: AnalysisResult):
        assert isinstance(sbin_result, AnalysisResult)

    def test_confidence_high(self, sbin_result: AnalysisResult):
        assert sbin_result.confidence == "high"

    # -- Period: "quarter and half year ended" must resolve to quarterly,
    #    not annual (regression: "half year" contains substring "year") -------

    def test_period_end(self, sbin_result: AnalysisResult):
        facts = _facts(sbin_result, FactKind.REPORT_PERIOD_END)
        assert facts[0].value == "2024-09-30"

    def test_period_type_is_quarterly_not_annual(self, sbin_result: AnalysisResult):
        facts = _facts(sbin_result, FactKind.REPORT_PERIOD_TYPE)
        assert facts[0].value == "quarterly"

    # -- Banking ratio family — previously reserved, unpopulated FactKinds ----

    def test_net_interest_income(self, sbin_result: AnalysisResult):
        facts = _facts(sbin_result, FactKind.FINANCIAL_NET_INTEREST_INCOME)
        assert facts[0].value == pytest.approx(41620.0)

    def test_net_interest_margin(self, sbin_result: AnalysisResult):
        facts = _facts(sbin_result, FactKind.FINANCIAL_NET_INTEREST_MARGIN)
        assert facts[0].value == pytest.approx(3.14)

    def test_credit_cost(self, sbin_result: AnalysisResult):
        assert _facts(sbin_result, FactKind.FINANCIAL_CREDIT_COST)[
            0
        ].value == pytest.approx(0.38)

    def test_net_npa_ratio(self, sbin_result: AnalysisResult):
        assert _facts(sbin_result, FactKind.FINANCIAL_NET_NPA_RATIO)[
            0
        ].value == pytest.approx(0.53)

    def test_provision_coverage_ratio(self, sbin_result: AnalysisResult):
        facts = _facts(sbin_result, FactKind.FINANCIAL_PROVISION_COVERAGE_RATIO)
        assert facts[0].value == pytest.approx(92.21)

    def test_capital_adequacy_ratio(self, sbin_result: AnalysisResult):
        facts = _facts(sbin_result, FactKind.FINANCIAL_CAPITAL_ADEQUACY_RATIO)
        assert facts[0].value == pytest.approx(13.76)

    def test_banking_ratios_no_duplicates(self, sbin_result: AnalysisResult):
        # Regression: SBI's deck restates Capital Adequacy in a later detail
        # slide — must not produce a second, conflicting fact.
        assert len(_facts(sbin_result, FactKind.FINANCIAL_CAPITAL_ADEQUACY_RATIO)) == 1

    # -- FINANCIAL_ROE — inline disclosure -------------------------------------

    def test_roe_extracted(self, sbin_result: AnalysisResult):
        assert _facts(sbin_result, FactKind.FINANCIAL_ROE)

    # -- Segment growth: value-then-label with connector-word skip ------------

    def test_deposits_growth_extracted(self, sbin_result: AnalysisResult):
        names = [f.value for f in _facts(sbin_result, FactKind.SEGMENT_NAME)]
        assert "Deposits" in names
        assert "in" not in names

    # -- Cross-sector concepts absent for a bank -------------------------------

    def test_no_production_volume(self, sbin_result: AnalysisResult):
        assert _facts(sbin_result, FactKind.FINANCIAL_PRODUCTION_VOLUME) == []

    def test_no_csat(self, sbin_result: AnalysisResult):
        assert _facts(sbin_result, FactKind.STRATEGY_CSAT) == []

    def test_all_facts_have_provenance_section(self, sbin_result: AnalysisResult):
        for f in sbin_result.facts:
            assert f.provenance.section, f"fact {f.kind} missing provenance section"
