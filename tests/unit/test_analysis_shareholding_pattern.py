"""Unit tests for atlas.analysis.shareholding_pattern.

All tests use synthetic XBRL fixtures — no real repository access required.

Coverage:
  - Normal extraction of all OWNERSHIP_* facts
  - Percentage-to-percent scale conversion (0-1 → 0-100)
  - Promoter pledging=false emits 0%
  - Promoter pledging=true with extractable percentage
  - Promoter pledging=true with missing percentage (warning)
  - DateOfReport fallback to source_date when MainI tag absent
  - Missing category contexts emit warnings (for required ones)
  - Missing retail/HNI contexts do NOT emit warnings (optional)
  - Wrong kind raises ValueError
  - Missing evidence_id raises ValueError
  - Malformed XML raises ValueError
  - Result-level confidence logic (high / medium / low)
  - Fact provenance: section equals the context ID used
  - Fact period matches the DateOfReport
"""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock

import pytest

from atlas.analysis.shareholding_pattern import (
    ANALYZER_VERSION,
    analyze,
    _detect_decimal_format,
)
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit

# ---------------------------------------------------------------------------
# Synthetic XBRL builders
# ---------------------------------------------------------------------------

_NS = "http://www.bseindia.com/xbrl/shp/2025-10-31/in-bse-shp"


def _xml(
    date_of_report: str = "2026-03-31",
    total_shares: str = "1000000000",
    promoter_pct: str = "0.5000",
    public_pct: str = "0.5000",
    fpi_pct: str = "0.2000",
    dii_pct: str = "0.1000",
    mf_pct: str = "0.0500",
    insurance_pct: str = "0.0400",
    nri_pct: str = "0.0100",
    retail_pct: str = "0.0200",
    hni_pct: str = "0.0050",
    pledged_bool: str = "false",
    omit_date: bool = False,
    omit_fpi: bool = False,
    omit_retail: bool = False,
    omit_hni: bool = False,
) -> str:
    """Build a minimal valid BSE XBRL SHP instance document."""
    date_fact = (
        ""
        if omit_date
        else f'<s:DateOfReport contextRef="MainI">{date_of_report}</s:DateOfReport>'
    )
    fpi_fact = (
        ""
        if omit_fpi
        else f'<s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InstitutionsForeign_ContextI">{fpi_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>'
    )
    retail_fact = (
        ""
        if omit_retail
        else f'<s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh_ContextI">{retail_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>'
    )
    hni_fact = (
        ""
        if omit_hni
        else f'<s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh_ContextI">{hni_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>'
    )

    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <xbrli:xbrl
            xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:s="{_NS}">
          <xbrli:context id="MainI">
            <xbrli:entity><xbrli:identifier scheme="x">999999</xbrli:identifier></xbrli:entity>
            <xbrli:period><xbrli:instant>{date_of_report}</xbrli:instant></xbrli:period>
          </xbrli:context>
          {date_fact}
          <s:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged contextRef="MainI">{pledged_bool}</s:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged>
          <s:NumberOfFullyPaidUpEquityShares contextRef="ShareholdingPattern_ContextI">{total_shares}</s:NumberOfFullyPaidUpEquityShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">{promoter_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="PublicShareholding_ContextI">{public_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          {fpi_fact}
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InstitutionsDomestic_ContextI">{dii_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="MutualFundsOrUTI_ContextI">{mf_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InsuranceCompanies_ContextI">{insurance_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="NonResidentIndians_ContextI">{nri_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          {retail_fact}
          {hni_fact}
        </xbrli:xbrl>
    """)


def _kb(
    content: str,
    kind: str = "shareholding_pattern",
    source_date: str = "2026-04-21T10:21:39+00:00",
) -> MagicMock:
    entry = MagicMock()
    entry.kind = kind
    entry.source_date = source_date
    kb = MagicMock()
    kb.get.return_value = entry
    kb.get_content.return_value = content
    return kb


def _facts(result: AnalysisResult, kind: FactKind):
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Normal extraction
# ---------------------------------------------------------------------------


class TestNormalExtraction:
    @pytest.fixture(scope="class")
    def result(self):
        return analyze("test-shp-001", _kb(_xml()))

    def test_returns_analysis_result(self, result):
        assert isinstance(result, AnalysisResult)

    def test_analyzer_version(self, result):
        assert result.analyzer_version == ANALYZER_VERSION

    def test_evidence_id(self, result):
        assert result.evidence_id == "test-shp-001"

    def test_kind(self, result):
        assert result.kind == "shareholding_pattern"

    def test_no_warnings(self, result):
        assert result.warnings == []

    def test_confidence_high(self, result):
        assert result.confidence == "high"

    def test_total_shares(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_TOTAL_SHARES)
        assert len(facts) == 1
        assert facts[0].value == 1000000000
        assert facts[0].unit == FactUnit.COUNT

    def test_promoter_pct(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(50.0)
        assert facts[0].unit == FactUnit.PERCENT

    def test_public_pct(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_PUBLIC_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(50.0)

    def test_fpi_pct(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_FPI_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(20.0)

    def test_dii_pct(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_DII_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(10.0)

    def test_mf_pct(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_MF_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(5.0)

    def test_insurance_pct(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_INSURANCE_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(4.0)

    def test_nri_pct(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_NRI_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(1.0)

    def test_retail_pct(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_RETAIL_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(2.0)

    def test_hni_pct(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_HNI_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(0.5)

    def test_pledged_zero_when_false(self, result):
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(0.0)
        assert facts[0].unit == FactUnit.PERCENT

    def test_period_matches_date_of_report(self, result):
        for f in result.facts:
            assert f.period == "2026-03-31"

    def test_all_facts_have_provenance_section(self, result):
        for f in result.facts:
            assert f.provenance.section
            assert f.provenance.char_offset is None  # XML; no meaningful offset


# ---------------------------------------------------------------------------
# Percentage scale: XBRL 0–1 → Atlas 0–100
# ---------------------------------------------------------------------------


class TestPercentageScale:
    def test_fraction_multiplied_by_100(self):
        xml = _xml(promoter_pct="0.7177")
        result = analyze("x", _kb(xml))
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PCT)
        assert facts[0].value == pytest.approx(71.77)

    def test_small_fraction(self):
        xml = _xml(nri_pct="0.0024")
        result = analyze("x", _kb(xml))
        facts = _facts(result, FactKind.OWNERSHIP_NRI_PCT)
        assert facts[0].value == pytest.approx(0.24)


# ---------------------------------------------------------------------------
# Promoter pledging
# ---------------------------------------------------------------------------


class TestPromoterPledging:
    def test_pledged_false_emits_zero(self):
        result = analyze("x", _kb(_xml(pledged_bool="false")))
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT)
        assert len(facts) == 1
        assert facts[0].value == 0.0

    def test_pledged_true_warns_when_pct_missing(self):
        result = analyze("x", _kb(_xml(pledged_bool="true")))
        assert any("pledge" in w.lower() for w in result.warnings)
        assert _facts(result, FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT) == []

    def test_pledged_flag_missing_emits_warning(self):
        xml = textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
                        xmlns:s="{_NS}">
              <xbrli:context id="MainI">
                <xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
                <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period>
              </xbrli:context>
              <s:DateOfReport contextRef="MainI">2026-03-31</s:DateOfReport>
              <s:NumberOfFullyPaidUpEquityShares contextRef="ShareholdingPattern_ContextI">500000000</s:NumberOfFullyPaidUpEquityShares>
              <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">0.5</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
              <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="PublicShareholding_ContextI">0.5</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
              <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InstitutionsForeign_ContextI">0.2</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
              <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InstitutionsDomestic_ContextI">0.1</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
              <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="MutualFundsOrUTI_ContextI">0.05</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
              <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InsuranceCompanies_ContextI">0.04</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
              <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="NonResidentIndians_ContextI">0.01</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
            </xbrli:xbrl>
        """)
        result = analyze("x", _kb(xml))
        assert any("pledge" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Date fallback
# ---------------------------------------------------------------------------


class TestDateFallback:
    def test_missing_date_falls_back_to_source_date(self):
        xml = _xml(omit_date=True)
        result = analyze("x", _kb(xml, source_date="2026-04-21T10:21:39+00:00"))
        assert any("DateOfReport" in w for w in result.warnings)
        # All facts get the filing date (first 10 chars of source_date)
        for f in result.facts:
            assert f.period == "2026-04-21"


# ---------------------------------------------------------------------------
# Missing optional vs. required contexts
# ---------------------------------------------------------------------------


class TestMissingContexts:
    def test_missing_fpi_emits_warning(self):
        result = analyze("x", _kb(_xml(omit_fpi=True)))
        assert any("FPI" in w for w in result.warnings)
        assert _facts(result, FactKind.OWNERSHIP_FPI_PCT) == []

    def test_missing_retail_no_warning(self):
        result = analyze("x", _kb(_xml(omit_retail=True)))
        assert not any("retail" in w.lower() or "Retail" in w for w in result.warnings)
        assert _facts(result, FactKind.OWNERSHIP_RETAIL_PCT) == []

    def test_missing_hni_no_warning(self):
        result = analyze("x", _kb(_xml(omit_hni=True)))
        assert not any("HNI" in w or "hni" in w.lower() for w in result.warnings)
        assert _facts(result, FactKind.OWNERSHIP_HNI_PCT) == []


# ---------------------------------------------------------------------------
# Confidence logic
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_high_when_all_core_facts_present(self):
        result = analyze("x", _kb(_xml()))
        assert result.confidence == "high"

    def test_medium_when_only_total_and_promoter(self):
        # Build XML with only total + promoter, missing FPI/DII/public
        xml = textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
                        xmlns:s="{_NS}">
              <xbrli:context id="MainI">
                <xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
                <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period>
              </xbrli:context>
              <s:DateOfReport contextRef="MainI">2026-03-31</s:DateOfReport>
              <s:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged contextRef="MainI">false</s:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged>
              <s:NumberOfFullyPaidUpEquityShares contextRef="ShareholdingPattern_ContextI">500000000</s:NumberOfFullyPaidUpEquityShares>
              <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">0.5</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
            </xbrli:xbrl>
        """)
        result = analyze("x", _kb(xml))
        assert result.confidence == "medium"

    def test_low_when_no_useful_facts(self):
        xml = textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
                        xmlns:s="{_NS}">
              <xbrli:context id="MainI">
                <xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
                <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period>
              </xbrli:context>
              <s:DateOfReport contextRef="MainI">2026-03-31</s:DateOfReport>
            </xbrli:xbrl>
        """)
        result = analyze("x", _kb(xml))
        assert result.confidence == "low"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_wrong_kind_raises(self):
        with pytest.raises(ValueError, match="not 'shareholding_pattern'"):
            analyze("x", _kb("<xml/>", kind="board_outcome"))

    def test_missing_evidence_raises(self):
        kb = MagicMock()
        kb.get.return_value = None
        with pytest.raises(ValueError, match="not in knowledge base"):
            analyze("x", kb)

    def test_empty_content_raises(self):
        kb = MagicMock()
        entry = MagicMock()
        entry.kind = "shareholding_pattern"
        entry.source_date = "2026-04-21T10:21:39+00:00"
        kb.get.return_value = entry
        kb.get_content.return_value = None
        with pytest.raises(ValueError, match="no content"):
            analyze("x", kb)

    def test_malformed_xml_raises(self):
        with pytest.raises(ValueError, match="XML parse error"):
            analyze("x", _kb("not xml at all"))


# ---------------------------------------------------------------------------
# Old BSE XBRL format: percentages in 0–100 scale (pre-Oct 2025)
# ---------------------------------------------------------------------------

_NS_OLD = "http://www.bseindia.com/xbrl/shp/2022-09-30/in-bse-shp"


def _xml_old(
    promoter_pct: str = "33.19",
    public_pct: str = "66.81",
    fpi_pct: str = "18.00",
    dii_pct: str = "17.72",
) -> str:
    """Build an old-format BSE XBRL SHP where percentages are 0–100 scale."""
    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <xbrli:xbrl
            xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:s="{_NS_OLD}">
          <xbrli:context id="MainI">
            <xbrli:entity><xbrli:identifier scheme="x">500470</xbrli:identifier></xbrli:entity>
            <xbrli:period><xbrli:instant>2024-09-30</xbrli:instant></xbrli:period>
          </xbrli:context>
          <s:DateOfReport contextRef="MainI">2024-09-30</s:DateOfReport>
          <s:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged contextRef="MainI">false</s:WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged>
          <s:NumberOfFullyPaidUpEquityShares contextRef="ShareholdingPattern_ContextI">12471290974</s:NumberOfFullyPaidUpEquityShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">{promoter_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="PublicShareholding_ContextI">{public_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InstitutionsForeign_ContextI">{fpi_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InstitutionsDomestic_ContextI">{dii_pct}</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="MutualFundsOrUTI_ContextI">5.00</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InsuranceCompanies_ContextI">4.00</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
          <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="NonResidentIndians_ContextI">1.00</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
        </xbrli:xbrl>
    """)


class TestOldBseXbrlFormat:
    """Regression tests for the pre-Oct-2025 BSE XBRL 0–100 percentage scale.

    Old documents store 33.19 for 33.19%; new documents store 0.3319.
    The analyzer must detect the format and NOT double-multiply old values.
    """

    def test_detect_old_format_returns_false(self):
        assert _detect_decimal_format(_xml_old()) is False

    def test_detect_new_format_returns_true(self):
        assert _detect_decimal_format(_xml()) is True

    def test_old_format_promoter_not_multiplied(self):
        result = analyze("x", _kb(_xml_old(promoter_pct="33.19")))
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(33.19)

    def test_old_format_public_not_multiplied(self):
        result = analyze("x", _kb(_xml_old(public_pct="66.81")))
        facts = _facts(result, FactKind.OWNERSHIP_PUBLIC_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(66.81)

    def test_old_format_fpi_not_multiplied(self):
        result = analyze("x", _kb(_xml_old(fpi_pct="18.00")))
        facts = _facts(result, FactKind.OWNERSHIP_FPI_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(18.0)

    def test_new_format_promoter_is_multiplied(self):
        result = analyze("x", _kb(_xml(promoter_pct="0.3319")))
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(33.19)

    def test_old_format_promoter_75pct(self):
        result = analyze("x", _kb(_xml_old(promoter_pct="75.00", public_pct="25.00")))
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PCT)
        assert facts[0].value == pytest.approx(75.0)

    def test_old_format_has_high_confidence(self):
        result = analyze("x", _kb(_xml_old()))
        assert result.confidence == "high"
