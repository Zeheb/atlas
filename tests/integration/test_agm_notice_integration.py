"""Integration tests for atlas.analysis.agm_notice.

Uses three real TCS AGM voting-results filings from the repository:

  bse-news-142ec3b0-9c40-44d4-a91a-90209663497a  30th AGM 2025-06-19
  bse-news-d73b015e-301e-43d4-a739-f44bdbaaf3c9  31st AGM 2026-06-09
  bse-news-481ce326-fd14-4e6f-9676-1d68115654bb  29th AGM 2024-05-31

Run with: pytest -m integration -v -s
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.acquisition.repository import Repository
from atlas.analysis.agm_notice import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.knowledge.base import KnowledgeBase

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

_AGM_2025_ID = "bse-news-142ec3b0-9c40-44d4-a91a-90209663497a"  # 30th AGM
_AGM_2026_ID = "bse-news-d73b015e-301e-43d4-a739-f44bdbaaf3c9"  # 31st AGM
_AGM_2024_ID = "bse-news-481ce326-fd14-4e6f-9676-1d68115654bb"  # 29th AGM


@pytest.fixture(scope="module")
def tcs_root(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(
        _TCS_REPO, evidence_ids=[_AGM_2025_ID, _AGM_2026_ID, _AGM_2024_ID]
    )


@pytest.fixture(scope="module")
def kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(tcs_root)
    repo = Repository(tcs_root)
    for eid in (_AGM_2025_ID, _AGM_2026_ID, _AGM_2024_ID):
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
# 30th AGM — 2025-06-19 (Format A: 10 resolutions, vote percentages via col-split)
# ---------------------------------------------------------------------------


class TestAGM2025:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _AGM_2025_ID)
        return analyze(_AGM_2025_ID, kb)

    def test_returns_analysis_result(self, result: AnalysisResult):
        assert isinstance(result, AnalysisResult)

    def test_kind(self, result: AnalysisResult):
        assert result.kind == "agm_notice"

    def test_analyzer_version(self, result: AnalysisResult):
        assert result.analyzer_version == ANALYZER_VERSION

    def test_subtype_is_voting_results(self, result: AnalysisResult):
        assert result.excerpts["subtype"] == "voting_results"

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_no_warnings(self, result: AnalysisResult):
        assert result.warnings == [], result.warnings

    def test_agm_date(self, result: AnalysisResult):
        assert result.excerpts["agm_date"] == "2025-06-19"

    # -- Resolution titles --------------------------------------------------

    def test_ten_resolution_titles(self, result: AnalysisResult):
        assert len(_facts(result, FactKind.GOVERNANCE_RESOLUTION_TITLE)) == 10

    def test_all_resolutions_ordinary(self, result: AnalysisResult):
        types = _facts(result, FactKind.GOVERNANCE_RESOLUTION_TYPE)
        assert len(types) == 10
        assert all(f.value == "ordinary" for f in types)

    def test_all_resolutions_passed(self, result: AnalysisResult):
        outcomes = _facts(result, FactKind.GOVERNANCE_RESOLUTION_OUTCOME)
        assert all(f.value == "passed" for f in outcomes)

    def test_res1_mentions_financial_statements(self, result: AnalysisResult):
        titles = _facts(result, FactKind.GOVERNANCE_RESOLUTION_TITLE)
        res1 = next(f for f in titles if f.provenance.section == "resolution_1")
        assert "financial" in res1.value.lower() or "statement" in res1.value.lower()

    def test_period_is_agm_date(self, result: AnalysisResult):
        for f in _facts(result, FactKind.GOVERNANCE_RESOLUTION_TITLE):
            assert f.period == "2025-06-19"

    # -- Vote percentages ---------------------------------------------------

    def test_eight_or_more_vote_pct_facts(self, result: AnalysisResult):
        assert len(_facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR)) >= 8

    def test_vote_pct_units_are_percent(self, result: AnalysisResult):
        for f in _facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR):
            assert f.unit == FactUnit.PERCENT
        for f in _facts(result, FactKind.GOVERNANCE_VOTE_PCT_AGAINST):
            assert f.unit == FactUnit.PERCENT

    def test_res3_pct_for(self, result: AnalysisResult):
        pcts = _facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR)
        res3 = next((f for f in pcts if f.provenance.section == "resolution_3"), None)
        assert res3 is not None
        assert abs(res3.value - 99.3305) < 0.001

    def test_res3_pct_against(self, result: AnalysisResult):
        pcts = _facts(result, FactKind.GOVERNANCE_VOTE_PCT_AGAINST)
        res3 = next((f for f in pcts if f.provenance.section == "resolution_3"), None)
        assert res3 is not None
        assert abs(res3.value - 0.6695) < 0.001

    def test_res4_pct_for(self, result: AnalysisResult):
        """Resolution 4 uses Layout A-robust (garbled col7 header)."""
        pcts = _facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR)
        res4 = next((f for f in pcts if f.provenance.section == "resolution_4"), None)
        assert res4 is not None
        assert abs(res4.value - 99.6558) < 0.001

    def test_res4_pct_against(self, result: AnalysisResult):
        pcts = _facts(result, FactKind.GOVERNANCE_VOTE_PCT_AGAINST)
        res4 = next((f for f in pcts if f.provenance.section == "resolution_4"), None)
        assert res4 is not None
        assert abs(res4.value - 0.3442) < 0.001

    def test_vote_pct_pairs_sum_to_100(self, result: AnalysisResult):
        for_facts = {
            f.provenance.section: f.value
            for f in _facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR)
        }
        against_facts = {
            f.provenance.section: f.value
            for f in _facts(result, FactKind.GOVERNANCE_VOTE_PCT_AGAINST)
        }
        for section in for_facts:
            if section in against_facts:
                total = for_facts[section] + against_facts[section]
                assert abs(total - 100.0) < 0.05, f"{section}: {total} != 100"

    # -- Provenance ---------------------------------------------------------

    def test_all_facts_have_provenance_section(self, result: AnalysisResult):
        for f in result.facts:
            assert f.provenance.section, f"{f.kind} missing section"

    def test_vote_pct_confidence_is_medium(self, result: AnalysisResult):
        for f in _facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR):
            assert f.confidence == "medium"


# ---------------------------------------------------------------------------
# 31st AGM — 2026-06-09 (Format B: 3 resolutions, global outcome)
# ---------------------------------------------------------------------------


class TestAGM2026:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _AGM_2026_ID)
        return analyze(_AGM_2026_ID, kb)

    def test_returns_analysis_result(self, result: AnalysisResult):
        assert isinstance(result, AnalysisResult)

    def test_kind(self, result: AnalysisResult):
        assert result.kind == "agm_notice"

    def test_subtype_is_voting_results(self, result: AnalysisResult):
        assert result.excerpts["subtype"] == "voting_results"

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_agm_date(self, result: AnalysisResult):
        assert result.excerpts["agm_date"] == "2026-06-09"

    def test_three_resolution_titles(self, result: AnalysisResult):
        assert len(_facts(result, FactKind.GOVERNANCE_RESOLUTION_TITLE)) == 3

    def test_all_resolutions_passed(self, result: AnalysisResult):
        outcomes = _facts(result, FactKind.GOVERNANCE_RESOLUTION_OUTCOME)
        assert len(outcomes) == 3
        assert all(f.value == "passed" for f in outcomes)

    def test_three_vote_pct_facts(self, result: AnalysisResult):
        assert len(_facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR)) == 3

    def test_res3_pct_for(self, result: AnalysisResult):
        pcts = _facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR)
        res3 = next((f for f in pcts if f.provenance.section == "resolution_3"), None)
        assert res3 is not None
        assert abs(res3.value - 96.4936) < 0.001

    def test_res3_pct_against(self, result: AnalysisResult):
        pcts = _facts(result, FactKind.GOVERNANCE_VOTE_PCT_AGAINST)
        res3 = next((f for f in pcts if f.provenance.section == "resolution_3"), None)
        assert res3 is not None
        assert abs(res3.value - 3.5064) < 0.001

    def test_period_is_agm_date(self, result: AnalysisResult):
        for f in result.facts:
            assert f.period == "2026-06-09"


# ---------------------------------------------------------------------------
# 29th AGM — 2024-05-31 (Format A: 7 resolutions, only Res1 has vote pcts)
# ---------------------------------------------------------------------------


class TestAGM2024:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _AGM_2024_ID)
        return analyze(_AGM_2024_ID, kb)

    def test_returns_analysis_result(self, result: AnalysisResult):
        assert isinstance(result, AnalysisResult)

    def test_kind(self, result: AnalysisResult):
        assert result.kind == "agm_notice"

    def test_subtype_is_voting_results(self, result: AnalysisResult):
        assert result.excerpts["subtype"] == "voting_results"

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_agm_date(self, result: AnalysisResult):
        assert result.excerpts["agm_date"] == "2024-05-31"

    def test_seven_resolution_titles(self, result: AnalysisResult):
        assert len(_facts(result, FactKind.GOVERNANCE_RESOLUTION_TITLE)) == 7

    def test_all_resolutions_passed(self, result: AnalysisResult):
        outcomes = _facts(result, FactKind.GOVERNANCE_RESOLUTION_OUTCOME)
        assert all(f.value == "passed" for f in outcomes)

    def test_one_vote_pct_fact(self, result: AnalysisResult):
        # 2024 scrutineer report format only yields extractable pcts for Res1
        assert len(_facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR)) == 1

    def test_res1_pct_for(self, result: AnalysisResult):
        pcts = _facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR)
        assert abs(pcts[0].value - 99.9753) < 0.001

    def test_res1_pct_against(self, result: AnalysisResult):
        pcts = _facts(result, FactKind.GOVERNANCE_VOTE_PCT_AGAINST)
        assert abs(pcts[0].value - 0.0247) < 0.001

    def test_res1_section_name(self, result: AnalysisResult):
        pcts = _facts(result, FactKind.GOVERNANCE_VOTE_PCT_FOR)
        assert pcts[0].provenance.section == "resolution_1"
