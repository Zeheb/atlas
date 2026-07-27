"""Integration tests for atlas.analysis.brsr.

Uses four real TCS BRSR filings from the repository:

  bse-news-ffe33416-6ca6-4c63-ae04-f914bb97c4cc  FY2026, filed 2026-05-15
  bse-news-2e389663-765c-46b8-975a-7d07faf5c25e  FY2025, filed 2025-05-27
  bse-news-85c29641-f356-4579-95eb-3d8e9d2915c8  FY2024, filed 2024-05-08
  bse-news-bb1cd39b-eeb4-4b23-baef-a4cb402fd832  FY2023, filed 2023-06-06

Run with: pytest -m integration -v -s
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.acquisition.repository import Repository
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.analysis.brsr import ANALYZER_VERSION, analyze
from atlas.knowledge.base import KnowledgeBase

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

_FY26_ID = "bse-news-ffe33416-6ca6-4c63-ae04-f914bb97c4cc"
_FY25_ID = "bse-news-2e389663-765c-46b8-975a-7d07faf5c25e"
_FY24_ID = "bse-news-85c29641-f356-4579-95eb-3d8e9d2915c8"
_FY23_ID = "bse-news-bb1cd39b-eeb4-4b23-baef-a4cb402fd832"


@pytest.fixture(scope="module")
def tcs_root(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(
        _TCS_REPO, evidence_ids=[_FY26_ID, _FY25_ID, _FY24_ID, _FY23_ID]
    )


@pytest.fixture(scope="module")
def kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(tcs_root)
    repo = Repository(tcs_root)
    for eid in (_FY26_ID, _FY25_ID, _FY24_ID, _FY23_ID):
        entry = repo.get(eid)
        if entry is not None:
            instance.parse(entry)
    yield instance


def _facts(result: AnalysisResult, kind: FactKind) -> list:
    return [f for f in result.facts if f.kind == kind]


def _skip_if_not_parsed(kb: KnowledgeBase, eid: str) -> None:
    entry = kb.get(eid)
    if entry is None or entry.status != "ok":
        pytest.skip(f"{eid[:16]}... not parsed")


# ---------------------------------------------------------------------------
# FY2026 — primary year; should have all 15 facts, 0 warnings
# ---------------------------------------------------------------------------


class TestBRSR_FY26:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _FY26_ID)
        return analyze(_FY26_ID, kb)

    def test_kind(self, result: AnalysisResult):
        assert result.kind == "brsr"

    def test_analyzer_version(self, result: AnalysisResult):
        assert result.analyzer_version == ANALYZER_VERSION

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_no_warnings(self, result: AnalysisResult):
        assert result.warnings == [], result.warnings

    def test_fiscal_period(self, result: AnalysisResult):
        assert result.excerpts["fiscal_period"] == "2026-03-31"

    def test_fifteen_facts(self, result: AnalysisResult):
        assert len(result.facts) == 15

    # GHG
    def test_scope1_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_GHG_SCOPE1)
        assert len(facts) == 1
        assert abs(facts[0].value - 22_631.0) < 1.0

    def test_scope2_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_GHG_SCOPE2)
        assert abs(facts[0].value - 53_971.0) < 1.0

    def test_scope3_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_GHG_SCOPE3)
        assert abs(facts[0].value - 573_872.0) < 1.0

    def test_ghg_units(self, result: AnalysisResult):
        for kind in (
            FactKind.ESG_GHG_SCOPE1,
            FactKind.ESG_GHG_SCOPE2,
            FactKind.ESG_GHG_SCOPE3,
        ):
            for f in _facts(result, kind):
                assert f.unit == FactUnit.TCO2E

    def test_ghg_period(self, result: AnalysisResult):
        for kind in (
            FactKind.ESG_GHG_SCOPE1,
            FactKind.ESG_GHG_SCOPE2,
            FactKind.ESG_GHG_SCOPE3,
        ):
            for f in _facts(result, kind):
                assert f.period == "2026-03-31"

    # Scope 2 specific: FY26 market-based value is far less than location-based
    def test_scope2_is_market_based_not_location_based(self, result: AnalysisResult):
        # Location-based Scope 2 (FY26) = 318,184 tCO2e; market-based = 53,971.
        # We must extract the market-based value (from the main table, not the note).
        scope2 = _facts(result, FactKind.ESG_GHG_SCOPE2)[0].value
        assert (
            scope2 < 100_000
        ), "Expected market-based (53,971), not location-based (318,184)"

    # Energy
    def test_energy_total(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_ENERGY_TOTAL_MJ)
        assert abs(facts[0].value - 1_884_760_270.0) < 1000

    def test_energy_renewable_pct(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_ENERGY_RENEWABLE_PCT)
        assert abs(facts[0].value - 79.0) < 0.5

    # Water
    def test_water_consumed(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_WATER_CONSUMED_KL)
        assert abs(facts[0].value - 2_832_920.0) < 10

    # Waste
    def test_waste_generated(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_WASTE_GENERATED_MT)
        assert abs(facts[0].value - 8_808.4) < 5.0

    def test_waste_recovery_pct(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_WASTE_RECOVERY_PCT)
        assert abs(facts[0].value - 76.4) < 0.1

    # Workforce
    def test_headcount(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_WORKFORCE_HEADCOUNT)
        assert facts[0].value == 617_437

    def test_female_pct(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_WORKFORCE_FEMALE_PCT)
        assert abs(facts[0].value - 35.3) < 0.1

    def test_female_wage_pct(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_WORKFORCE_FEMALE_WAGE_PCT)
        assert abs(facts[0].value - 24.9) < 0.1

    def test_attrition_pct(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_WORKFORCE_ATTRITION_PCT)
        assert abs(facts[0].value - 13.7) < 0.1

    # Safety
    def test_ltifr(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_SAFETY_LTIFR)
        assert abs(facts[0].value - 0.028) < 0.001

    def test_ltifr_unit_is_none(self, result: AnalysisResult):
        assert _facts(result, FactKind.ESG_SAFETY_LTIFR)[0].unit is None

    # SBTi
    def test_sbti_scope12_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_CLIMATE_SBTI_SCOPE12_REDUCTION_PCT)
        assert facts[0].value == pytest.approx(90.0)

    def test_sbti_scope12_period(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_CLIMATE_SBTI_SCOPE12_REDUCTION_PCT)
        assert facts[0].period == "2030-03-31"

    def test_sbti_scope3_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_CLIMATE_SBTI_SCOPE3_REDUCTION_PCT)
        assert facts[0].value == pytest.approx(35.0)

    def test_sbti_scope3_period(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_CLIMATE_SBTI_SCOPE3_REDUCTION_PCT)
        assert facts[0].period == "2034-03-31"

    def test_all_yearly_facts_have_correct_period(self, result: AnalysisResult):
        yearly_kinds = {
            FactKind.ESG_GHG_SCOPE1,
            FactKind.ESG_GHG_SCOPE2,
            FactKind.ESG_GHG_SCOPE3,
            FactKind.ESG_ENERGY_TOTAL_MJ,
            FactKind.ESG_ENERGY_RENEWABLE_PCT,
            FactKind.ESG_WATER_CONSUMED_KL,
            FactKind.ESG_WASTE_GENERATED_MT,
            FactKind.ESG_WASTE_RECOVERY_PCT,
            FactKind.ESG_WORKFORCE_HEADCOUNT,
            FactKind.ESG_WORKFORCE_FEMALE_PCT,
            FactKind.ESG_WORKFORCE_FEMALE_WAGE_PCT,
            FactKind.ESG_WORKFORCE_ATTRITION_PCT,
            FactKind.ESG_SAFETY_LTIFR,
        }
        for f in result.facts:
            if f.kind in yearly_kinds:
                assert (
                    f.period == "2026-03-31"
                ), f"{f.kind}: expected 2026-03-31, got {f.period}"


# ---------------------------------------------------------------------------
# FY2025
# ---------------------------------------------------------------------------


class TestBRSR_FY25:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _FY25_ID)
        return analyze(_FY25_ID, kb)

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_no_warnings(self, result: AnalysisResult):
        assert result.warnings == [], result.warnings

    def test_fiscal_period(self, result: AnalysisResult):
        assert result.excerpts["fiscal_period"] == "2025-03-31"

    def test_fifteen_facts(self, result: AnalysisResult):
        assert len(result.facts) == 15

    def test_scope1(self, result: AnalysisResult):
        assert abs(_facts(result, FactKind.ESG_GHG_SCOPE1)[0].value - 20_494.8) < 1.0

    def test_scope2(self, result: AnalysisResult):
        assert abs(_facts(result, FactKind.ESG_GHG_SCOPE2)[0].value - 55_599.0) < 1.0

    def test_scope3(self, result: AnalysisResult):
        assert abs(_facts(result, FactKind.ESG_GHG_SCOPE3)[0].value - 523_810.0) < 1.0

    def test_scope2_less_than_fy24(self, result: AnalysisResult):
        # Scope 2 trend: FY23 117,265 → FY24 73,722 → FY25 55,599 → FY26 53,971
        assert _facts(result, FactKind.ESG_GHG_SCOPE2)[0].value < 73_722.0

    def test_energy_total(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_ENERGY_TOTAL_MJ)[0].value - 1_940_926_732.0)
            < 1000
        )

    def test_water_consumed(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WATER_CONSUMED_KL)[0].value - 2_871_784.0)
            < 10
        )

    def test_waste_generated(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WASTE_GENERATED_MT)[0].value - 9_983.0)
            < 5.0
        )

    def test_waste_recovery_56pct(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WASTE_RECOVERY_PCT)[0].value - 56.0) < 0.1
        )

    def test_headcount(self, result: AnalysisResult):
        assert _facts(result, FactKind.ESG_WORKFORCE_HEADCOUNT)[0].value == 636_833

    def test_female_wage_pct_with_asterisk(self, result: AnalysisResult):
        """FY25 BRSR has asterisk footnote on female wage line — must still extract."""
        facts = _facts(result, FactKind.ESG_WORKFORCE_FEMALE_WAGE_PCT)
        assert len(facts) == 1
        assert abs(facts[0].value - 24.8) < 0.1

    def test_attrition_pct(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WORKFORCE_ATTRITION_PCT)[0].value - 13.3)
            < 0.1
        )

    def test_ltifr(self, result: AnalysisResult):
        assert abs(_facts(result, FactKind.ESG_SAFETY_LTIFR)[0].value - 0.025) < 0.001

    def test_sbti_both_present(self, result: AnalysisResult):
        assert len(_facts(result, FactKind.ESG_CLIMATE_SBTI_SCOPE12_REDUCTION_PCT)) == 1
        assert len(_facts(result, FactKind.ESG_CLIMATE_SBTI_SCOPE3_REDUCTION_PCT)) == 1


# ---------------------------------------------------------------------------
# FY2024 — SBTi targets and waste recovery not in BRSR text (expected gaps)
# ---------------------------------------------------------------------------


class TestBRSR_FY24:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _FY24_ID)
        return analyze(_FY24_ID, kb)

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_fiscal_period(self, result: AnalysisResult):
        assert result.excerpts["fiscal_period"] == "2024-03-31"

    def test_scope1(self, result: AnalysisResult):
        assert abs(_facts(result, FactKind.ESG_GHG_SCOPE1)[0].value - 21_949.0) < 1.0

    def test_scope2(self, result: AnalysisResult):
        assert abs(_facts(result, FactKind.ESG_GHG_SCOPE2)[0].value - 73_722.0) < 1.0

    def test_scope3(self, result: AnalysisResult):
        # FY24 BRSR current year Scope 3
        assert abs(_facts(result, FactKind.ESG_GHG_SCOPE3)[0].value - 498_509.0) < 100.0

    def test_energy_total(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_ENERGY_TOTAL_MJ)[0].value - 1_709_182_976.0)
            < 1000
        )

    def test_water_consumed(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WATER_CONSUMED_KL)[0].value - 2_467_342.0)
            < 10
        )

    def test_waste_generated(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WASTE_GENERATED_MT)[0].value - 6_716.2)
            < 5.0
        )

    def test_headcount(self, result: AnalysisResult):
        assert _facts(result, FactKind.ESG_WORKFORCE_HEADCOUNT)[0].value == 631_858

    def test_female_pct(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WORKFORCE_FEMALE_PCT)[0].value - 35.6) < 0.1
        )

    def test_female_wage_pct(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WORKFORCE_FEMALE_WAGE_PCT)[0].value - 26.1)
            < 0.1
        )

    def test_attrition_pct(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WORKFORCE_ATTRITION_PCT)[0].value - 12.5)
            < 0.1
        )

    def test_ltifr(self, result: AnalysisResult):
        assert abs(_facts(result, FactKind.ESG_SAFETY_LTIFR)[0].value - 0.009) < 0.001

    def test_sbti_absent_in_fy24_brsr(self, result: AnalysisResult):
        """FY2024 BRSR does not include SBTi specific targets in text."""
        assert _facts(result, FactKind.ESG_CLIMATE_SBTI_SCOPE12_REDUCTION_PCT) == []

    def test_waste_recovery_absent_in_fy24_brsr(self, result: AnalysisResult):
        """FY2024 BRSR uses a table format for waste recovery, not a narrative %."""
        assert _facts(result, FactKind.ESG_WASTE_RECOVERY_PCT) == []

    def test_expected_warning_count(self, result: AnalysisResult):
        # waste recovery + SBTi scope12 + SBTi scope3 = 3
        assert len(result.warnings) == 3


# ---------------------------------------------------------------------------
# FY2023 — oldest year; additional gaps expected
# ---------------------------------------------------------------------------


class TestBRSR_FY23:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _FY23_ID)
        return analyze(_FY23_ID, kb)

    def test_fiscal_period(self, result: AnalysisResult):
        assert result.excerpts["fiscal_period"] == "2023-03-31"

    def test_scope1(self, result: AnalysisResult):
        assert abs(_facts(result, FactKind.ESG_GHG_SCOPE1)[0].value - 20_972.0) < 1.0

    def test_scope2(self, result: AnalysisResult):
        # FY23 Scope 2 is highest in series — before major renewable electricity shift
        assert abs(_facts(result, FactKind.ESG_GHG_SCOPE2)[0].value - 117_265.0) < 1.0

    def test_scope3(self, result: AnalysisResult):
        assert abs(_facts(result, FactKind.ESG_GHG_SCOPE3)[0].value - 366_606.0) < 100.0

    def test_energy_computed_from_renewable_plus_nonrenewable(
        self, result: AnalysisResult
    ):
        """FY23 BRSR has no total energy label (tab in label); computed from parts."""
        facts = _facts(result, FactKind.ESG_ENERGY_TOTAL_MJ)
        assert len(facts) == 1
        # 830,543,637 + 674,472,442 = 1,505,016,079
        assert abs(facts[0].value - 1_505_016_079.0) < 1000

    def test_renewable_pct_approximately_55pct(self, result: AnalysisResult):
        facts = _facts(result, FactKind.ESG_ENERGY_RENEWABLE_PCT)
        assert len(facts) == 1
        assert 50.0 <= facts[0].value <= 60.0

    def test_water_consumed(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WATER_CONSUMED_KL)[0].value - 2_082_781.0)
            < 10
        )

    def test_waste_total_suppressed(self, result: AnalysisResult):
        """FY23 construction waste anomaly triggers suppression."""
        assert _facts(result, FactKind.ESG_WASTE_GENERATED_MT) == []

    def test_waste_anomaly_warning_present(self, result: AnalysisResult):
        assert any("anomalous" in w for w in result.warnings)

    def test_headcount(self, result: AnalysisResult):
        assert _facts(result, FactKind.ESG_WORKFORCE_HEADCOUNT)[0].value == 615_721

    def test_female_pct(self, result: AnalysisResult):
        assert (
            abs(_facts(result, FactKind.ESG_WORKFORCE_FEMALE_PCT)[0].value - 35.8) < 0.1
        )

    def test_ltifr(self, result: AnalysisResult):
        # FY23 LTIFR = 0.016 (not 0.0032 which is FY22 prior year)
        assert abs(_facts(result, FactKind.ESG_SAFETY_LTIFR)[0].value - 0.016) < 0.002

    def test_scope2_trend_highest_in_series(self, result: AnalysisResult):
        """Scope 2 FY23 > FY24 confirms the renewable energy shift narrative."""
        assert _facts(result, FactKind.ESG_GHG_SCOPE2)[0].value > 100_000.0

    def test_all_ghg_facts_have_period_2023(self, result: AnalysisResult):
        for kind in (
            FactKind.ESG_GHG_SCOPE1,
            FactKind.ESG_GHG_SCOPE2,
            FactKind.ESG_GHG_SCOPE3,
        ):
            for f in _facts(result, kind):
                assert f.period == "2023-03-31"


# ---------------------------------------------------------------------------
# Cross-year trend assertions
# ---------------------------------------------------------------------------


class TestCrossYearTrends:
    @pytest.fixture(scope="class")
    def results(self, kb: KnowledgeBase) -> dict[str, AnalysisResult]:
        out = {}
        for label, eid in [
            ("FY26", _FY26_ID),
            ("FY25", _FY25_ID),
            ("FY24", _FY24_ID),
            ("FY23", _FY23_ID),
        ]:
            entry = kb.get(eid)
            if entry is not None and entry.status == "ok":
                out[label] = analyze(eid, kb)
        return out

    def _get(self, results: dict, label: str, kind: FactKind) -> float | None:
        r = results.get(label)
        if r is None:
            return None
        facts = [f for f in r.facts if f.kind == kind]
        return facts[0].value if facts else None

    def test_scope2_decreasing_trend(self, results: dict):
        """Scope 2 must strictly decrease across all four years (renewable shift)."""
        s2 = [
            self._get(results, y, FactKind.ESG_GHG_SCOPE2)
            for y in ("FY23", "FY24", "FY25", "FY26")
        ]
        s2 = [v for v in s2 if v is not None]
        if len(s2) >= 2:
            for a, b in zip(s2, s2[1:]):
                assert a > b, f"Scope 2 not decreasing: {a} -> {b}"

    def test_renewable_pct_increasing_trend(self, results: dict):
        """Renewable energy % should increase as TCS added renewable contracts."""
        pcts = [
            self._get(results, y, FactKind.ESG_ENERGY_RENEWABLE_PCT)
            for y in ("FY23", "FY24", "FY25", "FY26")
        ]
        pcts = [v for v in pcts if v is not None]
        if len(pcts) >= 2:
            assert (
                pcts[-1] >= pcts[0]
            ), "Renewable % should be at least as high as earliest year"

    def test_scope2_fy26_less_than_half_of_fy23(self, results: dict):
        """FY26 market-based Scope 2 should be <50% of FY23 Scope 2 (renewable shift)."""
        s2_fy23 = self._get(results, "FY23", FactKind.ESG_GHG_SCOPE2)
        s2_fy26 = self._get(results, "FY26", FactKind.ESG_GHG_SCOPE2)
        if s2_fy23 and s2_fy26:
            assert (
                s2_fy26 < s2_fy23 * 0.5
            ), f"Expected FY26 Scope 2 ({s2_fy26}) to be less than half of FY23 ({s2_fy23})"

    def test_scope3_dominates_total_ghg_in_fy26(self, results: dict):
        """Scope 3 (employee travel + commuting) should far exceed Scope 1+2."""
        if "FY26" in results:
            r = results["FY26"]
            s1 = self._get(results, "FY26", FactKind.ESG_GHG_SCOPE1) or 0
            s2 = self._get(results, "FY26", FactKind.ESG_GHG_SCOPE2) or 0
            s3 = self._get(results, "FY26", FactKind.ESG_GHG_SCOPE3) or 0
            assert (
                s3 > (s1 + s2) * 5
            ), "Scope 3 should be >5× Scope 1+2 for a software company"
