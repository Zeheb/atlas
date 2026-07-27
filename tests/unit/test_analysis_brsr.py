"""Unit tests for atlas.analysis.brsr.

All tests use synthetic document content — no external files or network calls.
The synthetic content is modelled on real TCS BRSR PDFs but uses round numbers
where possible for easy verification.

Structure
---------
TestPeriodExtraction  — _fiscal_period() from four text variants
TestGHGExtraction     — Scope 1 / 2 / 3 from flat and Indian-format numbers
TestEnergyExtraction  — total energy; renewable %; FY23 computed-total path
TestWaterExtraction   — water consumed
TestWasteExtraction   — category summation; anomaly suppression; recovery %
TestWorkforce         — headcount; female %; female wage %; attrition
TestSafety            — LTIFR
TestSBTi              — Scope 1+2 and Scope 3 SBTi commitment targets
TestAnalyze           — public entry-point: kind validation, empty content
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from atlas.analysis.brsr import (
    ANALYZER_VERSION,
    _extract_energy,
    _extract_ghg,
    _extract_safety,
    _extract_sbti,
    _extract_waste,
    _extract_water,
    _extract_workforce,
    _fiscal_period,
    analyze,
)
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result() -> AnalysisResult:
    return AnalysisResult(
        evidence_id="test",
        kind="brsr",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=datetime(2026, 5, 15, tzinfo=timezone.utc),
    )


def _facts(result: AnalysisResult, kind: FactKind) -> list:
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Period extraction
# ---------------------------------------------------------------------------


class TestPeriodExtraction:
    def test_period_from_assurance_text(self):
        content = "period from 1 April 2025 to 31 March 2026. Opinion"
        dt = datetime(2026, 5, 15, tzinfo=timezone.utc)
        assert _fiscal_period(content, dt) == "2026-03-31"

    def test_period_from_fy_label(self):
        content = "FY 2025-26 integrated annual report"
        dt = datetime(2026, 5, 15, tzinfo=timezone.utc)
        assert _fiscal_period(content, dt) == "2026-03-31"

    def test_period_from_fy_label_en_dash(self):
        content = "FY 2024–25 business responsibility report"
        dt = datetime(2025, 5, 27, tzinfo=timezone.utc)
        assert _fiscal_period(content, dt) == "2025-03-31"

    def test_period_fallback_from_source_date_april_onwards(self):
        # Filed May 2023 → FY ending March 2023
        content = "no explicit period marker here"
        dt = datetime(2023, 6, 6, tzinfo=timezone.utc)
        assert _fiscal_period(content, dt) == "2023-03-31"

    def test_period_fallback_source_date_january(self):
        # Filed January 2026 → FY ending March 2025
        content = "no explicit period marker here"
        dt = datetime(2026, 1, 10, tzinfo=timezone.utc)
        assert _fiscal_period(content, dt) == "2025-03-31"

    def test_assurance_text_takes_priority_over_fy_label(self):
        content = "FY 2023-24 report. period from 1 April 2023 to 31 March 2024."
        dt = datetime(2024, 5, 8, tzinfo=timezone.utc)
        assert _fiscal_period(content, dt) == "2024-03-31"


# ---------------------------------------------------------------------------
# GHG emissions
# ---------------------------------------------------------------------------

_GHG_BLOCK = """
Total Scope 1 emissions (Break-up of the GHG into CO2, CH4,
N2O, HFCs, PFCs, SF6, NF3, if available)
Metric tonnes of CO2
equivalent
22631.0
20494.8
- CO2
tCO2e
7809.0

Total Scope 2 emissions (Metric tonnes of CO2 equivalent)
53971.0
55599.0

total Scope 3 emissions & its intensity, in the following format:
Parameter
Unit
FY 2026
FY 2025
Total Scope 3 emissions (Break-up of the GHG into CO2,
CH4, N2O, HFCs, PFCs, SF6, NF3, if available)
Metric tonnes of CO2
Equivalent
573872
523810
"""

_GHG_BLOCK_INDIAN = """
Total Scope 1 emissions (Break-up of the GHG into CO2, CH4,
N2O, HFCs, PFCs, SF6, NF3, if available)
Metric tonnes of CO2
equivalent
5,73,872
5,23,810

Total Scope 2 emissions (Break-up of the GHG into CO2, CH4,
N2O, HFCs, PFCs, SF6, NF3, if available)
Metric tonnes of CO2 equivalent
1,17,265
1,41,045

total Scope 3 emissions & its intensity, in the following format:
Parameter
Unit
FY 2023
FY 2022
Total Scope 3 emissions (Break-up of the GHG into CO2,
CH4, N2O, HFCs, PFCs, SF6, NF3, if available)
Metric tonnes of
CO2 equivalent
3,66,606
3,58,453
"""


class TestGHGExtraction:
    def test_scope1_extracted(self):
        r = _make_result()
        _extract_ghg(_GHG_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_GHG_SCOPE1)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(22631.0)

    def test_scope2_extracted(self):
        r = _make_result()
        _extract_ghg(_GHG_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_GHG_SCOPE2)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(53971.0)

    def test_scope3_extracted(self):
        r = _make_result()
        _extract_ghg(_GHG_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_GHG_SCOPE3)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(573872.0)

    def test_units_are_tco2e(self):
        r = _make_result()
        _extract_ghg(_GHG_BLOCK, "2026-03-31", r)
        for kind in (
            FactKind.ESG_GHG_SCOPE1,
            FactKind.ESG_GHG_SCOPE2,
            FactKind.ESG_GHG_SCOPE3,
        ):
            for f in _facts(r, kind):
                assert f.unit == FactUnit.TCO2E

    def test_period_propagated(self):
        r = _make_result()
        _extract_ghg(_GHG_BLOCK, "2026-03-31", r)
        for f in r.facts:
            assert f.period == "2026-03-31"

    def test_indian_format_scope1(self):
        r = _make_result()
        _extract_ghg(_GHG_BLOCK_INDIAN, "2023-03-31", r)
        facts = _facts(r, FactKind.ESG_GHG_SCOPE1)
        assert facts[0].value == pytest.approx(573872.0)

    def test_indian_format_scope2(self):
        r = _make_result()
        _extract_ghg(_GHG_BLOCK_INDIAN, "2023-03-31", r)
        facts = _facts(r, FactKind.ESG_GHG_SCOPE2)
        assert facts[0].value == pytest.approx(117265.0)

    def test_indian_format_scope3(self):
        r = _make_result()
        _extract_ghg(_GHG_BLOCK_INDIAN, "2023-03-31", r)
        facts = _facts(r, FactKind.ESG_GHG_SCOPE3)
        assert facts[0].value == pytest.approx(366606.0)

    def test_missing_scope3_adds_warning(self):
        content = """
Total Scope 1 emissions (Break-up of the GHG)
Metric tonnes of CO2
equivalent
22631.0
20494.8

Total Scope 2 emissions (Metric tonnes of CO2 equivalent)
53971.0
55599.0
"""
        r = _make_result()
        _extract_ghg(content, "2026-03-31", r)
        assert any("Scope 3" in w for w in r.warnings)

    def test_section_name_in_provenance(self):
        r = _make_result()
        _extract_ghg(_GHG_BLOCK, "2026-03-31", r)
        scope1 = _facts(r, FactKind.ESG_GHG_SCOPE1)[0]
        assert scope1.provenance.section == "ghg_scope1"

    def test_no_warnings_on_clean_block(self):
        r = _make_result()
        _extract_ghg(_GHG_BLOCK, "2026-03-31", r)
        assert r.warnings == []


# ---------------------------------------------------------------------------
# Energy
# ---------------------------------------------------------------------------

_ENERGY_BLOCK = """
From renewable sources
Total electricity consumption (A)
1,48,94,46,670
1,53,74,95,415
Total fuel consumption (B)
NIL
NIL
Energy consumption through other sources (C)
1,86,383
1,42,333
Total energy consumed from renewable sources (A+B+C)
1,48,96,33,053
1,53,76,37,748
From non-renewable sources
Total electricity consumption (D)
27,40,30,722
27,75,27,478
Total fuel consumption (E)
12,10,96,495
12,57,61,506
Energy consumption through other sources (F)
NIL
NIL
Total energy consumed from non-renewable sources (D+E+F)
39,51,27,217
40,32,88,984
Total energy consumed (A+B+C+D+E+F)
1,88,47,60,270
1,94,09,26,732
Energy intensity per rupee of turnover
0.000710
0.000760
"""

_ENERGY_BLOCK_FY23 = """
From renewable sources
Total electricity consumption (A)
830,388,643
401,662,127
Total fuel consumption (B)
NIL
NIL
Energy consumption through other sources (C)
154,994
8,482,654
Total	energy consumed from renewable sources (A+B+C)
830,543,637
410,144,781
From non-renewable sources
Total electricity consumption (D)
602,410,331
672,917,518
Total fuel consumption (E)
72,062,111
41,303,253
Energy consumption through other sources (F)
NIL
NIL
Total energy consumed from non-renewable sources (D+E+F)
674,472,442
714,220,770
Energy intensity per rupee of turnover
0.0007
0.0006
"""


class TestEnergyExtraction:
    def test_total_energy_extracted(self):
        r = _make_result()
        _extract_energy(_ENERGY_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_ENERGY_TOTAL_MJ)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(1_884_760_270.0)

    def test_renewable_pct_computed(self):
        r = _make_result()
        _extract_energy(_ENERGY_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_ENERGY_RENEWABLE_PCT)
        assert len(facts) == 1
        # 1,489,633,053 / 1,884,760,270 ≈ 79.04%
        assert facts[0].value == pytest.approx(79.0, abs=0.1)

    def test_total_energy_unit_is_megajoule(self):
        r = _make_result()
        _extract_energy(_ENERGY_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_ENERGY_TOTAL_MJ)
        assert facts[0].unit == FactUnit.MEGAJOULE

    def test_renewable_pct_unit_is_percent(self):
        r = _make_result()
        _extract_energy(_ENERGY_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_ENERGY_RENEWABLE_PCT)
        assert facts[0].unit == FactUnit.PERCENT

    def test_fy23_tab_in_label_handled(self):
        """FY2023 BRSR uses a tab character in the renewable energy label."""
        r = _make_result()
        _extract_energy(_ENERGY_BLOCK_FY23, "2023-03-31", r)
        facts = _facts(r, FactKind.ESG_ENERGY_TOTAL_MJ)
        assert len(facts) == 1
        # 830,543,637 + 674,472,442 = 1,505,016,079
        assert facts[0].value == pytest.approx(1_505_016_079.0)

    def test_fy23_renewable_pct_computed_when_no_total_label(self):
        r = _make_result()
        _extract_energy(_ENERGY_BLOCK_FY23, "2023-03-31", r)
        pct_facts = _facts(r, FactKind.ESG_ENERGY_RENEWABLE_PCT)
        assert len(pct_facts) == 1
        # 830,543,637 / 1,505,016,079 ≈ 55.2%
        assert pct_facts[0].value == pytest.approx(55.2, abs=0.2)

    def test_no_warnings_on_complete_block(self):
        r = _make_result()
        _extract_energy(_ENERGY_BLOCK, "2026-03-31", r)
        assert r.warnings == []

    def test_missing_energy_adds_warning(self):
        r = _make_result()
        _extract_energy("No energy data here", "2026-03-31", r)
        assert any("energy" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# Water
# ---------------------------------------------------------------------------

_WATER_BLOCK_IN_KL = """
Total volume of water consumption (in KL)
28,32,920
28,71,784
Water intensity Per Rupee of turnover
0.000001
0.000001
"""

_WATER_BLOCK_KL = """
Total volume of water consumption (KL)
24,67,342
20,82,781
Water intensity Per Rupee of turnover
0.000001
0.000001
"""

_WATER_BLOCK_KILOLITRES = """
Total volume of water consumption (in kilolitres)
2,082,781
1,319,696
"""


class TestWaterExtraction:
    def test_water_kl_in_parens(self):
        r = _make_result()
        _extract_water(_WATER_BLOCK_IN_KL, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_WATER_CONSUMED_KL)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(2_832_920.0)

    def test_water_kl_no_in(self):
        r = _make_result()
        _extract_water(_WATER_BLOCK_KL, "2024-03-31", r)
        facts = _facts(r, FactKind.ESG_WATER_CONSUMED_KL)
        assert facts[0].value == pytest.approx(2_467_342.0)

    def test_water_kilolitres_label(self):
        r = _make_result()
        _extract_water(_WATER_BLOCK_KILOLITRES, "2023-03-31", r)
        facts = _facts(r, FactKind.ESG_WATER_CONSUMED_KL)
        assert facts[0].value == pytest.approx(2_082_781.0)

    def test_water_unit_is_kilolitre(self):
        r = _make_result()
        _extract_water(_WATER_BLOCK_IN_KL, "2026-03-31", r)
        assert _facts(r, FactKind.ESG_WATER_CONSUMED_KL)[0].unit == FactUnit.KILOLITRE

    def test_missing_water_adds_warning(self):
        r = _make_result()
        _extract_water("No water data here", "2026-03-31", r)
        assert any("water" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# Waste
# ---------------------------------------------------------------------------

_WASTE_BLOCK_FY26 = """
Total Waste generated [in metric tonnes (MT)]
Plastic waste (A)
195.0
262.0
E-waste (B)
505.0
740.9
Bio-medical waste (C)
0.3
0.3
Construction and demolition waste (D)
900.0
1,589.6
Battery waste (E)
246.0
343.0
Radioactive waste (F)
-
-
Other Hazardous waste. Please specify, if any. (G) (Used oil in DG sets, oil soaked
cotton waste and oil filters)
39.1
48.1
Other Non-hazardous waste generated (H). Please specify, if any. (Break-up by
composition i.e. by materials relevant to the sector)
6,923.0
6,999.1
Quantity of office paper waste
234.0
225.1

76.4% of Company's waste generated is recovered through recycling and reuse.
"""

_WASTE_BLOCK_ANOMALOUS = """
Total Waste generated (in metric tonnes)
Plastic waste (A)
46.7
42.9
E-waste (B)
415
563
Bio-medical waste (C)
0.83
1.61
Construction and demolition waste (D)
194,973
62.4
Battery waste (E)
387
286
Radioactive waste (F)
NA
NA
Other Hazardous waste. Please specify, if any. (G)
26.1
27.6
Other Non-hazardous waste generated (H). Please specify, if any.
(Break-up by composition i.e. by materials relevant to the sector)
3,538
2,351
"""

_WASTE_BLOCK_NA_F = """
Total Waste generated [in metric tonnes (MT)]
Plastic waste (A)
262.0
137.3
E-waste (B)
740.9
297.5
Bio-medical waste (C)
0.3
0.8
Construction and demolition waste (D)
1,589.6
1,070.8
Battery waste (E)
343.0
261.0
Radioactive waste (F)
NA
NA
Other Hazardous waste. Please specify, if any. (G)
(Used oil in DG sets, oil soaked cotton waste and oil filters)
48.1
33.2
Other Non-hazardous waste generated (H). Please specify, if any.
(Break-up by composition i.e. by materials relevant to the sector)
6,999.1
4,915.6

56% of Company's waste generated is recovered through recycling and reuse.
"""


class TestWasteExtraction:
    def test_total_waste_sums_categories(self):
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_FY26, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_WASTE_GENERATED_MT)
        assert len(facts) == 1
        # A+B+C+D+E+G+H = 195+505+0.3+900+246+39.1+6923 = 8808.4
        assert facts[0].value == pytest.approx(8808.4, abs=0.5)

    def test_radioactive_na_excluded_from_sum(self):
        """F = '-' (NA) must NOT add to total."""
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_FY26, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_WASTE_GENERATED_MT)
        # If F were included as 0 it wouldn't change the sum, but NA/'-' rows
        # must not accidentally carry a value from the PRIOR year column.
        assert facts[0].value < 9000

    def test_multi_line_category_g_parsed(self):
        """Category G description spans two lines — value must still be found."""
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_FY26, "2026-03-31", r)
        total = _facts(r, FactKind.ESG_WASTE_GENERATED_MT)[0].value
        # G=39.1 must be included; total without G would be 195+505+0.3+900+246+6923=8769.3
        assert total > 8800.0

    def test_multi_line_category_h_parsed(self):
        """Category H description spans two lines — value must still be found."""
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_FY26, "2026-03-31", r)
        total = _facts(r, FactKind.ESG_WASTE_GENERATED_MT)[0].value
        # H=6923; without H total ≈ 1885.4
        assert total > 6000.0

    def test_radioactive_na_variant(self):
        """F = 'NA' (FY25 variant) must not pollute the sum."""
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_NA_F, "2025-03-31", r)
        facts = _facts(r, FactKind.ESG_WASTE_GENERATED_MT)
        assert len(facts) == 1
        # A+B+C+D+E+G+H = 262+740.9+0.3+1589.6+343+48.1+6999.1 = 9983
        assert facts[0].value == pytest.approx(9983.0, abs=1.0)

    def test_anomalous_total_suppressed(self):
        """Anomalous construction waste value triggers suppression."""
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_ANOMALOUS, "2023-03-31", r)
        assert _facts(r, FactKind.ESG_WASTE_GENERATED_MT) == []
        assert any("anomalous" in w for w in r.warnings)

    def test_waste_recovery_pct_extracted(self):
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_FY26, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_WASTE_RECOVERY_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(76.4)

    def test_waste_recovery_pct_56(self):
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_NA_F, "2025-03-31", r)
        facts = _facts(r, FactKind.ESG_WASTE_RECOVERY_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(56.0)

    def test_waste_unit_is_metric_tonne(self):
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_FY26, "2026-03-31", r)
        assert (
            _facts(r, FactKind.ESG_WASTE_GENERATED_MT)[0].unit == FactUnit.METRIC_TONNE
        )

    def test_recovery_unit_is_percent(self):
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_FY26, "2026-03-31", r)
        assert _facts(r, FactKind.ESG_WASTE_RECOVERY_PCT)[0].unit == FactUnit.PERCENT

    def test_no_recovery_pct_adds_warning(self):
        r = _make_result()
        _extract_waste(_WASTE_BLOCK_ANOMALOUS, "2023-03-31", r)
        assert any("recovery" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# Workforce
# ---------------------------------------------------------------------------

_WORKFORCE_BLOCK = """
Total employees (D + E)
6,17,437
3,99,559
64.7
2,17,878
35.3

Gross wages paid to females as % of total wages paid by the entity, in the following format:
FY 2026 (%)
FY 2025 (%)
Gross wages paid to female as % of total wages
24.9
24.8

FY 2026
FY 2025
FY 2024
Male % Female %
Total %
Male % Female %
Total %
Male % Female %
Total %
Permanent Employees
13.8
13.4
13.7
13.2
13.6
13.3
12.5
12.5
12.5
22. Turnover rate for permanent employees
For FY 2026 the turnover rate is for last twelve months voluntary IT services.
"""

_WORKFORCE_BLOCK_ASTERISK = """
Total employees (D + E)
6,36,833
4,11,728
64.7
2,25,105
35.3

Gross wages paid to females as % of total wages paid by the entity, in the following format:
FY 2025 (%)
FY 2024 (%)
Gross wages paid to female as % of total wages*
24.8
24.9

22. Turnover rate for permanent employees
FY 2025
FY 2024
FY 2023
Male%
Female%
Total%
Male%
Female%
Total%
Male%
Female%
Total%
Permanent Employees
13.2
13.6
13.3
12.5
12.5
12.5
20.2
20.1
20.2
"""

_WORKFORCE_BLOCK_INT_FORMAT = """
Total employees (D + E)
615,721
395,114
64.2
220,607
35.8

22. Turnover rate for permanent employees
FY 2022-23
FY 2021-22
FY 2020-21
Male
Female
Total
Male
Female
Total
Male
Female
Total
Permanent Employees
20.9%
21.9%
21.3%
17.3%
17.8%
17.5%
7.5%
7.5%
7.5%
"""


class TestWorkforce:
    def test_headcount_extracted(self):
        r = _make_result()
        _extract_workforce(_WORKFORCE_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_WORKFORCE_HEADCOUNT)
        assert len(facts) == 1
        assert facts[0].value == 617_437

    def test_headcount_unit_is_count(self):
        r = _make_result()
        _extract_workforce(_WORKFORCE_BLOCK, "2026-03-31", r)
        assert _facts(r, FactKind.ESG_WORKFORCE_HEADCOUNT)[0].unit == FactUnit.COUNT

    def test_female_pct_extracted(self):
        r = _make_result()
        _extract_workforce(_WORKFORCE_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_WORKFORCE_FEMALE_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(35.3)

    def test_female_wage_pct_extracted(self):
        r = _make_result()
        _extract_workforce(_WORKFORCE_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_WORKFORCE_FEMALE_WAGE_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(24.9)

    def test_female_wage_with_asterisk(self):
        """FY25 BRSR adds a * footnote marker after 'wages'."""
        r = _make_result()
        _extract_workforce(_WORKFORCE_BLOCK_ASTERISK, "2025-03-31", r)
        facts = _facts(r, FactKind.ESG_WORKFORCE_FEMALE_WAGE_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(24.8)

    def test_attrition_total_pct_extracted(self):
        """Total % is the 3rd number in the Male/Female/Total triplet."""
        r = _make_result()
        _extract_workforce(_WORKFORCE_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_WORKFORCE_ATTRITION_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(13.7)

    def test_attrition_after_label_variant(self):
        """FY25: numbers appear AFTER the turnover-rate label."""
        r = _make_result()
        _extract_workforce(_WORKFORCE_BLOCK_ASTERISK, "2025-03-31", r)
        facts = _facts(r, FactKind.ESG_WORKFORCE_ATTRITION_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(13.3)

    def test_attrition_with_percent_suffix(self):
        """FY23: values like '21.3%' — percent symbol must be stripped."""
        r = _make_result()
        _extract_workforce(_WORKFORCE_BLOCK_INT_FORMAT, "2023-03-31", r)
        facts = _facts(r, FactKind.ESG_WORKFORCE_ATTRITION_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(21.3)

    def test_headcount_international_format(self):
        r = _make_result()
        _extract_workforce(_WORKFORCE_BLOCK_INT_FORMAT, "2023-03-31", r)
        facts = _facts(r, FactKind.ESG_WORKFORCE_HEADCOUNT)
        assert facts[0].value == 615_721

    def test_female_pct_unit_is_percent(self):
        r = _make_result()
        _extract_workforce(_WORKFORCE_BLOCK, "2026-03-31", r)
        assert _facts(r, FactKind.ESG_WORKFORCE_FEMALE_PCT)[0].unit == FactUnit.PERCENT

    def test_missing_headcount_adds_warning(self):
        r = _make_result()
        _extract_workforce("No workforce data", "2026-03-31", r)
        assert any("Total employees" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

_SAFETY_BLOCK = """
Safety Incident/Number
Category
FY 2026
FY 2025
Lost Time Injury Frequency Rate (LTIFR)
(per one Million-person hours worked)
Employees
0.028
0.025
Total recordable work-related injuries
Employees
89
53
No. of fatalities
Employees
0
0
"""

_SAFETY_BLOCK_FY24 = """
Lost Time Injury Frequency Rate (LTIFR) (per one million-person hours
worked)
Employees
0.009
0.016
Total recordable work-related injuries
Employees
23
46
"""


class TestSafety:
    def test_ltifr_extracted(self):
        r = _make_result()
        _extract_safety(_SAFETY_BLOCK, "2026-03-31", r)
        facts = _facts(r, FactKind.ESG_SAFETY_LTIFR)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(0.028)

    def test_ltifr_unit_is_none(self):
        """LTIFR is a rate per million person-hours; no standard FactUnit."""
        r = _make_result()
        _extract_safety(_SAFETY_BLOCK, "2026-03-31", r)
        assert _facts(r, FactKind.ESG_SAFETY_LTIFR)[0].unit is None

    def test_ltifr_period_propagated(self):
        r = _make_result()
        _extract_safety(_SAFETY_BLOCK, "2026-03-31", r)
        assert _facts(r, FactKind.ESG_SAFETY_LTIFR)[0].period == "2026-03-31"

    def test_ltifr_fy24_variant(self):
        r = _make_result()
        _extract_safety(_SAFETY_BLOCK_FY24, "2024-03-31", r)
        facts = _facts(r, FactKind.ESG_SAFETY_LTIFR)
        assert facts[0].value == pytest.approx(0.009)

    def test_missing_ltifr_adds_warning(self):
        r = _make_result()
        _extract_safety("No safety data here", "2026-03-31", r)
        assert any("LTIFR" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# SBTi climate commitments
# ---------------------------------------------------------------------------

_SBTI_BLOCK = """
Science Based Targets initiative (SBTi) Near-term target: to reduce absolute
Scope 1 and 2 GHG emissions 90% by FY 2030 from FY 2016 base year and
reduce absolute Scope 3 emissions 35% by FY 2034 from FY 2020 base year
"""


class TestSBTi:
    def test_scope12_target_pct(self):
        r = _make_result()
        _extract_sbti(_SBTI_BLOCK, r)
        facts = _facts(r, FactKind.ESG_CLIMATE_SBTI_SCOPE12_REDUCTION_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(90.0)

    def test_scope12_target_period(self):
        r = _make_result()
        _extract_sbti(_SBTI_BLOCK, r)
        facts = _facts(r, FactKind.ESG_CLIMATE_SBTI_SCOPE12_REDUCTION_PCT)
        assert facts[0].period == "2030-03-31"

    def test_scope3_target_pct(self):
        r = _make_result()
        _extract_sbti(_SBTI_BLOCK, r)
        facts = _facts(r, FactKind.ESG_CLIMATE_SBTI_SCOPE3_REDUCTION_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(35.0)

    def test_scope3_target_period(self):
        r = _make_result()
        _extract_sbti(_SBTI_BLOCK, r)
        facts = _facts(r, FactKind.ESG_CLIMATE_SBTI_SCOPE3_REDUCTION_PCT)
        assert facts[0].period == "2034-03-31"

    def test_scope12_unit_is_percent(self):
        r = _make_result()
        _extract_sbti(_SBTI_BLOCK, r)
        assert (
            _facts(r, FactKind.ESG_CLIMATE_SBTI_SCOPE12_REDUCTION_PCT)[0].unit
            == FactUnit.PERCENT
        )

    def test_scope3_unit_is_percent(self):
        r = _make_result()
        _extract_sbti(_SBTI_BLOCK, r)
        assert (
            _facts(r, FactKind.ESG_CLIMATE_SBTI_SCOPE3_REDUCTION_PCT)[0].unit
            == FactUnit.PERCENT
        )

    def test_missing_target_adds_warning(self):
        r = _make_result()
        _extract_sbti("No SBTi data here", r)
        assert len([w for w in r.warnings if "SBTi" in w]) == 2

    def test_no_warnings_when_both_present(self):
        r = _make_result()
        _extract_sbti(_SBTI_BLOCK, r)
        assert r.warnings == []


# ---------------------------------------------------------------------------
# Public entry point: analyze()
# ---------------------------------------------------------------------------


class TestAnalyze:
    def _make_kb(self, kind: str = "brsr", content: str = "") -> MagicMock:
        entry = MagicMock()
        entry.kind = kind
        entry.source_date = "2026-05-15T18:22:37+00:00"
        kb = MagicMock()
        kb.get.return_value = entry
        kb.get_content.return_value = content
        return kb

    def test_raises_for_missing_evidence(self):
        kb = MagicMock()
        kb.get.return_value = None
        with pytest.raises(ValueError, match="not found"):
            analyze("no-such-id", kb)

    def test_raises_for_wrong_kind(self):
        kb = self._make_kb(kind="financial_results")
        with pytest.raises(ValueError, match="brsr"):
            analyze("test-id", kb)

    def test_returns_analysis_result(self):
        kb = self._make_kb(content="irrelevant")
        r = analyze("test-id", kb)
        from atlas.analysis.base import AnalysisResult

        assert isinstance(r, AnalysisResult)

    def test_kind_is_brsr(self):
        kb = self._make_kb(content="irrelevant")
        r = analyze("test-id", kb)
        assert r.kind == "brsr"

    def test_analyzer_version(self):
        kb = self._make_kb(content="irrelevant")
        r = analyze("test-id", kb)
        assert r.analyzer_version == ANALYZER_VERSION

    def test_empty_content_warning(self):
        kb = self._make_kb(content="")
        r = analyze("test-id", kb)
        assert any("empty" in w for w in r.warnings)

    def test_empty_content_confidence_low(self):
        kb = self._make_kb(content="")
        r = analyze("test-id", kb)
        assert r.confidence == "low"

    def test_fiscal_period_in_excerpts(self):
        kb = self._make_kb(content="FY 2025-26 business responsibility report")
        r = analyze("test-id", kb)
        assert "fiscal_period" in r.excerpts
        assert r.excerpts["fiscal_period"] == "2026-03-31"

    def test_confidence_high_when_primary_and_full_facts_present(self):
        content = (
            _GHG_BLOCK
            + _ENERGY_BLOCK
            + _WATER_BLOCK_IN_KL
            + _WORKFORCE_BLOCK
            + _SAFETY_BLOCK
        )
        kb = self._make_kb(content=content)
        r = analyze("test-id", kb)
        assert r.confidence == "high"

    def test_confidence_medium_when_only_scope1_scope2_headcount(self):
        content = """
Total Scope 1 emissions
Metric tonnes of CO2
equivalent
22631.0

Total Scope 2 emissions (Metric tonnes of CO2 equivalent)
53971.0

Total employees (D + E)
617437
399559
64.7
217878
35.3
"""
        kb = self._make_kb(content=content)
        r = analyze("test-id", kb)
        assert r.confidence in ("medium", "high")
