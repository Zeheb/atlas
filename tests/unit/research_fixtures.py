"""Shared synthetic CompanyProfile builder for atlas.research tests.

Not a test file itself (no test_ prefix) — imported by the test_research_*
files. Every section builder is a pure function of CompanyProfile, so a
single rich, hand-built profile (not derived from any real company) is
enough to exercise every section without a PDF or KnowledgeBase in sight.
"""
from __future__ import annotations

from datetime import datetime, timezone

from atlas.analysis.base import FactKind
from atlas.company.model import (
    AcquisitionEvent,
    AGMResolution,
    BuybackEvent,
    CapitalEventLedger,
    CompanyProfile,
    CreditHistory,
    CreditRatingEntry,
    DirectorChange,
    DividendEvent,
    ESGSnapshot,
    ESGTimeSeries,
    FinancialSnapshot,
    FinancialTimeSeries,
    FundraisingEvent,
    GovernanceProfile,
    OwnershipSnapshot,
    OwnershipTimeSeries,
    RiskEntry,
    SegmentEntry,
    SegmentTimeSeries,
    StrategyEntry,
    StrategyProfile,
)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def make_profile(company_id: str = "ACME") -> CompanyProfile:
    financial = FinancialTimeSeries(snapshots=[
        FinancialSnapshot(
            period="2024-03-31", period_type="annual", basis="consolidated",
            facts={
                FactKind.FINANCIAL_REVENUE: 90_000.0,
                FactKind.FINANCIAL_PAT: 12_000.0,
                FactKind.FINANCIAL_OPERATING_MARGIN: 19.0,
                FactKind.FINANCIAL_CASH_AND_EQUIVALENTS: 4_000.0,
                FactKind.FINANCIAL_TOTAL_DEBT: 3_500.0,
            },
            sources=["ev-fin-2024"],
        ),
        FinancialSnapshot(
            period="2025-03-31", period_type="annual", basis="consolidated",
            facts={
                FactKind.FINANCIAL_REVENUE: 100_000.0,
                FactKind.FINANCIAL_PAT: 15_000.0,
                FactKind.FINANCIAL_OPERATING_MARGIN: 20.0,
                FactKind.FINANCIAL_CASH_AND_EQUIVALENTS: 5_000.0,
                FactKind.FINANCIAL_TOTAL_DEBT: 3_000.0,
            },
            sources=["ev-fin-2025"],
        ),
        FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={
                FactKind.FINANCIAL_REVENUE: 120_000.0,
                FactKind.FINANCIAL_PAT: 19_000.0,
                FactKind.FINANCIAL_OPERATING_MARGIN: 22.0,
                FactKind.FINANCIAL_CASH_AND_EQUIVALENTS: 6_000.0,
            },
            sources=["ev-fin-2026"],
        ),
    ])

    esg = ESGTimeSeries(snapshots=[
        ESGSnapshot(
            period="2025-03-31",
            facts={FactKind.ESG_WORKFORCE_HEADCOUNT: 10_000.0, FactKind.ESG_WORKFORCE_ATTRITION_PCT: 12.0},
            sources=["ev-esg-2025"],
        ),
        ESGSnapshot(
            period="2026-03-31",
            facts={FactKind.ESG_WORKFORCE_HEADCOUNT: 10_500.0, FactKind.ESG_WORKFORCE_ATTRITION_PCT: 14.0},
            sources=["ev-esg-2026"],
        ),
    ])

    ownership = OwnershipTimeSeries(snapshots=[
        OwnershipSnapshot(
            period="2026-03-31",
            facts={FactKind.OWNERSHIP_PROMOTER_PCT: 55.0, FactKind.OWNERSHIP_FPI_PCT: 20.0},
            sources=["ev-own-2026"],
        ),
    ])

    capital_events = CapitalEventLedger(
        dividends=[DividendEvent(source_date=_dt("2026-04-01"), per_share=5.0, dividend_type="final", evidence_id="ev-div-1")],
        buybacks=[BuybackEvent(source_date=_dt("2025-12-01"), sub_type="announcement", amount=1000.0, evidence_id="ev-bb-1")],
        acquisitions=[AcquisitionEvent(
            source_date=_dt("2025-11-01"), target_name="Widget Co", stake_pct=100.0,
            expected_completion="2026-09-30", evidence_id="ev-acq-1",
        )],
        fundraises=[FundraisingEvent(
            source_date=_dt("2026-03-01"), fundraise_type="NCD", amount=2_000.0, evidence_id="ev-fund-1",
        )],
    )

    credit_history = CreditHistory(
        debt_ratings=[CreditRatingEntry(source_date=_dt("2026-01-01"), agency="CRISIL", rating="AAA", action="reaffirmed", evidence_id="ev-rate-1")],
    )

    segments = SegmentTimeSeries(entries=[
        SegmentEntry(period="2026-03-31", name="Segment A", revenue=70_000.0, ebit=15_000.0, evidence_id="ev-seg-1"),
        SegmentEntry(period="2026-03-31", name="Segment B", revenue=50_000.0, ebit=8_000.0, evidence_id="ev-seg-2"),
    ])

    strategy = StrategyProfile(entries=[
        StrategyEntry(source_date=_dt("2025-06-01"), kind="guidance", text="We target an aspirational margin band of 20-22% over time.", evidence_id="ev-strat-1"),
        StrategyEntry(source_date=_dt("2026-04-01"), kind="aspiration", text="We aim to be the market leader.", evidence_id="ev-strat-2"),
        StrategyEntry(source_date=_dt("2026-06-01"), kind="guidance", text="We reiterate our margin band of 20-22% as the medium-term target.", evidence_id="ev-strat-3"),
    ])

    governance = GovernanceProfile(
        resolutions=[AGMResolution(source_date=_dt("2026-07-01"), period="2026-06-30", title="Re-appointment of auditor", resolution_type="ordinary", outcome="passed", evidence_id="ev-agm-1")],
        director_changes=[DirectorChange(source_date=_dt("2026-02-01"), change_type="appointment", name="Jane Doe", role="Independent Director", evidence_id="ev-dir-1")],
        audit_kams=["Revenue recognition"],
        risk_factors=[
            RiskEntry(period="2025-03-31", text="Currency fluctuations may adversely impact reported revenue and margins over time.", evidence_id="ev-risk-1"),
            RiskEntry(period="2026-03-31", text="Currency fluctuations may adversely impact reported revenue and margins over time.", evidence_id="ev-risk-2"),
            RiskEntry(period="2026-03-31", text="Short frag", evidence_id="ev-risk-3"),
        ],
    )

    return CompanyProfile(
        company_id=company_id,
        financial=financial,
        esg=esg,
        capital_events=capital_events,
        credit_history=credit_history,
        ownership=ownership,
        segments=segments,
        strategy=strategy,
        governance=governance,
    )


def make_empty_profile(company_id: str = "EMPTY") -> CompanyProfile:
    return CompanyProfile(company_id=company_id)
