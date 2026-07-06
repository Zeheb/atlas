"""Unit tests for atlas.acquisition.classifier.

Every case here is grounded in a real document found during the evidence
coverage audit and Stage 2 investigation — see classifier.py's module
docstring for the specific TCS filings each pattern was calibrated against.
"""
from __future__ import annotations

from atlas.acquisition.classifier import classify


# ---------------------------------------------------------------------------
# Cross-kind reclassification: financial_results -> regulatory_filing
# ---------------------------------------------------------------------------


class TestRelatedPartyReclassification:
    def test_clean_related_party_text_reclassified(self):
        text = (
            "Dear Sirs,\n"
            "Sub: Disclosure of Related Party Transactions pursuant to Regulation 23(9) of the "
            "Securities and Exchange Board of India (Listing Obligations and Disclosure "
            "Requirements) Regulations, 2015\n"
            "Pursuant to Regulation 23(9)..."
        )
        result = classify("financial_results", text, page_count=25)
        assert result.resolved_kind == "regulatory_filing"
        assert result.was_reclassified is True
        assert result.is_substantive is True

    def test_ocr_garbled_text_still_reclassified_via_regulation_number(self):
        # Regression: a real 2019 TCS filing's OCR corrupted "Regulation"
        # to "Resulation" and "pursuant" to "nursuant" character-by-
        # character, but "23(9)" survived intact — digits resist OCR
        # confusion far better than prose.
        text = (
            "Sub: Disclosure of Related Partv Transactions nursuant to Resulation 23(9) of the\n"
            "Securifies a Exchanse Roard of In"
        )
        result = classify("financial_results", text, page_count=3)
        assert result.resolved_kind == "regulatory_filing"

    def test_real_financial_results_not_reclassified(self):
        text = (
            "Dear Sirs,\n"
            "Sub: Financial Results for the year ended on March 31, 2026 and Recommendation "
            "of a Final Dividend\n"
            "We enclose the audited standalone financial results..."
        )
        result = classify("financial_results", text, page_count=25)
        assert result.resolved_kind == "financial_results"
        assert result.was_reclassified is False
        assert result.is_substantive is True

    def test_only_applies_to_financial_results_kind(self):
        # A related-party Sub line on a document already correctly
        # catalogued as regulatory_filing shouldn't "reclassify" to itself
        # in a way that looks like a correction was made.
        text = "Sub: Disclosure of Related Party Transactions pursuant to Regulation 23(9)"
        result = classify("regulatory_filing", text, page_count=5)
        assert result.was_reclassified is False


# ---------------------------------------------------------------------------
# Substantive vs. cover-letter / schedule notice (same kind, not reclassified)
# ---------------------------------------------------------------------------


class TestInvestorPresentationSubstance:
    def test_schedule_notice_flagged_not_substantive(self):
        text = "Dear Sirs,\nSub: Schedule of Analyst / Institutional Investor Meetings\n"
        result = classify("investor_presentation", text, page_count=2)
        assert result.is_substantive is False
        assert result.was_reclassified is False

    def test_real_deck_submission_flagged_substantive(self):
        text = "Sub: Submission of presentation to be made during TCS Analyst Day 2025\n" + ("x" * 3000)
        result = classify("investor_presentation", text, page_count=55)
        assert result.is_substantive is True

    def test_low_page_count_alone_flags_non_substantive(self):
        # No recognizable Sub line at all, but page count is decisive on
        # its own — a 2-page "presentation" isn't one.
        text = "Some cover text with no Sub line pattern at all, just noise."
        result = classify("investor_presentation", text, page_count=2)
        assert result.is_substantive is False

    def test_high_page_count_passes_without_sub_line(self):
        text = "No sub line here either." + ("content " * 500)
        result = classify("investor_presentation", text, page_count=40)
        assert result.is_substantive is True

    def test_missing_page_count_does_not_crash(self):
        text = "Sub: Submission of presentation"
        result = classify("investor_presentation", text, page_count=None)
        assert result.is_substantive is True


class TestAnnualReportSubstance:
    def test_agm_forwarding_letter_flagged_not_substantive(self):
        text = "Sub: Intimation under Regulation 34 of SEBI (Listing Obligations and Disclosure"
        result = classify("annual_report", text, page_count=2)
        assert result.is_substantive is False

    def test_real_annual_report_flagged_substantive(self):
        text = 'Sub: Notice convening the 31st Annual General Meeting ("AGM") and Integrated Annual Report'
        result = classify("annual_report", text, page_count=150)
        assert result.is_substantive is True

    def test_agm_notice_that_also_names_annual_report_passes(self):
        # The substantive-keyword check runs first — a Sub line that
        # mentions both AGM *and* "annual report" must not be penalized
        # just because it also looks like a notice. Page count is a real,
        # independent floor too (no genuine annual report is 3 pages), so
        # this uses a realistic page count to isolate the Sub-line check.
        text = "Sub: Notice convening AGM and Integrated Annual Report 2025-26"
        result = classify("annual_report", text, page_count=120)
        assert result.is_substantive is True


class TestEarningsTranscriptSubstance:
    def test_real_transcript_substantive(self):
        text = "Sub: Transcript of the earnings conference call\n" + ("x" * 3000)
        result = classify("earnings_transcript", text, page_count=34)
        assert result.is_substantive is True

    def test_short_non_transcript_flagged(self):
        text = "Sub: Schedule of the earnings conference call"
        result = classify("earnings_transcript", text, page_count=2)
        assert result.is_substantive is False


# ---------------------------------------------------------------------------
# Kinds with no calibrated rules pass through unexamined
# ---------------------------------------------------------------------------


class TestUncalibratedKindsPassThrough:
    def test_board_outcome_always_substantive(self):
        result = classify("board_outcome", "any text at all", page_count=1)
        assert result.is_substantive is True
        assert result.was_reclassified is False

    def test_credit_rating_report_always_substantive(self):
        result = classify("credit_rating_report", "any text at all", page_count=1)
        assert result.is_substantive is True


# ---------------------------------------------------------------------------
# ClassificationResult properties
# ---------------------------------------------------------------------------


class TestClassificationResult:
    def test_was_reclassified_false_when_kind_unchanged(self):
        result = classify("board_outcome", "text", page_count=5)
        assert result.was_reclassified is False

    def test_reason_always_populated(self):
        for kind, text, pages in [
            ("investor_presentation", "Sub: Schedule of Analyst Meetings", 2),
            ("financial_results", "Sub: Financial Results", 10),
            ("board_outcome", "no sub line", 3),
        ]:
            result = classify(kind, text, pages)
            assert result.reason
