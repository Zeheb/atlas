"""Integration tests for shareholding_trend analysis pipeline.

Two test scenarios:

1. RealQ4Fy26 — loads the real TCS Q4 FY26 SHP XML via the repository and
   knowledge base, runs the SHP analyzer, then verifies that analyze_trend
   produces a valid HoldingPoint with the correct values.

2. MultiQuarter — uses mock KBs with synthetic minimal XBRL XML for four
   quarters (Q4 FY25 through Q3 FY26), runs the real SHP analyzer on each,
   then runs analyze_trend on all four results. Validates QoQ deltas, YoY
   deltas, and that streak signals fire correctly.

Run with: pytest -m integration -v -s
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock

import pytest

from atlas.analysis.shareholding_pattern import analyze as shp_analyze
from atlas.analysis.shareholding_trend import (
    HoldingPoint,
    TrendResult,
    analyze_trend,
)
from atlas.analysis.base import AnalysisResult, FactKind
from atlas.knowledge.base import KnowledgeBase
from atlas.acquisition.repository import Repository

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"
_TCS_SHP_ID = "bse-shp-532540-129"


# ---------------------------------------------------------------------------
# Minimal XBRL XML generator
# ---------------------------------------------------------------------------

def _shp_xml(
    period: str,
    promoter: float,
    public: float,
    fpi: float,
    dii: float,
    mf: float,
    insurance: float,
    nri: float,
    pledged: bool = False,
    pledged_pct: float = 0.0,
    total_shares: int = 3_618_087_518,
) -> str:
    """Generate a minimal BSE XBRL SHP document parseable by the SHP analyzer.

    Values for percentages should be given on the 0–100 scale; they are
    divided by 100 here to match the XBRL 0–1 convention.
    """
    pledged_tag = "true" if pledged else "false"
    xml = dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <xbrl xmlns:in-bse-shp="https://example.com/in-bse-shp-test">
          <in-bse-shp:DateOfReport contextRef="MainI">{period}</in-bse-shp:DateOfReport>
          <in-bse-shp:NumberOfFullyPaidUpEquityShares contextRef="ShareholdingPattern_ContextI">{total_shares}</in-bse-shp:NumberOfFullyPaidUpEquityShares>
          <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">{promoter / 100:.6f}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="PublicShareholding_ContextI">{public / 100:.6f}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InstitutionsForeign_ContextI">{fpi / 100:.6f}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InstitutionsDomestic_ContextI">{dii / 100:.6f}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="MutualFundsOrUTI_ContextI">{mf / 100:.6f}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InsuranceCompanies_ContextI">{insurance / 100:.6f}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="NonResidentIndians_ContextI">{nri / 100:.6f}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <in-bse-shp:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged contextRef="MainI">{pledged_tag}</in-bse-shp:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged>
          <in-bse-shp:PercentageOfSharesEncumberedToTotalSharesHeldByPromoter contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">{pledged_pct / 100:.6f}</in-bse-shp:PercentageOfSharesEncumberedToTotalSharesHeldByPromoter>
        </xbrl>
    """)
    return xml


def _mock_kb(eid: str, xml: str, period: str) -> MagicMock:
    """Build a minimal mock KnowledgeBase that returns synthetic XML."""
    entry = MagicMock()
    entry.kind = "shareholding_pattern"
    entry.source_date = period + "T00:00:00+00:00"
    entry.status = "ok"

    kb = MagicMock()
    kb.get.return_value = entry
    kb.get_content.return_value = xml
    return kb


# ---------------------------------------------------------------------------
# Scenario 1: Real TCS Q4 FY26 SHP through the repository pipeline
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tcs_root(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(_TCS_REPO, evidence_ids=[_TCS_SHP_ID])


@pytest.fixture(scope="module")
def real_kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(tcs_root)
    repo = Repository(tcs_root)
    entry = repo.get(_TCS_SHP_ID)
    if entry is not None:
        instance.parse(entry)
    yield instance


@pytest.fixture(scope="module")
def real_shp_result(real_kb: KnowledgeBase) -> AnalysisResult:
    entry = real_kb.get(_TCS_SHP_ID)
    if entry is None or entry.status != "ok":
        pytest.skip(f"{_TCS_SHP_ID!r} not parsed — run acquisition pipeline first")
    return shp_analyze(_TCS_SHP_ID, real_kb)


class TestRealQ4Fy26:
    """Single real SHP → analyze_trend produces one valid HoldingPoint."""

    @pytest.fixture(autouse=True)
    def trend(self, real_shp_result: AnalysisResult):
        self.t = analyze_trend([real_shp_result])

    def test_one_holding_point(self):
        assert len(self.t.points) == 1

    def test_holding_point_period(self):
        assert self.t.points[0].period == "2026-03-31"

    def test_holding_point_evidence_id(self):
        assert self.t.points[0].evidence_id == _TCS_SHP_ID

    def test_promoter_pct_in_facts(self):
        p = self.t.points[0]
        assert FactKind.OWNERSHIP_PROMOTER_PCT in p.facts
        assert p.facts[FactKind.OWNERSHIP_PROMOTER_PCT] == pytest.approx(71.77, abs=0.01)

    def test_fpi_pct_in_facts(self):
        p = self.t.points[0]
        assert FactKind.OWNERSHIP_FPI_PCT in p.facts
        assert p.facts[FactKind.OWNERSHIP_FPI_PCT] == pytest.approx(9.66, abs=0.01)

    def test_total_shares_in_facts(self):
        p = self.t.points[0]
        assert FactKind.OWNERSHIP_TOTAL_SHARES in p.facts
        assert p.facts[FactKind.OWNERSHIP_TOTAL_SHARES] == 3_618_087_518

    def test_no_deltas_single_point(self):
        assert self.t.qoq_deltas == []
        assert self.t.yoy_deltas == []

    def test_no_warnings(self):
        assert self.t.warnings == []


# ---------------------------------------------------------------------------
# Scenario 2: Four synthetic quarters via mock KB → full trend pipeline
# ---------------------------------------------------------------------------

# Approximate TCS data Q4 FY25 through Q3 FY26
_SYNTHETIC_QUARTERS = [
    {
        "eid": "bse-shp-test-q4fy25",
        "period": "2025-03-31",
        "promoter": 71.77, "public": 28.23,
        "fpi": 11.24, "dii": 12.54, "mf": 5.46, "insurance": 6.18, "nri": 0.24,
    },
    {
        "eid": "bse-shp-test-q1fy26",
        "period": "2025-06-30",
        "promoter": 71.77, "public": 28.23,
        "fpi": 10.59, "dii": 12.98, "mf": 5.68, "insurance": 6.44, "nri": 0.25,
    },
    {
        "eid": "bse-shp-test-q2fy26",
        "period": "2025-09-30",
        "promoter": 71.77, "public": 28.23,
        "fpi": 10.28, "dii": 13.09, "mf": 5.65, "insurance": 6.58, "nri": 0.27,
    },
    {
        "eid": "bse-shp-test-q3fy26",
        "period": "2025-12-31",
        "promoter": 71.77, "public": 28.23,
        "fpi": 10.01, "dii": 13.27, "mf": 5.72, "insurance": 6.64, "nri": 0.26,
    },
]


@pytest.fixture(scope="module")
def multi_quarter_trend() -> TrendResult:
    """Run SHP analyzer + analyze_trend over 4 synthetic quarters."""
    results = []
    for q in _SYNTHETIC_QUARTERS:
        xml = _shp_xml(
            period=q["period"],
            promoter=q["promoter"],
            public=q["public"],
            fpi=q["fpi"],
            dii=q["dii"],
            mf=q["mf"],
            insurance=q["insurance"],
            nri=q["nri"],
        )
        kb = _mock_kb(q["eid"], xml, q["period"])
        result = shp_analyze(q["eid"], kb)
        results.append(result)
    return analyze_trend(results)


class TestMultiQuarterTrend:
    """Four quarters of synthetic data → verify QoQ deltas, signals, no YoY."""

    def test_four_holding_points(self, multi_quarter_trend: TrendResult):
        assert len(multi_quarter_trend.points) == 4

    def test_periods_sorted_ascending(self, multi_quarter_trend: TrendResult):
        periods = [p.period for p in multi_quarter_trend.points]
        assert periods == sorted(periods)

    def test_fpi_qoq_all_negative(self, multi_quarter_trend: TrendResult):
        fpi = [d for d in multi_quarter_trend.qoq_deltas
               if d.kind == FactKind.OWNERSHIP_FPI_PCT]
        assert len(fpi) == 3
        assert all(d.delta < 0 for d in fpi)

    def test_dii_qoq_all_positive(self, multi_quarter_trend: TrendResult):
        dii = [d for d in multi_quarter_trend.qoq_deltas
               if d.kind == FactKind.OWNERSHIP_DII_PCT]
        assert all(d.delta > 0 for d in dii)

    def test_fpi_first_qoq_value(self, multi_quarter_trend: TrendResult):
        fpi = [d for d in multi_quarter_trend.qoq_deltas
               if d.kind == FactKind.OWNERSHIP_FPI_PCT][0]
        assert fpi.from_period == "2025-03-31"
        assert fpi.to_period == "2025-06-30"
        assert fpi.delta == pytest.approx(-0.65, abs=1e-3)

    def test_no_yoy_with_four_quarters(self, multi_quarter_trend: TrendResult):
        # All four are within the same FY26; no quarter has a same-quarter match 1 year prior
        assert multi_quarter_trend.yoy_deltas == []

    def test_fpi_streak_signal_present(self, multi_quarter_trend: TrendResult):
        assert any(
            "fpi pct" in s and "falling" in s and "3+" in s
            for s in multi_quarter_trend.signals
        )

    def test_dii_streak_signal_present(self, multi_quarter_trend: TrendResult):
        assert any(
            "dii pct" in s and "rising" in s and "3+" in s
            for s in multi_quarter_trend.signals
        )

    def test_no_warnings(self, multi_quarter_trend: TrendResult):
        assert multi_quarter_trend.warnings == []


# ---------------------------------------------------------------------------
# Scenario 3: Real Q4 FY26 + 3 synthetic quarters → YoY delta
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def five_quarter_trend(real_shp_result: AnalysisResult) -> TrendResult:
    """Real Q4 FY26 SHP + 3 synthetic quarters including Q4 FY25 → YoY delta."""
    results = [real_shp_result]

    for q in _SYNTHETIC_QUARTERS:  # includes Q4 FY25 (2025-03-31)
        xml = _shp_xml(
            period=q["period"],
            promoter=q["promoter"],
            public=q["public"],
            fpi=q["fpi"],
            dii=q["dii"],
            mf=q["mf"],
            insurance=q["insurance"],
            nri=q["nri"],
        )
        kb = _mock_kb(q["eid"], xml, q["period"])
        results.append(shp_analyze(q["eid"], kb))

    return analyze_trend(results)


class TestFiveQuarterTrend:
    """Real Q4 FY26 + 3 synthetic quarters → QoQ, YoY deltas, and streak signals."""

    def test_five_holding_points(self, five_quarter_trend: TrendResult):
        assert len(five_quarter_trend.points) == 5

    def test_yoy_fpi_delta_produced(self, five_quarter_trend: TrendResult):
        # Q4 FY26 vs Q4 FY25
        yoy_fpi = [d for d in five_quarter_trend.yoy_deltas
                   if d.kind == FactKind.OWNERSHIP_FPI_PCT
                   and d.to_period == "2026-03-31"]
        assert len(yoy_fpi) == 1

    def test_yoy_fpi_is_negative(self, five_quarter_trend: TrendResult):
        yoy_fpi = [d for d in five_quarter_trend.yoy_deltas
                   if d.kind == FactKind.OWNERSHIP_FPI_PCT
                   and d.to_period == "2026-03-31"][0]
        assert yoy_fpi.delta < 0    # FPI declined year-over-year
        assert yoy_fpi.from_period == "2025-03-31"

    def test_yoy_dii_is_positive(self, five_quarter_trend: TrendResult):
        yoy_dii = [d for d in five_quarter_trend.yoy_deltas
                   if d.kind == FactKind.OWNERSHIP_DII_PCT
                   and d.to_period == "2026-03-31"]
        assert len(yoy_dii) == 1
        assert yoy_dii[0].delta > 0

    def test_last_point_is_real_data(self, five_quarter_trend: TrendResult):
        last = five_quarter_trend.points[-1]
        assert last.evidence_id == _TCS_SHP_ID
        assert last.period == "2026-03-31"
        assert last.facts[FactKind.OWNERSHIP_FPI_PCT] == pytest.approx(9.66, abs=0.01)
