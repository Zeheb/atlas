"""Integration tests for atlas.analysis.board_outcome against real TCS filings.

Run with: pytest -m integration -v -s

Validates all four board outcome documents in the TCS repository:
  c8be78c9  2024-10-10  Q2 FY2025 results + second interim dividend INR 10/share
  6f7c8d3d  2025-11-20  HyperVault AI JV with TPG Terabyte (agreement sub-type)
  2636b0ad  2025-12-10  Coastal Cloud acquisition (Annexure A, EV USD 700M)
  6f1cf0de  2026-04-09  FY2026 results + final dividend INR 31/share recommended
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.acquisition.repository import Repository
from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit
from atlas.analysis.board_outcome import ANALYZER_VERSION, analyze
from atlas.company.builder import build_profile
from atlas.knowledge.base import KnowledgeBase

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

_ID_Q2_2024 = "bse-news-c8be78c9-b40f-486a-853b-825e1919c160"
_ID_HYPERVAULT = "bse-news-6f7c8d3d-ab76-46cb-bca9-efda08d9d559"
_ID_COASTAL = "bse-news-2636b0ad-4ee8-4506-8ba5-9eaeaf800020"
_ID_FY2026 = "bse-news-6f1cf0de-6044-4195-8d91-f479cbfa778a"

_ALL_IDS = [_ID_Q2_2024, _ID_HYPERVAULT, _ID_COASTAL, _ID_FY2026]


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


def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


def _skip_if_not_parsed(kb: KnowledgeBase, eid: str) -> None:
    entry = kb.get(eid)
    if entry is None or entry.status != "ok":
        pytest.skip(f"{eid[:16]}... not parsed")


# ---------------------------------------------------------------------------
# Q2 FY2025: second interim dividend INR 10/share
# ---------------------------------------------------------------------------


class TestQ2Dividend:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_Q2_2024)
        return analyze(_ID_Q2_2024, kb)

    def test_returns_analysis_result(self, result: AnalysisResult) -> None:
        assert isinstance(result, AnalysisResult)

    def test_analyzer_version(self, result: AnalysisResult) -> None:
        assert result.analyzer_version == ANALYZER_VERSION

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_source_date_populated(self, result: AnalysisResult) -> None:
        assert result.source_date is not None
        assert result.source_date.year == 2024

    def test_dividend_amount_10(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(10.0)

    def test_dividend_unit(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert facts[0].unit == FactUnit.RUPEES_PER_SHARE

    def test_dividend_type_interim(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_TYPE)
        assert len(facts) == 1
        assert facts[0].value == "interim"

    def test_record_date_oct_18(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_RECORD_DATE)
        assert len(facts) == 1
        assert facts[0].value == "2024-10-18"

    def test_payment_date_nov_5(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE)
        assert len(facts) == 1
        assert facts[0].value == "2024-11-05"

    def test_dividend_period_sep_30(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert facts[0].period == "2024-09-30"

    def test_cover_letter_in_excerpts(self, result: AnalysisResult) -> None:
        assert "cover_letter" in result.excerpts

    def test_no_acquisition_facts(self, result: AnalysisResult) -> None:
        assert _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME) == []


# ---------------------------------------------------------------------------
# HyperVault investment: SSA with TPG into wholly-owned subsidiary
# ---------------------------------------------------------------------------


class TestHyperVaultInvestment:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_HYPERVAULT)
        return analyze(_ID_HYPERVAULT, kb)

    def test_returns_analysis_result(self, result: AnalysisResult) -> None:
        assert isinstance(result, AnalysisResult)

    def test_confidence_medium(self, result: AnalysisResult) -> None:
        assert result.confidence == "medium"

    def test_invest_target_name(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_INVEST_TARGET_NAME)
        assert len(facts) == 1
        assert "HyperVault" in str(facts[0].value)

    def test_invest_amount_18000_crore(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_INVEST_AMOUNT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(18000.0)
        assert facts[0].unit == FactUnit.CRORE_INR

    def test_invest_amount_has_provenance(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_INVEST_AMOUNT)
        assert facts[0].provenance.section in ("press_release", "annexure_a")

    def test_no_warnings(self, result: AnalysisResult) -> None:
        assert result.warnings == []

    def test_no_dividend_facts(self, result: AnalysisResult) -> None:
        assert _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE) == []

    def test_no_acquisition_facts(self, result: AnalysisResult) -> None:
        assert _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME) == []

    def test_annexure_a_captured(self, result: AnalysisResult) -> None:
        assert "annexure_a" in result.excerpts
        assert len(result.excerpts["annexure_a"]) > 100

    def test_press_release_captured(self, result: AnalysisResult) -> None:
        assert "press_release" in result.excerpts


# ---------------------------------------------------------------------------
# Coastal Cloud acquisition: Annexure A Type A
# ---------------------------------------------------------------------------


class TestCoastalCloudAcquisition:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_COASTAL)
        return analyze(_ID_COASTAL, kb)

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_target_name_coastal_cloud(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert len(facts) == 1
        assert "Coastal Cloud" in str(facts[0].value)

    def test_consideration_cash(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE)
        assert len(facts) == 1
        assert facts[0].value == "cash"

    def test_enterprise_value_700_usd_million(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(700.0)
        assert facts[0].unit == FactUnit.USD_MILLION

    def test_stake_100_pct(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_ACQ_STAKE_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(100.0)

    def test_expected_completion_jan_2026(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION)
        assert len(facts) == 1
        assert facts[0].value == "2026-01-31"

    def test_annexure_a_in_excerpts(self, result: AnalysisResult) -> None:
        assert "annexure_a" in result.excerpts

    def test_no_dividend_facts(self, result: AnalysisResult) -> None:
        assert _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE) == []


# ---------------------------------------------------------------------------
# FY2026 annual results: final dividend INR 31/share recommended
# ---------------------------------------------------------------------------


class TestFY2026FinalDividend:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_FY2026)
        return analyze(_ID_FY2026, kb)

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_dividend_amount_31(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(31.0)

    def test_dividend_type_final(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_TYPE)
        assert len(facts) == 1
        assert facts[0].value == "final"

    def test_no_record_date(self, result: AnalysisResult) -> None:
        # Record date not set at recommendation stage
        assert _facts(result, FactKind.CAPITAL_DIVIDEND_RECORD_DATE) == []

    def test_no_payment_date(self, result: AnalysisResult) -> None:
        # Payment date is "third day after AGM" — not a parseable date
        assert _facts(result, FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE) == []

    def test_dividend_period_fy_end(self, result: AnalysisResult) -> None:
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert facts[0].period == "2026-03-31"

    def test_source_date_2026(self, result: AnalysisResult) -> None:
        assert result.source_date.year == 2026

    def test_no_acquisition_facts(self, result: AnalysisResult) -> None:
        assert _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME) == []


# ---------------------------------------------------------------------------
# Analyzer version
# ---------------------------------------------------------------------------


class TestAnalyzerVersion:
    """All four board outcome filings should report the current ANALYZER_VERSION."""

    @pytest.mark.parametrize("eid", _ALL_IDS)
    def test_version(self, kb: KnowledgeBase, eid: str) -> None:
        _skip_if_not_parsed(kb, eid)
        result = analyze(eid, kb)
        assert result.analyzer_version == ANALYZER_VERSION


# ---------------------------------------------------------------------------
# No spurious new facts — existing documents must not produce false positives
# for buyback / fundraising / management changes
# ---------------------------------------------------------------------------


class TestNoSpuriousBoardOutcomeFacts:
    """The four TCS board outcome filings contain no buybacks, fundraising events,
    or director/KMP changes.  The new extractors must not produce false positives.
    """

    @pytest.mark.parametrize("eid", _ALL_IDS)
    def test_no_buyback_facts(self, kb: KnowledgeBase, eid: str) -> None:
        _skip_if_not_parsed(kb, eid)
        result = analyze(eid, kb)
        assert _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT) == []

    @pytest.mark.parametrize("eid", _ALL_IDS)
    def test_no_fundraise_facts(self, kb: KnowledgeBase, eid: str) -> None:
        _skip_if_not_parsed(kb, eid)
        result = analyze(eid, kb)
        assert _facts(result, FactKind.CAPITAL_FUNDRAISE_TYPE) == []

    @pytest.mark.parametrize("eid", _ALL_IDS)
    def test_no_director_change_facts(self, kb: KnowledgeBase, eid: str) -> None:
        _skip_if_not_parsed(kb, eid)
        result = analyze(eid, kb)
        assert _facts(result, FactKind.GOVERNANCE_DIRECTOR) == []


# ---------------------------------------------------------------------------
# CompanyProfile ingestion — board outcomes flow into capital_events + governance
# ---------------------------------------------------------------------------


class TestBoardOutcomeProfileIngestion:
    """Proves that board_outcome results are correctly ingested into CompanyProfile."""

    @pytest.fixture(scope="class")
    def all_results(self, kb: KnowledgeBase) -> list[AnalysisResult]:
        results = []
        for eid in _ALL_IDS:
            entry = kb.get(eid)
            if entry is not None and entry.status == "ok":
                results.append(analyze(eid, kb))
        return results

    def test_dividends_ingested(self, all_results: list[AnalysisResult]) -> None:
        if not all_results:
            pytest.skip("No board outcome results available")
        profile = build_profile("TCS", all_results)
        assert len(profile.capital_events.dividends) > 0

    def test_acquisitions_ingested(self, all_results: list[AnalysisResult]) -> None:
        if not all_results:
            pytest.skip("No board outcome results available")
        profile = build_profile("TCS", all_results)
        assert len(profile.capital_events.acquisitions) > 0

    def test_investments_ingested(self, all_results: list[AnalysisResult]) -> None:
        if not all_results:
            pytest.skip("No board outcome results available")
        profile = build_profile("TCS", all_results)
        assert len(profile.capital_events.investments) > 0

    def test_fundraises_empty_for_tcs_corpus(
        self, all_results: list[AnalysisResult]
    ) -> None:
        if not all_results:
            pytest.skip("No board outcome results available")
        profile = build_profile("TCS", all_results)
        assert profile.capital_events.fundraises == []

    def test_director_changes_empty_for_tcs_corpus(
        self, all_results: list[AnalysisResult]
    ) -> None:
        if not all_results:
            pytest.skip("No board outcome results available")
        profile = build_profile("TCS", all_results)
        assert profile.governance.director_changes == []
