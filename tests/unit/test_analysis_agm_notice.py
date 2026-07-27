"""Unit tests for atlas.analysis.agm_notice.

All tests use synthetic fixtures — no real repository access required.

Coverage:

  Error handling:
    - Missing evidence_id raises ValueError
    - Wrong kind raises ValueError
    - Empty content returns result with warning and no facts

  Sub-type detection:
    - 'voting_results' when 'VOTING RESULTS OF THE MEETING' section present
    - 'voting_results' when 'All the Resolutions were declared as passed' present
    - 'notice' for pre-meeting AGM notices without voting result table

  AGM date extraction:
    - Extracted from 'was held on Weekday, Month DD, YYYY' pattern
    - Stored in excerpts['agm_date'] as ISO date

  Format A resolution extraction (2024/2025 summary table):
    - Numbered entries with '.' separator parsed correctly
    - Description captured before Ordinary/Special type keyword
    - 'special' embedded in description does NOT poison the type field
    - Ordinary/Special correctly classified
    - 'Passed with requisite majority' → outcome='passed'
    - Page break headers (company name, column headers) stripped from description

  Format B resolution extraction (2026 proceedings format):
    - Numbered entries without '.' separator parsed
    - Global 'All Resolutions were declared as passed' sets outcome for all
    - Description captured before Ordinary/Special type keyword

  Vote percentage extraction:
    - Layout A (column-split): last XX.XXXX before col(7) header = pct_for;
      last XX.XXXX before Yes = pct_against; pair sums to ~100
    - Layout A-robust (garbled col7 header): complement search finds pct_for
    - Layout B (Total-row): second-to-last and last XX.XXXX before Whether
    - Returned pair always validated to sum within +/-0.05 of 100.0
    - (None, None) when no valid pair found

  Confidence:
    - 'high' when >=3 resolution titles extracted
    - 'medium' when 1-2 titles
    - 'low' when 0 titles
    - 'low' for 'notice' sub-type

  Provenance:
    - All facts carry provenance.section = 'resolution_N'
    - Period field of resolution facts = AGM date ISO string
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from atlas.analysis.agm_notice import ANALYZER_VERSION, _extract_vote_pcts, analyze
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _kb(
    content: str,
    kind: str = "agm_notice",
    source_date: str = "2025-06-19T10:00:00+00:00",
) -> MagicMock:
    entry = MagicMock()
    entry.kind = kind
    entry.source_date = datetime.fromisoformat(source_date)
    kb = MagicMock()
    kb.get.return_value = entry
    kb.get_content.return_value = content
    return kb


def _missing_kb() -> MagicMock:
    kb = MagicMock()
    kb.get.return_value = None
    return kb


def _facts(result: AnalysisResult, kind: FactKind) -> list:
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Minimal content blocks
# ---------------------------------------------------------------------------

# The split regex is \n(\d{1,2})\.\s+\n — requires at least one whitespace
# character between the '.' and the next newline.  The real PDFs have a blank
# line after each resolution number; replicated here as "\n\n" (the first \n
# is consumed by \s+ and the second by the trailing literal \n in the pattern).
_VOTING_SUMMARY_SECTION = """
VOTING RESULTS OF THE MEETING
Sr. No.
Agenda
Resolution required (Ordinary/Special)
Mode of Voting
Remarks
1.

To receive, consider and adopt the Audited Financial Statements
for the financial year ended March 31, 2025.

Ordinary
Remote e-voting prior and during the AGM
Passed
with
requisite
majority
2.

To confirm the payment of Interim Dividends (including a
special
dividend) on Equity Shares.

Ordinary
Remote e-voting prior and during the AGM
Passed
with
requisite
majority
"""

_PROCEEDINGS_SECTION = """
The following resolutions set out in the Notice convening the AGM were put to vote by remote
e-voting before/during the AGM:

Res.
No.
Brief Description of the Resolution
Resolution
Type
1
To receive, consider and adopt the Financial Statements for FY 2026.
Ordinary
2
To confirm the payment of Interim Dividends.
Ordinary
3
To re-appoint Director N Chandrasekaran.
Ordinary

Members who attended the Meeting...

All the Resolutions were declared as passed with requisite majority.
"""

_RESOLUTION_BLOCK_COL_SPLIT = """
Resolution (1)
Whether promoter/promoter group are interested in the agenda/resolution?
No
To adopt financial statements.

% of Votes polled on outstanding shares (3)=[(2)/(1)]*100
100.0000 0.0000 0.0000 100.0000
90.0000 0.0000 0.0000 90.0000
0.5000 0.0000 0.0000 0.5000
92.0000

No. of votes - in favour (4)
...

Whether resolution is Pass or Not.
Disclosure of notes on resolution
% of votes in favour on votes polled
(6)=[(4)/(2)]*100
100.0000
0.0000
0.0000
100.0000
99.5000
0.0000
0.0000
99.5000
98.0000
0.0000
0.0000
98.0000
99.8500
% of Votes against on votes polled
(7)=[(5)/(2)]*100
0.0000
0.0000
0.0000
0.0000
0.5000
0.0000
0.0000
0.5000
2.0000
0.0000
0.0000
2.0000
0.1500
Yes
"""

_RESOLUTION_BLOCK_TOTAL_ROW = """
Resolution (1)
Whether promoter/promoter group are interested in the agenda/resolution?
No
To adopt financial statements.

% of Votes polled on outstanding shares (3)=[(2)/(1)]*100
100.0000 0.0000 0.0000 100.0000

Total
3618087518
3356614614
92.7732
3350900289
5714325
99.8298
0.1702
Whether resolution is Pass or Not.
Yes
"""

_RESOLUTION_BLOCK_COMPLEMENT = """
Resolution (1)
Whether promoter/promoter group are interested in the agenda/resolution?
No
To adopt financial statements.

% of Votes polled on outstanding shares
...
Whether resolution is Pass or Not.
Disclosure of notes on resolution
% of votes In favour on votes polled
l7l=l4I/12)]*100
100.0000
0.0000
0.0000
100.0000
99.6000
0.0000
0.0000
99.6000
98.0000
0.0000
0.0000
98.0000
99.6558
against on votes polled
l7l=IISJ/12Wloo
0.0000
0.0000
0.0000
0.0000
0.5000
0.0000
0.0000
0.5000
2.0000
0.0000
0.0000
2.0000
0.3442
Yes
"""


def _voting_doc(summary: str = "", blocks: str = "") -> str:
    """Compose a minimal voting_results document."""
    return (
        "Sub: Regulation 30 and Regulation 44(3) - Proceedings\n\n"
        "The 30th Annual General Meeting of the Company was held on "
        "Thursday, June 19, 2025 at 3.00 p.m. (IST)\n\n" + summary + "\n" + blocks
    )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    def test_missing_evidence_id_raises(self):
        with pytest.raises(ValueError, match="not found"):
            analyze("missing-id", _missing_kb())

    def test_wrong_kind_raises(self):
        kb = _kb("content", kind="board_outcome")
        with pytest.raises(ValueError, match="agm_notice"):
            analyze("eid", kb)

    def test_empty_content_returns_warning(self):
        r = analyze("eid", _kb(""))
        assert r.warnings
        assert r.confidence == "low"
        assert r.facts == []


# ---------------------------------------------------------------------------
# Sub-type detection
# ---------------------------------------------------------------------------


class TestSubtypeDetection:
    def test_voting_results_from_section_header(self):
        content = _voting_doc(summary=_VOTING_SUMMARY_SECTION)
        r = analyze("eid", _kb(content))
        assert r.excerpts["subtype"] == "voting_results"

    def test_voting_results_from_all_passed_phrase(self):
        content = (
            "Regulation 44(3) filing\n\n"
            "The 31st AGM was held on Tuesday, June 9, 2026.\n\n" + _PROCEEDINGS_SECTION
        )
        r = analyze("eid", _kb(content))
        assert r.excerpts["subtype"] == "voting_results"

    def test_notice_subtype_for_pre_meeting(self):
        content = "Sub: AGM Notice and Annual Report 2024-25\n\nDear Shareholder,\n..."
        r = analyze("eid", _kb(content))
        assert r.excerpts["subtype"] == "notice"
        assert r.confidence == "low"
        assert r.facts == []

    def test_notice_emits_warning(self):
        content = "Sub: AGM Notice\n\nDear Shareholder..."
        r = analyze("eid", _kb(content))
        assert any("pre-meeting" in w for w in r.warnings)

    def test_analyzer_version_present(self):
        r = analyze("eid", _kb(_voting_doc(summary=_VOTING_SUMMARY_SECTION)))
        assert r.analyzer_version == ANALYZER_VERSION


# ---------------------------------------------------------------------------
# AGM date extraction
# ---------------------------------------------------------------------------


class TestAGMDate:
    def test_date_extracted_from_cover(self):
        content = _voting_doc(summary=_VOTING_SUMMARY_SECTION)
        r = analyze("eid", _kb(content))
        assert r.excerpts.get("agm_date") == "2025-06-19"

    def test_date_used_as_period_for_facts(self):
        content = _voting_doc(summary=_VOTING_SUMMARY_SECTION)
        r = analyze("eid", _kb(content))
        titles = _facts(r, FactKind.GOVERNANCE_RESOLUTION_TITLE)
        assert all(f.period == "2025-06-19" for f in titles)

    def test_missing_date_emits_warning(self):
        content = "VOTING RESULTS OF THE MEETING\n" + _VOTING_SUMMARY_SECTION
        r = analyze("eid", _kb(content))
        assert any("AGM date" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# Format A: summary table (2024/2025 style)
# ---------------------------------------------------------------------------


class TestFormatA:
    def setup_method(self):
        content = _voting_doc(summary=_VOTING_SUMMARY_SECTION)
        self.r = analyze("eid", _kb(content))

    def test_two_resolution_titles_extracted(self):
        assert len(_facts(self.r, FactKind.GOVERNANCE_RESOLUTION_TITLE)) == 2

    def test_resolution_types_both_ordinary(self):
        types = _facts(self.r, FactKind.GOVERNANCE_RESOLUTION_TYPE)
        assert len(types) == 2
        assert all(f.value == "ordinary" for f in types)

    def test_outcomes_both_passed(self):
        outcomes = _facts(self.r, FactKind.GOVERNANCE_RESOLUTION_OUTCOME)
        assert all(f.value == "passed" for f in outcomes)

    def test_special_in_description_does_not_poison_type(self):
        """Resolution 2 contains 'special dividend' — type must still be 'ordinary'."""
        types = _facts(self.r, FactKind.GOVERNANCE_RESOLUTION_TYPE)
        res2_type = next(
            (f for f in types if f.provenance.section == "resolution_2"), None
        )
        assert res2_type is not None
        assert res2_type.value == "ordinary"

    def test_description_1_mentions_financial_statements(self):
        titles = _facts(self.r, FactKind.GOVERNANCE_RESOLUTION_TITLE)
        res1 = next(f for f in titles if f.provenance.section == "resolution_1")
        assert "financial" in res1.value.lower()

    def test_description_2_mentions_dividends(self):
        titles = _facts(self.r, FactKind.GOVERNANCE_RESOLUTION_TITLE)
        res2 = next(f for f in titles if f.provenance.section == "resolution_2")
        assert "dividend" in res2.value.lower()

    def test_sections_named_resolution_n(self):
        titles = _facts(self.r, FactKind.GOVERNANCE_RESOLUTION_TITLE)
        sections = {f.provenance.section for f in titles}
        assert "resolution_1" in sections
        assert "resolution_2" in sections

    def test_confidence_medium_with_two_titles(self):
        # <3 titles → medium (>=3 required for high)
        assert self.r.confidence == "medium"


# ---------------------------------------------------------------------------
# Format B: proceedings section (2026 style)
# ---------------------------------------------------------------------------


class TestFormatB:
    def setup_method(self):
        content = (
            "Regulation 44(3) filing\n\n"
            "The 31st Annual General Meeting was held on Tuesday, June 9, 2026.\n\n"
            + _PROCEEDINGS_SECTION
        )
        self.r = analyze("eid", _kb(content, source_date="2026-06-09T10:00:00+00:00"))

    def test_three_resolutions_extracted(self):
        assert len(_facts(self.r, FactKind.GOVERNANCE_RESOLUTION_TITLE)) == 3

    def test_all_ordinary(self):
        types = _facts(self.r, FactKind.GOVERNANCE_RESOLUTION_TYPE)
        assert all(f.value == "ordinary" for f in types)

    def test_all_passed_from_global_phrase(self):
        outcomes = _facts(self.r, FactKind.GOVERNANCE_RESOLUTION_OUTCOME)
        assert all(f.value == "passed" for f in outcomes)

    def test_resolution_3_mentions_chandrasekaran(self):
        titles = _facts(self.r, FactKind.GOVERNANCE_RESOLUTION_TITLE)
        res3 = next(f for f in titles if f.provenance.section == "resolution_3")
        assert "Chandrasekaran" in res3.value

    def test_agm_date_2026(self):
        assert self.r.excerpts.get("agm_date") == "2026-06-09"


# ---------------------------------------------------------------------------
# Vote percentage extraction (unit-level, testing _extract_vote_pcts directly)
# ---------------------------------------------------------------------------


class TestVotePctExtraction:
    def test_layout_a_column_split(self):
        """Column (7) header separates col 6 from col 7 in the tail."""
        pct_for, pct_against = _extract_vote_pcts(_RESOLUTION_BLOCK_COL_SPLIT)
        assert pct_for == pytest.approx(99.85, abs=0.01)
        assert pct_against == pytest.approx(0.15, abs=0.01)
        assert abs(pct_for + pct_against - 100.0) < 0.05

    def test_layout_b_total_row(self):
        """Grand totals are in the Total row just before Whether marker."""
        pct_for, pct_against = _extract_vote_pcts(_RESOLUTION_BLOCK_TOTAL_ROW)
        assert pct_for == pytest.approx(99.8298)
        assert pct_against == pytest.approx(0.1702)

    def test_layout_a_robust_garbled_col7_header(self):
        """Garbled col(7) header => complement search still finds pct_for."""
        pct_for, pct_against = _extract_vote_pcts(_RESOLUTION_BLOCK_COMPLEMENT)
        assert pct_for == pytest.approx(99.6558)
        assert pct_against == pytest.approx(0.3442)

    def test_sum_always_close_to_100(self):
        for block in (
            _RESOLUTION_BLOCK_COL_SPLIT,
            _RESOLUTION_BLOCK_TOTAL_ROW,
            _RESOLUTION_BLOCK_COMPLEMENT,
        ):
            pf, pa = _extract_vote_pcts(block)
            if pf is not None:
                assert abs(pf + pa - 100.0) < 0.05

    def test_returns_none_pair_when_no_valid_data(self):
        pct_for, pct_against = _extract_vote_pcts("No numbers here at all.")
        assert pct_for is None
        assert pct_against is None

    def test_returns_none_when_sum_out_of_range(self):
        # Two numbers that don't sum to ~100
        block = "Whether resolution is Pass or Not.\n50.0000\n30.0000\nYes"
        pct_for, pct_against = _extract_vote_pcts(block)
        assert pct_for is None


# ---------------------------------------------------------------------------
# Vote percentage facts in full analyzer output
# ---------------------------------------------------------------------------


class TestVotePctFacts:
    def setup_method(self):
        content = _voting_doc(
            summary=_VOTING_SUMMARY_SECTION,
            blocks=_RESOLUTION_BLOCK_TOTAL_ROW,
        )
        self.r = analyze("eid", _kb(content))

    def test_pct_for_fact_emitted(self):
        facts = _facts(self.r, FactKind.GOVERNANCE_VOTE_PCT_FOR)
        assert len(facts) >= 1

    def test_pct_for_unit_is_percent(self):
        facts = _facts(self.r, FactKind.GOVERNANCE_VOTE_PCT_FOR)
        assert all(f.unit == FactUnit.PERCENT for f in facts)

    def test_pct_against_unit_is_percent(self):
        facts = _facts(self.r, FactKind.GOVERNANCE_VOTE_PCT_AGAINST)
        assert all(f.unit == FactUnit.PERCENT for f in facts)

    def test_pct_for_value_correct(self):
        facts = _facts(self.r, FactKind.GOVERNANCE_VOTE_PCT_FOR)
        assert any(abs(f.value - 99.8298) < 0.001 for f in facts)

    def test_pct_against_value_correct(self):
        facts = _facts(self.r, FactKind.GOVERNANCE_VOTE_PCT_AGAINST)
        assert any(abs(f.value - 0.1702) < 0.001 for f in facts)

    def test_pct_confidence_is_medium(self):
        facts = _facts(self.r, FactKind.GOVERNANCE_VOTE_PCT_FOR)
        assert all(f.confidence == "medium" for f in facts)


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_high_with_three_or_more_titles(self):
        # Add a 3rd resolution (blank line after number required for split)
        big_summary = _VOTING_SUMMARY_SECTION + """3.

To appoint Secretarial Auditors.

Ordinary
Remote e-voting prior and during the AGM
Passed
with
requisite
majority
"""
        content = _voting_doc(summary=big_summary)
        r = analyze("eid", _kb(content))
        assert r.confidence == "high"

    def test_medium_with_one_title(self):
        # Single resolution — blank line after number required for split
        one_res = """
VOTING RESULTS OF THE MEETING
Sr. No.
Agenda
Resolution required
Mode of Voting
Remarks
1.

To adopt the financial statements.

Ordinary
Remote e-voting
Passed
with
requisite
majority
"""
        content = _voting_doc(summary=one_res)
        r = analyze("eid", _kb(content))
        assert r.confidence == "medium"

    def test_low_confidence_for_notice_subtype(self):
        content = "Sub: AGM Notice\n\nDear Shareholders..."
        r = analyze("eid", _kb(content))
        assert r.confidence == "low"


# ---------------------------------------------------------------------------
# Provenance invariants
# ---------------------------------------------------------------------------


class TestProvenance:
    def setup_method(self):
        content = _voting_doc(summary=_VOTING_SUMMARY_SECTION)
        self.r = analyze("eid", _kb(content))

    def test_all_facts_have_provenance_section(self):
        for f in self.r.facts:
            assert f.provenance.section, f"fact {f.kind} missing provenance section"

    def test_resolution_facts_in_resolution_sections(self):
        res_kinds = {
            FactKind.GOVERNANCE_RESOLUTION_TITLE,
            FactKind.GOVERNANCE_RESOLUTION_TYPE,
            FactKind.GOVERNANCE_RESOLUTION_OUTCOME,
        }
        for f in self.r.facts:
            if f.kind in res_kinds:
                assert f.provenance.section.startswith("resolution_")

    def test_period_is_agm_date(self):
        for f in self.r.facts:
            assert f.period == "2025-06-19"
