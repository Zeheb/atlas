"""Unit tests for atlas.analysis.credit_rating.

All tests use synthetic fixtures — no real repository access required.

Coverage:
  ESG cover letters:
    - Agency extraction (NSE Sustainability, CRISIL ESG)
    - Score extraction (numeric, prefixed "CRISIL ESG 74")
    - Category → CREDIT_OUTLOOK ("leader", "leadership")
    - Action extraction (reaffirmed, assigned)
    - Missing score warning
    - Missing action warning
    - No CREDIT_AMOUNT emitted for ESG

  Debt rating rationale PDFs:
    - Single long-term instrument row
    - Short-term instrument (Commercial Paper) — no outlook
    - Multiple instrument rows in one document
    - Embedded outlook in rating symbol "AAA(Stable)"
    - Amount extraction (Rs. / INR / crore)
    - Action extraction
    - No instrument table → warning
    - Key rationale excerpts (key_strengths, key_concerns, liquidity)

  Common:
    - Wrong kind raises ValueError
    - Missing evidence_id raises ValueError
    - Empty content raises ValueError
    - CREDIT_AGENCY emitted once per document
    - All facts carry period = source_date[:10]
    - Result-level confidence: high / medium / low
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from atlas.analysis.credit_rating import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _kb(content: str, kind: str = "credit_rating_report",
        source_date: str = "2025-12-12T06:08:59+00:00") -> MagicMock:
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
# Synthetic ESG cover letter fixtures
# ---------------------------------------------------------------------------

_ESG_NSE_REAFFIRMED = """\
TCS/SE/162/2025-26
December 12, 2025

Dear Sirs,

Sub: Disclosure under Regulation 30 — ESG Rating

Pursuant to Regulation 30 of SEBI Listing Regulations, we wish to inform you
that the NSE Sustainability Ratings & Analytics Limited (NSE Sustainability)
has reaffirmed the overall Environmental, Social and Governance (ESG) Rating
of 73 under the category 'Leader', based on disclosures of FY 2024-25.

Please note that the Company has not engaged NSE Sustainability for ESG Rating.
"""

_ESG_NSE_ASSIGNED = """\
TCS/SE/48/2025-26
June 6, 2025

Dear Sirs,

Sub: ESG Rating

We wish to inform that NSE Sustainability Ratings & Analytics Limited
('NSE Sustainability'), has assigned an ESG Rating of '73'.

Please note that the Company has not engaged NSE Sustainability for ESG Rating.
"""

_ESG_CRISIL_ASSIGNED = """\
TCS/SE/16/2025-26
April 18, 2025

Sub: ESG Rating

CRISIL ESG Ratings & Analytics Limited (CRISIL) has assigned an ESG rating of
'CRISIL ESG 74' under the category 'Leadership'.

Please note that the Company has not engaged CRISIL for ESG Rating.
"""

# ---------------------------------------------------------------------------
# Synthetic debt rating fixture (CRISIL long-term + CP)
# ---------------------------------------------------------------------------

_DEBT_CRISIL_LT_CP = """\
CRISIL Ratings
Rating Rationale

Tata Consultancy Services Limited
Ratings
Long-term Bank Facilities  Rs. 1,000 Crore  CRISIL AAA  Reaffirmed  Stable
Commercial Paper           Rs. 500 Crore    CRISIL A1+  Reaffirmed  --

Rationale
Key Rating Strengths
Strong market position and diversified revenue stream.
Robust cash generation and low leverage.

Key Rating Concerns
Exposure to foreign exchange volatility.
High concentration in a few clients.

Liquidity: Strong
Adequate liquidity with significant cash reserves.
"""

_DEBT_ICRA_NCD = """\
ICRA LIMITED
Rating Action

Instruments Rated:
Non-Convertible Debentures  [ICRA]AAA(Stable)  Assigned  INR 2,000 Crore

Key Strengths
Established track record and leadership position.

Key Concerns
Regulatory changes in major markets.

Liquidity:
Adequate cash and bank balances.
"""

_DEBT_NO_TABLE = """\
CRISIL Ratings

Rating Update

The rating for XYZ Limited has been upgraded.

Key Strengths
Improved financial profile following debt reduction.
"""


# ---------------------------------------------------------------------------
# ESG: NSE reaffirmed
# ---------------------------------------------------------------------------

class TestESGNSEReaffirmed:
    @pytest.fixture(scope="class")
    def result(self):
        return analyze("esg-001", _kb(_ESG_NSE_REAFFIRMED))

    def test_returns_analysis_result(self, result):
        assert isinstance(result, AnalysisResult)

    def test_analyzer_version(self, result):
        assert result.analyzer_version == ANALYZER_VERSION

    def test_confidence_high(self, result):
        assert result.confidence == "high"

    def test_no_warnings(self, result):
        assert result.warnings == []

    def test_agency_nse_sustainability(self, result):
        facts = _facts(result, FactKind.CREDIT_AGENCY)
        assert len(facts) == 1
        assert facts[0].value == "NSE Sustainability"
        assert facts[0].unit is None

    def test_agency_period(self, result):
        facts = _facts(result, FactKind.CREDIT_AGENCY)
        assert facts[0].period == "2025-12-12"

    def test_instrument_esg(self, result):
        facts = _facts(result, FactKind.CREDIT_INSTRUMENT)
        assert len(facts) == 1
        assert facts[0].value == "ESG"

    def test_rating_73(self, result):
        facts = _facts(result, FactKind.CREDIT_RATING)
        assert len(facts) == 1
        assert facts[0].value == "73"

    def test_outlook_leader(self, result):
        facts = _facts(result, FactKind.CREDIT_OUTLOOK)
        assert len(facts) == 1
        assert facts[0].value == "leader"

    def test_action_reaffirmed(self, result):
        facts = _facts(result, FactKind.CREDIT_ACTION)
        assert len(facts) == 1
        assert facts[0].value == "reaffirmed"

    def test_no_credit_amount(self, result):
        # ESG ratings carry no rated amount
        assert _facts(result, FactKind.CREDIT_AMOUNT) == []

    def test_cover_letter_in_excerpts(self, result):
        assert "cover_letter" in result.excerpts


# ---------------------------------------------------------------------------
# ESG: NSE assigned (no category)
# ---------------------------------------------------------------------------

class TestESGNSEAssigned:
    @pytest.fixture(scope="class")
    def result(self):
        return analyze("esg-002", _kb(_ESG_NSE_ASSIGNED))

    def test_confidence_high(self, result):
        # Has agency + rating + action even without category
        assert result.confidence == "high"

    def test_action_assigned(self, result):
        facts = _facts(result, FactKind.CREDIT_ACTION)
        assert facts[0].value == "assigned"

    def test_rating_73(self, result):
        assert _facts(result, FactKind.CREDIT_RATING)[0].value == "73"

    def test_no_outlook_when_no_category(self, result):
        # This fixture has no "under the category" phrase
        assert _facts(result, FactKind.CREDIT_OUTLOOK) == []


# ---------------------------------------------------------------------------
# ESG: CRISIL assigned with prefixed score and "Leadership" category
# ---------------------------------------------------------------------------

class TestESGCRISILAssigned:
    @pytest.fixture(scope="class")
    def result(self):
        return analyze("esg-003", _kb(_ESG_CRISIL_ASSIGNED))

    def test_agency_crisil_esg(self, result):
        facts = _facts(result, FactKind.CREDIT_AGENCY)
        assert facts[0].value == "CRISIL ESG"

    def test_rating_crisil_esg_74(self, result):
        facts = _facts(result, FactKind.CREDIT_RATING)
        assert facts[0].value == "CRISIL ESG 74"

    def test_outlook_leadership(self, result):
        facts = _facts(result, FactKind.CREDIT_OUTLOOK)
        assert facts[0].value == "leadership"

    def test_action_assigned(self, result):
        facts = _facts(result, FactKind.CREDIT_ACTION)
        assert facts[0].value == "assigned"

    def test_confidence_high(self, result):
        assert result.confidence == "high"


# ---------------------------------------------------------------------------
# Debt: CRISIL with LT + CP instruments
# ---------------------------------------------------------------------------

class TestDebtCRISILLtCp:
    @pytest.fixture(scope="class")
    def result(self):
        return analyze("debt-001", _kb(_DEBT_CRISIL_LT_CP))

    def test_confidence_high(self, result):
        assert result.confidence == "high"

    def test_agency_crisil(self, result):
        facts = _facts(result, FactKind.CREDIT_AGENCY)
        assert len(facts) == 1
        assert facts[0].value == "CRISIL"

    def test_two_instruments(self, result):
        facts = _facts(result, FactKind.CREDIT_INSTRUMENT)
        labels = {f.value for f in facts}
        assert "Long-term Bank Facilities" in labels
        assert "Commercial Paper" in labels

    def test_lt_rating(self, result):
        # Should find CRISIL AAA for LT instrument
        ratings = _facts(result, FactKind.CREDIT_RATING)
        values = {f.value for f in ratings}
        assert any("AAA" in v for v in values)

    def test_cp_rating(self, result):
        ratings = _facts(result, FactKind.CREDIT_RATING)
        values = {f.value for f in ratings}
        assert any("A1" in v for v in values)

    def test_lt_outlook_stable(self, result):
        outlooks = _facts(result, FactKind.CREDIT_OUTLOOK)
        assert any(f.value == "stable" for f in outlooks)

    def test_lt_amount_1000(self, result):
        amounts = _facts(result, FactKind.CREDIT_AMOUNT)
        values = {f.value for f in amounts}
        assert 1000.0 in values

    def test_cp_amount_500(self, result):
        amounts = _facts(result, FactKind.CREDIT_AMOUNT)
        values = {f.value for f in amounts}
        assert 500.0 in values

    def test_amounts_unit_crore_inr(self, result):
        for f in _facts(result, FactKind.CREDIT_AMOUNT):
            assert f.unit == FactUnit.CRORE_INR

    def test_action_reaffirmed(self, result):
        actions = _facts(result, FactKind.CREDIT_ACTION)
        assert all(f.value == "reaffirmed" for f in actions)

    def test_key_strengths_excerpt(self, result):
        assert "key_strengths" in result.excerpts
        assert "market position" in result.excerpts["key_strengths"].lower()

    def test_key_concerns_excerpt(self, result):
        assert "key_concerns" in result.excerpts

    def test_liquidity_excerpt(self, result):
        assert "liquidity" in result.excerpts


# ---------------------------------------------------------------------------
# Debt: ICRA NCD with embedded outlook in rating symbol
# ---------------------------------------------------------------------------

class TestDebtICRANCD:
    @pytest.fixture(scope="class")
    def result(self):
        return analyze("debt-002", _kb(_DEBT_ICRA_NCD))

    def test_agency_icra(self, result):
        facts = _facts(result, FactKind.CREDIT_AGENCY)
        assert facts[0].value == "ICRA"

    def test_instrument_ncd(self, result):
        facts = _facts(result, FactKind.CREDIT_INSTRUMENT)
        assert any("Non-Convertible Debentures" in f.value for f in facts)

    def test_rating_contains_aaa(self, result):
        ratings = _facts(result, FactKind.CREDIT_RATING)
        assert any("AAA" in f.value for f in ratings)

    def test_outlook_stable_from_embedded(self, result):
        outlooks = _facts(result, FactKind.CREDIT_OUTLOOK)
        assert any(f.value == "stable" for f in outlooks)

    def test_amount_2000(self, result):
        amounts = _facts(result, FactKind.CREDIT_AMOUNT)
        assert any(f.value == 2000.0 for f in amounts)

    def test_action_assigned(self, result):
        actions = _facts(result, FactKind.CREDIT_ACTION)
        assert any(f.value == "assigned" for f in actions)


# ---------------------------------------------------------------------------
# Debt: no instrument table (cover letter only) → warning
# ---------------------------------------------------------------------------

class TestDebtNoTable:
    @pytest.fixture(scope="class")
    def result(self):
        return analyze("debt-003", _kb(_DEBT_NO_TABLE))

    def test_no_instrument_facts(self, result):
        assert _facts(result, FactKind.CREDIT_INSTRUMENT) == []

    def test_warning_no_instrument_table(self, result):
        assert any("instrument" in w.lower() for w in result.warnings)

    def test_agency_still_extracted(self, result):
        # CRISIL is still mentioned
        facts = _facts(result, FactKind.CREDIT_AGENCY)
        assert facts[0].value == "CRISIL"

    def test_key_strengths_excerpt(self, result):
        assert "key_strengths" in result.excerpts


# ---------------------------------------------------------------------------
# Period assignment
# ---------------------------------------------------------------------------

class TestPeriod:
    def test_all_facts_carry_source_date_as_period(self):
        result = analyze("x", _kb(_ESG_NSE_REAFFIRMED, source_date="2025-12-12T06:08:59+00:00"))
        for f in result.facts:
            assert f.period == "2025-12-12"

    def test_different_source_dates(self):
        result = analyze("x", _kb(_ESG_NSE_ASSIGNED, source_date="2025-06-06T13:47:56+00:00"))
        for f in result.facts:
            assert f.period == "2025-06-06"


# ---------------------------------------------------------------------------
# Confidence logic
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_high_when_agency_rating_action(self):
        result = analyze("x", _kb(_ESG_NSE_REAFFIRMED))
        assert result.confidence == "high"

    def test_medium_when_agency_and_rating_no_action(self):
        # Craft text with agency + score but no action word
        text = """\
NSE Sustainability Ratings & Analytics Limited
ESG Rating of 80 under the category 'Leader'.
"""
        result = analyze("x", _kb(text))
        assert result.confidence == "medium"
        assert any("action" in w.lower() for w in result.warnings)

    def test_low_when_nothing_found(self):
        result = analyze("x", _kb("Some generic document with no ratings."))
        assert result.confidence == "low"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_wrong_kind_raises(self):
        with pytest.raises(ValueError, match="not 'credit_rating_report'"):
            analyze("x", _kb("irrelevant", kind="board_outcome"))

    def test_missing_evidence_raises(self):
        kb = MagicMock()
        kb.get.return_value = None
        with pytest.raises(ValueError, match="not in knowledge base"):
            analyze("x", kb)

    def test_empty_content_raises(self):
        kb = MagicMock()
        entry = MagicMock()
        entry.kind = "credit_rating_report"
        entry.source_date = "2025-12-12T06:08:59+00:00"
        kb.get.return_value = entry
        kb.get_content.return_value = None
        with pytest.raises(ValueError, match="no content"):
            analyze("x", kb)


# ---------------------------------------------------------------------------
# Agency detection ordering (more specific patterns win)
# ---------------------------------------------------------------------------

class TestAgencyDetection:
    def _result(self, text: str) -> AnalysisResult:
        return analyze("x", _kb(text))

    def test_crisil_esg_wins_over_crisil(self):
        text = "CRISIL ESG Ratings & Analytics Limited (CRISIL) has assigned an ESG rating."
        result = self._result(text)
        agency = _facts(result, FactKind.CREDIT_AGENCY)[0].value
        assert agency == "CRISIL ESG"

    def test_care_ratings_detected(self):
        text = "CARE Ratings has reaffirmed the rating of Non-Convertible Debentures Rs. 1000 Crore CARE AAA Stable."
        result = analyze("x", _kb(text))
        agency = _facts(result, FactKind.CREDIT_AGENCY)[0].value
        assert agency == "CARE Ratings"

    def test_india_ratings_detected(self):
        text = "India Ratings and Research has assigned IND AAA/Stable to the Long-term Bank Facilities of Rs. 500 Crore."
        result = analyze("x", _kb(text))
        agency = _facts(result, FactKind.CREDIT_AGENCY)[0].value
        assert agency == "India Ratings"


# ---------------------------------------------------------------------------
# Revision-table parsing (CARE / India Ratings BSE intimation format)
# ---------------------------------------------------------------------------

_REVISION_TABLE_TEXT = (
    "Details of revision in ratings for Company:\n"
    "Name of the Company\tCredit Rating Agency\tType of Credit Rating\tExisting\tRevised\n"
    "Tata Steel Limited\tCARE Ratings\tLong-term credit rating\t"
    "‘AA’\nOutlook:\nNegative\t"
    "‘AA+’\nOutlook:\nStable\n"
    "The report from the credit rating agency covering the rationale for revision is enclosed."
)


class TestRevisionTableParsing:
    def _result(self, text: str = _REVISION_TABLE_TEXT) -> AnalysisResult:
        return analyze("x", _kb(text))

    def test_revised_rating_extracted(self) -> None:
        rating = _facts(self._result(), FactKind.CREDIT_RATING)
        assert rating and rating[0].value == "AA+"

    def test_revised_outlook_is_stable_not_existing(self) -> None:
        # Regression: prior bug extracted 'negative' (Existing column) instead
        # of 'stable' (Revised column) because the outlook search started at
        # m.start() (the 'Revised' header) rather than m.end() (after 'AA+').
        outlook = _facts(self._result(), FactKind.CREDIT_OUTLOOK)
        assert outlook and outlook[0].value == "stable"

    def test_action_is_revised(self) -> None:
        actions = _facts(self._result(), FactKind.CREDIT_ACTION)
        assert any(a.value == "revised" for a in actions)

    def test_instrument_is_long_term(self) -> None:
        instruments = _facts(self._result(), FactKind.CREDIT_INSTRUMENT)
        # Should have revision_table section instrument
        assert any(i.value == "Long-term" for i in instruments)
