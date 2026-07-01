"""Unit tests for atlas.analysis.investor_presentation.

All tests use synthetic fixtures — no real repository access required.

Coverage:

  Sub-type detection:
    - "strategy" for Analyst Day / slide-deck cover letters
    - "ir_activity" for investor meeting schedule filings

  Error handling:
    - Missing evidence_id raises ValueError
    - Wrong kind raises ValueError
    - Empty content raises ValueError

  Strategy path:
    - STRATEGY_ASPIRATION extracted from aspiration statement
    - STRATEGY_PRIORITY emitted once per pillar (5 pillars)
    - STRATEGY_GUIDANCE extracted as range text from Margin Levers slide
    - SEGMENT_NAME + SEGMENT_GROWTH_PCT pairs from "Y-O-Y CC" table
    - Duplicate segment names deduplicated
    - FINANCIAL_ROE extracted from "Return on Equity" bar chart section
    - FINANCIAL_FCF extracted from "Capital Allocation" bar chart section
    - STRATEGY_CSAT extracted as most-recent half-year value
    - Result confidence: high when aspiration + ROE + CSAT present
    - Result confidence: medium when only aspiration present

  IR activity path:
    - REPORT_PERIOD_END + REPORT_PERIOD_TYPE extracted from quarter end date
    - Quarter date spanning lines is handled via whitespace normalization
    - Result confidence: high when period extracted; medium otherwise
    - Missing quarter date → warning emitted

  Provenance:
    - All facts have a non-empty provenance section
    - Excerpts contain "subtype", "aspiration", "margin_levers" (strategy)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from atlas.analysis.investor_presentation import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit


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


def _strategy(core: str) -> str:
    """Wrap core text with an Analyst Day cover letter header."""
    return (
        "Sub: Submission of presentation to be made during TCS Analyst Day 2025\n\n"
        + core
    )


def _ir(core: str) -> str:
    """Wrap core text with an IR schedule cover letter header."""
    return (
        "Sub: Schedule of Analyst/Institutional Investor Meeting\n\n"
        + core
    )


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


# ---------------------------------------------------------------------------
# Sub-type detection
# ---------------------------------------------------------------------------

class TestSubtypeDetection:
    def test_analyst_day_cover_returns_strategy(self):
        content = _strategy("Some slide text here.")
        result = analyze("eid", _kb(content))
        assert result.excerpts["subtype"] == "strategy"

    def test_ir_schedule_returns_ir_activity(self):
        content = _ir("Schedule of meetings for November 2021.")
        result = analyze("eid", _kb(content))
        assert result.excerpts["subtype"] == "ir_activity"

    def test_earnings_announcement_returns_ir_activity(self):
        content = (
            "Sub: Schedule of Analyst/Institutional Investor Meeting\n\n"
            "TCS to Announce First Quarter FY 2025 Results on July 11, 2024\n"
            "Quarter Ended June 30, 2024\n"
        )
        result = analyze("eid", _kb(content))
        assert result.excerpts["subtype"] == "ir_activity"

    def test_kind_recorded_in_result(self):
        result = analyze("eid", _kb(_strategy("text")))
        assert result.kind == "investor_presentation"

    def test_analyzer_version(self):
        result = analyze("eid", _kb(_strategy("text")))
        assert result.analyzer_version == ANALYZER_VERSION


# ---------------------------------------------------------------------------
# Strategy path — aspiration
# ---------------------------------------------------------------------------

class TestAspiration:
    def test_aspiration_extracted(self):
        content = _strategy(
            "We will be the world's largest\nAI-led Technology Services company\n"
            "Our Aspiration\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_ASPIRATION)
        assert len(facts) == 1

    def test_aspiration_value_normalized(self):
        content = _strategy(
            "We will be the world's largest\nAI-led Technology Services company\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_ASPIRATION)
        assert "\n" not in facts[0].value
        assert "world's largest" in facts[0].value
        assert "AI-led" in facts[0].value

    def test_aspiration_unit_is_none(self):
        content = _strategy(
            "We will be the world's largest\nAI-led Technology Services company\n"
        )
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_ASPIRATION)[0].unit is None

    def test_aspiration_period_is_none(self):
        content = _strategy(
            "We will be the world's largest\nAI-led Technology Services company\n"
        )
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_ASPIRATION)[0].period is None

    def test_aspiration_not_found_emits_warning(self):
        content = _strategy("No aspiration text here.")
        result = analyze("eid", _kb(content))
        assert any("aspiration" in w.lower() for w in result.warnings)
        assert _facts(result, FactKind.STRATEGY_ASPIRATION) == []

    def test_aspiration_in_excerpts(self):
        content = _strategy(
            "We will be the world's largest\nAI-led Technology Services company\n"
        )
        result = analyze("eid", _kb(content))
        assert "aspiration" in result.excerpts


# ---------------------------------------------------------------------------
# Strategy path — transformation pillars
# ---------------------------------------------------------------------------

class TestPillars:
    _PILLAR_TEXT = _strategy(
        "tcsAI Internal Transformation\n"
        "Redefining all Services\n"
        "Future-ready Talent Model\n"
        "Making AI Real for clients\n"
        "AI Ecosystem Play\n"
    )

    def test_five_pillars_extracted(self):
        result = analyze("eid", _kb(self._PILLAR_TEXT))
        facts = _facts(result, FactKind.STRATEGY_PRIORITY)
        values = [f.value for f in facts]
        assert "tcsAI Internal Transformation" in values
        assert "Redefining all Services" in values
        assert "Future-ready Talent Model" in values
        assert "Making AI Real for clients" in values
        assert "AI Ecosystem Play" in values

    def test_each_pillar_extracted_once(self):
        # Pillars repeat many times in a deck; only one fact per pillar.
        repeated = self._PILLAR_TEXT + self._PILLAR_TEXT
        result = analyze("eid", _kb(repeated))
        facts = _facts(result, FactKind.STRATEGY_PRIORITY)
        values = [f.value for f in facts]
        assert values.count("tcsAI Internal Transformation") == 1

    def test_pillar_unit_is_none(self):
        result = analyze("eid", _kb(self._PILLAR_TEXT))
        for f in _facts(result, FactKind.STRATEGY_PRIORITY):
            assert f.unit is None

    def test_partial_pillars_ok(self):
        content = _strategy("tcsAI Internal Transformation\nRedefining all Services\n")
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_PRIORITY)
        assert len(facts) == 2


# ---------------------------------------------------------------------------
# Strategy path — margin guidance
# ---------------------------------------------------------------------------

class TestMarginGuidance:
    def test_guidance_extracted(self):
        content = _strategy(
            "Margin Levers\nOperation Excellence\nAI as an Accelerator\n26-28%\n25.2%\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_GUIDANCE)
        assert len(facts) == 1
        assert facts[0].value == "26-28%"

    def test_guidance_unit_is_none(self):
        content = _strategy("Margin Levers\n26-28%\n")
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_GUIDANCE)[0].unit is None

    def test_guidance_period_is_none(self):
        content = _strategy("Margin Levers\n26-28%\n")
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_GUIDANCE)[0].period is None

    def test_margin_levers_in_excerpts(self):
        content = _strategy("Margin Levers\n26-28%\n")
        result = analyze("eid", _kb(content))
        assert "margin_levers" in result.excerpts


# ---------------------------------------------------------------------------
# Strategy path — service line growth
# ---------------------------------------------------------------------------

class TestServiceLineGrowth:
    _GROWTH_TEXT = _strategy(
        "38.2%\nY-O-Y CC\nAI Services\n"
        "9%\nY-O-Y CC\nInteractive\n"
        "7.5%\nY-O-Y CC\nCyber Security\n"
    )

    def test_segment_names_extracted(self):
        result = analyze("eid", _kb(self._GROWTH_TEXT))
        names = [f.value for f in _facts(result, FactKind.SEGMENT_NAME)]
        assert "AI Services" in names
        assert "Interactive" in names
        assert "Cyber Security" in names

    def test_segment_growth_pct_extracted(self):
        result = analyze("eid", _kb(self._GROWTH_TEXT))
        growths = [f.value for f in _facts(result, FactKind.SEGMENT_GROWTH_PCT)]
        assert 38.2 in growths
        assert 9.0 in growths
        assert 7.5 in growths

    def test_name_and_growth_counts_match(self):
        result = analyze("eid", _kb(self._GROWTH_TEXT))
        n_names   = len(_facts(result, FactKind.SEGMENT_NAME))
        n_growths = len(_facts(result, FactKind.SEGMENT_GROWTH_PCT))
        assert n_names == n_growths

    def test_growth_unit_is_percent(self):
        result = analyze("eid", _kb(self._GROWTH_TEXT))
        for f in _facts(result, FactKind.SEGMENT_GROWTH_PCT):
            assert f.unit == FactUnit.PERCENT

    def test_duplicate_segment_deduplicated(self):
        # Same segment appearing twice should produce only one fact pair.
        content = _strategy(
            "38.2%\nY-O-Y CC\nAI Services\n"
            "35.0%\nY-O-Y CC\nAI Services\n"
        )
        result = analyze("eid", _kb(content))
        names = [f.value for f in _facts(result, FactKind.SEGMENT_NAME)]
        assert names.count("AI Services") == 1


# ---------------------------------------------------------------------------
# Strategy path — Return on Equity
# ---------------------------------------------------------------------------

class TestROE:
    _ROE_TEXT = _strategy(
        "Return on Equity\n"
        "FY 2021\nFY 2022\nFY 2023\n"
        "38.2%\n42.6%\n45.9%\n"
        "23.6%\nPeer\nAverage\n"
        "Industry Leading RoE\n"
    )

    def test_roe_extracted_for_each_year(self):
        result = analyze("eid", _kb(self._ROE_TEXT))
        facts = _facts(result, FactKind.FINANCIAL_ROE)
        assert len(facts) == 3

    def test_roe_values(self):
        result = analyze("eid", _kb(self._ROE_TEXT))
        facts = _facts(result, FactKind.FINANCIAL_ROE)
        vals = {f.period: f.value for f in facts}
        assert vals["2021-03-31"] == pytest.approx(38.2)
        assert vals["2022-03-31"] == pytest.approx(42.6)
        assert vals["2023-03-31"] == pytest.approx(45.9)

    def test_peer_average_excluded(self):
        result = analyze("eid", _kb(self._ROE_TEXT))
        values = [f.value for f in _facts(result, FactKind.FINANCIAL_ROE)]
        assert 23.6 not in values

    def test_roe_unit_is_percent(self):
        result = analyze("eid", _kb(self._ROE_TEXT))
        for f in _facts(result, FactKind.FINANCIAL_ROE):
            assert f.unit == FactUnit.PERCENT

    def test_roe_period_format(self):
        result = analyze("eid", _kb(self._ROE_TEXT))
        for f in _facts(result, FactKind.FINANCIAL_ROE):
            assert f.period.endswith("-03-31")

    def test_roe_missing_emits_warning(self):
        content = _strategy("No ROE section here.")
        result = analyze("eid", _kb(content))
        assert any("ROE" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Strategy path — Free Cash Flow
# ---------------------------------------------------------------------------

class TestFCF:
    _FCF_TEXT = _strategy(
        "Capital Allocation\n"
        "FY 2021\n30,664\nFY 2022\nFY 2023\n31,424\n45,602\n"
        "Free Cash Flow\n"
        "Free cashflow after all investments\n"
    )

    def test_fcf_extracted_for_each_year(self):
        result = analyze("eid", _kb(self._FCF_TEXT))
        facts = _facts(result, FactKind.FINANCIAL_FCF)
        assert len(facts) == 3

    def test_fcf_values(self):
        result = analyze("eid", _kb(self._FCF_TEXT))
        facts = _facts(result, FactKind.FINANCIAL_FCF)
        vals = {f.period: f.value for f in facts}
        assert vals["2021-03-31"] == 30664
        assert vals["2022-03-31"] == 31424
        assert vals["2023-03-31"] == 45602

    def test_fcf_unit_is_crore_inr(self):
        result = analyze("eid", _kb(self._FCF_TEXT))
        for f in _facts(result, FactKind.FINANCIAL_FCF):
            assert f.unit == FactUnit.CRORE_INR

    def test_fcf_period_format(self):
        result = analyze("eid", _kb(self._FCF_TEXT))
        for f in _facts(result, FactKind.FINANCIAL_FCF):
            assert f.period.endswith("-03-31")

    def test_fcf_missing_emits_warning(self):
        content = _strategy("No capital allocation section.")
        result = analyze("eid", _kb(content))
        assert any("FCF" in w or "Capital Allocation" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Strategy path — Customer Satisfaction Score
# ---------------------------------------------------------------------------

class TestCSAT:
    def test_csat_most_recent_extracted(self):
        content = _strategy(
            "92.90%\n93.44%\nH2 FY23\nH1 FY24\n"
            "Customer Satisfaction Score\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_CSAT)
        assert len(facts) == 1
        assert facts[0].value == pytest.approx(93.44)

    def test_csat_period_h1(self):
        # H1 FY24 = April–September 2023 → period end 2023-09-30
        content = _strategy(
            "93.44%\nH1 FY24\nCustomer Satisfaction Score\n"
        )
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_CSAT)[0].period == "2023-09-30"

    def test_csat_period_h2(self):
        # H2 FY25 = October 2024–March 2025 → period end 2025-03-31
        content = _strategy(
            "93.93%\nH2 FY25\nCustomer Satisfaction Score\n"
        )
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_CSAT)[0].period == "2025-03-31"

    def test_csat_unit_is_percent(self):
        content = _strategy("94.18%\nH1 FY26\nCustomer Satisfaction Score\n")
        result = analyze("eid", _kb(content))
        assert _facts(result, FactKind.STRATEGY_CSAT)[0].unit == FactUnit.PERCENT

    def test_csat_takes_last_pair(self):
        content = _strategy(
            "92.90%\n93.44%\n94.18%\nH2 FY23\nH1 FY24\nH1 FY26\n"
            "Customer Satisfaction Score\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_CSAT)
        assert facts[0].value == pytest.approx(94.18)
        assert facts[0].period == "2025-09-30"

    def test_csat_missing_emits_warning(self):
        content = _strategy("No satisfaction score here.")
        result = analyze("eid", _kb(content))
        assert any("Customer Satisfaction" in w or "CSAT" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Strategy path — confidence levels
# ---------------------------------------------------------------------------

class TestStrategyConfidence:
    def test_high_confidence_with_aspiration_roe_csat(self):
        content = _strategy(
            "We will be the world's largest\nAI-led Technology Services company\n"
            "Return on Equity\nFY 2025\n51.2%\nIndustry Leading RoE\n"
            "94.18%\nH1 FY26\nCustomer Satisfaction Score\n"
        )
        result = analyze("eid", _kb(content))
        assert result.confidence == "high"

    def test_medium_confidence_aspiration_only(self):
        content = _strategy(
            "We will be the world's largest\nAI-led Technology Services company\n"
        )
        result = analyze("eid", _kb(content))
        assert result.confidence == "medium"

    def test_low_confidence_no_primary_facts(self):
        content = _strategy("Some generic text without key sections.")
        result = analyze("eid", _kb(content))
        assert result.confidence == "low"


# ---------------------------------------------------------------------------
# IR activity path — period extraction
# ---------------------------------------------------------------------------

class TestIRActivity:
    def test_period_extracted_from_quarter_end(self):
        content = _ir("Quarter Ended September 30, 2024\n")
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.REPORT_PERIOD_END)
        assert len(facts) == 1
        assert facts[0].value == "2024-09-30"

    def test_period_type_quarterly(self):
        content = _ir("Quarter Ended June 30, 2024\n")
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        assert len(facts) == 1
        assert facts[0].value == "quarterly"

    def test_period_from_newline_split_date(self):
        # PDF extraction often splits "September\n30, 2024" across lines.
        content = _ir(
            "Earnings Conference Call for\nthe Quarter Ended September\n30, 2024\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.REPORT_PERIOD_END)
        assert len(facts) == 1
        assert facts[0].value == "2024-09-30"

    def test_multiple_quarter_dates_picks_first(self):
        # Both the meeting schedule and earnings announcement mention the date.
        content = _ir(
            "Quarter Ended September 30, 2024\n"
            "Quarter Ended September 30, 2024\n"
        )
        result = analyze("eid", _kb(content))
        facts = _facts(result, FactKind.REPORT_PERIOD_END)
        assert len(facts) == 1

    def test_various_month_dates(self):
        test_cases = [
            ("Quarter Ended December 31, 2023\n", "2023-12-31"),
            ("Quarter Ended March 31, 2024\n",    "2024-03-31"),
            ("Quarter Ended June 30, 2023\n",     "2023-06-30"),
        ]
        for text, expected in test_cases:
            content = _ir(text)
            result = analyze("eid", _kb(content))
            assert _facts(result, FactKind.REPORT_PERIOD_END)[0].value == expected

    def test_no_quarter_date_emits_warning(self):
        content = _ir("Meeting schedules with no date mention.")
        result = analyze("eid", _kb(content))
        assert result.warnings
        assert _facts(result, FactKind.REPORT_PERIOD_END) == []

    def test_ir_activity_high_confidence_with_period(self):
        content = _ir("Quarter Ended September 30, 2024\n")
        result = analyze("eid", _kb(content))
        assert result.confidence == "high"

    def test_ir_activity_medium_confidence_without_period(self):
        content = _ir("Generic meeting schedule text.")
        result = analyze("eid", _kb(content))
        assert result.confidence == "medium"


# ---------------------------------------------------------------------------
# Provenance invariants
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_all_facts_have_section(self):
        content = _strategy(
            "We will be the world's largest\nAI-led Technology Services company\n"
            "tcsAI Internal Transformation\n"
            "Margin Levers\n26-28%\n"
            "38.2%\nY-O-Y CC\nAI Services\n"
            "Return on Equity\nFY 2025\n51.2%\nIndustry Leading RoE\n"
            "Capital Allocation\nFY 2025\n44,962\nFree cashflow after all investments\n"
            "94.18%\nH1 FY26\nCustomer Satisfaction Score\n"
        )
        result = analyze("eid", _kb(content))
        for f in result.facts:
            assert f.provenance.section, f"fact {f.kind} missing section"

    def test_subtype_always_in_excerpts(self):
        for content in [
            _strategy("text"),
            _ir("text"),
        ]:
            result = analyze("eid", _kb(content))
            assert "subtype" in result.excerpts

    def test_source_date_preserved(self):
        result = analyze("eid", _kb(_strategy("text"), source_date="2025-12-17T10:00:00+00:00"))
        assert result.source_date.year == 2025
        assert result.source_date.month == 12
