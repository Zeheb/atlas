"""Unit tests for atlas.analysis.earnings_transcript.

All tests use synthetic fixtures — no real repository access required.
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


# ---------------------------------------------------------------------------
# Synthetic transcript fixtures
# ---------------------------------------------------------------------------

# Q4 + Full Year call (is_annual=True)
_Q4_TRANSCRIPT = """\
TCS/SE/10/2026-27
April 14, 2026

Sub: Transcript of the earnings conference call for the quarter and year ended\
 March 31, 2026

Tata Consultancy Services Limited
Financial Results Q4 & Full Year FY 2026 Conference Call
April 09, 2026

Moderator: Ladies and gentlemen, good day and welcome to the TCS Earnings Conference Call.
From the management side we have Mr. K Krithivasan, Chief Executive Officer, and \
Mr. Samir Seksaria, Chief Financial Officer.

Nehal Shah: Thank you, operator. Good evening, everyone. Our leadership team is present.

K Krithivasan: Thank you, Nehal. Good day everyone.
Our order book performance was very strong in Q4, with $12 billion in TCV.
North America growing 1.4% QoQ in constant currency.

Samir Seksaria: Hello everyone.

Samir Seksaria: Thank you, Krithi. Good day to all.
In the fourth quarter of financial year 2026, our revenue was ₹70,698 crore,
which is a quarter-on-quarter growth of 5.4%. In dollar terms, revenue was $7.621 billion.
In constant currency, we had a sequential revenue growth of 1.2%.
Our Q4 operating margin stood at 25.3%, a sequential increase of 10 basis points.
Net margins for Q4 were 19.4%, and our EPS grew 12.2% YoY.
Coming to the full year FY26, our revenue was ₹267,021 crore.
For FY26, our operating margin was 25%.
Net margins for FY26 were 19.8%.
"""

# Q2 call (is_annual=False, half-year)
_Q2_TRANSCRIPT = """\
TCS/SE/125/2025-26
October 15, 2025

Sub: Transcript of the earnings conference call for the quarter and six-month period ended\
 September 30, 2025

Moderator: Ladies and gentlemen, good day.
On the call today: Mr. K Krithivasan, Chief Executive Officer, and \
Mr. Samir Seksaria, Chief Financial Officer.

Nehal Shah: Thank you, operator.

K Krithivasan: Hello everyone.

K Krithivasan: Moving on to Q2 performance.
We are pleased to report a TCV of $10 billion.

Samir Seksaria: Hello, everyone.

Samir Seksaria: Thank you, Krithi. Good day everyone.
In the second quarter of FY26, our revenue was ₹65,799 crore.
In reported currency, our revenue grew 3.7% QoQ.
In dollar terms, revenue was $7.150 billion.
Our Q2 operating margin stood at 25.2%.
Our net income margin was 19.6%.
"""

# Minimal — no TCV
_NO_TCV_TRANSCRIPT = """\
TCS/SE/1/2025-26
April 12, 2025

Sub: Transcript of the earnings conference call for the quarter and year ended\
 March 31, 2025

Moderator: Welcome. Speakers today: Mr. K Krithivasan, Chief Executive Officer, \
and Mr. Samir Seksaria, Chief Financial Officer.

Nehal Shah: Good evening.

K Krithivasan: Hello.

K Krithivasan: We concluded FY25 surpassing the $30 billion revenue milestone.

Samir Seksaria: Hello.

Samir Seksaria: Our revenue was ₹61,237 crore. Revenue was $7.170 billion.
Our Q4 operating margin stood at 24.3%.
Net margins for Q4 were 19%.
"""


# ---------------------------------------------------------------------------
# Q4 + Annual call
# ---------------------------------------------------------------------------

class TestQ4Transcript:
    @pytest.fixture(scope="class")
    def result(self):
        return analyze("t-001", _kb(_Q4_TRANSCRIPT))

    def test_returns_analysis_result(self, result):
        assert isinstance(result, AnalysisResult)

    def test_analyzer_version(self, result):
        assert result.analyzer_version == ANALYZER_VERSION

    def test_kind(self, result):
        assert result.kind == "earnings_transcript"

    def test_confidence_high(self, result):
        assert result.confidence == "high"

    def test_period_end(self, result):
        facts = _facts(result, FactKind.REPORT_PERIOD_END)
        assert len(facts) == 1
        assert facts[0].value == "2026-03-31"
        assert facts[0].unit == FactUnit.ISO_DATE

    def test_period_type_quarterly(self, result):
        pts = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        assert any(f.value == "quarterly" for f in pts)

    def test_period_type_annual_emitted_for_q4(self, result):
        pts = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        assert any(f.value == "annual" for f in pts)

    def test_quarterly_inr_revenue(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        inr_q = [f for f in revs if f.unit == FactUnit.CRORE_INR and f.provenance.section == "quarterly"]
        assert inr_q
        assert inr_q[0].value == 70698.0

    def test_quarterly_usd_revenue(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        usd = [f for f in revs if f.unit == FactUnit.USD_BILLION]
        assert usd
        assert usd[0].value == 7.621

    def test_annual_inr_revenue(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        inr_a = [f for f in revs if f.unit == FactUnit.CRORE_INR and f.provenance.section == "annual"]
        assert inr_a
        assert inr_a[0].value == 267021.0

    def test_tcv(self, result):
        tcv = _facts(result, FactKind.FINANCIAL_TCV)
        assert len(tcv) == 1
        assert tcv[0].value == 12.0
        assert tcv[0].unit == FactUnit.USD_BILLION

    def test_quarterly_op_margin(self, result):
        margins = _facts(result, FactKind.FINANCIAL_OPERATING_MARGIN)
        q = [f for f in margins if f.provenance.section == "quarterly"]
        assert q
        assert q[0].value == 25.3
        assert q[0].unit == FactUnit.PERCENT

    def test_annual_op_margin(self, result):
        margins = _facts(result, FactKind.FINANCIAL_OPERATING_MARGIN)
        a = [f for f in margins if f.provenance.section == "annual"]
        assert a
        assert a[0].value == 25.0

    def test_quarterly_net_margin(self, result):
        margins = _facts(result, FactKind.FINANCIAL_NET_MARGIN)
        q = [f for f in margins if f.provenance.section == "quarterly"]
        assert q
        assert q[0].value == 19.4

    def test_annual_net_margin(self, result):
        margins = _facts(result, FactKind.FINANCIAL_NET_MARGIN)
        a = [f for f in margins if f.provenance.section == "annual"]
        assert a
        assert a[0].value == 19.8

    def test_ceo_commentary_in_excerpts(self, result):
        assert "ceo_commentary" in result.excerpts
        assert len(result.excerpts["ceo_commentary"]) > 50

    def test_cfo_commentary_in_excerpts(self, result):
        assert "cfo_commentary" in result.excerpts
        assert "operating margin" in result.excerpts["cfo_commentary"].lower()

    def test_no_warnings(self, result):
        assert result.warnings == [], result.warnings

    def test_all_facts_have_period(self, result):
        for f in result.facts:
            assert f.period == "2026-03-31", f"{f.kind} has period={f.period!r}"


# ---------------------------------------------------------------------------
# Q2 (half-year) call
# ---------------------------------------------------------------------------

class TestQ2Transcript:
    @pytest.fixture(scope="class")
    def result(self):
        return analyze("t-002", _kb(_Q2_TRANSCRIPT, source_date="2025-10-15T10:54:05+05:30"))

    def test_confidence_high(self, result):
        assert result.confidence == "high"

    def test_period_end(self, result):
        facts = _facts(result, FactKind.REPORT_PERIOD_END)
        assert facts[0].value == "2025-09-30"

    def test_period_type_quarterly_only(self, result):
        pts = _facts(result, FactKind.REPORT_PERIOD_TYPE)
        # Mid-year call: only "quarterly", not "annual"
        assert any(f.value == "quarterly" for f in pts)
        assert not any(f.value == "annual" for f in pts)

    def test_inr_revenue(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        inr = [f for f in revs if f.unit == FactUnit.CRORE_INR]
        assert inr[0].value == 65799.0

    def test_usd_revenue(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        usd = [f for f in revs if f.unit == FactUnit.USD_BILLION]
        assert usd[0].value == 7.150

    def test_tcv_10_billion(self, result):
        tcv = _facts(result, FactKind.FINANCIAL_TCV)
        assert tcv[0].value == 10.0

    def test_op_margin_252(self, result):
        m = _facts(result, FactKind.FINANCIAL_OPERATING_MARGIN)
        assert any(f.value == 25.2 for f in m)

    def test_net_margin_196(self, result):
        m = _facts(result, FactKind.FINANCIAL_NET_MARGIN)
        assert any(f.value == 19.6 for f in m)

    def test_no_annual_revenue(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        # No annual revenue for Q2 calls
        assert not any(f.provenance.section == "annual" for f in revs)


# ---------------------------------------------------------------------------
# Transcript without TCV (e.g. non-IT company or TCS call with no TCV mention)
# ---------------------------------------------------------------------------

class TestNoTCV:
    @pytest.fixture(scope="class")
    def result(self):
        return analyze("t-003", _kb(_NO_TCV_TRANSCRIPT, source_date="2025-04-12T17:46:16+05:30"))

    def test_no_tcv_warning_emitted(self, result):
        # TCV absence no longer produces a warning — TCV is IT-sector specific.
        assert not any("TCV" in w for w in result.warnings)

    def test_still_extracts_revenue(self, result):
        revs = _facts(result, FactKind.FINANCIAL_REVENUE)
        assert revs

    def test_still_extracts_margin(self, result):
        m = _facts(result, FactKind.FINANCIAL_OPERATING_MARGIN)
        assert m


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_wrong_kind_raises(self):
        with pytest.raises(ValueError, match="not 'earnings_transcript'"):
            analyze("x", _kb("text", kind="board_outcome"))

    def test_missing_evidence_raises(self):
        kb = MagicMock()
        kb.get.return_value = None
        with pytest.raises(ValueError, match="not in knowledge base"):
            analyze("x", kb)

    def test_empty_content_raises(self):
        kb = MagicMock()
        entry = MagicMock()
        entry.kind = "earnings_transcript"
        entry.source_date = "2026-04-14T00:00:00+00:00"
        kb.get.return_value = entry
        kb.get_content.return_value = None
        with pytest.raises(ValueError, match="no content"):
            analyze("x", kb)


# ---------------------------------------------------------------------------
# Period parsing edge cases
# ---------------------------------------------------------------------------

class TestPeriodParsing:
    def _result_for(self, text: str, source_date: str = "2026-04-14T00:00:00+00:00"):
        return analyze("x", _kb(text, source_date=source_date))

    def test_march_31_parsed(self):
        r = self._result_for(_Q4_TRANSCRIPT)
        assert _facts(r, FactKind.REPORT_PERIOD_END)[0].value == "2026-03-31"

    def test_september_30_parsed(self):
        r = self._result_for(_Q2_TRANSCRIPT, source_date="2025-10-15T00:00:00+00:00")
        assert _facts(r, FactKind.REPORT_PERIOD_END)[0].value == "2025-09-30"

    def test_missing_period_gives_warning(self):
        minimal = "Hello world this is a transcript with no date."
        r = analyze("x", _kb(minimal))
        assert any("date" in w.lower() for w in r.warnings)
        assert r.confidence == "low"
