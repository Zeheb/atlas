"""GroundingContext assembly (§10 C5, M0 commit 3). No network, synthetic profile."""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.analysis.base import FactKind
from atlas.company.model import (
    CompanyProfile,
    FinancialSnapshot,
    FinancialTimeSeries,
    SegmentEntry,
    SegmentTimeSeries,
    StrategyEntry,
    StrategyProfile,
)
from atlas.reasoning.context import build_context
from atlas.reasoning.contracts import SubjectRef

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")


def _profile() -> CompanyProfile:
    return CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(
            snapshots=[
                FinancialSnapshot(
                    period="2026-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={
                        FactKind.FINANCIAL_REVENUE: 255000.0,
                        FactKind.FINANCIAL_OPERATING_MARGIN: 24.2,
                    },
                    sources=["ev-fin"],
                ),
                # An unbacked snapshot (no sources) must yield no claims (G10).
                FinancialSnapshot(
                    period="2025-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={FactKind.FINANCIAL_REVENUE: 240000.0},
                    sources=[],
                ),
            ]
        ),
        segments=SegmentTimeSeries(
            entries=[
                SegmentEntry(
                    period="2026-03-31",
                    name="BFSI",
                    revenue=80000.0,
                    ebit=20000.0,
                    growth_pct=8.1,
                    evidence_id="ev-seg",
                )
            ]
        ),
        strategy=StrategyProfile(
            entries=[
                StrategyEntry(
                    source_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
                    kind="guidance",
                    text="Targeting 26-28% EBIT margin",
                    evidence_id="ev-strat",
                )
            ]
        ),
    )


def test_builds_claims_with_closed_world_index() -> None:
    ctx = build_context(_profile(), SUBJECT)
    assert ctx.evidence_index == {"ev-fin", "ev-seg", "ev-strat"}
    # Every claim is backed (contract guarantees >=1 evidence) and indexed.
    for claim in ctx.claims:
        assert claim.evidence_ids
        assert claim.evidence_ids <= ctx.evidence_index


def test_unbacked_records_produce_no_claims() -> None:
    ctx = build_context(_profile(), SUBJECT)
    # The 2025 revenue fact had no sources -> no claim cites 2025 revenue alone.
    stmts = [c.statement for c in ctx.claims]
    assert not any("240000" in s for s in stmts)
    assert any("255000" in s for s in stmts)  # the backed 2026 revenue survives


def test_known_ids_filter_drops_unresolvable_evidence() -> None:
    ctx = build_context(_profile(), SUBJECT, known_ids={"ev-fin"})
    assert ctx.evidence_index == {"ev-fin"}
    # Claims that cited only ev-seg / ev-strat are gone.
    assert all(c.evidence_ids <= {"ev-fin"} for c in ctx.claims)


def test_strategy_text_is_grounded_verbatim() -> None:
    ctx = build_context(_profile(), SUBJECT)
    strat = [c for c in ctx.claims if "26-28%" in c.statement]
    assert strat and strat[0].evidence_ids == {"ev-strat"}
