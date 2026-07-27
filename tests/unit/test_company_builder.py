"""Unit tests for atlas.company.builder and atlas.company.derived.

All fixtures are synthetic AnalysisResult objects — no real PDFs or KB access.
Tests verify that build_profile correctly routes facts to the right domain model
and that derived metrics compute accurate values.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.company.builder import build_profile
from atlas.company.derived import (
    capex_intensity_pct,
    ebit,
    ebit_margin_pct,
    ebitda,
    ebitda_margin_pct,
    employee_cost_pct,
    fcf_gaap,
    net_cash,
    net_debt,
    pat_margin_pct,
)
from atlas.company.model import FinancialSnapshot

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_DT = datetime(2024, 10, 10, tzinfo=timezone.utc)
_DT2 = datetime(2025, 1, 15, tzinfo=timezone.utc)


def _fact(
    kind: FactKind,
    value: object,
    unit: FactUnit | None = None,
    period: str | None = None,
    section: str = "consolidated_pl_table",
    char_offset: int | None = None,
    confidence: str = "high",
    excerpt: str | None = None,
) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence=confidence,
        provenance=Provenance(
            section=section, char_offset=char_offset, excerpt=excerpt
        ),
    )


def _result(
    kind: str,
    facts: list[AnalysisFact],
    evidence_id: str = "ev-001",
    source_date: datetime = _DT,
    confidence: str = "high",
) -> AnalysisResult:
    return AnalysisResult(
        evidence_id=evidence_id,
        kind=kind,
        analyzer_version="1.0",
        confidence=confidence,
        source_date=source_date,
        facts=facts,
    )


def _financial_result(
    period: str = "2024-09-30",
    period_type: str = "quarterly",
    revenue: float = 60000.0,
    pat: float = 12000.0,
    basis: str = "consolidated",
    evidence_id: str = "fr-001",
    source_date: datetime = _DT,
) -> AnalysisResult:
    section = f"{basis}_pl_table"
    facts = [
        _fact(
            FactKind.REPORT_PERIOD_END,
            period,
            FactUnit.ISO_DATE,
            section="cover_letter",
        ),
        _fact(FactKind.REPORT_PERIOD_TYPE, period_type, section="cover_letter"),
        _fact(
            FactKind.FINANCIAL_REVENUE,
            revenue,
            FactUnit.CRORE_INR,
            period=period,
            section=section,
        ),
        _fact(
            FactKind.FINANCIAL_PAT,
            pat,
            FactUnit.CRORE_INR,
            period=period,
            section=section,
        ),
    ]
    return _result(
        "financial_results", facts, evidence_id=evidence_id, source_date=source_date
    )


def _esg_result(
    period: str = "2024-03-31",
    scope1: float = 5000.0,
    workforce: int = 600000,
    evidence_id: str = "brsr-001",
) -> AnalysisResult:
    facts = [
        _fact(
            FactKind.ESG_GHG_SCOPE1,
            scope1,
            FactUnit.TCO2E,
            period=period,
            section="emissions",
        ),
        _fact(
            FactKind.ESG_WORKFORCE_HEADCOUNT,
            workforce,
            FactUnit.COUNT,
            period=period,
            section="workforce",
        ),
    ]
    return _result("brsr", facts, evidence_id=evidence_id)


def _shp_result(
    period: str = "2024-09-30",
    promoter_pct: float = 71.8,
    public_pct: float = 28.2,
    evidence_id: str = "shp-001",
) -> AnalysisResult:
    facts = [
        _fact(
            FactKind.OWNERSHIP_PROMOTER_PCT,
            promoter_pct,
            FactUnit.PERCENT,
            period=period,
            section="promoter",
        ),
        _fact(
            FactKind.OWNERSHIP_PUBLIC_PCT,
            public_pct,
            FactUnit.PERCENT,
            period=period,
            section="public",
        ),
    ]
    return _result("shareholding_pattern", facts, evidence_id=evidence_id)


def _investor_presentation_result(
    evidence_id: str = "ip-001",
    source_date: datetime = _DT,
) -> AnalysisResult:
    facts = [
        _fact(
            FactKind.STRATEGY_PRIORITY,
            "Cloud and AI platform leadership",
            section="strategy",
        ),
        _fact(
            FactKind.STRATEGY_ASPIRATION,
            "50 billion dollar company",
            section="strategy",
        ),
        _fact(
            FactKind.STRATEGY_CSAT,
            78.5,
            FactUnit.PERCENT,
            period="2024-09-30",
            section="customer",
        ),
        _fact(
            FactKind.FINANCIAL_ROE,
            52.0,
            FactUnit.PERCENT,
            period="2025-03-31",
            section="financial_highlights",
        ),
    ]
    return _result(
        "investor_presentation", facts, evidence_id=evidence_id, source_date=source_date
    )


def _agm_result(
    evidence_id: str = "agm-001",
    source_date: datetime = _DT,
) -> AnalysisResult:
    facts = [
        _fact(
            FactKind.GOVERNANCE_RESOLUTION_TITLE,
            "Re-appointment of auditor Deloitte",
            period="2024-08-14",
            section="resolution_1",
        ),
        _fact(
            FactKind.GOVERNANCE_RESOLUTION_TYPE,
            "ordinary",
            period="2024-08-14",
            section="resolution_1",
        ),
        _fact(
            FactKind.GOVERNANCE_RESOLUTION_OUTCOME,
            "passed",
            period="2024-08-14",
            section="resolution_1",
        ),
        _fact(
            FactKind.GOVERNANCE_VOTE_PCT_FOR,
            99.12,
            FactUnit.PERCENT,
            period="2024-08-14",
            section="resolution_1",
        ),
        _fact(
            FactKind.GOVERNANCE_VOTE_PCT_AGAINST,
            0.88,
            FactUnit.PERCENT,
            period="2024-08-14",
            section="resolution_1",
        ),
        _fact(
            FactKind.GOVERNANCE_RESOLUTION_TITLE,
            "Approve remuneration of MD & CEO",
            period="2024-08-14",
            section="resolution_2",
        ),
        _fact(
            FactKind.GOVERNANCE_RESOLUTION_TYPE,
            "special",
            period="2024-08-14",
            section="resolution_2",
        ),
        _fact(
            FactKind.GOVERNANCE_RESOLUTION_OUTCOME,
            "passed",
            period="2024-08-14",
            section="resolution_2",
        ),
        _fact(
            FactKind.GOVERNANCE_VOTE_PCT_FOR,
            85.3,
            FactUnit.PERCENT,
            period="2024-08-14",
            section="resolution_2",
        ),
        _fact(
            FactKind.GOVERNANCE_VOTE_PCT_AGAINST,
            14.7,
            FactUnit.PERCENT,
            period="2024-08-14",
            section="resolution_2",
        ),
    ]
    return _result(
        "agm_notice", facts, evidence_id=evidence_id, source_date=source_date
    )


# ---------------------------------------------------------------------------
# build_profile — basic routing
# ---------------------------------------------------------------------------


def test_build_profile_empty():
    profile = build_profile("TCS", [])
    assert profile.company_id == "TCS"
    assert profile.financial.snapshots == []
    assert profile.esg.snapshots == []
    assert profile.ownership.snapshots == []
    assert profile.capital_events.dividends == []
    assert profile.capital_events.buybacks == []
    assert profile.capital_events.acquisitions == []
    assert profile.credit_history.debt_ratings == []
    assert profile.credit_history.esg_ratings == []
    assert profile.segments.entries == []
    assert profile.strategy.entries == []
    assert profile.strategy.csat == []
    assert profile.governance.resolutions == []


def test_build_profile_financial_quarterly():
    profile = build_profile("TCS", [_financial_result()])
    assert len(profile.financial.snapshots) == 1
    snap = profile.financial.snapshots[0]
    assert snap.period == "2024-09-30"
    assert snap.period_type == "quarterly"
    assert snap.basis == "consolidated"
    assert snap.facts[FactKind.FINANCIAL_REVENUE] == 60000.0
    assert snap.facts[FactKind.FINANCIAL_PAT] == 12000.0
    assert snap.sources == ["fr-001"]


def test_build_profile_financial_standalone_and_consolidated():
    cons = _financial_result(basis="consolidated", evidence_id="fr-cons")
    sa = _financial_result(basis="standalone", revenue=55000.0, evidence_id="fr-sa")
    profile = build_profile("TCS", [cons, sa])
    assert len(profile.financial.snapshots) == 2
    bases = {s.basis for s in profile.financial.snapshots}
    assert bases == {"consolidated", "standalone"}


def test_build_profile_financial_multiple_periods_sorted():
    q1 = _financial_result(period="2024-06-30", evidence_id="fr-q1", source_date=_DT)
    q2 = _financial_result(period="2024-09-30", evidence_id="fr-q2", source_date=_DT2)
    profile = build_profile("TCS", [q2, q1])  # reversed input order
    periods = [s.period for s in profile.financial.snapshots]
    assert periods == sorted(periods), "Snapshots should be sorted ASC"


def test_build_profile_financial_merge_same_period():
    r1 = _financial_result(revenue=59000.0, evidence_id="fr-r1", source_date=_DT)
    r2 = _financial_result(revenue=60000.0, evidence_id="fr-r2", source_date=_DT2)
    profile = build_profile("TCS", [r1, r2])
    assert len(profile.financial.snapshots) == 1
    snap = profile.financial.snapshots[0]
    assert snap.facts[FactKind.FINANCIAL_REVENUE] == 60000.0  # later wins
    assert "fr-r1" in snap.sources
    assert "fr-r2" in snap.sources


def test_build_profile_annual_result():
    section = "consolidated_pl_table"
    annual_facts = [
        _fact(FactKind.REPORT_PERIOD_TYPE, "annual", section="cover_letter"),
        _fact(
            FactKind.FINANCIAL_REVENUE,
            240000.0,
            FactUnit.CRORE_INR,
            period="2025-03-31",
            section=section,
        ),
        _fact(
            FactKind.FINANCIAL_PAT,
            47000.0,
            FactUnit.CRORE_INR,
            period="2025-03-31",
            section=section,
        ),
        _fact(
            FactKind.FINANCIAL_CASH_AND_EQUIVALENTS,
            8000.0,
            FactUnit.CRORE_INR,
            period="2025-03-31",
            section="consolidated_bs_table",
        ),
        _fact(
            FactKind.FINANCIAL_TOTAL_DEBT,
            0.0,
            FactUnit.CRORE_INR,
            period="2025-03-31",
            section="consolidated_bs_table",
        ),
        _fact(
            FactKind.FINANCIAL_OPERATING_CASH_FLOW,
            50000.0,
            FactUnit.CRORE_INR,
            period="2025-03-31",
            section="consolidated_cf_table",
        ),
        _fact(
            FactKind.FINANCIAL_CAPEX,
            2000.0,
            FactUnit.CRORE_INR,
            period="2025-03-31",
            section="consolidated_cf_table",
        ),
    ]
    r = _result("financial_results", annual_facts, evidence_id="fr-ann")
    profile = build_profile("TCS", [r])
    assert len(profile.financial.snapshots) == 1
    snap = profile.financial.snapshots[0]
    assert snap.period_type == "annual"
    assert snap.facts[FactKind.FINANCIAL_CASH_AND_EQUIVALENTS] == 8000.0
    assert snap.facts[FactKind.FINANCIAL_CAPEX] == 2000.0


# ---------------------------------------------------------------------------
# ESG ingestion
# ---------------------------------------------------------------------------


def test_build_profile_esg():
    profile = build_profile("TCS", [_esg_result()])
    assert len(profile.esg.snapshots) == 1
    snap = profile.esg.snapshots[0]
    assert snap.period == "2024-03-31"
    assert snap.facts[FactKind.ESG_GHG_SCOPE1] == 5000.0
    assert snap.facts[FactKind.ESG_WORKFORCE_HEADCOUNT] == 600000.0


def test_build_profile_esg_multiple_years_sorted():
    fy25 = _esg_result(period="2025-03-31", evidence_id="brsr-25")
    fy24 = _esg_result(period="2024-03-31", evidence_id="brsr-24")
    profile = build_profile("TCS", [fy25, fy24])
    periods = [s.period for s in profile.esg.snapshots]
    assert periods == sorted(periods)


# ---------------------------------------------------------------------------
# Ownership ingestion
# ---------------------------------------------------------------------------


def test_build_profile_ownership():
    profile = build_profile("TCS", [_shp_result()])
    assert len(profile.ownership.snapshots) == 1
    snap = profile.ownership.snapshots[0]
    assert snap.period == "2024-09-30"
    assert snap.facts[FactKind.OWNERSHIP_PROMOTER_PCT] == pytest.approx(71.8)
    assert snap.sources == ["shp-001"]


def test_build_profile_ownership_multiple_periods():
    q1 = _shp_result(period="2024-06-30", evidence_id="shp-q1")
    q2 = _shp_result(period="2024-09-30", evidence_id="shp-q2")
    profile = build_profile("TCS", [q2, q1])
    periods = [s.period for s in profile.ownership.snapshots]
    assert periods == sorted(periods)


def test_build_profile_ownership_sources_tracks_evidence_id():
    profile = build_profile("TCS", [_shp_result(evidence_id="shp-xyz")])
    snap = profile.ownership.snapshots[0]
    assert "shp-xyz" in snap.sources


# ---------------------------------------------------------------------------
# Capital events — dividends
# ---------------------------------------------------------------------------


def test_build_profile_dividend_from_financial_result():
    section = "consolidated_pl_table"
    offset = 100
    facts = [
        _fact(FactKind.REPORT_PERIOD_TYPE, "quarterly", section="cover_letter"),
        _fact(
            FactKind.FINANCIAL_REVENUE,
            60000.0,
            FactUnit.CRORE_INR,
            period="2024-09-30",
            section=section,
        ),
        _fact(
            FactKind.CAPITAL_DIVIDEND_PER_SHARE,
            10.0,
            FactUnit.RUPEES_PER_SHARE,
            section="cover_letter",
            char_offset=offset,
        ),
        _fact(
            FactKind.CAPITAL_DIVIDEND_TYPE,
            "interim",
            section="cover_letter",
            char_offset=offset,
        ),
        _fact(
            FactKind.CAPITAL_DIVIDEND_RECORD_DATE,
            "2024-10-18",
            FactUnit.ISO_DATE,
            section="cover_letter",
        ),
        _fact(
            FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE,
            "2024-11-05",
            FactUnit.ISO_DATE,
            section="cover_letter",
        ),
    ]
    profile = build_profile("TCS", [_result("financial_results", facts)])
    assert len(profile.capital_events.dividends) == 1
    div = profile.capital_events.dividends[0]
    assert div.per_share == 10.0
    assert div.dividend_type == "interim"
    assert div.record_date == "2024-10-18"
    assert div.payment_date == "2024-11-05"


def test_build_profile_multiple_dividends_same_result():
    facts = [
        _fact(
            FactKind.FINANCIAL_REVENUE,
            60000.0,
            FactUnit.CRORE_INR,
            period="2025-03-31",
            section="consolidated_pl_table",
        ),
        _fact(
            FactKind.CAPITAL_DIVIDEND_PER_SHARE,
            28.0,
            FactUnit.RUPEES_PER_SHARE,
            section="cover_letter",
            char_offset=50,
        ),
        _fact(
            FactKind.CAPITAL_DIVIDEND_TYPE,
            "final",
            section="cover_letter",
            char_offset=50,
        ),
        _fact(
            FactKind.CAPITAL_DIVIDEND_PER_SHARE,
            4.5,
            FactUnit.RUPEES_PER_SHARE,
            section="cover_letter",
            char_offset=200,
        ),
        _fact(
            FactKind.CAPITAL_DIVIDEND_TYPE,
            "special",
            section="cover_letter",
            char_offset=200,
        ),
    ]
    profile = build_profile("TCS", [_result("financial_results", facts)])
    assert len(profile.capital_events.dividends) == 2
    types = {d.dividend_type for d in profile.capital_events.dividends}
    assert types == {"final", "special"}


# ---------------------------------------------------------------------------
# Capital events — buybacks
# ---------------------------------------------------------------------------


def test_build_profile_buyback_announcement():
    facts = [
        _fact(
            FactKind.CAPITAL_BUYBACK_AMOUNT,
            17000.0,
            FactUnit.CRORE_INR,
            section="cover_letter",
        ),
        _fact(
            FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE,
            4500.0,
            FactUnit.RUPEES_PER_SHARE,
            section="cover_letter",
        ),
        _fact(
            FactKind.CAPITAL_BUYBACK_SHARES_OFFERED,
            37777778,
            FactUnit.COUNT,
            section="cover_letter",
        ),
    ]
    profile = build_profile("TCS", [_result("buyback", facts)])
    assert len(profile.capital_events.buybacks) == 1
    bb = profile.capital_events.buybacks[0]
    assert bb.sub_type == "announcement"
    assert bb.amount == 17000.0
    assert bb.shares_offered == 37777778


def test_build_profile_buyback_extinguishment():
    facts = [
        _fact(
            FactKind.CAPITAL_BUYBACK_SHARES_BOUGHT,
            1000000,
            FactUnit.COUNT,
            section="cover_letter",
        ),
    ]
    profile = build_profile("TCS", [_result("buyback", facts)])
    assert profile.capital_events.buybacks[0].sub_type == "extinguishment"
    assert profile.capital_events.buybacks[0].shares_bought == 1000000


def test_build_profile_buyback_schedule():
    facts = [
        _fact(
            FactKind.CAPITAL_BUYBACK_RECORD_DATE,
            "2024-11-01",
            FactUnit.ISO_DATE,
            section="cover_letter",
        ),
    ]
    profile = build_profile("TCS", [_result("buyback", facts)])
    assert profile.capital_events.buybacks[0].sub_type == "schedule"
    assert profile.capital_events.buybacks[0].record_date == "2024-11-01"


# ---------------------------------------------------------------------------
# Capital events — acquisitions
# ---------------------------------------------------------------------------


def test_build_profile_acquisition():
    facts = [
        _fact(FactKind.CAPITAL_ACQ_TARGET_NAME, "Acme Corp", section="annexure_a"),
        _fact(FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE, "cash", section="annexure_a"),
        _fact(
            FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE,
            700.0,
            FactUnit.USD_MILLION,
            section="annexure_a",
        ),
        _fact(
            FactKind.CAPITAL_ACQ_STAKE_PCT,
            100.0,
            FactUnit.PERCENT,
            section="annexure_a",
        ),
        _fact(
            FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION, "2025-03-31", section="annexure_a"
        ),
    ]
    profile = build_profile("TCS", [_result("acquisition", facts)])
    assert len(profile.capital_events.acquisitions) == 1
    ev = profile.capital_events.acquisitions[0]
    assert ev.target_name == "Acme Corp"
    assert ev.enterprise_value == 700.0
    assert ev.enterprise_value_unit == FactUnit.USD_MILLION
    assert ev.stake_pct == 100.0


def test_build_profile_acquisition_multiple_targets():
    # Type B: multiple subsidiary incorporations in one filing
    facts = [
        _fact(FactKind.CAPITAL_ACQ_TARGET_NAME, "Sub A Ltd", section="annexure_a"),
        _fact(FactKind.CAPITAL_ACQ_TARGET_NAME, "Sub B Ltd", section="annexure_a"),
        _fact(
            FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE,
            "subscription",
            section="annexure_a",
        ),
    ]
    profile = build_profile("TCS", [_result("acquisition", facts)])
    assert len(profile.capital_events.acquisitions) == 2
    names = {ev.target_name for ev in profile.capital_events.acquisitions}
    assert names == {"Sub A Ltd", "Sub B Ltd"}


def test_build_profile_board_outcome_investment():
    facts = [
        _fact(
            FactKind.CAPITAL_INVEST_TARGET_NAME,
            "HyperVault Private Limited",
            section="annexure_b",
        ),
        _fact(
            FactKind.CAPITAL_INVEST_AMOUNT,
            500.0,
            FactUnit.CRORE_INR,
            section="annexure_b",
        ),
    ]
    profile = build_profile("TCS", [_result("board_outcome", facts)])
    assert len(profile.capital_events.investments) == 1
    iv = profile.capital_events.investments[0]
    assert iv.target_name == "HyperVault Private Limited"
    assert iv.amount == 500.0
    assert iv.amount_unit == FactUnit.CRORE_INR


# ---------------------------------------------------------------------------
# Credit history — separated debt and ESG
# ---------------------------------------------------------------------------


def test_build_profile_credit_esg_goes_to_esg_ratings():
    facts = [
        _fact(FactKind.CREDIT_AGENCY, "NSE Sustainability", section="document"),
        _fact(FactKind.CREDIT_INSTRUMENT, "ESG", section="document"),
        _fact(FactKind.CREDIT_RATING, "74", section="esg"),
        _fact(FactKind.CREDIT_OUTLOOK, "Leader", section="esg"),
        _fact(FactKind.CREDIT_ACTION, "reaffirmed", section="document"),
    ]
    profile = build_profile("TCS", [_result("credit_rating_report", facts)])
    assert profile.credit_history.debt_ratings == []
    assert len(profile.credit_history.esg_ratings) == 1
    entry = profile.credit_history.esg_ratings[0]
    assert entry.agency == "NSE Sustainability"
    assert entry.instrument == "ESG"
    assert entry.rating == "74"
    assert entry.outlook == "Leader"
    assert entry.action == "reaffirmed"
    assert entry.amount is None


def test_build_profile_credit_debt_goes_to_debt_ratings():
    facts = [
        _fact(FactKind.CREDIT_AGENCY, "CRISIL", section="document"),
        _fact(
            FactKind.CREDIT_INSTRUMENT,
            "Long-term Bank Facilities",
            section="Long-term Bank Facilities",
        ),
        _fact(FactKind.CREDIT_RATING, "AAA", section="Long-term Bank Facilities"),
        _fact(FactKind.CREDIT_OUTLOOK, "stable", section="Long-term Bank Facilities"),
        _fact(
            FactKind.CREDIT_AMOUNT,
            5000.0,
            FactUnit.CRORE_INR,
            section="Long-term Bank Facilities",
        ),
    ]
    profile = build_profile("TCS", [_result("credit_rating_report", facts)])
    assert profile.credit_history.esg_ratings == []
    assert len(profile.credit_history.debt_ratings) == 1
    entry = profile.credit_history.debt_ratings[0]
    assert entry.instrument == "Long-term Bank Facilities"
    assert entry.rating == "AAA"
    assert entry.amount == 5000.0


def test_build_profile_credit_debt_multiple_instruments():
    facts = [
        _fact(FactKind.CREDIT_AGENCY, "CRISIL", section="document"),
        _fact(
            FactKind.CREDIT_INSTRUMENT,
            "Long-term Bank Facilities",
            section="Long-term Bank Facilities",
        ),
        _fact(FactKind.CREDIT_RATING, "AAA", section="Long-term Bank Facilities"),
        _fact(FactKind.CREDIT_OUTLOOK, "stable", section="Long-term Bank Facilities"),
        _fact(
            FactKind.CREDIT_AMOUNT,
            5000.0,
            FactUnit.CRORE_INR,
            section="Long-term Bank Facilities",
        ),
        _fact(
            FactKind.CREDIT_INSTRUMENT, "Commercial Paper", section="Commercial Paper"
        ),
        _fact(FactKind.CREDIT_RATING, "A1+", section="Commercial Paper"),
    ]
    profile = build_profile("TCS", [_result("credit_rating_report", facts)])
    assert len(profile.credit_history.debt_ratings) == 2
    instruments = {e.instrument for e in profile.credit_history.debt_ratings}
    assert instruments == {"Long-term Bank Facilities", "Commercial Paper"}
    lt = next(
        e
        for e in profile.credit_history.debt_ratings
        if e.instrument == "Long-term Bank Facilities"
    )
    assert lt.rating == "AAA"
    assert lt.amount == 5000.0


def test_build_profile_credit_no_instrument_fact_skipped():
    facts = [
        _fact(FactKind.CREDIT_AGENCY, "CRISIL", section="document"),
        _fact(FactKind.CREDIT_RATING, "AAA", section="some_section"),
    ]
    profile = build_profile("TCS", [_result("credit_rating_report", facts)])
    assert profile.credit_history.debt_ratings == []
    assert profile.credit_history.esg_ratings == []


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


def test_build_profile_segments():
    period = "2024-09-30"
    # Pair SEGMENT_NAME + SEGMENT_REVENUE by char_offset
    facts = [
        _fact(
            FactKind.SEGMENT_NAME,
            "Banking, Financial Services and Insurance",
            period=period,
            section="segment_table",
            char_offset=1000,
        ),
        _fact(
            FactKind.SEGMENT_REVENUE,
            14000.0,
            FactUnit.CRORE_INR,
            period=period,
            section="segment_table",
            char_offset=1000,
        ),
        _fact(
            FactKind.SEGMENT_NAME,
            "Manufacturing",
            period=period,
            section="segment_table",
            char_offset=1200,
        ),
        _fact(
            FactKind.SEGMENT_REVENUE,
            6000.0,
            FactUnit.CRORE_INR,
            period=period,
            section="segment_table",
            char_offset=1200,
        ),
        # SEGMENT_EBIT: excerpt starts with segment name
        AnalysisFact(
            kind=FactKind.SEGMENT_EBIT,
            value=2500.0,
            unit=FactUnit.CRORE_INR,
            period=period,
            confidence="high",
            provenance=Provenance(
                section="segment_table",
                char_offset=2000,
                excerpt="Banking, Financial Services and Insurance\n12345",
            ),
        ),
    ]
    profile = build_profile("TCS", [_result("financial_results", facts)])
    assert len(profile.segments.entries) >= 2
    bfsi = next((e for e in profile.segments.entries if "Banking" in e.name), None)
    assert bfsi is not None
    assert bfsi.revenue == 14000.0
    assert bfsi.ebit == 2500.0
    mfg = next((e for e in profile.segments.entries if e.name == "Manufacturing"), None)
    assert mfg is not None
    assert mfg.revenue == 6000.0
    assert mfg.ebit is None


# ---------------------------------------------------------------------------
# Earnings transcript supplement
# ---------------------------------------------------------------------------


def test_transcript_supplements_financial_result():
    # financial_results has revenue; transcript adds TCV and margin
    fr = _financial_result(period="2024-09-30", revenue=60000.0)
    transcript_facts = [
        _fact(FactKind.REPORT_PERIOD_TYPE, "quarterly", section="cover_letter"),
        _fact(
            FactKind.FINANCIAL_REVENUE,
            59000.0,
            FactUnit.CRORE_INR,
            period="2024-09-30",
            section="cfo_section",
        ),
        _fact(
            FactKind.FINANCIAL_TCV,
            9.8,
            FactUnit.USD_BILLION,
            period="2024-09-30",
            section="cfo_section",
        ),
        _fact(
            FactKind.FINANCIAL_OPERATING_MARGIN,
            24.5,
            FactUnit.PERCENT,
            period="2024-09-30",
            section="cfo_section",
        ),
    ]
    tr = _result(
        "earnings_transcript", transcript_facts, evidence_id="tr-001", source_date=_DT2
    )
    profile = build_profile("TCS", [fr, tr])
    assert len(profile.financial.snapshots) == 1
    snap = profile.financial.snapshots[0]
    # XBRL revenue should NOT be overwritten by transcript
    assert snap.facts[FactKind.FINANCIAL_REVENUE] == 60000.0
    # Transcript-only facts should be added
    assert snap.facts[FactKind.FINANCIAL_TCV] == pytest.approx(9.8)
    assert snap.facts[FactKind.FINANCIAL_OPERATING_MARGIN] == pytest.approx(24.5)


def test_transcript_creates_new_snapshot_when_no_financial_result():
    transcript_facts = [
        _fact(FactKind.REPORT_PERIOD_TYPE, "quarterly", section="cover_letter"),
        _fact(
            FactKind.FINANCIAL_REVENUE,
            60000.0,
            FactUnit.CRORE_INR,
            period="2024-09-30",
            section="cfo_section",
        ),
        _fact(
            FactKind.FINANCIAL_TCV,
            9.8,
            FactUnit.USD_BILLION,
            period="2024-09-30",
            section="cfo_section",
        ),
    ]
    tr = _result("earnings_transcript", transcript_facts, evidence_id="tr-001")
    profile = build_profile("TCS", [tr])
    assert len(profile.financial.snapshots) == 1
    snap = profile.financial.snapshots[0]
    assert snap.basis == "consolidated"
    assert snap.facts[FactKind.FINANCIAL_REVENUE] == 60000.0


# ---------------------------------------------------------------------------
# Unknown kinds still silently skipped (annual_report)
# ---------------------------------------------------------------------------


def test_annual_report_kind_ignored():
    facts = [
        _fact(
            FactKind.SEGMENT_NAME, "BFSI", section="segment_table", period="2024-03-31"
        )
    ]
    r = _result("annual_report", facts)
    profile = build_profile("TCS", [r])
    assert profile.financial.snapshots == []
    assert profile.segments.entries == []


# ---------------------------------------------------------------------------
# Strategy — investor_presentation
# ---------------------------------------------------------------------------


def test_investor_presentation_strategy_entries():
    profile = build_profile("TCS", [_investor_presentation_result()])
    assert len(profile.strategy.entries) == 2
    kinds = {e.kind for e in profile.strategy.entries}
    assert kinds == {"priority", "aspiration"}


def test_investor_presentation_strategy_text_preserved():
    profile = build_profile("TCS", [_investor_presentation_result()])
    priority = next(e for e in profile.strategy.entries if e.kind == "priority")
    assert "Cloud" in priority.text
    assert priority.evidence_id == "ip-001"


def test_investor_presentation_csat_entry():
    profile = build_profile("TCS", [_investor_presentation_result()])
    assert len(profile.strategy.csat) == 1
    csat = profile.strategy.csat[0]
    assert csat.period == "2024-09-30"
    assert csat.score == pytest.approx(78.5)


def test_investor_presentation_financial_roe_supplements_snapshot():
    # ROE from IP should land in FinancialTimeSeries
    profile = build_profile("TCS", [_investor_presentation_result()])
    assert len(profile.financial.snapshots) == 1
    snap = profile.financial.snapshots[0]
    assert snap.period == "2025-03-31"
    assert snap.facts[FactKind.FINANCIAL_ROE] == pytest.approx(52.0)
    assert snap.period_type == "annual"


def test_investor_presentation_does_not_overwrite_financial_result_roe():
    # financial_result creates a snapshot; IP should not overwrite it
    fr_facts = [
        _fact(FactKind.REPORT_PERIOD_TYPE, "annual", section="cover_letter"),
        _fact(
            FactKind.FINANCIAL_REVENUE,
            240000.0,
            FactUnit.CRORE_INR,
            period="2025-03-31",
            section="consolidated_pl_table",
        ),
        _fact(
            FactKind.FINANCIAL_ROE,
            55.0,
            FactUnit.PERCENT,
            period="2025-03-31",
            section="consolidated_pl_table",
        ),
    ]
    fr = _result("financial_results", fr_facts, evidence_id="fr-ann")
    ip = _investor_presentation_result()  # has ROE=52.0 for same period
    profile = build_profile("TCS", [fr, ip])
    snap = next(s for s in profile.financial.snapshots if s.period == "2025-03-31")
    assert snap.facts[FactKind.FINANCIAL_ROE] == pytest.approx(55.0)  # fr wins


def test_investor_presentation_strategy_entries_sorted_by_date():
    ip1 = _investor_presentation_result(evidence_id="ip-old", source_date=_DT)
    ip2_facts = [
        _fact(FactKind.STRATEGY_GUIDANCE, "30% operating margin", section="guidance")
    ]
    ip2 = _result(
        "investor_presentation", ip2_facts, evidence_id="ip-new", source_date=_DT2
    )
    profile = build_profile("TCS", [ip2, ip1])
    dates = [e.source_date for e in profile.strategy.entries]
    assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# Governance — agm_notice
# ---------------------------------------------------------------------------


def test_agm_notice_resolutions_ingested():
    profile = build_profile("TCS", [_agm_result()])
    assert len(profile.governance.resolutions) == 2


def test_agm_notice_resolution_fields():
    profile = build_profile("TCS", [_agm_result()])
    # Resolutions sorted by (period, title)
    res = next(
        r for r in profile.governance.resolutions if "auditor" in r.title.lower()
    )
    assert res.period == "2024-08-14"
    assert res.resolution_type == "ordinary"
    assert res.outcome == "passed"
    assert res.pct_for == pytest.approx(99.12)
    assert res.pct_against == pytest.approx(0.88)
    assert res.evidence_id == "agm-001"


def test_agm_notice_special_resolution():
    profile = build_profile("TCS", [_agm_result()])
    special = next(
        r for r in profile.governance.resolutions if r.resolution_type == "special"
    )
    assert special.pct_for == pytest.approx(85.3)


def test_agm_notice_resolutions_sorted_by_period_then_title():
    profile = build_profile("TCS", [_agm_result()])
    keys = [(r.period or "", r.title) for r in profile.governance.resolutions]
    assert keys == sorted(keys)


def test_agm_notice_pre_meeting_notice_yields_no_resolutions():
    # Pre-meeting notice has no GOVERNANCE_RESOLUTION_TITLE facts
    facts = [_fact(FactKind.STRATEGY_PRIORITY, "Some text", section="cover")]
    r = _result("agm_notice", facts)
    profile = build_profile("TCS", [r])
    assert profile.governance.resolutions == []


def test_agm_notice_evidence_id_tracked():
    profile = build_profile("TCS", [_agm_result(evidence_id="agm-xyz")])
    assert all(r.evidence_id == "agm-xyz" for r in profile.governance.resolutions)


# ---------------------------------------------------------------------------
# Multiple kinds combined
# ---------------------------------------------------------------------------


def test_build_profile_multi_domain():
    results = [
        _financial_result(period="2024-09-30"),
        _esg_result(period="2024-03-31"),
        _shp_result(period="2024-09-30"),
        _investor_presentation_result(),
        _agm_result(),
    ]
    profile = build_profile("TCS", results)
    assert len(profile.financial.snapshots) >= 1
    assert len(profile.esg.snapshots) == 1
    assert len(profile.ownership.snapshots) == 1
    assert len(profile.strategy.entries) >= 1
    assert len(profile.governance.resolutions) == 2


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------


def _snap(**kwargs: float) -> FinancialSnapshot:
    return FinancialSnapshot(
        period="2025-03-31",
        period_type="annual",
        basis="consolidated",
        facts={FactKind[k]: v for k, v in kwargs.items()},
    )


def test_net_debt_positive():
    s = _snap(FINANCIAL_TOTAL_DEBT=5000.0, FINANCIAL_CASH_AND_EQUIVALENTS=2000.0)
    assert net_debt(s) == pytest.approx(3000.0)


def test_net_debt_negative_is_net_cash():
    s = _snap(FINANCIAL_TOTAL_DEBT=0.0, FINANCIAL_CASH_AND_EQUIVALENTS=8000.0)
    assert net_debt(s) == pytest.approx(-8000.0)
    assert net_cash(s) == pytest.approx(8000.0)


def test_net_debt_missing_returns_none():
    s = _snap(FINANCIAL_TOTAL_DEBT=5000.0)  # cash absent
    assert net_debt(s) is None
    assert net_cash(s) is None


def test_ebit():
    s = _snap(
        FINANCIAL_PROFIT_BEFORE_EXCEPTIONAL=50000.0,
        FINANCIAL_FINANCE_COST=200.0,
    )
    assert ebit(s) == pytest.approx(50200.0)


def test_ebitda():
    s = _snap(
        FINANCIAL_PROFIT_BEFORE_EXCEPTIONAL=50000.0,
        FINANCIAL_FINANCE_COST=200.0,
        FINANCIAL_DEPRECIATION=3000.0,
    )
    assert ebitda(s) == pytest.approx(53200.0)


def test_ebit_margin():
    s = _snap(
        FINANCIAL_REVENUE=200000.0,
        FINANCIAL_PROFIT_BEFORE_EXCEPTIONAL=49800.0,
        FINANCIAL_FINANCE_COST=200.0,
    )
    assert ebit_margin_pct(s) == pytest.approx(25.0)


def test_ebitda_margin():
    s = _snap(
        FINANCIAL_REVENUE=200000.0,
        FINANCIAL_PROFIT_BEFORE_EXCEPTIONAL=46800.0,
        FINANCIAL_FINANCE_COST=200.0,
        FINANCIAL_DEPRECIATION=3000.0,
    )
    assert ebitda_margin_pct(s) == pytest.approx(25.0)


def test_pat_margin():
    s = _snap(FINANCIAL_REVENUE=200000.0, FINANCIAL_PAT=40000.0)
    assert pat_margin_pct(s) == pytest.approx(20.0)


def test_pat_margin_zero_revenue_returns_none():
    s = _snap(FINANCIAL_REVENUE=0.0, FINANCIAL_PAT=40000.0)
    assert pat_margin_pct(s) is None


def test_capex_intensity():
    s = _snap(FINANCIAL_REVENUE=200000.0, FINANCIAL_CAPEX=4000.0)
    assert capex_intensity_pct(s) == pytest.approx(2.0)


def test_fcf_gaap():
    s = _snap(FINANCIAL_OPERATING_CASH_FLOW=50000.0, FINANCIAL_CAPEX=4000.0)
    assert fcf_gaap(s) == pytest.approx(46000.0)


def test_fcf_gaap_missing_capex_returns_none():
    s = _snap(FINANCIAL_OPERATING_CASH_FLOW=50000.0)
    assert fcf_gaap(s) is None


def test_employee_cost_pct():
    s = _snap(FINANCIAL_REVENUE=200000.0, FINANCIAL_EMPLOYEE_COST=130000.0)
    assert employee_cost_pct(s) == pytest.approx(65.0)


def test_derived_missing_inputs_return_none():
    s = FinancialSnapshot(
        period="2025-03-31", period_type="annual", basis="consolidated"
    )
    assert ebit(s) is None
    assert ebitda(s) is None
    assert ebit_margin_pct(s) is None
    assert ebitda_margin_pct(s) is None
    assert pat_margin_pct(s) is None
    assert capex_intensity_pct(s) is None
    assert fcf_gaap(s) is None
    assert employee_cost_pct(s) is None
