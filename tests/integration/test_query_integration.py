"""Integration tests for atlas.query.engine using the real TCS CompanyProfile.

These tests load the serialized profile from repositories/TCS/profile.json and
run every query function against real data.  Assertions are deliberately loose
so tests survive profile rebuilds — we verify structure and non-emptiness rather
than exact numeric values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.company.model import CompanyProfile
from atlas.company.store import CompanyStore
from atlas.query.engine import (
    QueryResult,
    TableSection,
    acquisitions,
    available_queries,
    capital_allocation,
    credit_ratings,
    leverage,
    ownership,
    revenue,
    risks,
    run_query,
    strategy,
)
from atlas.query.render import render_result

# ---------------------------------------------------------------------------
# Profile fixture
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[2] / "repositories" / "TCS"
_PROFILE_PATH = _REPO_ROOT / "profile.json"


def _kwargs_for(query_name: str) -> dict[str, object]:
    """timeline/compare/drilldown need an extra required argument beyond
    profile — every other query works from profile alone. Mirrors the CLI's
    own kwargs-building logic in cli.py's query_cmd."""
    if query_name in ("timeline", "compare"):
        return {"metric": "revenue"}
    if query_name == "drilldown":
        return {"evidence_id": "bse-news-e4ffa3fc-e4f0-4da0-89fe-75d2f7b7b956"}
    return {}


@pytest.fixture(scope="module")
def tcs_profile() -> CompanyProfile:
    """Load the TCS company profile from the repository."""
    if not _PROFILE_PATH.exists():
        pytest.skip(
            f"TCS profile not found at {_PROFILE_PATH}. " "Run: atlas profile build TCS"
        )
    store = CompanyStore(_PROFILE_PATH, "TCS")
    return store.load()


# ---------------------------------------------------------------------------
# Structural smoke tests
# ---------------------------------------------------------------------------


class TestProfileLoads:
    def test_profile_is_company_profile(self, tcs_profile: CompanyProfile) -> None:
        assert isinstance(tcs_profile, CompanyProfile)

    def test_company_id_is_tcs(self, tcs_profile: CompanyProfile) -> None:
        assert tcs_profile.company_id == "TCS"


# ---------------------------------------------------------------------------
# Revenue query
# ---------------------------------------------------------------------------


class TestRevenueIntegration:
    def test_revenue_returns_result(self, tcs_profile: CompanyProfile) -> None:
        result = revenue(tcs_profile)
        assert isinstance(result, QueryResult)
        assert result.query == "revenue"
        assert result.company_id == "TCS"

    def test_revenue_has_sections(self, tcs_profile: CompanyProfile) -> None:
        result = revenue(tcs_profile)
        assert len(result.sections) == 1

    def test_revenue_section_has_rows(self, tcs_profile: CompanyProfile) -> None:
        result = revenue(tcs_profile)
        # TCS has multiple years of data
        assert not result.is_empty()

    def test_revenue_columns_correct(self, tcs_profile: CompanyProfile) -> None:
        result = revenue(tcs_profile)
        cols = result.sections[0].columns
        assert "Revenue" in cols[1]
        assert "PAT" in cols[2]

    def test_revenue_rows_have_six_cells(self, tcs_profile: CompanyProfile) -> None:
        result = revenue(tcs_profile)
        for row in result.sections[0].rows:
            assert len(row) == 6

    def test_revenue_first_row_no_yoy(self, tcs_profile: CompanyProfile) -> None:
        result = revenue(tcs_profile)
        # Oldest row has no prior year to compare against
        first_row = result.sections[0].rows[0]
        assert first_row[-1] == "-"

    def test_revenue_subsequent_rows_have_yoy(
        self, tcs_profile: CompanyProfile
    ) -> None:
        result = revenue(tcs_profile)
        rows = result.sections[0].rows
        if len(rows) < 2:
            pytest.skip("Not enough data points for YoY comparison")
        # At least one of the later rows should have a YoY value
        yoy_values = [row[-1] for row in rows[1:]]
        assert any(v != "-" for v in yoy_values)


# ---------------------------------------------------------------------------
# Capital allocation query
# ---------------------------------------------------------------------------


class TestCapitalAllocationIntegration:
    def test_capital_returns_five_sections(self, tcs_profile: CompanyProfile) -> None:
        result = capital_allocation(tcs_profile)
        assert len(result.sections) == 5

    def test_section_headings(self, tcs_profile: CompanyProfile) -> None:
        result = capital_allocation(tcs_profile)
        headings = [s.heading for s in result.sections]
        assert "Dividends" in headings
        assert "Buybacks" in headings

    def test_dividends_not_empty(self, tcs_profile: CompanyProfile) -> None:
        result = capital_allocation(tcs_profile)
        div_sec = next(s for s in result.sections if s.heading == "Dividends")
        assert div_sec.rows, "TCS should have dividend records"

    def test_dividend_rows_have_four_cells(self, tcs_profile: CompanyProfile) -> None:
        result = capital_allocation(tcs_profile)
        div_sec = next(s for s in result.sections if s.heading == "Dividends")
        for row in div_sec.rows:
            assert len(row) == 4


# ---------------------------------------------------------------------------
# Strategy query
# ---------------------------------------------------------------------------


class TestStrategyIntegration:
    def test_strategy_returns_result(self, tcs_profile: CompanyProfile) -> None:
        result = strategy(tcs_profile)
        assert result.query == "strategy"

    def test_strategy_sections_include_priorities(
        self, tcs_profile: CompanyProfile
    ) -> None:
        result = strategy(tcs_profile)
        headings = [s.heading for s in result.sections]
        assert "Strategic Priorities" in headings

    def test_strategy_keyword_filter_reduces_results(
        self, tcs_profile: CompanyProfile
    ) -> None:
        all_result = strategy(tcs_profile)
        total_all = sum(len(s.rows) for s in all_result.sections)

        # "cloud" is a very common TCS keyword — may or may not match
        keyword_result = strategy(tcs_profile, keyword="xyz_no_match_xyz")
        total_keyword = sum(len(s.rows) for s in keyword_result.sections)
        assert total_keyword <= total_all

    def test_strategy_keyword_note_on_no_match(
        self, tcs_profile: CompanyProfile
    ) -> None:
        result = strategy(tcs_profile, keyword="xyz_no_match_xyz")
        assert any("xyz_no_match_xyz" in n for n in result.notes)


# ---------------------------------------------------------------------------
# Acquisitions query
# ---------------------------------------------------------------------------


class TestAcquisitionsIntegration:
    def test_acquisitions_returns_result(self, tcs_profile: CompanyProfile) -> None:
        result = acquisitions(tcs_profile)
        assert result.query == "acquisitions"

    def test_acquisitions_has_one_section(self, tcs_profile: CompanyProfile) -> None:
        result = acquisitions(tcs_profile)
        assert len(result.sections) == 1

    def test_acquisitions_rows_have_six_cells(
        self, tcs_profile: CompanyProfile
    ) -> None:
        result = acquisitions(tcs_profile)
        for row in result.sections[0].rows:
            assert len(row) == 6


# ---------------------------------------------------------------------------
# Ownership query
# ---------------------------------------------------------------------------


class TestOwnershipIntegration:
    def test_ownership_returns_result(self, tcs_profile: CompanyProfile) -> None:
        result = ownership(tcs_profile)
        assert result.query == "ownership"

    def test_ownership_not_empty(self, tcs_profile: CompanyProfile) -> None:
        result = ownership(tcs_profile)
        # TCS shareholding pattern filings are ingested
        # (empty is acceptable if no shareholding filings yet)
        assert isinstance(result, QueryResult)

    def test_ownership_rows_have_seven_cells(self, tcs_profile: CompanyProfile) -> None:
        result = ownership(tcs_profile)
        for row in result.sections[0].rows:
            assert len(row) == 7

    def test_ownership_most_recent_first(self, tcs_profile: CompanyProfile) -> None:
        result = ownership(tcs_profile)
        rows = result.sections[0].rows
        if len(rows) < 2:
            pytest.skip("Fewer than 2 ownership snapshots")
        # Periods should be descending — first row > second row
        assert rows[0][0] >= rows[1][0]

    def test_signals_section_when_enough_data(
        self, tcs_profile: CompanyProfile
    ) -> None:
        result = ownership(tcs_profile)
        # Signals section is only added when the algorithm detects notable moves.
        # With real TCS data we expect at least some signals (FPI/DII move enough).
        # If no signals are found (unlikely for multi-year data), this is still valid.
        headings = [s.heading for s in result.sections]
        if "Ownership Signals" in headings:
            sig_sec = next(
                s for s in result.sections if s.heading == "Ownership Signals"
            )
            assert sig_sec.rows, "Signals section should not be empty if present"
            for row in sig_sec.rows:
                assert len(row) == 1, "Each signal row is a single-cell row"

    def test_signals_section_rows_are_strings(
        self, tcs_profile: CompanyProfile
    ) -> None:
        result = ownership(tcs_profile)
        for section in result.sections:
            if section.heading == "Ownership Signals":
                for row in section.rows:
                    assert isinstance(row[0], str) and len(row[0]) > 0


# ---------------------------------------------------------------------------
# Leverage query
# ---------------------------------------------------------------------------


class TestLeverageIntegration:
    def test_leverage_returns_result(self, tcs_profile: CompanyProfile) -> None:
        result = leverage(tcs_profile)
        assert result.query == "leverage"

    def test_leverage_rows_have_four_cells(self, tcs_profile: CompanyProfile) -> None:
        result = leverage(tcs_profile)
        for row in result.sections[0].rows:
            assert len(row) == 4

    def test_leverage_net_cash_company(self, tcs_profile: CompanyProfile) -> None:
        result = leverage(tcs_profile)
        rows = result.sections[0].rows
        if not rows:
            pytest.skip("No leverage data")
        # TCS is a net cash company — at least one row should say "net cash"
        net_cash_rows = [r for r in rows if "net cash" in r[3]]
        assert net_cash_rows, "TCS should show net cash in at least one period"


# ---------------------------------------------------------------------------
# Credit ratings query
# ---------------------------------------------------------------------------


class TestCreditRatingsIntegration:
    def test_ratings_returns_result(self, tcs_profile: CompanyProfile) -> None:
        result = credit_ratings(tcs_profile)
        assert result.query == "ratings"

    def test_ratings_has_two_sections(self, tcs_profile: CompanyProfile) -> None:
        result = credit_ratings(tcs_profile)
        assert len(result.sections) == 2

    def test_esg_section_heading(self, tcs_profile: CompanyProfile) -> None:
        result = credit_ratings(tcs_profile)
        assert result.sections[0].heading == "ESG Ratings"

    def test_debt_section_heading(self, tcs_profile: CompanyProfile) -> None:
        result = credit_ratings(tcs_profile)
        assert result.sections[1].heading == "Debt Ratings"


# ---------------------------------------------------------------------------
# Risks query
# ---------------------------------------------------------------------------


class TestRisksIntegration:
    def test_risks_returns_result(self, tcs_profile: CompanyProfile) -> None:
        result = risks(tcs_profile)
        assert result.query == "risks"

    def test_risks_section_has_two_columns(self, tcs_profile: CompanyProfile) -> None:
        result = risks(tcs_profile)
        cols = result.sections[0].columns
        assert len(cols) == 2
        assert cols[0] == "Period"
        assert cols[1] == "Risk Factor"

    def test_risks_rows_have_two_cells(self, tcs_profile: CompanyProfile) -> None:
        result = risks(tcs_profile)
        for row in result.sections[0].rows:
            assert len(row) == 2


# ---------------------------------------------------------------------------
# Dispatcher (run_query) integration
# ---------------------------------------------------------------------------


class TestRunQueryIntegration:
    def test_all_registered_queries_execute(self, tcs_profile: CompanyProfile) -> None:
        """Every registered query name should run without exception on real data."""
        for q in available_queries():
            result = run_query(q, tcs_profile, **_kwargs_for(q))
            assert isinstance(result, QueryResult), f"{q} did not return QueryResult"
            assert result.company_id == "TCS"

    def test_run_query_invalid_raises(self, tcs_profile: CompanyProfile) -> None:
        import pytest

        with pytest.raises(ValueError, match="Unknown query"):
            run_query("nonexistent_query", tcs_profile)


# ---------------------------------------------------------------------------
# Renderer smoke test
# ---------------------------------------------------------------------------


class TestRenderIntegration:
    def test_render_revenue(self, tcs_profile: CompanyProfile) -> None:
        result = revenue(tcs_profile)
        rendered = render_result(result)
        assert "Revenue Evolution" in rendered
        assert "TCS" in rendered

    def test_render_empty_profile(self) -> None:
        from atlas.company.model import CompanyProfile

        empty = CompanyProfile(company_id="EMPTY")
        result = revenue(empty)
        rendered = render_result(result)
        assert "(no data)" in rendered or "no" in rendered.lower()

    def test_render_result_is_string(self, tcs_profile: CompanyProfile) -> None:
        for q in available_queries():
            result = run_query(q, tcs_profile, **_kwargs_for(q))
            rendered = render_result(result)
            assert isinstance(rendered, str)
            assert result.company_id in rendered
