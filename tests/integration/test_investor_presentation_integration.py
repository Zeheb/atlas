"""Integration tests for atlas.analysis.investor_presentation.

Uses the single real TCS Analyst Day 2025 strategy deck in the repository:
  bse-news-d4482add-0416-449e-babc-d6e5aeefe1ab  (December 17, 2025)

This is the only actual slide deck among the 50 investor_presentation entries
in the TCS catalog. The rest are short IR activity filings.

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
_TCS_REPO     = _PROJECT_ROOT / "repositories" / "TCS"

_ANALYST_DAY_ID = "bse-news-d4482add-0416-449e-babc-d6e5aeefe1ab"


@pytest.fixture(scope="module")
def tcs_root() -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return _TCS_REPO


@pytest.fixture(scope="module")
def kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    db = tcs_root / "knowledge.db"
    db.unlink(missing_ok=True)
    instance = KnowledgeBase(tcs_root)
    repo = Repository(tcs_root)
    entry = repo.get(_ANALYST_DAY_ID)
    if entry is not None:
        instance.parse(entry)
    yield instance
    db.unlink(missing_ok=True)


def _facts(result: AnalysisResult, kind: FactKind):
    return [f for f in result.facts if f.kind == kind]


def _skip_if_not_parsed(kb: KnowledgeBase) -> None:
    entry = kb.get(_ANALYST_DAY_ID)
    if entry is None or entry.status != "ok":
        pytest.skip(f"{_ANALYST_DAY_ID[:16]}... not parsed")


# ---------------------------------------------------------------------------
# TCS Analyst Day 2025 — strategy deck
# ---------------------------------------------------------------------------

class TestAnalystDay2025:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb)
        return analyze(_ANALYST_DAY_ID, kb)

    def test_returns_analysis_result(self, result: AnalysisResult):
        assert isinstance(result, AnalysisResult)

    def test_kind(self, result: AnalysisResult):
        assert result.kind == "investor_presentation"

    def test_analyzer_version(self, result: AnalysisResult):
        assert result.analyzer_version == ANALYZER_VERSION

    def test_subtype_is_strategy(self, result: AnalysisResult):
        assert result.excerpts["subtype"] == "strategy"

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_no_warnings(self, result: AnalysisResult):
        assert result.warnings == [], result.warnings

    # -- STRATEGY_ASPIRATION --------------------------------------------------

    def test_aspiration_extracted(self, result: AnalysisResult):
        facts = _facts(result, FactKind.STRATEGY_ASPIRATION)
        assert len(facts) == 1

    def test_aspiration_mentions_ai(self, result: AnalysisResult):
        facts = _facts(result, FactKind.STRATEGY_ASPIRATION)
        assert "AI" in facts[0].value or "largest" in facts[0].value

    def test_aspiration_no_newlines(self, result: AnalysisResult):
        facts = _facts(result, FactKind.STRATEGY_ASPIRATION)
        assert "\n" not in facts[0].value

    # -- STRATEGY_PRIORITY (5 transformation pillars) -------------------------

    def test_five_pillars_extracted(self, result: AnalysisResult):
        facts = _facts(result, FactKind.STRATEGY_PRIORITY)
        values = {f.value for f in facts}
        assert "tcsAI Internal Transformation" in values
        assert "Redefining all Services" in values
        assert "Future-ready Talent Model" in values
        assert "Making AI Real for clients" in values
        assert "AI Ecosystem Play" in values

    def test_pillar_count_exactly_five(self, result: AnalysisResult):
        facts = _facts(result, FactKind.STRATEGY_PRIORITY)
        assert len(facts) == 5, f"expected 5 pillars, got {len(facts)}"

    # -- STRATEGY_GUIDANCE (margin target) ------------------------------------

    def test_margin_guidance_26_28(self, result: AnalysisResult):
        facts = _facts(result, FactKind.STRATEGY_GUIDANCE)
        assert len(facts) >= 1
        assert facts[0].value == "26-28%"

    # -- SEGMENT_NAME + SEGMENT_GROWTH_PCT ------------------------------------

    def test_service_line_growth_extracted(self, result: AnalysisResult):
        growths = _facts(result, FactKind.SEGMENT_GROWTH_PCT)
        assert len(growths) >= 4, f"expected ≥4 service lines, got {len(growths)}"

    def test_ai_services_growth_present(self, result: AnalysisResult):
        names = {f.value for f in _facts(result, FactKind.SEGMENT_NAME)}
        assert "AI Services" in names

    def test_segment_growth_units_percent(self, result: AnalysisResult):
        for f in _facts(result, FactKind.SEGMENT_GROWTH_PCT):
            assert f.unit == FactUnit.PERCENT

    # -- FINANCIAL_ROE --------------------------------------------------------

    def test_five_roe_years_extracted(self, result: AnalysisResult):
        facts = _facts(result, FactKind.FINANCIAL_ROE)
        assert len(facts) == 5, f"expected 5 ROE years, got {len(facts)}"

    def test_roe_fy2021(self, result: AnalysisResult):
        facts = _facts(result, FactKind.FINANCIAL_ROE)
        fy21 = next((f for f in facts if f.period == "2021-03-31"), None)
        assert fy21 is not None
        assert fy21.value == pytest.approx(38.2)

    def test_roe_fy2025(self, result: AnalysisResult):
        facts = _facts(result, FactKind.FINANCIAL_ROE)
        fy25 = next((f for f in facts if f.period == "2025-03-31"), None)
        assert fy25 is not None
        assert fy25.value == pytest.approx(51.2)

    def test_roe_units_percent(self, result: AnalysisResult):
        for f in _facts(result, FactKind.FINANCIAL_ROE):
            assert f.unit == FactUnit.PERCENT

    def test_peer_average_not_in_roe(self, result: AnalysisResult):
        values = [f.value for f in _facts(result, FactKind.FINANCIAL_ROE)]
        assert 23.6 not in values

    # -- FINANCIAL_FCF --------------------------------------------------------

    def test_five_fcf_years_extracted(self, result: AnalysisResult):
        facts = _facts(result, FactKind.FINANCIAL_FCF)
        assert len(facts) == 5, f"expected 5 FCF years, got {len(facts)}"

    def test_fcf_fy2021(self, result: AnalysisResult):
        facts = _facts(result, FactKind.FINANCIAL_FCF)
        fy21 = next((f for f in facts if f.period == "2021-03-31"), None)
        assert fy21 is not None
        assert fy21.value == 30664

    def test_fcf_fy2025(self, result: AnalysisResult):
        facts = _facts(result, FactKind.FINANCIAL_FCF)
        fy25 = next((f for f in facts if f.period == "2025-03-31"), None)
        assert fy25 is not None
        assert fy25.value == 44962

    def test_fcf_units_crore_inr(self, result: AnalysisResult):
        for f in _facts(result, FactKind.FINANCIAL_FCF):
            assert f.unit == FactUnit.CRORE_INR

    # -- STRATEGY_CSAT --------------------------------------------------------

    def test_csat_extracted(self, result: AnalysisResult):
        facts = _facts(result, FactKind.STRATEGY_CSAT)
        assert len(facts) == 1

    def test_csat_value_h1_fy26(self, result: AnalysisResult):
        facts = _facts(result, FactKind.STRATEGY_CSAT)
        assert facts[0].value == pytest.approx(94.18)

    def test_csat_period_h1_fy26(self, result: AnalysisResult):
        facts = _facts(result, FactKind.STRATEGY_CSAT)
        # H1 FY26 = April–September 2025
        assert facts[0].period == "2025-09-30"

    def test_csat_unit_percent(self, result: AnalysisResult):
        facts = _facts(result, FactKind.STRATEGY_CSAT)
        assert facts[0].unit == FactUnit.PERCENT

    # -- Provenance invariants ------------------------------------------------

    def test_all_facts_have_provenance_section(self, result: AnalysisResult):
        for f in result.facts:
            assert f.provenance.section, f"fact {f.kind} missing provenance section"

    def test_source_date_dec_2025(self, result: AnalysisResult):
        assert result.source_date.year == 2025
        assert result.source_date.month == 12
