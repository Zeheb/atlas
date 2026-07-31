"""Unit tests for atlas.analysis.investor_presentation (v2.0).

All tests use synthetic fixtures — no real repository access required.

v2.0 redesigns extraction around cross-sector concepts (see module docstring
in investor_presentation.py for the full rationale) rather than v1.0's
TCS-slide-title-literal patterns. Coverage:

  Error handling:
    - Missing evidence_id / wrong kind / empty content raise ValueError

  Period detection:
    - Textual date ("Quarter Ended September 30, 2024")
    - Numeric DD.MM.YYYY date (SBI cover-letter style)
    - "half year ended" is not misdetected as annual (substring-match bug)
    - "quarter and year ended" (Q4-bundled) is detected as annual

  Strategy facts:
    - STRATEGY_ASPIRATION: multiple lead-in phrasings, recurring-header
      truncation avoidance (regression: real TCS deck repeats the aspiration
      sentence before every slide's own heading)
    - STRATEGY_PRIORITY: heading-anchored bullet extraction, dedup, cap
    - STRATEGY_GUIDANCE: keyword-anchored sentence, chart-style bare-range
      fallback with no verb at all

  Financial facts:
    - FINANCIAL_ROE / FINANCIAL_FCF: inline sentence disclosure, bar-chart
      block disclosure (regression: interleaved "year1 value1, year2..year6,
      value2..value5" layout observed in a real TCS filing), ambiguous
      heading discrimination (regression: "Capital Allocation" heading
      precedes a clean chart in one company's deck and unrelated prose
      bullets in another's — the prose case must not produce false facts)
    - Banking ratio family (NII/NIM/NPA/PCR/credit cost/CASA/CAR/slippage):
      labelled KPI table, dedup across repeated table appearances
    - FINANCIAL_PRODUCTION_VOLUME / FINANCIAL_DELIVERY_VOLUME: labelled row

  Segment growth:
    - Value-then-label pairing, dedup
    - Stray connector-word skip (regression: SBI's "YoY Growth in\\nDeposits"
      layout inserts an extra "in" line the label must not capture)

  Confidence and provenance invariants
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.analysis.investor_presentation import ANALYZER_VERSION, analyze

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _kb(
    content: str,
    kind: str = "investor_presentation",
    source_date: str = "2025-12-17T10:00:00+00:00",
) -> MagicMock:
    entry = MagicMock()
    entry.kind = kind
    entry.source_date = source_date
    kb = MagicMock()
    kb.get.return_value = entry
    kb.get_content.return_value = content
    return kb


def _missing_kb() -> MagicMock:
    kb = MagicMock()
    kb.get.return_value = None
    return kb


def _facts(result: AnalysisResult, kind: FactKind):
    return [f for f in result.facts if f.kind == kind]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    def test_missing_entry_raises(self):
        with pytest.raises(ValueError, match="not in knowledge base"):
            analyze("eid", _missing_kb())

    def test_wrong_kind_raises(self):
        with pytest.raises(ValueError, match="not 'investor_presentation'"):
            analyze("eid", _kb("content", kind="financial_results"))

    def test_empty_content_raises(self):
        with pytest.raises(ValueError, match="no content"):
            analyze("eid", _kb(""))

    def test_analyzer_version(self):
        result = analyze("eid", _kb("Quarter Ended June 30, 2024\n"))
        assert result.analyzer_version == ANALYZER_VERSION

    def test_kind_recorded_in_result(self):
        result = analyze("eid", _kb("Quarter Ended June 30, 2024\n"))
        assert result.kind == "investor_presentation"


# ---------------------------------------------------------------------------
# Period detection
# ---------------------------------------------------------------------------


class TestPeriodDetection:
    def test_textual_quarter_end(self):
        result = analyze("eid", _kb("Quarter Ended September 30, 2024\n"))
        facts = _facts(result, FactKind.REPORT_PERIOD_END)
        assert len(facts) == 1
        assert facts[0].value == "2024-09-30"

    def test_textual_quarter_type_is_quarterly(self):
        result = analyze("eid", _kb("Quarter Ended June 30, 2024\n"))
        facts = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        assert facts[0].value == "quarterly"

    def test_numeric_ddmmyyyy_date(self):
        # SBI cover-letter style: "quarter and half year ended 30.09.2024"
        content = "Presentation on financial results for the quarter and half year ended 30.09.2024.\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.REPORT_PERIOD_END)
        assert facts[0].value == "2024-09-30"

    def test_half_year_not_misdetected_as_annual(self):
        # Regression: "half year" contains the substring "year" — a naive
        # check would wrongly classify this as an annual filing.
        content = "Presentation for the quarter and half year ended 30.09.2024.\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        assert facts[0].value == "quarterly"

    def test_quarter_and_year_ended_is_annual(self):
        # Tata Steel style: Q4 results bundled with full-year figures.
        content = "Investor presentation for the quarter and financial year ended March 31, 2026.\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        assert facts[0].value == "annual"

    def test_period_from_newline_split_date(self):
        content = (
            "Earnings Conference Call for\nthe Quarter Ended September\n30, 2024\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.REPORT_PERIOD_END)
        assert facts[0].value == "2024-09-30"

    def test_no_period_emits_warning(self):
        result = analyze("eid", _kb("No date mentioned anywhere in this text.\n"))
        assert any("period" in w.lower() for w in result.warnings)
        assert _facts(result, FactKind.REPORT_PERIOD_END) == []


# ---------------------------------------------------------------------------
# Strategic aspiration
# ---------------------------------------------------------------------------


class TestAspiration:
    def test_we_will_be_phrasing(self):
        content = "We will be the world's largest AI-led Technology Services company.\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_ASPIRATION)
        assert len(facts) == 1
        assert "world's largest" in facts[0].value

    def test_our_vision_is_to_phrasing(self):
        content = "Our vision is to be the most trusted digital bank in India.\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_ASPIRATION)
        assert "most trusted digital bank" in facts[0].value

    def test_our_purpose_is_to_phrasing(self):
        content = "Our purpose is to power sustainable steel for a better India.\n"
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_ASPIRATION)

    def test_recurring_header_does_not_bleed_into_capture(self):
        # Regression: a real TCS deck repeats "We will be the world's
        # largest AI-led Technology Services company" before every slide's
        # own "Our Aspiration" heading — the first occurrence in the raw
        # PDF text has a hard line-wrap, and later slide-title text run
        # together by whitespace normalization must not be captured.
        content = (
            "We will be the world's largest\n"
            "AI-led Technology Services company\n"
            "Our Aspiration\n\n"
            "Pillars of our Transformation\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_ASPIRATION)
        assert len(facts) == 1
        assert "Our Aspiration" not in facts[0].value
        assert "Pillars" not in facts[0].value

    def test_aspiration_unit_and_period_are_none(self):
        content = "We will be the world's largest AI-led Technology Services company.\n"
        result = analyze("eid", _kb(content))
        fact = _facts(result, FactKind.STRATEGY_ASPIRATION)[0]
        assert fact.unit is None
        assert fact.period is None

    def test_missing_aspiration_emits_warning(self):
        result = analyze("eid", _kb("Quarter Ended June 30, 2024\n"))
        assert any("aspiration" in w.lower() for w in result.warnings)

    def test_aspiration_in_excerpts(self):
        content = "We will be the world's largest AI-led Technology Services company.\n"
        result = analyze("eid", _kb(content))
        assert "aspiration" in result.excerpts


# ---------------------------------------------------------------------------
# Strategic priorities
# ---------------------------------------------------------------------------


class TestPriorities:
    _PRIORITY_TEXT = (
        "Strategic Priorities\n"
        "Operational Excellence\n"
        "Digital Transformation\n"
        "Sustainable Growth\n"
    )

    def test_priorities_extracted_under_heading(self):
        result = analyze("eid", _kb(self._PRIORITY_TEXT))
        values = [f.value for f in _facts(result, FactKind.STRATEGY_PRIORITY)]
        assert "Operational Excellence" in values
        assert "Digital Transformation" in values
        assert "Sustainable Growth" in values

    def test_no_heading_no_priorities(self):
        # Bullet lists without an explicit "Strategic Priorities"-style
        # heading must not be treated as priorities — too easy to false-
        # positive on arbitrary bullet lists in a deck.
        content = "Operational Excellence\nDigital Transformation\n"
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_PRIORITY) == []

    def test_duplicate_priorities_deduplicated(self):
        repeated = self._PRIORITY_TEXT + self._PRIORITY_TEXT
        result = analyze("eid", _kb(repeated))
        values = [f.value for f in _facts(result, FactKind.STRATEGY_PRIORITY)]
        assert values.count("Operational Excellence") == 1

    def test_priority_unit_is_none(self):
        result = analyze("eid", _kb(self._PRIORITY_TEXT))
        for f in _facts(result, FactKind.STRATEGY_PRIORITY):
            assert f.unit is None

    def test_priority_count_capped(self):
        many = "Transformation Pillars\n" + "".join(
            f"Pillar Number {i}\n" for i in range(20)
        )
        result = analyze("eid", _kb(many))
        assert len(_facts(result, FactKind.STRATEGY_PRIORITY)) <= 8


# ---------------------------------------------------------------------------
# Forward guidance
# ---------------------------------------------------------------------------


class TestGuidance:
    def test_targeting_keyword_sentence(self):
        content = "Cost transformation program targeting Rs 7,140 crores in FY2027.\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_GUIDANCE)
        assert any("targeting" in f.value.lower() for f in facts)

    def test_guidance_keyword_sentence(self):
        content = "Long-term margin guidance stands at 26-28% over the cycle.\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_GUIDANCE)
        assert facts

    def test_chart_style_range_under_margin_heading(self):
        # No verb at all — a bare range sitting under a generic heading,
        # as in TCS's "Margin Levers" bar-chart slide.
        content = (
            "Margin Levers\nOperation Excellence\nAI as an Accelerator\n26-28%\n25.2%\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_GUIDANCE)
        assert any("26-28" in f.value for f in facts)

    def test_guidance_unit_and_period_are_none(self):
        content = "Targeting Rs 7,140 crores in FY2027.\n"
        result = analyze("eid", _kb(content))
        fact = _facts(result, FactKind.STRATEGY_GUIDANCE)[0]
        assert fact.unit is None
        assert fact.period is None

    def test_no_guidance_emits_warning(self):
        result = analyze("eid", _kb("Quarter Ended June 30, 2024\n"))
        assert any("guidance" in w.lower() for w in result.warnings)

    def test_guidance_count_capped(self):
        many = "".join(f"targeting {i}% by FY203{i % 9}. " for i in range(10)) + "\n"
        result = analyze("eid", _kb(many))
        assert len(_facts(result, FactKind.STRATEGY_GUIDANCE)) <= 3


# ---------------------------------------------------------------------------
# Return on Equity / Free Cash Flow
# ---------------------------------------------------------------------------


class TestROEFCF:
    def test_roe_inline_sentence(self):
        content = "Return on Equity at 21.78% for H1FY25.\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_ROE)
        assert facts[0].value == pytest.approx(21.78)
        assert facts[0].unit == FactUnit.PERCENT

    def test_fcf_inline_sentence(self):
        content = "Consolidated EBITDA grew and free cash flows ~Rs 10,738 crores in FY2026.\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_FCF)
        assert facts[0].value == pytest.approx(10738.0)
        assert facts[0].unit == FactUnit.CRORE_INR

    def test_roe_bar_chart_block_clean_layout(self):
        # "All labels, then all values" — the common layout.
        content = (
            "Return on Equity\n"
            "FY 2021\nFY 2022\nFY 2023\n"
            "38.2%\n42.6%\n45.9%\n"
            "23.6%\nPeer\nAverage\n"
            "Industry Leading RoE\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_ROE)
        vals = {f.period: f.value for f in facts}
        assert vals["2021-03-31"] == pytest.approx(38.2)
        assert vals["2022-03-31"] == pytest.approx(42.6)
        assert vals["2023-03-31"] == pytest.approx(45.9)
        # The "Peer Average" annotation must not be captured as a 4th year.
        assert 23.6 not in vals.values()

    def test_fcf_bar_chart_block_interleaved_layout(self):
        # Regression: a real TCS filing's PDF extraction interleaves the
        # first bar's label+value, then groups the *remaining* years and
        # values separately — "FY 2021, 30664, FY 2022, FY 2023, 31424,
        # 45602" rather than "FY 2021, FY 2022, FY 2023, 30664, 31424,
        # 45602". A naive "years block then values block" split mis-pairs
        # every single year in this layout.
        content = (
            "Capital Allocation\n"
            "FY 2021\n30,664\nFY 2022\nFY 2023\n31,424\n45,602\n"
            "Free cashflow after all investments\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_FCF)
        vals = {f.period: f.value for f in facts}
        assert vals["2021-03-31"] == 30664
        assert vals["2022-03-31"] == 31424
        assert vals["2023-03-31"] == 45602

    def test_capital_allocation_heading_prose_not_misread_as_chart(self):
        # Regression: the exact same "Capital Allocation" heading text
        # precedes unrelated bulleted prose in a real Tata Steel filing,
        # containing a capex figure that must not be captured as FCF.
        content = (
            "Capital Allocation\n"
            "Operational excellence\n"
            "Optimise Capital Structure & Cost\n"
            "Value accretive investments\n"
            "Capex of ~Rs 14,026 crores in FY2026\n"
            "Optimise working capital\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_FCF)
        assert 14026.0 not in [f.value for f in facts]

    def test_fcf_heading_window_does_not_bleed_into_the_next_slide(self):
        # Regression, from the real Tata Steel 2QFY22 results deck
        # (bse-news-1ac7b809..., OCR-extracted, quality 0.9339). The "Free
        # Cash Flow" slide's own chart is an image that OCR yields no numbers
        # for, so the 300-character heading window runs past the page footer
        # ("TATA STEEL| 23") into the NEXT slide -- a gross debt waterfall.
        #
        # Text below is verbatim from that document at char_offset 25112,
        # OCR noise included. The three numbers are a debt repayment figure
        # and two gross-debt balances; none is free cash flow. The analyzer
        # emitted all three as FINANCIAL_FCF for 2022-03-31, because
        # _RE_FY_YEAR matches inside "2QFY22" twice and "1HFY22" once and
        # FIFO gave each repeated year its own value.
        #
        # The discriminator is that a multi-year bar chart labels each bar
        # with a DIFFERENT year. Repeated year tokens mean the labels are
        # incidental prose, not an axis.
        content = (
            "Free Cash Flow\n"
            "2QFY22\n"
            "movement\n"
            "2QFY22\n"
            "TATA STEEL| 23\n"
            "\n"
            "Debt repayment of Rs.11,424 crores in 1HFY22\n"
            "88,501\n"
            "Rs. Crores\n"
            "106 |\n"
            "5,894\n"
            "84,237\n"
        )
        result = analyze("eid", _kb(content))
        values = [f.value for f in _facts(result, FactKind.FINANCIAL_FCF)]
        assert 11424 not in values, "debt repayment captured as free cash flow"
        assert 88501 not in values, "gross debt at Mar'21 captured as free cash flow"
        assert 84237 not in values, "gross debt at Jun'21 captured as free cash flow"

    def test_repeated_year_labels_are_not_a_chart(self):
        # The same rule stated directly, without the OCR noise: three values
        # under one heading all claiming the same year is not a three-bar
        # chart, and keeping the first would be keeping an arbitrary one.
        content = "Free Cash Flow\nFY 2022\n11,424\nFY 2022\n88,501\nFY 2022\n84,237\n"
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.FINANCIAL_FCF) == []

    def test_roe_fcf_period_ends_in_march(self):
        # _nearest_fy_period looks backward from the match, matching real
        # disclosure phrasing ("FY2025 Return on Equity at 21.78%").
        content = "FY2025 Return on Equity at 21.78%.\n"
        result = analyze("eid", _kb(content))
        for f in _facts(result, FactKind.FINANCIAL_ROE):
            assert f.period is not None and f.period.endswith("-03-31")


# ---------------------------------------------------------------------------
# Customer Satisfaction Score
# ---------------------------------------------------------------------------


class TestCSAT:
    def test_csat_most_recent_extracted(self):
        content = "92.90%\n93.44%\nH2 FY23\nH1 FY24\nCustomer Satisfaction Score\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_CSAT)
        assert facts[0].value == pytest.approx(93.44)

    def test_csat_period_h1(self):
        content = "93.44%\nH1 FY24\nCustomer Satisfaction Score\n"
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_CSAT)[0].period == "2023-09-30"

    def test_csat_period_h2(self):
        content = "93.93%\nH2 FY25\nCustomer Satisfaction Score\n"
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_CSAT)[0].period == "2025-03-31"

    def test_csat_unit_is_percent(self):
        content = "94.18%\nH1 FY26\nCustomer Satisfaction Score\n"
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_CSAT)[0].unit == FactUnit.PERCENT

    def test_no_csat_no_facts_no_warning(self):
        # CSAT is a services-sector concept — its absence for a bank or a
        # steel company is not an extraction problem worth warning about.
        result = analyze("eid", _kb("Quarter Ended June 30, 2024\n"))
        assert _facts(result, FactKind.STRATEGY_CSAT) == []


# ---------------------------------------------------------------------------
# Banking ratio family
# ---------------------------------------------------------------------------


class TestBankingRatios:
    _KPI_TABLE = (
        "Key indicators\n"
        "Quarter Ended\nYoY Growth\n"
        "Q2FY24\nQ2FY25\n"
        "Net Interest Income\n39,500\n41,620\n5.37%\n"
        "Net Interest Margin\n3.29\n3.14\n-15 bps\n"
        "Credit Cost\n0.22\n0.38\n16 bps\n"
        "Net NPA\n0.64\n0.53\n-11 bps\n"
        "PCR\n75.45\n75.66\n21 bps\n"
        "Capital Adequacy\n14.28\n13.76\n\n"
    )

    def test_net_interest_income(self):
        result = analyze("eid", _kb(self._KPI_TABLE))
        facts = _facts(result, FactKind.FINANCIAL_NET_INTEREST_INCOME)
        assert facts[0].value == pytest.approx(41620.0)
        assert facts[0].unit == FactUnit.CRORE_INR

    def test_net_interest_margin(self):
        result = analyze("eid", _kb(self._KPI_TABLE))
        facts = _facts(result, FactKind.FINANCIAL_NET_INTEREST_MARGIN)
        assert facts[0].value == pytest.approx(3.14)
        assert facts[0].unit == FactUnit.PERCENT

    def test_credit_cost(self):
        result = analyze("eid", _kb(self._KPI_TABLE))
        assert _facts(result, FactKind.FINANCIAL_CREDIT_COST)[0].value == pytest.approx(
            0.38
        )

    def test_net_npa_ratio(self):
        result = analyze("eid", _kb(self._KPI_TABLE))
        assert _facts(result, FactKind.FINANCIAL_NET_NPA_RATIO)[
            0
        ].value == pytest.approx(0.53)

    def test_provision_coverage_ratio(self):
        result = analyze("eid", _kb(self._KPI_TABLE))
        assert _facts(result, FactKind.FINANCIAL_PROVISION_COVERAGE_RATIO)[
            0
        ].value == pytest.approx(75.66)

    def test_capital_adequacy_ratio(self):
        result = analyze("eid", _kb(self._KPI_TABLE))
        assert _facts(result, FactKind.FINANCIAL_CAPITAL_ADEQUACY_RATIO)[
            0
        ].value == pytest.approx(13.76)

    def test_gross_npa_ratio(self):
        content = "Key indicators\nGross NPA\n2.42\n2.13\n-29 bps\n"
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.FINANCIAL_GROSS_NPA_RATIO)[
            0
        ].value == pytest.approx(2.13)

    def test_casa_ratio(self):
        content = "Key indicators\nCASA\n40.5\n39.8\n-70 bps\n"
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.FINANCIAL_CASA_RATIO)[0].value == pytest.approx(
            39.8
        )

    def test_slippage_ratio(self):
        content = "Key indicators\nSlippage Ratio\n0.45\n0.51\n6 bps\n"
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.FINANCIAL_SLIPPAGE_RATIO)[
            0
        ].value == pytest.approx(0.51)

    def test_repeated_table_deduplicated(self):
        # Regression: the same ratio restated in a later detail slide must
        # not produce a second, possibly-conflicting fact.
        repeated = self._KPI_TABLE + "\nCapital Adequacy\n13.49\n13.49\n\n"
        result = analyze("eid", _kb(repeated))
        facts = _facts(result, FactKind.FINANCIAL_CAPITAL_ADEQUACY_RATIO)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(13.76)  # first occurrence wins

    def test_no_kpi_table_no_facts_no_warning(self):
        # A non-financial-sector company simply has no such table — not a
        # warning-worthy extraction failure. ("ratio" is deliberately not
        # searched for here — "aspiration" contains "ratio" as a substring.)
        result = analyze("eid", _kb("Quarter Ended June 30, 2024\n"))
        assert _facts(result, FactKind.FINANCIAL_NET_INTEREST_MARGIN) == []
        assert not any(
            "Key indicators" in w or "NPA" in w or "NIM" in w for w in result.warnings
        )


# ---------------------------------------------------------------------------
# Physical production / delivery volume
# ---------------------------------------------------------------------------


class TestOperatingVolume:
    _VOLUME_TEXT = (
        "Production (mn tons)\n6.22\n6.34\n5.44\n23.43\n21.68\n"
        "Deliveries (mn tons)\n6.19\n6.04\n5.60\n22.53\n20.94\n"
    )

    def test_production_volume_extracted(self):
        result = analyze("eid", _kb(self._VOLUME_TEXT))
        facts = _facts(result, FactKind.FINANCIAL_PRODUCTION_VOLUME)
        assert facts[0].value == pytest.approx(6.22)
        assert facts[0].unit == FactUnit.MILLION_TONNES

    def test_delivery_volume_extracted(self):
        result = analyze("eid", _kb(self._VOLUME_TEXT))
        facts = _facts(result, FactKind.FINANCIAL_DELIVERY_VOLUME)
        assert facts[0].value == pytest.approx(6.19)

    def test_no_volume_row_no_facts(self):
        result = analyze("eid", _kb("Quarter Ended June 30, 2024\n"))
        assert _facts(result, FactKind.FINANCIAL_PRODUCTION_VOLUME) == []
        assert _facts(result, FactKind.FINANCIAL_DELIVERY_VOLUME) == []

    def test_footnote_marker_not_read_as_value(self):
        # Regression: a real Tata Steel filing appends a footnote superscript
        # digit directly to the row label with no separating newline
        # ("Production (mn tons)2 \n6.22 \n...") — extract_n_values must not
        # read that stray "2" as the row's production figure.
        content = "Production (mn tons)2 \n6.22\n6.34\n5.44\n23.43\n21.68\n"
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_PRODUCTION_VOLUME)
        assert facts[0].value == pytest.approx(6.22)


# ---------------------------------------------------------------------------
# Segment growth
# ---------------------------------------------------------------------------


class TestSegmentGrowth:
    _GROWTH_TEXT = (
        "38.2%\nY-O-Y CC\nAI Services\n"
        "9%\nY-O-Y CC\nInteractive\n"
        "7.5%\nY-O-Y CC\nCyber Security\n"
    )

    def test_segment_names_and_growth_paired(self):
        result = analyze("eid", _kb(self._GROWTH_TEXT))
        names = [f.value for f in _facts(result, FactKind.SEGMENT_NAME)]
        growths = [f.value for f in _facts(result, FactKind.SEGMENT_GROWTH_PCT)]
        assert "AI Services" in names
        assert 38.2 in growths
        assert len(names) == len(growths)

    def test_growth_unit_is_percent(self):
        result = analyze("eid", _kb(self._GROWTH_TEXT))
        for f in _facts(result, FactKind.SEGMENT_GROWTH_PCT):
            assert f.unit == FactUnit.PERCENT

    def test_duplicate_segment_deduplicated(self):
        content = "38.2%\nY-O-Y CC\nAI Services\n35.0%\nY-O-Y CC\nAI Services\n"
        result = analyze("eid", _kb(content))
        names = [f.value for f in _facts(result, FactKind.SEGMENT_NAME)]
        assert names.count("AI Services") == 1

    def test_connector_word_skipped(self):
        # Regression: SBI's layout inserts a stray "in" line between the
        # growth-label line and the real name ("YoY Growth\nin\nDeposits").
        content = "9.13%\nYoY Growth\nin\nDeposits\n"
        result = analyze("eid", _kb(content))
        names = [f.value for f in _facts(result, FactKind.SEGMENT_NAME)]
        assert names == ["Deposits"]
        assert "in" not in names

    def test_yoy_variant_without_cc_suffix(self):
        content = "9.13%\nYoY Growth\nin\nDeposits\n"
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.SEGMENT_GROWTH_PCT)[0].value == pytest.approx(
            9.13
        )


# ---------------------------------------------------------------------------
# Management commentary excerpt
# ---------------------------------------------------------------------------


class TestManagementCommentary:
    def test_named_quote_block_captured_as_excerpt(self):
        content = (
            "Management Comments:\n"
            "Mr. T V Narendran, Chief Executive Officer & Managing Director:\n"
            "FY2026 was characterised by elevated uncertainty across global markets, "
            "and our sustained focus on operational discipline delivered strong results.\n"
            "Disclaimer\n"
            "Statements in this release are forward-looking.\n"
        )
        result = analyze("eid", _kb(content))
        assert "management_commentary" in result.excerpts
        assert "T V Narendran" in result.excerpts["management_commentary"]

    def test_no_commentary_block_no_excerpt(self):
        result = analyze("eid", _kb("Quarter Ended June 30, 2024\n"))
        assert "management_commentary" not in result.excerpts

    def test_commentary_is_excerpt_not_fact(self):
        content = (
            "Management Comments:\n"
            "Mr. T V Narendran, Chief Executive Officer:\n"
            "Strong performance across all our geographies this year.\n"
        )
        result = analyze("eid", _kb(content))
        # No FactKind exists for free-text commentary — it is excerpt-only.
        assert len(result.facts) == 0 or all(
            "Narendran" not in str(f.value) for f in result.facts
        )


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_high_confidence_with_multiple_fact_categories(self):
        content = (
            "We will be the world's largest AI-led Technology Services company.\n"
            "Return on Equity at 51.2% for FY2025.\n"
            "94.18%\nH1 FY26\nCustomer Satisfaction Score\n"
        )
        result = analyze("eid", _kb(content))
        assert result.confidence == "high"

    def test_medium_confidence_single_category(self):
        content = "We will be the world's largest AI-led Technology Services company.\n"
        result = analyze("eid", _kb(content))
        assert result.confidence == "medium"

    def test_medium_confidence_period_only(self):
        result = analyze("eid", _kb("Quarter Ended June 30, 2024\n"))
        assert result.confidence == "medium"

    def test_low_confidence_nothing_found(self):
        result = analyze(
            "eid", _kb("Some generic text without any recognisable section.\n")
        )
        assert result.confidence == "low"


# ---------------------------------------------------------------------------
# Provenance invariants
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_all_facts_have_section(self):
        content = (
            "Quarter Ended June 30, 2024\n"
            "We will be the world's largest AI-led Technology Services company.\n"
            "Strategic Priorities\nOperational Excellence\n"
            "Return on Equity at 51.2% for FY2025.\n"
            "94.18%\nH1 FY26\nCustomer Satisfaction Score\n"
            "38.2%\nY-O-Y CC\nAI Services\n"
        )
        result = analyze("eid", _kb(content))
        assert result.facts
        for f in result.facts:
            assert f.provenance.section, f"fact {f.kind} missing section"

    def test_source_date_preserved(self):
        result = analyze(
            "eid",
            _kb(
                "Quarter Ended June 30, 2024\n", source_date="2025-12-17T10:00:00+00:00"
            ),
        )
        assert result.source_date.year == 2025
        assert result.source_date.month == 12
