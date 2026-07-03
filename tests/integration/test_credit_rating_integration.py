"""Integration tests for atlas.analysis.credit_rating.

Uses the three real TCS ESG rating cover letters in the repository:
  bse-news-f5e7effc  ESG Rating (NSE Sustainability, Dec 2025) — reaffirmed 73, "Leader"
  bse-news-cc058c30  ESG Rating (NSE Sustainability, Jun 2025) — assigned 73, no category
  bse-news-820cd8b2  ESG Rating (CRISIL ESG, Apr 2025)        — assigned "CRISIL ESG 74", "Leadership"

Run with: pytest -m integration -v -s

Note: TCS carries no rated debt so no CRISIL/ICRA/CARE debt rating PDFs exist
in this repository.  All three real documents are ESG cover letters.
"""
from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.credit_rating import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.knowledge.base import KnowledgeBase
from atlas.acquisition.repository import Repository

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

_ID_NSE_DEC  = "bse-news-f5e7effc-58ad-40dd-9418-cd55733c6b8c"
_ID_NSE_JUN  = "bse-news-cc058c30-6e60-4779-b61e-67f67028408d"
_ID_CRISIL   = "bse-news-820cd8b2-2882-4766-819e-10f0c0dc8714"

_ALL_IDS = [_ID_NSE_DEC, _ID_NSE_JUN, _ID_CRISIL]


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


def _facts(result: AnalysisResult, kind: FactKind):
    return [f for f in result.facts if f.kind == kind]


def _skip_if_not_parsed(kb: KnowledgeBase, eid: str) -> None:
    entry = kb.get(eid)
    if entry is None or entry.status != "ok":
        pytest.skip(f"{eid[:16]}... not parsed")


# ---------------------------------------------------------------------------
# NSE Sustainability Dec 2025 — reaffirmed 73, "Leader"
# ---------------------------------------------------------------------------

class TestNSEDecReaffirmed:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_NSE_DEC)
        return analyze(_ID_NSE_DEC, kb)

    def test_returns_analysis_result(self, result: AnalysisResult):
        assert isinstance(result, AnalysisResult)

    def test_analyzer_version(self, result: AnalysisResult):
        assert result.analyzer_version == ANALYZER_VERSION

    def test_kind(self, result: AnalysisResult):
        assert result.kind == "credit_rating_report"

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_no_warnings(self, result: AnalysisResult):
        assert result.warnings == [], result.warnings

    def test_agency_nse_sustainability(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_AGENCY)
        assert len(facts) == 1
        assert facts[0].value == "NSE Sustainability"

    def test_instrument_esg(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_INSTRUMENT)
        assert len(facts) == 1
        assert facts[0].value == "ESG"

    def test_rating_73(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_RATING)
        assert len(facts) == 1
        assert facts[0].value == "73"

    def test_outlook_leader(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_OUTLOOK)
        assert len(facts) == 1
        assert facts[0].value == "leader"

    def test_action_reaffirmed(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_ACTION)
        assert len(facts) == 1
        assert facts[0].value == "reaffirmed"

    def test_period_is_filing_date(self, result: AnalysisResult):
        for f in result.facts:
            assert f.period == "2025-12-12"

    def test_no_credit_amount(self, result: AnalysisResult):
        assert _facts(result, FactKind.CREDIT_AMOUNT) == []

    def test_cover_letter_in_excerpts(self, result: AnalysisResult):
        assert "cover_letter" in result.excerpts
        assert len(result.excerpts["cover_letter"]) > 100

    def test_source_date_preserved(self, result: AnalysisResult):
        assert result.source_date.year == 2025
        assert result.source_date.month == 12


# ---------------------------------------------------------------------------
# NSE Sustainability Jun 2025 — assigned 73, no category phrase
# ---------------------------------------------------------------------------

class TestNSEJunAssigned:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_NSE_JUN)
        return analyze(_ID_NSE_JUN, kb)

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_agency_nse_sustainability(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_AGENCY)
        assert facts[0].value == "NSE Sustainability"

    def test_rating_73(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_RATING)
        assert facts[0].value == "73"

    def test_action_assigned(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_ACTION)
        assert facts[0].value == "assigned"

    def test_no_outlook_no_category(self, result: AnalysisResult):
        # This cover letter has no "under the category" phrase
        assert _facts(result, FactKind.CREDIT_OUTLOOK) == []

    def test_period_is_filing_date(self, result: AnalysisResult):
        for f in result.facts:
            assert f.period == "2025-06-06"


# ---------------------------------------------------------------------------
# CRISIL ESG Apr 2025 — assigned "CRISIL ESG 74", "Leadership"
# ---------------------------------------------------------------------------

class TestCRISILESGAssigned:
    @pytest.fixture(scope="class")
    def result(self, kb: KnowledgeBase) -> AnalysisResult:
        _skip_if_not_parsed(kb, _ID_CRISIL)
        return analyze(_ID_CRISIL, kb)

    def test_confidence_high(self, result: AnalysisResult):
        assert result.confidence == "high"

    def test_agency_crisil_esg(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_AGENCY)
        assert facts[0].value == "CRISIL ESG"

    def test_rating_crisil_esg_74(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_RATING)
        assert len(facts) == 1
        # Value is the full prefixed score from the filing
        assert "74" in facts[0].value

    def test_action_assigned(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_ACTION)
        assert facts[0].value == "assigned"

    def test_outlook_leadership(self, result: AnalysisResult):
        facts = _facts(result, FactKind.CREDIT_OUTLOOK)
        assert len(facts) == 1
        assert facts[0].value == "leadership"

    def test_period_is_filing_date(self, result: AnalysisResult):
        for f in result.facts:
            assert f.period == "2025-04-18"


# ---------------------------------------------------------------------------
# Cross-document invariants
# ---------------------------------------------------------------------------

class TestCrossDocumentInvariants:
    @pytest.fixture(scope="class")
    def results(self, kb: KnowledgeBase) -> list[AnalysisResult]:
        out = []
        for eid in _ALL_IDS:
            _skip_if_not_parsed(kb, eid)
            out.append(analyze(eid, kb))
        return out

    def test_all_high_confidence(self, results: list[AnalysisResult]):
        for r in results:
            assert r.confidence == "high", f"{r.evidence_id}: confidence={r.confidence}"

    def test_all_have_agency(self, results: list[AnalysisResult]):
        for r in results:
            assert _facts(r, FactKind.CREDIT_AGENCY), f"{r.evidence_id} missing CREDIT_AGENCY"

    def test_all_have_rating(self, results: list[AnalysisResult]):
        for r in results:
            assert _facts(r, FactKind.CREDIT_RATING), f"{r.evidence_id} missing CREDIT_RATING"

    def test_all_have_action(self, results: list[AnalysisResult]):
        for r in results:
            assert _facts(r, FactKind.CREDIT_ACTION), f"{r.evidence_id} missing CREDIT_ACTION"

    def test_all_instrument_is_esg(self, results: list[AnalysisResult]):
        for r in results:
            instruments = _facts(r, FactKind.CREDIT_INSTRUMENT)
            assert all(f.value == "ESG" for f in instruments)

    def test_no_amounts_in_any_doc(self, results: list[AnalysisResult]):
        for r in results:
            assert _facts(r, FactKind.CREDIT_AMOUNT) == []

    def test_all_agency_facts_no_unit(self, results: list[AnalysisResult]):
        for r in results:
            for f in _facts(r, FactKind.CREDIT_AGENCY):
                assert f.unit is None

    def test_all_facts_have_provenance_section(self, results: list[AnalysisResult]):
        for r in results:
            for f in r.facts:
                assert f.provenance.section, f"{r.evidence_id} fact {f.kind} missing section"
