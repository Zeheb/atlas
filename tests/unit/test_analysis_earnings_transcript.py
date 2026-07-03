"""Unit tests for atlas.analysis.earnings_transcript (v2.0).

All tests use synthetic fixtures — no real repository access required.

v2.0 redesigns extraction around cross-sector concepts (see module
docstring in earnings_transcript.py) rather than v1.0's TCS-only speaker
structure and phrasing. Coverage:

  Period detection:
    - Phrase-based ("quarter ended...", "quarter and year ended...")
    - "half year" not misdetected as annual (substring-match bug)
    - "QN FYyy" label fallback when no phrase is found
    - Quarter-to-month mapping for all four Indian fiscal quarters

  Prepared-remarks / Q&A boundary:
    - Regression: an early agenda-description sentence ("...followed by a
      Q&A session", "we will take any questions you may have") must not be
      mistaken for the real hand-off, which happens much later

  Financial facts:
    - Revenue: both "₹" and "Rs" currency markers, verb-anchored (not a
      bare currency-symbol match — a stray capex/dividend figure must not
      be misread as revenue)
    - Annual revenue: found by position, not object identity (regression:
      a naive `is`-comparison never actually skips the quarterly match)
    - Margin: generalized beyond "operating margin" to a bare "margin of
      NN%" (Tata Steel's phrasing), explicit "net margin" routes correctly
    - Margin-near-revenue preference (regression: an earlier, unrelated
      segment-level margin mention must not be preferred over the true
      headline figure stated right next to revenue)
    - TCV (IT-services specific)

  Forward guidance (shared pattern with investor_presentation.py)

  Workforce (reused ESG_WORKFORCE_* FactKinds, not new)

  Confidence and provenance invariants
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from atlas.analysis.earnings_transcript import ANALYZER_VERSION, analyze
from atlas.analysis.base import AnalysisResult, FactKind, FactUnit


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _kb(
    content: str,
    kind: str = "earnings_transcript",
    source_date: str = "2026-04-14T19:57:43+05:30",
) -> MagicMock:
    entry = MagicMock()
    entry.kind = kind
    entry.source_date = source_date
    kb = MagicMock()
    kb.get.return_value = entry
    kb.get_content.return_value = content
    return kb


def _facts(result: AnalysisResult, kind: FactKind):
    return [f for f in result.facts if f.kind == kind]


# A generic prepared-remarks-then-Q&A skeleton. The agenda-mention sentence
# ("session. We will then take questions.") appears early and deliberately
# resembles the real Q&A transition phrase family closely enough to test
# the false-positive guard, while the real transition ("We will now begin
# the question-and-answer session.") sits much later, mirroring the actual
# proportional gap observed in real filings.
def _transcript(prepared: str, qa: str = "") -> str:
    padding = "Filler commentary continuing the call. " * 40
    return (
        "Sub: Transcript of the earnings conference call for the quarter "
        "and year ended March 31, 2026\n\n"
        "Moderator: Welcome everyone. Management will make opening remarks "
        "and then we will take any questions you may have.\n\n"
        f"{prepared}\n{padding}\n"
        "Moderator: We will now begin the question-and-answer session.\n\n"
        f"{qa}"
    )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_missing_entry_raises(self):
        kb = MagicMock()
        kb.get.return_value = None
        with pytest.raises(ValueError, match="not in knowledge base"):
            analyze("x", kb)

    def test_wrong_kind_raises(self):
        with pytest.raises(ValueError, match="not 'earnings_transcript'"):
            analyze("x", _kb("text", kind="board_outcome"))

    def test_empty_content_raises(self):
        with pytest.raises(ValueError, match="no content"):
            analyze("x", _kb(""))

    def test_analyzer_version(self):
        result = analyze("x", _kb(_transcript("Revenue was ₹70,698 crore.")))
        assert result.analyzer_version == ANALYZER_VERSION

    def test_kind_recorded(self):
        result = analyze("x", _kb(_transcript("Revenue was ₹70,698 crore.")))
        assert result.kind == "earnings_transcript"


# ---------------------------------------------------------------------------
# Period detection
# ---------------------------------------------------------------------------

class TestPeriodDetection:
    def test_quarter_ended_phrase(self):
        content = "Sub: Transcript for the quarter ended September 30, 2025\n\nBody text.\n"
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.REPORT_PERIOD_END)[0].value == "2025-09-30"
        assert _facts(result, FactKind.REPORT_PERIOD_TYPE)[0].value == "quarterly"

    def test_quarter_and_year_ended_is_annual(self):
        content = "Sub: Transcript for the quarter and year ended March 31, 2026\n\nBody.\n"
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.REPORT_PERIOD_TYPE)[0].value == "annual"

    def test_half_year_not_misdetected_as_annual(self):
        # Regression: "half year" contains the substring "year" — a naive
        # check would wrongly classify this as an annual filing.
        content = "Sub: Transcript for the quarter and half year ended September 30, 2025\n\nBody.\n"
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.REPORT_PERIOD_TYPE)[0].value == "quarterly"

    def test_quarter_label_fallback_q4(self):
        content = "Q4FY26 ANALYST MEET TRANSCRIPT\n\nSome opening remarks with no explicit date phrase.\n"
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.REPORT_PERIOD_END)[0].value == "2026-03-31"

    def test_quarter_label_fallback_q2(self):
        content = "Transcript of Q2FY26 post-results Analyst Meet.\n\nOpening remarks.\n"
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.REPORT_PERIOD_END)[0].value == "2025-09-30"

    def test_quarter_label_fallback_q1(self):
        content = "Q1 FY26 Earnings Call Transcript.\n\nOpening remarks.\n"
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.REPORT_PERIOD_END)[0].value == "2025-06-30"

    def test_quarter_label_fallback_q3(self):
        content = "Q3FY26 Earnings Call Transcript.\n\nOpening remarks.\n"
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.REPORT_PERIOD_END)[0].value == "2025-12-31"

    def test_no_period_found_emits_warning(self):
        result = analyze("x", _kb("No date or quarter label mentioned anywhere.\n"))
        assert any("period" in w.lower() for w in result.warnings)
        assert _facts(result, FactKind.REPORT_PERIOD_END) == []


# ---------------------------------------------------------------------------
# Prepared-remarks / Q&A boundary
# ---------------------------------------------------------------------------

class TestQABoundary:
    def test_agenda_mention_does_not_truncate_prepared_remarks(self):
        # The skeleton's early "we will take any questions you may have"
        # (agenda mention) must not be treated as the real Q&A start — a
        # revenue figure placed after it, but before the real transition,
        # must still be found.
        content = _transcript("Our revenue was ₹70,698 crore.")
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.FINANCIAL_REVENUE)

    def test_figures_after_real_qa_transition_not_searched(self):
        content = _transcript(
            "Our operating margin was 25%.",
            qa="Analyst: What about next year? Management: Revenue was ₹99,999 crore.",
        )
        result = analyze("x", _kb(content))
        revs = [f.value for f in _facts(result, FactKind.FINANCIAL_REVENUE)]
        assert 99999.0 not in revs


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------

class TestRevenue:
    def test_rupee_symbol_with_stood_at(self):
        content = _transcript("Our revenue was ₹70,698 crore, a strong quarter.")
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_REVENUE)
        assert any(f.value == 70698.0 and f.unit == FactUnit.CRORE_INR for f in facts)

    def test_rs_text_marker_not_just_rupee_symbol(self):
        # Regression: v1.0 anchored purely on the "₹" glyph. Tata Steel's
        # CFO uses the text marker "Rs" instead.
        content = _transcript("Our consolidated revenues stood at Rs 63,270 crores this quarter.")
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_REVENUE)
        assert any(f.value == 63270.0 for f in facts)

    def test_requires_verb_not_bare_currency_match(self):
        # Regression: v1.0's bare "₹\s*NUMBER" pattern would misread ANY
        # rupee figure in the search window (e.g. a capex figure) as
        # revenue. A capex-only sentence must not produce a revenue fact.
        content = _transcript("We spent ₹14,026 crore on capital expenditure this year.")
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.FINANCIAL_REVENUE) == []

    def test_usd_revenue(self):
        content = _transcript("In dollar terms, revenue was $7.621 billion this quarter.")
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_REVENUE)
        assert any(f.value == 7.621 and f.unit == FactUnit.USD_BILLION for f in facts)

    def test_annual_revenue_found_by_position_not_identity(self):
        # Regression: comparing re.finditer Match objects with `is` never
        # actually skips the quarterly match (finditer yields a fresh
        # object even for an already-found position) — the "annual" figure
        # silently duplicated the quarterly one instead of finding FY26's
        # real full-year number.
        content = _transcript(
            "In Q4, our revenue was ₹70,698 crore. "
            "Coming to the full year, our revenue was ₹267,021 crore for FY26."
        )
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_REVENUE)
        inr = [f for f in facts if f.unit == FactUnit.CRORE_INR]
        annual = [f for f in inr if f.provenance.section == "annual"]
        assert annual
        assert annual[0].value == 267021.0


# ---------------------------------------------------------------------------
# Margin
# ---------------------------------------------------------------------------

class TestMargin:
    def test_operating_margin_stood_at(self):
        content = _transcript("Our Q4 operating margin stood at 25.3%.")
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_OPERATING_MARGIN)
        assert facts[0].value == 25.3
        assert facts[0].unit == FactUnit.PERCENT

    def test_bare_margin_routes_to_operating(self):
        # Regression: v1.0 required the literal phrase "operating margin".
        # Tata Steel's CFO says just "a margin of 16%" (EBITDA margin, no
        # qualifying word) — must still populate FINANCIAL_OPERATING_MARGIN,
        # the closest existing-ontology fit.
        content = _transcript(
            "Revenue was ₹63,270 crore and EBITDA was ₹9,953 crore, translating to a margin of 16%."
        )
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_OPERATING_MARGIN)
        assert facts and facts[0].value == 16.0

    def test_net_margin_routes_correctly(self):
        content = _transcript("Net margins for Q4 were 19.4%.")
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_NET_MARGIN)
        assert facts[0].value == 19.4

    def test_margin_near_revenue_preferred_over_earlier_unrelated_mention(self):
        # Regression: a real Tata Steel filing states an unrelated
        # India-segment annual EBITDA margin ("margin was 24%") well before
        # the true quarterly headline figure that immediately follows
        # revenue ("...translating to a margin of 16%"). The nearer-to-
        # revenue mention must win.
        content = _transcript(
            "India EBITDA margin was 24% for the full year, similar to the 10-year average. "
            "Moving to the quarter, revenue was ₹63,270 crore and EBITDA was ₹9,953 crore, "
            "translating to a margin of 16%."
        )
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_OPERATING_MARGIN)
        assert facts[0].value == 16.0


# ---------------------------------------------------------------------------
# TCV
# ---------------------------------------------------------------------------

class TestTCV:
    def test_tcv_of_dollar_billion(self):
        content = _transcript("Our order book was strong, with $12 billion in TCV this quarter.")
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.FINANCIAL_TCV)
        assert facts[0].value == 12.0
        assert facts[0].unit == FactUnit.USD_BILLION

    def test_no_tcv_no_warning(self):
        # TCV is IT-services specific — absence for a non-IT company is not
        # an extraction failure worth a warning.
        content = _transcript("Revenue was ₹63,270 crore, EBITDA margin was 16%.")
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.FINANCIAL_TCV) == []
        assert not any("TCV" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Forward guidance (shared pattern with investor_presentation.py)
# ---------------------------------------------------------------------------

class TestGuidance:
    def test_capex_guidance(self):
        content = _transcript(
            "We intend to increase capex, targeting Rs 20,000 crores in FY2027."
        )
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_GUIDANCE)
        assert any("targeting" in f.value.lower() for f in facts)

    def test_ratio_guidance(self):
        content = _transcript(
            "Domestic NIM was 3.03%, supporting our guidance to maintain NIM above 3%."
        )
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.STRATEGY_GUIDANCE)
        assert facts and "NIM" in facts[0].value


# ---------------------------------------------------------------------------
# Workforce (reused ESG_WORKFORCE_* FactKinds)
# ---------------------------------------------------------------------------

class TestWorkforce:
    def test_headcount(self):
        content = _transcript(
            "At the end of March 2026, our global headcount stood at 584,519 associates."
        )
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.ESG_WORKFORCE_HEADCOUNT)
        assert facts[0].value == 584519.0
        assert facts[0].unit == FactUnit.COUNT

    def test_female_pct(self):
        content = _transcript(
            "Our headcount includes associates from 149 nationalities of whom 35.2% are women."
        )
        result = analyze("x", _kb(content))
        facts = _facts(result, FactKind.ESG_WORKFORCE_FEMALE_PCT)
        assert facts[0].value == 35.2
        assert facts[0].unit == FactUnit.PERCENT

    def test_no_workforce_mention_no_facts(self):
        content = _transcript("Revenue was ₹63,270 crore.")
        result = analyze("x", _kb(content))
        assert _facts(result, FactKind.ESG_WORKFORCE_HEADCOUNT) == []
        assert _facts(result, FactKind.ESG_WORKFORCE_FEMALE_PCT) == []


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_high_confidence_with_revenue_and_margin(self):
        content = _transcript("Revenue was ₹70,698 crore. Operating margin stood at 25.3%.")
        result = analyze("x", _kb(content))
        assert result.confidence == "high"

    def test_medium_confidence_partial(self):
        content = _transcript("Our order book was strong, with $12 billion in TCV this quarter.")
        result = analyze("x", _kb(content))
        assert result.confidence == "medium"

    def test_low_confidence_period_only(self):
        content = _transcript("Nothing quantitative mentioned in this section at all.")
        result = analyze("x", _kb(content))
        assert result.confidence == "low"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_all_facts_have_period_or_are_guidance(self):
        content = _transcript(
            "Revenue was ₹70,698 crore. Operating margin stood at 25.3%. "
            "TCV was $12 billion. Headcount stood at 584,519. "
            "35.2% are women. Targeting Rs 7,140 crores in FY2027."
        )
        result = analyze("x", _kb(content))
        for f in result.facts:
            if f.kind == FactKind.STRATEGY_GUIDANCE:
                continue  # guidance is not period-anchored, by design
            assert f.period == "2026-03-31", f"{f.kind} has period={f.period!r}"

    def test_all_facts_have_provenance_section(self):
        content = _transcript("Revenue was ₹70,698 crore. Operating margin stood at 25.3%.")
        result = analyze("x", _kb(content))
        for f in result.facts:
            assert f.provenance.section, f"fact {f.kind} missing provenance section"

    def test_source_date_preserved(self):
        result = analyze(
            "x", _kb(_transcript("Revenue was ₹70,698 crore."), source_date="2026-04-14T19:57:43+05:30")
        )
        assert result.source_date.year == 2026
        assert result.source_date.month == 4
