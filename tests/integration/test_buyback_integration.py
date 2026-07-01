"""Integration tests for atlas.analysis.buyback against real TCS filings.

Run with: pytest -m integration -v -s

Validates all five buyback documents in the TCS repository:
  853000ae  2020 Public Announcement — terms in enclosed newspaper (opaque)
  b1dc2c18  2020 Schedule of Activities — record date update
  6233389e  2023 Public Announcement — terms in cover letter
  4d4a5575  2023 Post Buyback Public Announcement — terms + record date
  8b2b0027  2023 Extinguishment notice — shares bought back
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.buyback import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit
from atlas.knowledge.base import KnowledgeBase
from atlas.acquisition.repository import Repository
from atlas.acquisition.evidence import EvidenceKind

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

_ID_2020_PA       = "bse-news-853000ae-953d-4891-a58d-074e435e0de5"
_ID_2020_SCHEDULE = "bse-news-b1dc2c18-b69e-41c1-8e44-0614630cea37"
_ID_2023_PA       = "bse-news-6233389e-6f1b-4545-a03b-d3fca0b40cfb"
_ID_2023_POST_PA  = "bse-news-4d4a5575-3bbf-40c5-9e32-613f51c84105"
_ID_2023_EXT      = "bse-news-8b2b0027-67c5-4eb6-8012-153d22b30750"

_ALL_IDS = [_ID_2020_PA, _ID_2020_SCHEDULE, _ID_2023_PA, _ID_2023_POST_PA, _ID_2023_EXT]


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


def _skip_if_not_parsed(kb: KnowledgeBase, eid: str) -> None:
    entry = kb.get(eid)
    if entry is None or entry.status != "ok":
        pytest.skip(f"{eid[:16]}... not parsed")


# ---------------------------------------------------------------------------
# 2020 Public Announcement — opaque (terms in enclosed newspaper, not cover)
# ---------------------------------------------------------------------------

class Test2020PA:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_2020_PA)
        return analyze(_ID_2020_PA, kb)

    def test_returns_analysis_result(self, result: AnalysisResult) -> None:
        assert isinstance(result, AnalysisResult)

    def test_analyzer_version(self, result: AnalysisResult) -> None:
        assert result.analyzer_version == ANALYZER_VERSION

    def test_confidence_not_high(self, result: AnalysisResult) -> None:
        # Terms are in garbled newspaper — expect low or at most medium
        assert result.confidence in ("low", "medium")

    def test_warns_about_missing_terms(self, result: AnalysisResult) -> None:
        combined = " ".join(result.warnings)
        assert "cover letter" in combined.lower() or "not found" in combined.lower()

    def test_cover_letter_in_excerpts(self, result: AnalysisResult) -> None:
        assert "cover_letter" in result.excerpts

    def test_no_reliable_financial_facts(self, result: AnalysisResult) -> None:
        # The 2020 PA cover letter does not state the buyback terms
        # so either no amount fact is extracted, or if by coincidence
        # one is, it must come with a warning too
        amount = _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT)
        if amount:
            assert result.warnings  # must warn if terms came from garbled text


# ---------------------------------------------------------------------------
# 2020 Schedule of Activities — record date update
# ---------------------------------------------------------------------------

class Test2020Schedule:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_2020_SCHEDULE)
        return analyze(_ID_2020_SCHEDULE, kb)

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_no_warnings(self, result: AnalysisResult) -> None:
        assert result.warnings == []

    def test_record_date_2020_11_28(self, result: AnalysisResult) -> None:
        rec = _facts(result, FactKind.CAPITAL_BUYBACK_RECORD_DATE)
        assert len(rec) == 1
        assert rec[0].value == "2020-11-28"

    def test_record_date_unit_iso_date(self, result: AnalysisResult) -> None:
        rec = _facts(result, FactKind.CAPITAL_BUYBACK_RECORD_DATE)
        assert rec[0].unit == FactUnit.ISO_DATE

    def test_no_financial_terms(self, result: AnalysisResult) -> None:
        assert _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT) == []
        assert _facts(result, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE) == []
        assert _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_OFFERED) == []


# ---------------------------------------------------------------------------
# 2023 Public Announcement — terms in cover letter
# ---------------------------------------------------------------------------

class Test2023PA:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_2023_PA)
        return analyze(_ID_2023_PA, kb)

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_no_warnings(self, result: AnalysisResult) -> None:
        assert result.warnings == []

    def test_shares_offered(self, result: AnalysisResult) -> None:
        shares = _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_OFFERED)
        assert len(shares) == 1
        assert shares[0].value == 40963855

    def test_shares_offered_unit(self, result: AnalysisResult) -> None:
        shares = _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_OFFERED)
        assert shares[0].unit == FactUnit.COUNT

    def test_price_per_share(self, result: AnalysisResult) -> None:
        price = _facts(result, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE)
        assert len(price) == 1
        assert price[0].value == pytest.approx(4150.0)

    def test_price_per_share_unit(self, result: AnalysisResult) -> None:
        price = _facts(result, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE)
        assert price[0].unit == FactUnit.RUPEES_PER_SHARE

    def test_total_amount(self, result: AnalysisResult) -> None:
        amount = _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT)
        assert len(amount) == 1
        assert amount[0].value == pytest.approx(17000.0)

    def test_total_amount_unit(self, result: AnalysisResult) -> None:
        amount = _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT)
        assert amount[0].unit == FactUnit.CRORE_INR

    def test_all_facts_from_cover_letter(self, result: AnalysisResult) -> None:
        for f in result.facts:
            assert f.provenance.section == "cover_letter"

    def test_all_facts_have_char_offset(self, result: AnalysisResult) -> None:
        for f in result.facts:
            assert f.provenance.char_offset is not None


# ---------------------------------------------------------------------------
# 2023 Post Buyback Public Announcement
# ---------------------------------------------------------------------------

class Test2023PostPA:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_2023_POST_PA)
        return analyze(_ID_2023_POST_PA, kb)

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_shares_offered(self, result: AnalysisResult) -> None:
        shares = _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_OFFERED)
        assert len(shares) == 1
        assert shares[0].value == 40963855

    def test_price_per_share(self, result: AnalysisResult) -> None:
        price = _facts(result, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE)
        assert price[0].value == pytest.approx(4150.0)

    def test_total_amount(self, result: AnalysisResult) -> None:
        amount = _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT)
        assert amount[0].value == pytest.approx(17000.0)

    def test_record_date_2023_11_25(self, result: AnalysisResult) -> None:
        rec = _facts(result, FactKind.CAPITAL_BUYBACK_RECORD_DATE)
        assert len(rec) == 1
        assert rec[0].value == "2023-11-25"

    def test_record_date_unit_iso_date(self, result: AnalysisResult) -> None:
        rec = _facts(result, FactKind.CAPITAL_BUYBACK_RECORD_DATE)
        assert rec[0].unit == FactUnit.ISO_DATE


# ---------------------------------------------------------------------------
# 2023 Extinguishment / completion notice
# ---------------------------------------------------------------------------

class Test2023Extinguishment:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_2023_EXT)
        return analyze(_ID_2023_EXT, kb)

    def test_confidence_high(self, result: AnalysisResult) -> None:
        assert result.confidence == "high"

    def test_shares_bought(self, result: AnalysisResult) -> None:
        bought = _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_BOUGHT)
        assert len(bought) == 1
        assert bought[0].value == 40963855

    def test_shares_bought_unit_count(self, result: AnalysisResult) -> None:
        bought = _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_BOUGHT)
        assert bought[0].unit == FactUnit.COUNT

    def test_no_financial_terms(self, result: AnalysisResult) -> None:
        assert _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT) == []
        assert _facts(result, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE) == []

    def test_cover_letter_in_excerpts(self, result: AnalysisResult) -> None:
        assert "cover_letter" in result.excerpts
