"""Unit tests for atlas.analysis.acquisition.

Covers all three document types:
  Type A — External acquisition (with Annexure A "Name of the target entity")
  Type B — Subsidiary incorporation (with Annexure A "Name of the entity, date & country")
  Type C — Completion / update notice (no Annexure A)

Uses entirely synthetic fixtures so no real repository access is required.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from atlas.analysis.acquisition import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit

# ---------------------------------------------------------------------------
# Synthetic document fixtures
# ---------------------------------------------------------------------------

_COVER_TYPE_A = """\
TCS/SE/160/2025-26
December 10, 2025

Dear Sirs,

Sub: Disclosure under Regulation 30 of SEBI (Listing Obligations and Disclosure
Requirements) Regulations, 2015

Pursuant to Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements)
Regulations, 2015, we wish to inform you that the Board of Directors of Tata Consultancy
Services Limited ("Company" or "TCS") at its meeting held today inter alia considered and
approved execution of Securities Purchase Agreement and Plan of Merger ("Agreement")
for acquisition of Acme Cloud Holdings, LLC and its subsidiaries.
"""

_ANNEXURE_A_TYPE_A = """\
Annexure - A
Details under amended Regulation 30 of the SEBI (Listing Obligations and Disclosure
Requirements) Regulations, 2015

Sr.
No.
Particulars
Details
1.  Name of the target entity, details in
brief such as size, turnover etc.
Acme Cloud Holdings, LLC and its
subsidiaries – a leading cloud consulting
firm with USD 100 million annual revenue.

2.  Whether the acquisition would fall
within related party transaction(s)
No

3.  Industry to which the entity being
acquired belongs
Information Technology Services

4.  Objects and impact of acquisition
Strengthens TCS cloud capabilities.

5.  Brief details of any governmental or
regulatory approvals required for the acquisition
Hart-Scott-Rodino antitrust (HSR) approval in USA

6.  Indicative time period for completion
of the acquisition
The transaction is expected to be completed
by February 28, 2026.

7.  Consideration - whether cash
consideration or share swap or any
other form and details of the same
Cash consideration

8.  Cost of acquisition and/or the price at
which the shares are acquired
Enterprise Value of up to USD 500 million,
including upfront and deferred payments.

9.  Percentage of shareholding / control
acquired and / or number of shares
acquired
100%

10. Brief background about the entity
acquired
Founded in 2015 in Delaware, USA.
"""

_ANNEXURE_B_TYPE_A = """\
Annexure B

TCS Acquires Acme Cloud Holdings
MUMBAI, December 10, 2025: TCS has signed a definitive agreement to acquire 100%
stake in Acme Cloud Holdings for an all cash consideration of $500 million.
"""

_FULL_TYPE_A = _COVER_TYPE_A + _ANNEXURE_A_TYPE_A + _ANNEXURE_B_TYPE_A

# ---------------------------------------------------------------------------

_COVER_TYPE_B_SINGLE = """\
TCS/SE/166/2025-26
December 17, 2025

Dear Sirs,

Pursuant to Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements)
Regulations, 2015 ('SEBI Listing Regulations') we wish to inform that Tata Consultancy
Services Asia Pacific Pte. Ltd. ('TAPL') a wholly owned subsidiary of the Company, has
incorporated 'TATA CONSULTANCY SERVICES BT Private Limited' a wholly owned
subsidiary in Bhutan on December 16, 2025.
"""

_ANNEXURE_A_TYPE_B_SINGLE = """\
Annexure A
Details as per Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements)
Regulations, 2015

S/n.
Particulars
Details
1.  Name of the entity, date & country of incorporation, etc
Name: TATA CONSULTANCY SERVICES BT Private Limited
Country of Incorporation: Bhutan
Date of Incorporation: December 16, 2025
2.  Name of holding company of the incorporated company and relation with the listed entity
TAPL a wholly owned subsidiary of the Company, is the holding company.
TATA CONSULTANCY SERVICES BT Private Limited is a step down subsidiary.
3  Industry to which the entity being incorporated belongs;
Information Technology and Information Technology enabled Services
4. Brief background about the entity incorporated
Established to support operations in Bhutan.
5  Brief details of any governmental or regulatory approvals
Not Applicable
6  Nature of consideration
Initial capital subscription in Cash
7  Cost of subscription / price at which the shares are subscribed
Not specified
8  Percentage of shareholding / control by the listed entity
100%
"""

_FULL_TYPE_B_SINGLE = _COVER_TYPE_B_SINGLE + _ANNEXURE_A_TYPE_B_SINGLE

# ---------------------------------------------------------------------------

_COVER_TYPE_B_WITH_COST = """\
TCS/SE/135/2025-26
October 30, 2025

Dear Sirs,

Pursuant to Regulation 30 of the SEBI Listing Regulations we wish to inform that
'HyperVault AI Data Center Limited' has been incorporated as a wholly owned subsidiary
of the Company on October 29, 2025.
"""

_ANNEXURE_A_TYPE_B_WITH_COST = """\
Annexure - A
Details as per Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements)
Regulations, 2015

Sr.
No.
Particulars
Details
1  Name of the entity, date & country of incorporation, etc
Name: HyperVault AI Data Center Limited ("HyperVault")
Country of Incorporation: India
Date of Incorporation: October 29, 2025
2. Name of holding company
Tata Consultancy Services Limited is the holding company of HyperVault.
HyperVault is a wholly owned subsidiary of the Company.
3  Industry
Technology Infrastructure and Technology Enabled Services
4. Brief background
HyperVault has been incorporated to establish multiple AI and Sovereign Data Centers.
5  Governmental approvals
Not Applicable
6  Nature of consideration
Initial capital subscription in Cash
7  Cost of subscription
Tata Consultancy Services Limited will subscribe to 75,00,000 equity shares of INR 10 each
amounting to INR 7.5 crore as initial capital.
8  Percentage of shareholding
100%
"""

_FULL_TYPE_B_WITH_COST = _COVER_TYPE_B_WITH_COST + _ANNEXURE_A_TYPE_B_WITH_COST

# ---------------------------------------------------------------------------

_COVER_TYPE_B_MULTI = """\
TCS/SE/165/2025-26
December 16, 2025

Dear Sirs,

Pursuant to Regulation 30 of the SEBI Listing Regulations and in furtherance to our letter
dated December 10, 2025, we wish to inform that ListEngage MidCo LLC has formed
'TCS North America Corporation' and 'Trident LE LLC', wholly owned subsidiaries in the USA
on December 15, 2025.
"""

_ANNEXURE_A_TYPE_B_MULTI = """\
Annexure - A
Details as per Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements)
Regulations, 2015

Sr.
No.
Particulars
Details
1  Name of the entity, date & country of incorporation, etc
Name: TCS North America Corporation
Country of Incorporation: USA
Date of Incorporation: December 15, 2025
Name: Trident LE LLC
Country of Incorporation: USA
Date of Incorporation: December 15, 2025
2. Name of holding company
ListEngage MidCo LLC is the holding company of both entities.
Both are step down subsidiaries of the Company.
3  Industry
Advisory and AI services, IT and IT Enabled Services
4. Brief background
Acquisition of new business opportunities and investments.
5  Governmental approvals
Not Applicable
6  Nature of consideration
Initial capital subscription in Cash
7  Cost of subscription
Not specified
8  Percentage of shareholding
100%
"""

_FULL_TYPE_B_MULTI = _COVER_TYPE_B_MULTI + _ANNEXURE_A_TYPE_B_MULTI

# ---------------------------------------------------------------------------

_FULL_TYPE_C = """\
TCS/SE/25/2025-26
April 30, 2025

Dear Sirs,

Sub: Update on acquisition of TRIL Bengaluru Real Estate Five Limited and
TRIL Bengaluru Real Estate Six Limited (Entities).

Vide our letter dated January 29, 2025, we had informed about transfer of 65% of
equity shares and optionally redeemable convertible debentures of Entities held by
Tata Realty and Infrastructure Limited (TRIL) to the Company in the first tranche
pursuant to the Share Purchase and Securities Purchase Agreement.

The transfer of remaining 35% of Securities held by TRIL to the Company in the second
tranche has been completed today.

This is for your information and record.
"""


# ---------------------------------------------------------------------------
# KB mock factory
# ---------------------------------------------------------------------------


def _make_kb(eid: str, content: str, kind: str = "acquisition") -> MagicMock:
    entry = MagicMock()
    entry.kind = kind
    entry.evidence_id = eid
    entry.source_date = "2025-12-10T00:00:00+00:00"

    kb = MagicMock()
    kb.get.return_value = entry
    kb.get_content.return_value = content
    return kb


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _facts(result: AnalysisResult, kind: FactKind) -> list[AnalysisFact]:
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Tests: common result structure
# ---------------------------------------------------------------------------


class TestResultStructure:
    def test_returns_analysis_result(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        assert isinstance(result, AnalysisResult)

    def test_evidence_id_preserved(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        assert result.evidence_id == "eid-a"

    def test_kind_is_acquisition(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        assert result.kind == "acquisition"

    def test_analyzer_version(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        assert result.analyzer_version == ANALYZER_VERSION

    def test_analyzed_at_is_utc(self) -> None:
        from datetime import timezone

        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        assert result.analyzed_at.tzinfo == timezone.utc

    def test_all_facts_have_provenance_section(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        for f in result.facts:
            assert isinstance(f.provenance.section, str)
            assert f.provenance.section != ""


# ---------------------------------------------------------------------------
# Tests: error cases
# ---------------------------------------------------------------------------


class TestErrors:
    def test_raises_for_unknown_evidence_id(self) -> None:
        kb = MagicMock()
        kb.get.return_value = None
        with pytest.raises(ValueError, match="not in knowledge base"):
            analyze("missing-id", kb)

    def test_raises_for_wrong_kind(self) -> None:
        entry = MagicMock()
        entry.kind = "financial_results"
        kb = MagicMock()
        kb.get.return_value = entry
        with pytest.raises(ValueError, match="is not 'acquisition'"):
            analyze("eid-x", kb)

    def test_raises_for_empty_content(self) -> None:
        entry = MagicMock()
        entry.kind = "acquisition"
        kb = MagicMock()
        kb.get.return_value = entry
        kb.get_content.return_value = ""
        with pytest.raises(ValueError, match="has no content"):
            analyze("eid-x", kb)


# ---------------------------------------------------------------------------
# Tests: Type A — external acquisition
# ---------------------------------------------------------------------------


class TestTypeA:
    def test_confidence_high(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        assert result.confidence == "high"

    def test_no_warnings(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        assert result.warnings == []

    def test_target_name_extracted(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert len(names) == 1
        assert "Acme Cloud Holdings" in str(names[0].value)

    def test_target_name_from_cover_letter(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert names[0].provenance.section == "cover_letter"

    def test_consideration_type_cash(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        cons = _facts(result, FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE)
        assert len(cons) == 1
        assert cons[0].value == "cash"

    def test_consideration_no_unit(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        cons = _facts(result, FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE)
        assert cons[0].unit is None

    def test_enterprise_value_extracted(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        ev = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert len(ev) == 1
        assert ev[0].value == pytest.approx(500.0)

    def test_enterprise_value_unit_usd_million(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        ev = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert ev[0].unit == FactUnit.USD_MILLION

    def test_stake_pct_extracted(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        stake = _facts(result, FactKind.CAPITAL_ACQ_STAKE_PCT)
        assert len(stake) == 1
        assert stake[0].value == pytest.approx(100.0)

    def test_stake_pct_unit(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        stake = _facts(result, FactKind.CAPITAL_ACQ_STAKE_PCT)
        assert stake[0].unit == FactUnit.PERCENT

    def test_expected_completion_extracted(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        comp = _facts(result, FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION)
        assert len(comp) == 1
        assert comp[0].value == "2026-02-28"

    def test_expected_completion_unit_iso_date(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        comp = _facts(result, FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION)
        assert comp[0].unit == FactUnit.ISO_DATE

    def test_annexure_a_in_excerpts(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        assert "annexure_a" in result.excerpts

    def test_press_release_in_excerpts(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        assert "press_release" in result.excerpts

    def test_cover_letter_in_excerpts(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        assert "cover_letter" in result.excerpts

    def test_share_swap_consideration_type(self) -> None:
        content = _FULL_TYPE_A.replace("Cash consideration", "Share swap consideration")
        kb = _make_kb("eid-swap", content)
        result = analyze("eid-swap", kb)
        cons = _facts(result, FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE)
        assert cons[0].value == "share_swap"

    def test_all_facts_are_high_confidence(self) -> None:
        kb = _make_kb("eid-a", _FULL_TYPE_A)
        result = analyze("eid-a", kb)
        for f in result.facts:
            assert f.confidence == "high"


# ---------------------------------------------------------------------------
# Tests: Type B — subsidiary incorporation (single entity, no cost)
# ---------------------------------------------------------------------------


class TestTypeBSingle:
    def test_confidence_high(self) -> None:
        kb = _make_kb("eid-b1", _FULL_TYPE_B_SINGLE)
        result = analyze("eid-b1", kb)
        assert result.confidence == "high"

    def test_target_name_extracted(self) -> None:
        kb = _make_kb("eid-b1", _FULL_TYPE_B_SINGLE)
        result = analyze("eid-b1", kb)
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert len(names) == 1
        assert "TATA CONSULTANCY SERVICES BT" in str(names[0].value)

    def test_consideration_type_subscription(self) -> None:
        kb = _make_kb("eid-b1", _FULL_TYPE_B_SINGLE)
        result = analyze("eid-b1", kb)
        cons = _facts(result, FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE)
        assert cons[0].value == "subscription"

    def test_stake_100_pct(self) -> None:
        kb = _make_kb("eid-b1", _FULL_TYPE_B_SINGLE)
        result = analyze("eid-b1", kb)
        stake = _facts(result, FactKind.CAPITAL_ACQ_STAKE_PCT)
        assert stake[0].value == pytest.approx(100.0)

    def test_no_enterprise_value_when_cost_not_stated(self) -> None:
        kb = _make_kb("eid-b1", _FULL_TYPE_B_SINGLE)
        result = analyze("eid-b1", kb)
        ev = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert ev == []

    def test_no_completion_date(self) -> None:
        kb = _make_kb("eid-b1", _FULL_TYPE_B_SINGLE)
        result = analyze("eid-b1", kb)
        comp = _facts(result, FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION)
        assert comp == []


# ---------------------------------------------------------------------------
# Tests: Type B — subsidiary incorporation (with subscription cost)
# ---------------------------------------------------------------------------


class TestTypeBWithCost:
    def test_enterprise_value_inr_stated(self) -> None:
        kb = _make_kb("eid-b2", _FULL_TYPE_B_WITH_COST)
        result = analyze("eid-b2", kb)
        ev = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert len(ev) == 1
        assert ev[0].value == pytest.approx(7.5)

    def test_enterprise_value_unit_crore_inr(self) -> None:
        kb = _make_kb("eid-b2", _FULL_TYPE_B_WITH_COST)
        result = analyze("eid-b2", kb)
        ev = _facts(result, FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE)
        assert ev[0].unit == FactUnit.CRORE_INR

    def test_target_name_stripped_of_short_form(self) -> None:
        kb = _make_kb("eid-b2", _FULL_TYPE_B_WITH_COST)
        result = analyze("eid-b2", kb)
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        # Short-form alias ("HyperVault") should be stripped from the name
        assert "HyperVault AI Data Center Limited" in str(names[0].value)
        # The parenthetical alias should not appear as a separate name
        assert not any(f.value == '"HyperVault"' for f in names)


# ---------------------------------------------------------------------------
# Tests: Type B — multiple entities in one filing
# ---------------------------------------------------------------------------


class TestTypeBMulti:
    def test_two_target_name_facts(self) -> None:
        kb = _make_kb("eid-b3", _FULL_TYPE_B_MULTI)
        result = analyze("eid-b3", kb)
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert len(names) == 2

    def test_first_entity_name(self) -> None:
        kb = _make_kb("eid-b3", _FULL_TYPE_B_MULTI)
        result = analyze("eid-b3", kb)
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert any("TCS North America" in str(f.value) for f in names)

    def test_second_entity_name(self) -> None:
        kb = _make_kb("eid-b3", _FULL_TYPE_B_MULTI)
        result = analyze("eid-b3", kb)
        names = _facts(result, FactKind.CAPITAL_ACQ_TARGET_NAME)
        assert any("Trident LE LLC" in str(f.value) for f in names)

    def test_stake_still_extracted(self) -> None:
        kb = _make_kb("eid-b3", _FULL_TYPE_B_MULTI)
        result = analyze("eid-b3", kb)
        stake = _facts(result, FactKind.CAPITAL_ACQ_STAKE_PCT)
        assert len(stake) >= 1
        assert stake[0].value == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Tests: Type C — completion update notice
# ---------------------------------------------------------------------------


class TestTypeC:
    def test_confidence_low(self) -> None:
        kb = _make_kb("eid-c", _FULL_TYPE_C)
        result = analyze("eid-c", kb)
        assert result.confidence == "low"

    def test_no_facts(self) -> None:
        kb = _make_kb("eid-c", _FULL_TYPE_C)
        result = analyze("eid-c", kb)
        assert result.facts == []

    def test_warning_emitted(self) -> None:
        kb = _make_kb("eid-c", _FULL_TYPE_C)
        result = analyze("eid-c", kb)
        assert len(result.warnings) >= 1
        assert any("Annexure A" in w for w in result.warnings)

    def test_cover_letter_in_excerpts(self) -> None:
        kb = _make_kb("eid-c", _FULL_TYPE_C)
        result = analyze("eid-c", kb)
        assert "cover_letter" in result.excerpts
