"""Unit tests for atlas.analysis.buyback.

Covers all four document sub-types plus error cases. Uses entirely synthetic
fixtures — no real repository access required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit
from atlas.analysis.buyback import ANALYZER_VERSION, analyze

# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

# Type: Announcement — terms present in cover letter (2023-style)
_COVER_ANNOUNCEMENT = """\
TCS/BB/SE/207/2023-24

November 17, 2023

Dear Sirs,

Sub: Public Announcement for Buyback of Equity Shares

This is in furtherance of our letter no. TCS/BM/162/SE/2023-24 dated October 11, 2023 and letter
no. TCS/BB/SE/201/2023-24 dated November 15, 2023, informing the decision of the board of
directors and the members of the Company, respectively, to buyback up to 4,09,63,855 (Four crore
nine lakh sixty three thousand eight hundred and fifty five) fully paid-up equity shares of face value
of ₹1 each at ₹4,150 (Rupees four thousand one hundred and fifty only) per equity share for an
aggregate amount not exceeding ₹17,000 crore (Rupees seventeen thousand crore only) excluding
transaction costs, applicable taxes and other incidental and related expenses ("Buyback").

Pursuant to Regulation 30 we hereby enclose copies of Public Announcement.

Yours faithfully,
For Tata Consultancy Services Limited
Company Secretary
"""

# Type: Announcement — terms NOT in cover letter (2020-style, enclosed newspaper)
_COVER_ANNOUNCEMENT_OPAQUE = """\
TCS/BB/SE/127/2020-21

November 20, 2020

Dear Sirs,

Sub: Public Announcement for Buyback of Equity Shares

Pursuant to Regulation 30 read with Schedule III Part A Para A and Regulation 47 of Securities and
Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, 2015, we
hereby enclose copies of Public Announcement dated November 19, 2020, published in Financial
Express (English), Jansatta (Hindi) and Loksatta (Marathi) on November 20, 2020.

This is for your information and records.

Yours faithfully,
For Tata Consultancy Services Limited
Company Secretary
"""

# Type: Post-announcement — terms + record date
_COVER_POST_ANNOUNCEMENT = """\
TCS/BB/SE/247/2023-24

December 13, 2023

Dear Sirs,

Sub: Post Buyback Public Announcement for Buyback of Equity Shares

Pursuant to Regulation 24(vi) of the Securities and Exchange Board of India (Buy-Back of
Securities) Regulations, 2018, the Company has published Post Buyback Public Announcement for
the buyback of 4,09,63,855 (Four crore nine lakh sixty three thousand eight hundred and fifty five)
fully paid-up equity shares of face value of ₹1 (Rupee One) each from the existing
shareholders/beneficial owners of Equity Shares as on the Record Date
(i.e. Saturday, November 25, 2023), on a proportionate basis, through the Tender Offer route using
Stock Exchange mechanism, at a price of ₹4,150 (Rupees four thousand one hundred and fifty only)
per Equity Share payable in cash, for an aggregate consideration not exceeding ₹17,000 crore
(Rupees seventeen thousand crore only) excluding transaction costs.

Yours faithfully,
For Tata Consultancy Services Limited
Company Secretary
"""

# Type: Schedule — record date only
_COVER_SCHEDULE = """\
TCS/BB/SE/146/2020-21

December 9, 2020

Dear Sirs,

Sub: Buyback of Equity Shares - Update

Further to our letter no. TCS/BB/SE/126/2020-21 dated November 20, 2020, we wish to inform that
Securities and Exchange Board of India ("SEBI") has given its observation on the Draft Letter of Offer.

The record date for this purpose is November 28, 2020 as communicated vide our letter.

Schedule of Activities in relation to the Buyback is as follows:

Date of Opening of the Buy Back Offer Period    Friday, December 18, 2020
Date of Closing of the Buy Back Offer Period    Friday, January 1, 2021

Yours faithfully,
For Tata Consultancy Services Limited
"""

# Type: Extinguishment — share counts
_COVER_EXTINGUISHMENT = """\
TCS/BB/SE/49/2023-24

December 13, 2023

Dear Sirs,

Sub: Buyback of Equity Shares - Completion of extinguishment of a total of 4,09,63,855
Equity Shares.

Pursuant to the Public Announcement dated November 16, 2023 the Tendering Period for the Buyback
opened on Friday, December 1, 2023 and closed on Thursday, December 7, 2023.

Equity share capital before extinguishment: 365,90,51,373
Number of Equity Shares extinguished/destroyed: 4,09,63,855
Equity share capital after extinguishment: 361,80,87,518

Total Number of Equity Shares Extinguished/ Destroyed (A + B)  4,09,63,855

Yours faithfully,
For Tata Consultancy Services Limited
"""


# ---------------------------------------------------------------------------
# KB mock factory
# ---------------------------------------------------------------------------


def _make_kb(eid: str, content: str, kind: str = "buyback") -> MagicMock:
    entry = MagicMock()
    entry.kind = kind
    entry.evidence_id = eid
    entry.source_date = "2023-11-17T00:00:00+00:00"
    kb = MagicMock()
    kb.get.return_value = entry
    kb.get_content.return_value = content
    return kb


def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Common result structure
# ---------------------------------------------------------------------------


class TestResultStructure:
    def test_returns_analysis_result(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        assert isinstance(result, AnalysisResult)

    def test_evidence_id_preserved(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        assert result.evidence_id == "eid-a"

    def test_kind_is_buyback(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        assert result.kind == "buyback"

    def test_analyzer_version(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        assert result.analyzer_version == ANALYZER_VERSION

    def test_analyzed_at_is_utc(self) -> None:
        from datetime import timezone

        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        assert result.analyzed_at.tzinfo == timezone.utc

    def test_cover_letter_always_in_excerpts(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        assert "cover_letter" in result.excerpts

    def test_all_facts_have_provenance_section(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        for f in result.facts:
            assert f.provenance.section != ""


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrors:
    def test_raises_for_missing_entry(self) -> None:
        kb = MagicMock()
        kb.get.return_value = None
        with pytest.raises(ValueError, match="not in knowledge base"):
            analyze("missing", kb)

    def test_raises_for_wrong_kind(self) -> None:
        entry = MagicMock()
        entry.kind = "financial_results"
        kb = MagicMock()
        kb.get.return_value = entry
        with pytest.raises(ValueError, match="is not 'buyback'"):
            analyze("eid-x", kb)

    def test_raises_for_empty_content(self) -> None:
        entry = MagicMock()
        entry.kind = "buyback"
        kb = MagicMock()
        kb.get.return_value = entry
        kb.get_content.return_value = ""
        with pytest.raises(ValueError, match="has no content"):
            analyze("eid-x", kb)


# ---------------------------------------------------------------------------
# Type: Announcement (with terms)
# ---------------------------------------------------------------------------


class TestAnnouncement:
    def test_confidence_high(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        assert result.confidence == "high"

    def test_no_warnings(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        assert result.warnings == []

    def test_shares_offered(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        shares = _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_OFFERED)
        assert len(shares) == 1
        assert shares[0].value == 40963855

    def test_shares_offered_unit_count(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        shares = _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_OFFERED)
        assert shares[0].unit == FactUnit.COUNT

    def test_price_per_share(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        price = _facts(result, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE)
        assert len(price) == 1
        assert price[0].value == pytest.approx(4150.0)

    def test_price_per_share_unit(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        price = _facts(result, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE)
        assert price[0].unit == FactUnit.RUPEES_PER_SHARE

    def test_total_amount(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        amount = _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT)
        assert len(amount) == 1
        assert amount[0].value == pytest.approx(17000.0)

    def test_total_amount_unit_crore_inr(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        amount = _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT)
        assert amount[0].unit == FactUnit.CRORE_INR

    def test_no_record_date(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        assert _facts(result, FactKind.CAPITAL_BUYBACK_RECORD_DATE) == []

    def test_all_facts_period_none(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        for f in result.facts:
            assert f.period is None

    def test_all_facts_high_confidence(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_ANNOUNCEMENT))
        for f in result.facts:
            assert f.confidence == "high"


# ---------------------------------------------------------------------------
# Type: Announcement (opaque — terms in enclosed newspaper only)
# ---------------------------------------------------------------------------


class TestAnnouncementOpaque:
    def test_low_confidence(self) -> None:
        result = analyze("eid-op", _make_kb("eid-op", _COVER_ANNOUNCEMENT_OPAQUE))
        assert result.confidence == "low"

    def test_no_facts(self) -> None:
        result = analyze("eid-op", _make_kb("eid-op", _COVER_ANNOUNCEMENT_OPAQUE))
        assert result.facts == []

    def test_warns_about_terms_not_in_cover(self) -> None:
        result = analyze("eid-op", _make_kb("eid-op", _COVER_ANNOUNCEMENT_OPAQUE))
        assert any("not found in cover letter" in w for w in result.warnings)

    def test_cover_letter_in_excerpts(self) -> None:
        result = analyze("eid-op", _make_kb("eid-op", _COVER_ANNOUNCEMENT_OPAQUE))
        assert "cover_letter" in result.excerpts


# ---------------------------------------------------------------------------
# Type: Post-announcement
# ---------------------------------------------------------------------------


class TestPostAnnouncement:
    def test_confidence_high(self) -> None:
        result = analyze("eid-post", _make_kb("eid-post", _COVER_POST_ANNOUNCEMENT))
        assert result.confidence == "high"

    def test_shares_offered(self) -> None:
        result = analyze("eid-post", _make_kb("eid-post", _COVER_POST_ANNOUNCEMENT))
        shares = _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_OFFERED)
        assert len(shares) == 1
        assert shares[0].value == 40963855

    def test_price_per_share(self) -> None:
        result = analyze("eid-post", _make_kb("eid-post", _COVER_POST_ANNOUNCEMENT))
        price = _facts(result, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE)
        assert price[0].value == pytest.approx(4150.0)

    def test_total_amount(self) -> None:
        result = analyze("eid-post", _make_kb("eid-post", _COVER_POST_ANNOUNCEMENT))
        amount = _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT)
        assert amount[0].value == pytest.approx(17000.0)

    def test_record_date(self) -> None:
        result = analyze("eid-post", _make_kb("eid-post", _COVER_POST_ANNOUNCEMENT))
        rec = _facts(result, FactKind.CAPITAL_BUYBACK_RECORD_DATE)
        assert len(rec) == 1
        assert rec[0].value == "2023-11-25"

    def test_record_date_unit_iso_date(self) -> None:
        result = analyze("eid-post", _make_kb("eid-post", _COVER_POST_ANNOUNCEMENT))
        rec = _facts(result, FactKind.CAPITAL_BUYBACK_RECORD_DATE)
        assert rec[0].unit == FactUnit.ISO_DATE


# ---------------------------------------------------------------------------
# Type: Schedule / timeline update
# ---------------------------------------------------------------------------


class TestSchedule:
    def test_confidence_high(self) -> None:
        result = analyze("eid-sch", _make_kb("eid-sch", _COVER_SCHEDULE))
        assert result.confidence == "high"

    def test_record_date_extracted(self) -> None:
        result = analyze("eid-sch", _make_kb("eid-sch", _COVER_SCHEDULE))
        rec = _facts(result, FactKind.CAPITAL_BUYBACK_RECORD_DATE)
        assert len(rec) == 1
        assert rec[0].value == "2020-11-28"

    def test_no_financial_terms(self) -> None:
        result = analyze("eid-sch", _make_kb("eid-sch", _COVER_SCHEDULE))
        assert _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT) == []
        assert _facts(result, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE) == []


# ---------------------------------------------------------------------------
# Type: Extinguishment notice
# ---------------------------------------------------------------------------


class TestExtinguishment:
    def test_confidence_high(self) -> None:
        result = analyze("eid-ext", _make_kb("eid-ext", _COVER_EXTINGUISHMENT))
        assert result.confidence == "high"

    def test_shares_bought(self) -> None:
        result = analyze("eid-ext", _make_kb("eid-ext", _COVER_EXTINGUISHMENT))
        bought = _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_BOUGHT)
        assert len(bought) == 1
        assert bought[0].value == 40963855

    def test_shares_bought_unit_count(self) -> None:
        result = analyze("eid-ext", _make_kb("eid-ext", _COVER_EXTINGUISHMENT))
        bought = _facts(result, FactKind.CAPITAL_BUYBACK_SHARES_BOUGHT)
        assert bought[0].unit == FactUnit.COUNT

    def test_no_financial_terms(self) -> None:
        result = analyze("eid-ext", _make_kb("eid-ext", _COVER_EXTINGUISHMENT))
        assert _facts(result, FactKind.CAPITAL_BUYBACK_AMOUNT) == []
        assert _facts(result, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE) == []
