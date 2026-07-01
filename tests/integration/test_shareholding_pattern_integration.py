"""Integration tests for atlas.analysis.shareholding_pattern.

Uses the real TCS Q4 FY26 XBRL shareholding pattern downloaded as:
  repositories/TCS/shareholding_pattern/bse-shp-532540-129.xml

Run with: pytest -m integration -v -s

Expected values (extracted from the filed XBRL, verified against BSE website):
  Quarter end:   2026-03-31
  Total shares:  3,618,087,518
  Promoter:      71.77%
  Public:        28.23%
  FPI:            9.66%
  DII:           13.41%
  MF:             5.77%
  Insurance:      6.69%
  NRI:            0.24%
  Retail (≤₹2L): 4.31%
  HNI (>₹2L):    0.21%
  Pledged:        0.00%  (no pledging)
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.shareholding_pattern import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.knowledge.base import KnowledgeBase
from atlas.acquisition.repository import Repository

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"
_TCS_SHP_ID = "bse-shp-532540-129"


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
    entry = repo.get(_TCS_SHP_ID)
    if entry is not None:
        instance.parse(entry)
    yield instance
    db.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def result(kb: KnowledgeBase) -> AnalysisResult:
    entry = kb.get(_TCS_SHP_ID)
    if entry is None or entry.status != "ok":
        pytest.skip(f"Evidence {_TCS_SHP_ID!r} not parsed — run acquisition pipeline first")
    return analyze(_TCS_SHP_ID, kb)


def _facts(result: AnalysisResult, kind: FactKind):
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

class TestEnvelope:
    def test_returns_analysis_result(self, result: AnalysisResult):
        assert isinstance(result, AnalysisResult)

    def test_analyzer_version(self, result: AnalysisResult):
        assert result.analyzer_version == ANALYZER_VERSION

    def test_evidence_id(self, result: AnalysisResult):
        assert result.evidence_id == _TCS_SHP_ID

    def test_kind(self, result: AnalysisResult):
        assert result.kind == "shareholding_pattern"

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_no_warnings(self, result: AnalysisResult):
        assert result.warnings == []

    def test_source_date(self, result: AnalysisResult):
        assert result.source_date.year == 2026
        assert result.source_date.month == 4
        assert result.source_date.day == 21


# ---------------------------------------------------------------------------
# Quarter period
# ---------------------------------------------------------------------------

class TestPeriod:
    def test_all_facts_period_is_quarter_end(self, result: AnalysisResult):
        for f in result.facts:
            assert f.period == "2026-03-31", f"fact {f.kind} has period {f.period!r}"


# ---------------------------------------------------------------------------
# Total shares
# ---------------------------------------------------------------------------

class TestTotalShares:
    def test_total_shares_extracted(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_TOTAL_SHARES)
        assert len(facts) == 1

    def test_total_shares_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_TOTAL_SHARES)
        assert facts[0].value == 3_618_087_518

    def test_total_shares_unit_count(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_TOTAL_SHARES)
        assert facts[0].unit == FactUnit.COUNT

    def test_total_shares_confidence_high(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_TOTAL_SHARES)
        assert facts[0].confidence == "high"


# ---------------------------------------------------------------------------
# Promoter holding
# ---------------------------------------------------------------------------

class TestPromoterHolding:
    def test_promoter_pct_extracted(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PCT)
        assert len(facts) == 1

    def test_promoter_pct_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PCT)
        assert facts[0].value == pytest.approx(71.77, abs=0.01)

    def test_promoter_pct_unit(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PCT)
        assert facts[0].unit == FactUnit.PERCENT

    def test_promoter_provenance_section(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PCT)
        assert "Promoter" in facts[0].provenance.section


# ---------------------------------------------------------------------------
# Public shareholding
# ---------------------------------------------------------------------------

class TestPublicShareholding:
    def test_public_pct_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_PUBLIC_PCT)
        assert facts[0].value == pytest.approx(28.23, abs=0.01)

    def test_promoter_plus_public_near_100(self, result: AnalysisResult):
        promoter = _facts(result, FactKind.OWNERSHIP_PROMOTER_PCT)[0].value
        public = _facts(result, FactKind.OWNERSHIP_PUBLIC_PCT)[0].value
        assert promoter + public == pytest.approx(100.0, abs=0.02)


# ---------------------------------------------------------------------------
# Institutional breakdown
# ---------------------------------------------------------------------------

class TestInstitutionalBreakdown:
    def test_fpi_pct_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_FPI_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(9.66, abs=0.01)

    def test_dii_pct_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_DII_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(13.41, abs=0.01)

    def test_mf_pct_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_MF_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(5.77, abs=0.01)

    def test_insurance_pct_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_INSURANCE_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(6.69, abs=0.01)


# ---------------------------------------------------------------------------
# Retail / NRI
# ---------------------------------------------------------------------------

class TestRetailAndNRI:
    def test_nri_pct_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_NRI_PCT)
        assert facts[0].value == pytest.approx(0.24, abs=0.01)

    def test_retail_pct_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_RETAIL_PCT)
        assert facts[0].value == pytest.approx(4.31, abs=0.01)

    def test_hni_pct_value(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_HNI_PCT)
        assert facts[0].value == pytest.approx(0.21, abs=0.01)


# ---------------------------------------------------------------------------
# Promoter pledging (TCS has no pledging)
# ---------------------------------------------------------------------------

class TestPromoterPledging:
    def test_pledged_pct_zero(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(0.0)

    def test_pledged_pct_unit_percent(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT)
        assert facts[0].unit == FactUnit.PERCENT


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_all_facts_have_section(self, result: AnalysisResult):
        for f in result.facts:
            assert f.provenance.section, f"fact {f.kind} missing provenance.section"

    def test_all_facts_char_offset_none(self, result: AnalysisResult):
        # XML facts carry no meaningful byte offset
        for f in result.facts:
            assert f.provenance.char_offset is None

    def test_all_facts_confidence_high(self, result: AnalysisResult):
        for f in result.facts:
            assert f.confidence == "high"

    def test_total_shares_section_is_total_context(self, result: AnalysisResult):
        facts = _facts(result, FactKind.OWNERSHIP_TOTAL_SHARES)
        assert facts[0].provenance.section == "ShareholdingPattern_ContextI"
