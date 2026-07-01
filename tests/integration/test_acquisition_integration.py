"""Integration tests for atlas.analysis.acquisition against real TCS filings.

Run with: pytest -m integration -v -s

Validates all six acquisition documents in the TCS repository:
  c6427530  Coastal Cloud Holdings (Type A — external acquisition)
  f4a6b240  TCS BT Bhutan (Type B — single incorporation)
  de5103de  HyperVault (Type B — incorporation with stated cost)
  0179b556  TCS North America + Trident LE (Type B — two entities)
  4a229f29  Costa Rica subsidiary (Type B — incorporation)
  6526a894  TRIL completion update (Type C — no Annexure A)
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.acquisition import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit
from atlas.knowledge.base import KnowledgeBase
from atlas.acquisition.repository import Repository

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

_COASTAL_CLOUD_ID = "bse-news-c6427530-ce9c-4ed6-88a5-bdf314aeca25"
_BHUTAN_ID        = "bse-news-f4a6b240-0d7e-4f6f-9c4e-df11afd53c99"
_HYPERVAULT_ID    = "bse-news-de5103de-ad7c-4136-839d-b5b3cfccaf05"
_MULTI_ID         = "bse-news-0179b556-ec38-4936-8855-496263416d64"
_COSTA_RICA_ID    = "bse-news-4a229f29-4d77-4b17-894b-bc2564f5014e"
_TRIL_ID          = "bse-news-6526a894-ab8e-42a7-92fc-2ad9407d9f26"

_ALL_IDS = [
    _COASTAL_CLOUD_ID, _BHUTAN_ID, _HYPERVAULT_ID,
    _MULTI_ID, _COSTA_RICA_ID, _TRIL_ID,
]


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
    for eid in _ALL_IDS:
        entry = repo.get(eid)
        if entry is not None:
            instance.parse(entry)
    yield instance
    db.unlink(missing_ok=True)


def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Type A — Coastal Cloud external acquisition
# ---------------------------------------------------------------------------

class TestCoastalCloud:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        if kb.get(_COASTAL_CLOUD_ID) is None or kb.get(_COASTAL_CLOUD_ID).status != "ok":
            pytest.skip("Coastal Cloud filing not parsed")
        return analyze(_COASTAL_CLOUD_ID, kb)

    def test_returns_analysis_result(self, result: AnalysisResult) -> None:
        assert isinstance(result, AnalysisResult)

    def test_analyzer_version(self, result: AnalysisResult) -> None:
        assert result.analyzer_version == ANALYZER_VERSION

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_no_warnings(self, result: AnalysisResult) -> None:
        assert result.warnings == []

    def test_target_name(self, result: AnalysisResult) -> None:
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert len(names) == 1
        assert "Coastal Cloud" in str(names[0].value)

    def test_target_name_from_cover_letter(self, result: AnalysisResult) -> None:
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert names[0].provenance.section == "cover_letter"

    def test_consideration_type_cash(self, result: AnalysisResult) -> None:
        cons = _facts(result, FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE)
        assert len(cons) == 1
        assert cons[0].value == "cash"

    def test_enterprise_value_usd_700_million(self, result: AnalysisResult) -> None:
        ev = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert len(ev) == 1
        assert ev[0].value == pytest.approx(700.0)

    def test_enterprise_value_unit_usd_million(self, result: AnalysisResult) -> None:
        ev = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert ev[0].unit == FactUnit.USD_MILLION

    def test_stake_100_pct(self, result: AnalysisResult) -> None:
        stake = _facts(result, FactKind.CAPITAL_ACQ_STAKE_PCT)
        assert len(stake) == 1
        assert stake[0].value == pytest.approx(100.0)

    def test_stake_unit_percent(self, result: AnalysisResult) -> None:
        stake = _facts(result, FactKind.CAPITAL_ACQ_STAKE_PCT)
        assert stake[0].unit == FactUnit.PERCENT

    def test_expected_completion_2026_01_31(self, result: AnalysisResult) -> None:
        comp = _facts(result, FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION)
        assert len(comp) == 1
        assert comp[0].value == "2026-01-31"

    def test_expected_completion_unit_iso_date(self, result: AnalysisResult) -> None:
        comp = _facts(result, FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION)
        assert comp[0].unit == FactUnit.ISO_DATE

    def test_annexure_a_in_excerpts(self, result: AnalysisResult) -> None:
        assert "annexure_a" in result.excerpts

    def test_press_release_in_excerpts(self, result: AnalysisResult) -> None:
        assert "press_release" in result.excerpts

    def test_all_facts_have_provenance(self, result: AnalysisResult) -> None:
        for f in result.facts:
            assert f.provenance.section != ""
            assert f.provenance.char_offset is not None


# ---------------------------------------------------------------------------
# Type B — Bhutan subsidiary (single entity, no stated cost)
# ---------------------------------------------------------------------------

class TestBhutanSubsidiary:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        if kb.get(_BHUTAN_ID) is None or kb.get(_BHUTAN_ID).status != "ok":
            pytest.skip("Bhutan filing not parsed")
        return analyze(_BHUTAN_ID, kb)

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_no_warnings(self, result: AnalysisResult) -> None:
        assert result.warnings == []

    def test_target_name_tcs_bhutan(self, result: AnalysisResult) -> None:
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert len(names) == 1
        assert "TATA CONSULTANCY SERVICES BT" in str(names[0].value)
        assert "Private Limited" in str(names[0].value)

    def test_consideration_subscription(self, result: AnalysisResult) -> None:
        cons = _facts(result, FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE)
        assert cons[0].value == "subscription"

    def test_stake_100_pct(self, result: AnalysisResult) -> None:
        stake = _facts(result, FactKind.CAPITAL_ACQ_STAKE_PCT)
        assert stake[0].value == pytest.approx(100.0)

    def test_no_enterprise_value(self, result: AnalysisResult) -> None:
        ev = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert ev == []

    def test_no_completion_date(self, result: AnalysisResult) -> None:
        comp = _facts(result, FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION)
        assert comp == []


# ---------------------------------------------------------------------------
# Type B — HyperVault (single entity, stated subscription cost)
# ---------------------------------------------------------------------------

class TestHyperVault:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        if kb.get(_HYPERVAULT_ID) is None or kb.get(_HYPERVAULT_ID).status != "ok":
            pytest.skip("HyperVault filing not parsed")
        return analyze(_HYPERVAULT_ID, kb)

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_target_name_hypervault(self, result: AnalysisResult) -> None:
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert any("HyperVault AI Data Center" in str(f.value) for f in names)

    def test_alias_stripped_from_name(self, result: AnalysisResult) -> None:
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        # The short-form ("HyperVault") should not appear in the cleaned name
        assert not any('("HyperVault")' in str(f.value) for f in names)

    def test_enterprise_value_inr_crore(self, result: AnalysisResult) -> None:
        ev = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert len(ev) == 1
        assert ev[0].value == pytest.approx(7.5)
        assert ev[0].unit == FactUnit.CRORE_INR


# ---------------------------------------------------------------------------
# Type B — Two entities in one filing (ListEngage SPVs)
# ---------------------------------------------------------------------------

class TestMultiEntity:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        if kb.get(_MULTI_ID) is None or kb.get(_MULTI_ID).status != "ok":
            pytest.skip("Multi-entity filing not parsed")
        return analyze(_MULTI_ID, kb)

    def test_two_target_name_facts(self, result: AnalysisResult) -> None:
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert len(names) == 2

    def test_tcs_north_america_present(self, result: AnalysisResult) -> None:
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert any("TCS North America" in str(f.value) for f in names)

    def test_trident_le_present(self, result: AnalysisResult) -> None:
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert any("Trident LE" in str(f.value) for f in names)


# ---------------------------------------------------------------------------
# Type B — Costa Rica subsidiary
# ---------------------------------------------------------------------------

class TestCostaRica:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        if kb.get(_COSTA_RICA_ID) is None or kb.get(_COSTA_RICA_ID).status != "ok":
            pytest.skip("Costa Rica filing not parsed")
        return analyze(_COSTA_RICA_ID, kb)

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_target_name_sociedad_anonima(self, result: AnalysisResult) -> None:
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert any("SOCIEDAD ANONIMA" in str(f.value) for f in names)


# ---------------------------------------------------------------------------
# Type C — TRIL completion update (no Annexure A)
# ---------------------------------------------------------------------------

class TestTRILCompletion:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        if kb.get(_TRIL_ID) is None or kb.get(_TRIL_ID).status != "ok":
            pytest.skip("TRIL filing not parsed")
        return analyze(_TRIL_ID, kb)

    def test_confidence_low(self, result: AnalysisResult) -> None:
        assert result.confidence == "low"

    def test_no_facts(self, result: AnalysisResult) -> None:
        assert result.facts == []

    def test_warning_about_missing_annexure(self, result: AnalysisResult) -> None:
        assert any("Annexure A" in w for w in result.warnings)

    def test_cover_letter_in_excerpts(self, result: AnalysisResult) -> None:
        assert "cover_letter" in result.excerpts
