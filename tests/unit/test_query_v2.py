"""Unit tests for the Query Engine v2 additions: timeline, compare, summary,
drilldown (engine.py), and cross-company screen (screen.py).

Synthetic CompanyProfile fixtures — no real PDFs, no KB. Mirrors the
conventions in test_query_engine.py (_snap/_own_snap-style helpers).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas.analysis.base import FactKind, FactUnit
from atlas.company.model import (
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
    GovernanceProfile,
    OwnershipSnapshot,
    OwnershipTimeSeries,
    StrategyEntry,
    StrategyProfile,
)
from atlas.query.engine import compare, drilldown, run_query, summary, timeline
from atlas.query.screen import screen

_DT = datetime(2026, 5, 15, tzinfo=timezone.utc)


def _fsnap(
    period: str,
    facts: dict,
    period_type: str = "annual",
    basis: str = "consolidated",
    sources=None,
) -> FinancialSnapshot:
    return FinancialSnapshot(
        period=period,
        period_type=period_type,
        basis=basis,
        facts={FactKind(k): v for k, v in facts.items()},
        sources=sources if sources is not None else ["src-1"],
    )


def _esnap(period: str, facts: dict, sources=None) -> ESGSnapshot:
    return ESGSnapshot(
        period=period,
        facts={FactKind(k): v for k, v in facts.items()},
        sources=sources or ["src-esg"],
    )


def _osnap(period: str, facts: dict, sources=None) -> OwnershipSnapshot:
    return OwnershipSnapshot(
        period=period,
        facts={FactKind(k): v for k, v in facts.items()},
        sources=sources or ["src-own"],
    )


# ---------------------------------------------------------------------------
# timeline()
# ---------------------------------------------------------------------------


class TestTimeline:
    def _profile(self) -> CompanyProfile:
        p = CompanyProfile(company_id="TEST")
        p.financial = FinancialTimeSeries(
            snapshots=[
                _fsnap(
                    "2025-03-31", {"financial_gross_npa_ratio": 2.1}, sources=["e1"]
                ),
                _fsnap(
                    "2026-03-31", {"financial_gross_npa_ratio": 1.73}, sources=["e2"]
                ),
            ]
        )
        return p

    def test_previously_dark_banking_ratio_now_queryable(self) -> None:
        result = timeline(self._profile(), "gross_npa_ratio")
        rows = result.sections[0].rows
        assert len(rows) == 2
        assert rows[0][1] == "2.10%"
        assert rows[1][1] == "1.73%"

    def test_percent_delta_is_percentage_points(self) -> None:
        result = timeline(self._profile(), "gross_npa_ratio")
        rows = result.sections[0].rows
        assert rows[1][2] == "-0.37pp"

    def test_sources_column_present(self) -> None:
        result = timeline(self._profile(), "gross_npa_ratio")
        rows = result.sections[0].rows
        assert rows[0][3] == "e1"

    def test_unknown_metric_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown metric"):
            timeline(self._profile(), "not_a_metric")

    def test_no_data_produces_note(self) -> None:
        result = timeline(CompanyProfile(company_id="EMPTY"), "revenue")
        assert result.sections[0].rows == []
        assert result.notes

    def test_esg_domain_ignores_basis_period_type(self) -> None:
        p = CompanyProfile(company_id="TEST")
        p.esg = ESGTimeSeries(
            snapshots=[_esnap("2026-03-31", {"esg_workforce_headcount": 617437.0})]
        )
        result = timeline(
            p, "workforce_headcount", basis="standalone", period_type="quarterly"
        )
        assert result.sections[0].rows[0][1] == "617,437"

    def test_derived_metric_timeline(self) -> None:
        p = CompanyProfile(company_id="TEST")
        p.financial = FinancialTimeSeries(
            snapshots=[
                _fsnap(
                    "2026-03-31",
                    {
                        "financial_total_debt": 1000.0,
                        "financial_cash_and_equivalents": 300.0,
                    },
                ),
            ]
        )
        result = timeline(p, "net_debt")
        assert result.sections[0].rows[0][1] == "700 cr"

    def test_period_type_filter(self) -> None:
        p = CompanyProfile(company_id="TEST")
        p.financial = FinancialTimeSeries(
            snapshots=[
                _fsnap(
                    "2025-12-31", {"financial_revenue": 100.0}, period_type="quarterly"
                ),
                _fsnap(
                    "2026-03-31", {"financial_revenue": 400.0}, period_type="annual"
                ),
            ]
        )
        result = timeline(p, "revenue", period_type="annual")
        assert len(result.sections[0].rows) == 1
        assert result.sections[0].rows[0][0] == "Mar 2026"


# ---------------------------------------------------------------------------
# compare()
# ---------------------------------------------------------------------------


class TestCompare:
    def _profile(self) -> CompanyProfile:
        p = CompanyProfile(company_id="TEST")
        p.financial = FinancialTimeSeries(
            snapshots=[
                _fsnap(
                    "2025-03-31",
                    {"financial_operating_margin": 24.3},
                    period_type="quarterly",
                ),
                _fsnap(
                    "2025-09-30",
                    {"financial_operating_margin": 25.2},
                    period_type="quarterly",
                ),
                _fsnap(
                    "2026-03-31",
                    {"financial_operating_margin": 25.3},
                    period_type="quarterly",
                ),
            ]
        )
        return p

    def test_default_n_two(self) -> None:
        result = compare(self._profile(), "operating_margin", period_type="quarterly")
        rows = result.sections[0].rows
        assert len(rows) == 2
        assert rows[0][0] == "Sep 2025"
        assert rows[1][0] == "Mar 2026"

    def test_n_three(self) -> None:
        result = compare(
            self._profile(), "operating_margin", n=3, period_type="quarterly"
        )
        assert len(result.sections[0].rows) == 3

    def test_first_row_has_no_delta(self) -> None:
        result = compare(
            self._profile(), "operating_margin", n=3, period_type="quarterly"
        )
        assert result.sections[0].rows[0][2] == "-"

    def test_single_period_note(self) -> None:
        p = CompanyProfile(company_id="TEST")
        p.financial = FinancialTimeSeries(
            snapshots=[_fsnap("2026-03-31", {"financial_revenue": 100.0})]
        )
        result = compare(p, "revenue")
        assert any("one period" in n for n in result.notes)


# ---------------------------------------------------------------------------
# summary()
# ---------------------------------------------------------------------------


class TestSummary:
    def test_assembles_financial_and_ownership(self) -> None:
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(
            snapshots=[
                _fsnap(
                    "2026-03-31",
                    {"financial_revenue": 267021.0, "financial_pat": 49454.0},
                ),
            ]
        )
        p.ownership = OwnershipTimeSeries(
            snapshots=[
                _osnap(
                    "2026-03-31",
                    {"ownership_promoter_pct": 71.77, "ownership_fpi_pct": 9.66},
                ),
            ]
        )
        result = summary(p)
        headings = [s.heading for s in result.sections]
        assert "Latest Annual Financials" in headings
        assert "Latest Ownership" in headings

    def test_esg_headline_skips_target_only_snapshot(self) -> None:
        # Regression: SBTi target facts are stored with period = target
        # year, not report year — a bare target-only snapshot years in the
        # future must not be picked as "latest" over a real report.
        p = CompanyProfile(company_id="TCS")
        p.esg = ESGTimeSeries(
            snapshots=[
                _esnap(
                    "2026-03-31",
                    {
                        "esg_workforce_headcount": 617437.0,
                        "esg_workforce_female_pct": 35.3,
                    },
                ),
                _esnap("2034-03-31", {"esg_climate_sbti_scope12_reduction_pct": 42.0}),
            ]
        )
        result = summary(p)
        esg_section = next(s for s in result.sections if s.heading == "ESG Headline")
        assert esg_section.rows[0][0] == "Mar 2026"
        assert esg_section.rows[0][1] == "617,437"

    def test_empty_profile_has_no_data_note(self) -> None:
        result = summary(CompanyProfile(company_id="EMPTY"))
        assert result.sections == []
        assert "No data found in profile." in result.notes

    def test_recent_guidance_only_includes_guidance_kind(self) -> None:
        p = CompanyProfile(company_id="TCS")
        p.strategy = StrategyProfile(
            entries=[
                StrategyEntry(
                    source_date=_DT,
                    kind="priority",
                    text="Focus on AI",
                    evidence_id="e1",
                ),
                StrategyEntry(
                    source_date=_DT,
                    kind="guidance",
                    text="Margin 26-28%",
                    evidence_id="e2",
                ),
            ]
        )
        result = summary(p)
        guidance_section = next(
            s for s in result.sections if s.heading == "Recent Guidance"
        )
        assert len(guidance_section.rows) == 1
        assert guidance_section.rows[0][1] == "Margin 26-28%"


# ---------------------------------------------------------------------------
# drilldown()
# ---------------------------------------------------------------------------


class TestDrilldown:
    def test_finds_facts_by_snapshot_source(self) -> None:
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(
            snapshots=[
                _fsnap(
                    "2026-03-31",
                    {"financial_revenue": 267021.0},
                    sources=["bse-news-abc"],
                ),
            ]
        )
        result = drilldown(p, "bse-news-abc")
        assert result.sections
        assert "financial_revenue=267021.0" in result.sections[0].rows[0][3]

    def test_finds_events_by_evidence_id(self) -> None:
        p = CompanyProfile(company_id="TCS")
        p.capital_events = CapitalEventLedger(
            dividends=[
                DividendEvent(
                    source_date=_DT,
                    per_share=31.0,
                    dividend_type="final",
                    evidence_id="bse-news-xyz",
                ),
            ]
        )
        result = drilldown(p, "bse-news-xyz")
        heading_names = [s.heading for s in result.sections]
        assert "Capital Events" in heading_names

    def test_no_match_produces_note(self) -> None:
        result = drilldown(CompanyProfile(company_id="TCS"), "nonexistent-id")
        assert result.sections == []
        assert result.notes

    def test_governance_director_change_found(self) -> None:
        p = CompanyProfile(company_id="TCS")
        p.governance = GovernanceProfile(
            director_changes=[
                DirectorChange(
                    source_date=_DT,
                    change_type="appointment",
                    name="Jane Doe",
                    role="CFO",
                    evidence_id="e-gov",
                ),
            ]
        )
        result = drilldown(p, "e-gov")
        heading_names = [s.heading for s in result.sections]
        assert "Director Changes" in heading_names


# ---------------------------------------------------------------------------
# Dispatcher wiring for the 4 new queries
# ---------------------------------------------------------------------------


class TestRunQueryV2:
    def test_dispatches_summary(self) -> None:
        result = run_query("summary", CompanyProfile(company_id="TCS"))
        assert result.query == "summary"

    def test_dispatches_timeline(self) -> None:
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(
            snapshots=[_fsnap("2026-03-31", {"financial_revenue": 100.0})]
        )
        result = run_query("timeline", p, metric="revenue")
        assert result.query == "timeline"

    def test_dispatches_compare(self) -> None:
        p = CompanyProfile(company_id="TCS")
        p.financial = FinancialTimeSeries(
            snapshots=[_fsnap("2026-03-31", {"financial_revenue": 100.0})]
        )
        result = run_query("compare", p, metric="revenue")
        assert result.query == "compare"

    def test_dispatches_drilldown(self) -> None:
        result = run_query(
            "drilldown", CompanyProfile(company_id="TCS"), evidence_id="x"
        )
        assert result.query == "drilldown"


# ---------------------------------------------------------------------------
# Cross-company screen()
# ---------------------------------------------------------------------------


class TestScreen:
    def _profiles(self) -> dict[str, CompanyProfile]:
        tcs = CompanyProfile(company_id="TCS")
        tcs.financial = FinancialTimeSeries(
            snapshots=[_fsnap("2026-03-31", {"financial_operating_margin": 25.3})]
        )
        tata = CompanyProfile(company_id="TATASTEEL")
        tata.financial = FinancialTimeSeries(
            snapshots=[_fsnap("2026-03-31", {"financial_operating_margin": 16.0})]
        )
        sbin = CompanyProfile(company_id="SBIN")  # no operating_margin data at all
        return {"TCS": tcs, "TATASTEEL": tata, "SBIN": sbin}

    def test_ranks_descending_when_higher_is_better(self) -> None:
        result = screen(self._profiles(), "operating_margin")
        rows = result.sections[0].rows
        assert [r[0] for r in rows] == ["TCS", "TATASTEEL"]

    def test_company_without_data_excluded(self) -> None:
        result = screen(self._profiles(), "operating_margin")
        companies = [r[0] for r in result.sections[0].rows]
        assert "SBIN" not in companies

    def test_coverage_note(self) -> None:
        result = screen(self._profiles(), "operating_margin")
        assert any("2/3" in n for n in result.notes)

    def test_threshold_filter(self) -> None:
        result = screen(self._profiles(), "operating_margin", op="<", threshold=20.0)
        rows = result.sections[0].rows
        assert [r[0] for r in rows] == ["TATASTEEL"]

    def test_ascending_sort_when_lower_is_better(self) -> None:
        tcs = CompanyProfile(company_id="TCS")
        tcs.financial = FinancialTimeSeries(
            snapshots=[_fsnap("2026-03-31", {"financial_gross_npa_ratio": 3.0})]
        )
        sbin = CompanyProfile(company_id="SBIN")
        sbin.financial = FinancialTimeSeries(
            snapshots=[
                _fsnap(
                    "2025-09-30",
                    {"financial_gross_npa_ratio": 1.73},
                    period_type="quarterly",
                )
            ]
        )
        result = screen({"TCS": tcs, "SBIN": sbin}, "gross_npa_ratio", period_type=None)
        rows = result.sections[0].rows
        assert [r[0] for r in rows] == ["SBIN", "TCS"]

    def test_unknown_operator_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown operator"):
            screen(self._profiles(), "operating_margin", op="!=", threshold=1.0)

    def test_empty_profiles_no_crash(self) -> None:
        result = screen({}, "revenue")
        assert result.sections[0].rows == []
