"""Unit tests for atlas.analysis.board_outcome.

Covers all four document sub-types and error cases using synthetic fixtures.
No real repository access required.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from atlas.analysis.board_outcome import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit


# ---------------------------------------------------------------------------
# Synthetic document fixtures
# ---------------------------------------------------------------------------

# Sub-type: Results meeting + interim dividend (with record and payment dates)
_COVER_INTERIM_DIVIDEND = """\
TCS/BM/154/SE/2024-25

October 10, 2024

Dear Sirs,

Sub: Financial Results for the quarter and six-month period ended September 30, 2024, \
and declaration of second interim dividend

We enclose the audited standalone financial results of the Company and audited \
consolidated financial results of the Company and its subsidiaries for the quarter \
and six-month period ended September 30, 2024, under Ind AS ("the Statement"), which \
have been approved and taken on record at a meeting of the Board of Directors of the \
Company held today.

We would like to inform you that at the Board Meeting held today, the Directors have \
declared second interim dividend of INR 10 per Equity Share of INR 1 each of the Company.

The second interim dividend shall be paid on Tuesday, November 5, 2024, to the equity \
shareholders of the Company whose names appear on the Register of Members as on Friday, \
October 18, 2024, which is the Record Date fixed for the purpose.

Yours faithfully,
For Tata Consultancy Services Limited
Company Secretary
"""

# Sub-type: Final dividend recommended (no record/payment date yet — pending AGM)
_COVER_FINAL_DIVIDEND = """\
TCS/BM/5/SE/2026-27

April 9, 2026

Dear Sirs,

Sub: Financial Results for the year ended March 31, 2026 and Recommendation of a \
Final Dividend

We enclose the audited standalone financial results of the Company and audited \
consolidated financial results for the year ended March 31, 2026.

Further, we would like to inform you that at the Board Meeting held today, the \
Directors have recommended a Final Dividend of INR 31 per Equity Share of INR 1 each \
of the Company which shall be paid on the third day from the conclusion of the 31st \
Annual General Meeting, subject to approval of the shareholders of the Company.

Yours faithfully,
For Tata Consultancy Services Limited
Company Secretary
"""

# Sub-type: Acquisition — Annexure A with "Name of the target entity"
_COVER_ACQUISITION = """\
TCS/SE/160/2025-26
December 10, 2025

Dear Sirs,

Sub: Disclosure under Regulation 30 of SEBI (LODR) Regulations, 2015

Pursuant to Regulation 30 of the SEBI (LODR) Regulations, 2015, we wish to inform \
you that the Board of Directors of Tata Consultancy Services Limited ("Company") at \
its meeting held today inter alia considered and approved execution of a Securities \
Purchase Agreement for acquisition of Acme Cloud Holdings, LLC and its subsidiaries.

Yours faithfully,
For Tata Consultancy Services Limited
Company Secretary
"""

_ANNEXURE_A_ACQUISITION = """\
Annexure - A
Details under Regulation 30 of the SEBI (LODR) Regulations, 2015

Sr. No.  Particulars                                     Details
1.       Name of the target entity, details in brief
         such as size, turnover etc.
         Acme Cloud Holdings, LLC — a leading cloud consulting firm.

2.       Whether the acquisition would fall within related party transaction(s)
         No

7.       Consideration — whether cash consideration or share swap or any other form
         Cash consideration

8.       Cost of acquisition
         Enterprise Value of up to USD 500 million

9.       Percentage of shareholding / control acquired
         100%

10.      Indicative time period for completion
         The transaction is expected to be completed by March 31, 2026.
"""

_FULL_ACQUISITION = _COVER_ACQUISITION + _ANNEXURE_A_ACQUISITION

# Sub-type: Pure JV / distribution agreement (no investment amount, no SSA)
_COVER_AGREEMENT = """\
TCS/SE/140/2025-26
September 15, 2025

Dear Sirs,

Sub: Disclosure under Regulation 30 of SEBI (LODR) Regulations, 2015

Pursuant to Regulation 30 of the SEBI (LODR) Regulations, 2015, Tata Consultancy \
Services Limited has today entered into a Joint Venture Agreement with GlobalRetail \
Corp for a multi-year digital transformation partnership.

Yours faithfully,
For Tata Consultancy Services Limited
Company Secretary
"""

_ANNEXURE_A_AGREEMENT = """\
Annexure - A
Details as per Regulation 30 of the SEBI (LODR) Regulations, 2015

Sr. No.  Particulars                                   Details
1.       Name(s) of parties with whom the agreement    Tata Consultancy Services Limited
         is entered                                    and GlobalRetail Corp.

2.       Purpose of entering into the agreement        Multi-year digital transformation
                                                       services partnership.
"""

_FULL_AGREEMENT = _COVER_AGREEMENT + _ANNEXURE_A_AGREEMENT

# Sub-type: Investment (SSA into wholly-owned subsidiary with external co-investor)
_COVER_INVESTMENT = """\
TCS/SE/150/2025-26
November 20, 2025

Dear Sirs,

Sub: Disclosure under Regulation 30 of SEBI (LODR) Regulations, 2015

Pursuant to Regulation 30 of the SEBI (LODR) Regulations, 2015, Tata Consultancy \
Services Limited has today entered into a Securities Subscription Agreement and \
Shareholders Agreement among the Company, TPG Terabyte Bidco Pte. Ltd. and \
DataVault AI Data Center Limited, a wholly owned subsidiary of the Company \
(DataVault) for an investment in DataVault.

Yours faithfully,
For Tata Consultancy Services Limited
Company Secretary
"""

_ANNEXURE_A_INVESTMENT = """\
Annexure - A
Details as per Regulation 30 of the SEBI (LODR) Regulations, 2015

Sr. No.  Particulars                                   Details
1.       Name(s) of parties with whom the agreement    TCS, TPG Terabyte Bidco Pte. Ltd.
         is entered                                    and DataVault AI Data Center Limited

2.       Purpose of entering into the agreement        Development, ownership, and operation
                                                       of AI-ready data centers in India.

4.       Significant terms of the agreement            The Company and TPG will collectively
                                                       invest an aggregate amount of up to
                                                       INR 180,00,00,00,000 (Indian Rupees
                                                       Eighteen Thousand Crore) into DataVault.
"""

_PRESS_RELEASE_INVESTMENT = """\
Annexure - B

TCS Secures Investment from TPG for DataVault AI Data Center Business

MUMBAI: Both partners combined, will commit to invest up to Rs 18,000 crore over
the next few years. TPG will invest up to Rs 8,820 crore and is envisaged to have
final shareholding between 27.5% and 49% in DataVault.
"""

_FULL_INVESTMENT = _COVER_INVESTMENT + _ANNEXURE_A_INVESTMENT + _PRESS_RELEASE_INVESTMENT

# Sub-type: Other (buyback authorisation — no dividend, no annexure)
_COVER_OTHER = """\
TCS/SE/88/2024-25
October 11, 2023

Dear Sirs,

Sub: Outcome of Board Meeting

We wish to inform you that at the Board Meeting held today, the Board of Directors \
has approved the proposal for buyback of equity shares of the Company, subject to \
approval of the shareholders through postal ballot and other regulatory approvals.

Yours faithfully,
For Tata Consultancy Services Limited
Company Secretary
"""


# ---------------------------------------------------------------------------
# KB mock factory
# ---------------------------------------------------------------------------

def _make_kb(eid: str, content: str, kind: str = "board_outcome") -> MagicMock:
    entry = MagicMock()
    entry.kind = kind
    entry.evidence_id = eid
    entry.source_date = "2024-10-10T00:00:00+00:00"
    kb = MagicMock()
    kb.get.return_value = entry
    kb.get_content.return_value = content
    return kb


def _make_kb_with_date(
    eid: str, content: str, source_date: str, kind: str = "board_outcome",
) -> MagicMock:
    entry = MagicMock()
    entry.kind = kind
    entry.evidence_id = eid
    entry.source_date = source_date
    kb = MagicMock()
    kb.get.return_value = entry
    kb.get_content.return_value = content
    return kb


def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


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
        with pytest.raises(ValueError, match="is not 'board_outcome'"):
            analyze("eid-x", kb)

    def test_raises_for_empty_content(self) -> None:
        entry = MagicMock()
        entry.kind = "board_outcome"
        entry.source_date = "2024-10-10T00:00:00+00:00"
        kb = MagicMock()
        kb.get.return_value = entry
        kb.get_content.return_value = ""
        with pytest.raises(ValueError, match="has no content"):
            analyze("eid-x", kb)


# ---------------------------------------------------------------------------
# Common result structure
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_returns_analysis_result(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_INTERIM_DIVIDEND))
        assert isinstance(result, AnalysisResult)

    def test_evidence_id_preserved(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_INTERIM_DIVIDEND))
        assert result.evidence_id == "eid-a"

    def test_kind_is_board_outcome(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_INTERIM_DIVIDEND))
        assert result.kind == "board_outcome"

    def test_analyzer_version(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_INTERIM_DIVIDEND))
        assert result.analyzer_version == ANALYZER_VERSION

    def test_analyzed_at_is_utc(self) -> None:
        from datetime import timezone
        result = analyze("eid-a", _make_kb("eid-a", _COVER_INTERIM_DIVIDEND))
        assert result.analyzed_at.tzinfo == timezone.utc

    def test_source_date_populated(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_INTERIM_DIVIDEND))
        assert result.source_date is not None

    def test_cover_letter_always_in_excerpts(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_INTERIM_DIVIDEND))
        assert "cover_letter" in result.excerpts

    def test_all_facts_have_provenance_section(self) -> None:
        result = analyze("eid-a", _make_kb("eid-a", _COVER_INTERIM_DIVIDEND))
        for f in result.facts:
            assert f.provenance.section != ""


# ---------------------------------------------------------------------------
# Sub-type: Results + interim dividend
# ---------------------------------------------------------------------------

class TestInterimDividend:
    def test_confidence_high(self) -> None:
        result = analyze("eid-int", _make_kb("eid-int", _COVER_INTERIM_DIVIDEND))
        assert result.confidence == "high"

    def test_no_warnings(self) -> None:
        result = analyze("eid-int", _make_kb("eid-int", _COVER_INTERIM_DIVIDEND))
        assert result.warnings == []

    def test_dividend_amount(self) -> None:
        result = analyze("eid-int", _make_kb("eid-int", _COVER_INTERIM_DIVIDEND))
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(10.0)
        assert facts[0].unit == FactUnit.RUPEES_PER_SHARE

    def test_dividend_type_interim(self) -> None:
        result = analyze("eid-int", _make_kb("eid-int", _COVER_INTERIM_DIVIDEND))
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_TYPE)
        assert len(facts) == 1
        assert facts[0].value == "interim"

    def test_record_date(self) -> None:
        result = analyze("eid-int", _make_kb("eid-int", _COVER_INTERIM_DIVIDEND))
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_RECORD_DATE)
        assert len(facts) == 1
        assert facts[0].value == "2024-10-18"
        assert facts[0].unit == FactUnit.ISO_DATE

    def test_payment_date(self) -> None:
        result = analyze("eid-int", _make_kb("eid-int", _COVER_INTERIM_DIVIDEND))
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE)
        assert len(facts) == 1
        assert facts[0].value == "2024-11-05"
        assert facts[0].unit == FactUnit.ISO_DATE

    def test_dividend_period_is_quarter_end(self) -> None:
        result = analyze("eid-int", _make_kb("eid-int", _COVER_INTERIM_DIVIDEND))
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert facts[0].period == "2024-09-30"

    def test_no_acquisition_facts(self) -> None:
        result = analyze("eid-int", _make_kb("eid-int", _COVER_INTERIM_DIVIDEND))
        assert _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME) == []


# ---------------------------------------------------------------------------
# Sub-type: Final dividend recommended (pending AGM, no payment/record date)
# ---------------------------------------------------------------------------

class TestFinalDividend:
    def test_confidence_high(self) -> None:
        kb = _make_kb_with_date("eid-fin", _COVER_FINAL_DIVIDEND, "2026-04-09T00:00:00+00:00")
        result = analyze("eid-fin", kb)
        assert result.confidence == "high"

    def test_dividend_amount_31(self) -> None:
        kb = _make_kb_with_date("eid-fin", _COVER_FINAL_DIVIDEND, "2026-04-09T00:00:00+00:00")
        result = analyze("eid-fin", kb)
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(31.0)

    def test_dividend_type_final(self) -> None:
        kb = _make_kb_with_date("eid-fin", _COVER_FINAL_DIVIDEND, "2026-04-09T00:00:00+00:00")
        result = analyze("eid-fin", kb)
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_TYPE)
        assert facts[0].value == "final"

    def test_no_record_date(self) -> None:
        kb = _make_kb_with_date("eid-fin", _COVER_FINAL_DIVIDEND, "2026-04-09T00:00:00+00:00")
        result = analyze("eid-fin", kb)
        assert _facts(result, FactKind.CAPITAL_DIVIDEND_RECORD_DATE) == []

    def test_no_payment_date(self) -> None:
        kb = _make_kb_with_date("eid-fin", _COVER_FINAL_DIVIDEND, "2026-04-09T00:00:00+00:00")
        result = analyze("eid-fin", kb)
        assert _facts(result, FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE) == []

    def test_dividend_period_is_fy_end(self) -> None:
        kb = _make_kb_with_date("eid-fin", _COVER_FINAL_DIVIDEND, "2026-04-09T00:00:00+00:00")
        result = analyze("eid-fin", kb)
        facts = _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE)
        assert facts[0].period == "2026-03-31"


# ---------------------------------------------------------------------------
# Sub-type: Acquisition (Annexure A with target-entity table)
# ---------------------------------------------------------------------------

class TestAcquisition:
    def test_confidence_high(self) -> None:
        result = analyze("eid-acq", _make_kb("eid-acq", _FULL_ACQUISITION))
        assert result.confidence == "high"

    def test_target_name(self) -> None:
        result = analyze("eid-acq", _make_kb("eid-acq", _FULL_ACQUISITION))
        facts = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert len(facts) == 1
        assert "Acme Cloud Holdings" in str(facts[0].value)

    def test_consideration_cash(self) -> None:
        result = analyze("eid-acq", _make_kb("eid-acq", _FULL_ACQUISITION))
        facts = _facts(result, FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE)
        assert len(facts) == 1
        assert facts[0].value == "cash"

    def test_enterprise_value_usd_million(self) -> None:
        result = analyze("eid-acq", _make_kb("eid-acq", _FULL_ACQUISITION))
        facts = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(500.0)
        assert facts[0].unit == FactUnit.USD_MILLION

    def test_stake_100_pct(self) -> None:
        result = analyze("eid-acq", _make_kb("eid-acq", _FULL_ACQUISITION))
        facts = _facts(result, FactKind.CAPITAL_ACQ_STAKE_PCT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(100.0)
        assert facts[0].unit == FactUnit.PERCENT

    def test_expected_completion(self) -> None:
        result = analyze("eid-acq", _make_kb("eid-acq", _FULL_ACQUISITION))
        facts = _facts(result, FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION)
        assert len(facts) == 1
        assert facts[0].value == "2026-03-31"

    def test_annexure_a_in_excerpts(self) -> None:
        result = analyze("eid-acq", _make_kb("eid-acq", _FULL_ACQUISITION))
        assert "annexure_a" in result.excerpts

    def test_no_dividend_facts(self) -> None:
        result = analyze("eid-acq", _make_kb("eid-acq", _FULL_ACQUISITION))
        assert _facts(result, FactKind.CAPITAL_DIVIDEND_PER_SHARE) == []

    def test_acq_facts_period_none(self) -> None:
        result = analyze("eid-acq", _make_kb("eid-acq", _FULL_ACQUISITION))
        for f in result.facts:
            if f.kind in (
                FactKind.CAPITAL_ACQ_TARGET_NAME,
                FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE,
                FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE,
                FactKind.CAPITAL_ACQ_STAKE_PCT,
                FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION,
            ):
                assert f.period is None


# ---------------------------------------------------------------------------
# Sub-type: Pure JV / distribution agreement (no stated investment amount)
# ---------------------------------------------------------------------------

class TestAgreement:
    def test_confidence_low(self) -> None:
        result = analyze("eid-agr", _make_kb("eid-agr", _FULL_AGREEMENT))
        assert result.confidence == "low"

    def test_warns_about_agreement(self) -> None:
        result = analyze("eid-agr", _make_kb("eid-agr", _FULL_AGREEMENT))
        assert any("agreement" in w.lower() for w in result.warnings)

    def test_no_structured_facts(self) -> None:
        result = analyze("eid-agr", _make_kb("eid-agr", _FULL_AGREEMENT))
        assert result.facts == []

    def test_annexure_a_captured_as_excerpt(self) -> None:
        result = analyze("eid-agr", _make_kb("eid-agr", _FULL_AGREEMENT))
        assert "annexure_a" in result.excerpts


# ---------------------------------------------------------------------------
# Sub-type: Investment (Securities Subscription Agreement into subsidiary)
# ---------------------------------------------------------------------------

class TestInvestment:
    def test_confidence_medium(self) -> None:
        result = analyze("eid-inv", _make_kb("eid-inv", _FULL_INVESTMENT))
        assert result.confidence == "medium"

    def test_target_name(self) -> None:
        result = analyze("eid-inv", _make_kb("eid-inv", _FULL_INVESTMENT))
        facts = _facts(result, FactKind.CAPITAL_INVEST_TARGET_NAME)
        assert len(facts) == 1
        assert "DataVault AI Data Center Limited" in str(facts[0].value)

    def test_amount_18000_crore(self) -> None:
        result = analyze("eid-inv", _make_kb("eid-inv", _FULL_INVESTMENT))
        facts = _facts(result, FactKind.CAPITAL_INVEST_AMOUNT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(18000.0)
        assert facts[0].unit == FactUnit.CRORE_INR

    def test_amount_from_press_release(self) -> None:
        result = analyze("eid-inv", _make_kb("eid-inv", _FULL_INVESTMENT))
        facts = _facts(result, FactKind.CAPITAL_INVEST_AMOUNT)
        assert facts[0].provenance.section == "press_release"

    def test_no_warnings(self) -> None:
        result = analyze("eid-inv", _make_kb("eid-inv", _FULL_INVESTMENT))
        assert result.warnings == []

    def test_annexure_a_in_excerpts(self) -> None:
        result = analyze("eid-inv", _make_kb("eid-inv", _FULL_INVESTMENT))
        assert "annexure_a" in result.excerpts

    def test_press_release_in_excerpts(self) -> None:
        result = analyze("eid-inv", _make_kb("eid-inv", _FULL_INVESTMENT))
        assert "press_release" in result.excerpts

    def test_invest_facts_period_none(self) -> None:
        result = analyze("eid-inv", _make_kb("eid-inv", _FULL_INVESTMENT))
        for f in result.facts:
            if f.kind in (FactKind.CAPITAL_INVEST_TARGET_NAME, FactKind.CAPITAL_INVEST_AMOUNT):
                assert f.period is None

    def test_no_acquisition_facts(self) -> None:
        result = analyze("eid-inv", _make_kb("eid-inv", _FULL_INVESTMENT))
        assert _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME) == []


class TestInvestmentUSD:
    """Investment amount stated in USD billions (e.g. press release in English-only form)."""

    _COVER = """\
    Dear Sirs,

    Pursuant to Regulation 30, Tata Consultancy Services Limited has entered into a
    Securities Subscription Agreement with Atlantic Infra Fund and CloudBuild Asia
    Limited, a wholly owned subsidiary of the Company (CloudBuild).

    Yours faithfully,
    """

    _ANNEXURE_A = """\
    Annexure - A

    Name(s) of parties with whom the agreement is entered: TCS, Atlantic Infra Fund,
    CloudBuild Asia Limited.
    """

    _ANN_B = """\
    Annexure - B

    TCS secures $2 Bn investment from Atlantic Infra Fund for CloudBuild's expansion.
    """

    def test_amount_usd_billion(self) -> None:
        content = self._COVER + self._ANNEXURE_A + self._ANN_B
        result = analyze("eid-usd", _make_kb("eid-usd", content))
        facts = _facts(result, FactKind.CAPITAL_INVEST_AMOUNT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(2.0)
        assert facts[0].unit == FactUnit.USD_BILLION


class TestInvestmentNoAmount:
    """SSA signal present but no stated investment amount (e.g. pre-close announcement)."""

    _CONTENT = """\
Dear Sirs,

Pursuant to Regulation 30, the Company has entered into a Securities Subscription
Agreement and SHA with Infra PE Fund and LogisticsHub India Limited, a wholly owned
subsidiary of the Company.

Annexure - A

Name(s) of parties with whom the agreement is entered: TCS, Infra PE Fund, and
LogisticsHub India Limited.

Purpose of entering into the agreement: Build and operate logistics infrastructure.
"""

    def test_target_name_extracted(self) -> None:
        result = analyze("eid-noa", _make_kb("eid-noa", self._CONTENT))
        facts = _facts(result, FactKind.CAPITAL_INVEST_TARGET_NAME)
        assert len(facts) == 1
        assert "LogisticsHub India Limited" in str(facts[0].value)

    def test_no_amount_fact(self) -> None:
        result = analyze("eid-noa", _make_kb("eid-noa", self._CONTENT))
        assert _facts(result, FactKind.CAPITAL_INVEST_AMOUNT) == []

    def test_amount_warning_emitted(self) -> None:
        result = analyze("eid-noa", _make_kb("eid-noa", self._CONTENT))
        assert any("investment amount" in w.lower() for w in result.warnings)

    def test_confidence_medium(self) -> None:
        result = analyze("eid-noa", _make_kb("eid-noa", self._CONTENT))
        assert result.confidence == "medium"


# ---------------------------------------------------------------------------
# Sub-type: Other board decision (buyback auth, no dividend, no annexure)
# ---------------------------------------------------------------------------

class TestOther:
    def test_confidence_low(self) -> None:
        result = analyze("eid-oth", _make_kb("eid-oth", _COVER_OTHER))
        assert result.confidence == "low"

    def test_warns_about_no_facts(self) -> None:
        result = analyze("eid-oth", _make_kb("eid-oth", _COVER_OTHER))
        assert result.warnings  # at least one warning

    def test_no_structured_facts(self) -> None:
        result = analyze("eid-oth", _make_kb("eid-oth", _COVER_OTHER))
        assert result.facts == []

    def test_cover_letter_in_excerpts(self) -> None:
        result = analyze("eid-oth", _make_kb("eid-oth", _COVER_OTHER))
        assert "cover_letter" in result.excerpts
