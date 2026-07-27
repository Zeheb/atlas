"""Rating-action / preceding-risk timeline (M-P2.3, Q41).

Derived query only: reads CompanyProfile.credit_history.debt_ratings and
governance.risk_factors, computes nothing new to store. Presents a temporal
association, never causation; never compares ratings across agencies/scales;
under-emits (honest empty result) when a company has no debt ratings.
"""
from __future__ import annotations

from datetime import datetime, timezone

from atlas.company.model import (
    CompanyProfile,
    CreditHistory,
    CreditRatingEntry,
    GovernanceProfile,
    RiskEntry,
)
from atlas.query.engine import rating_risk_timeline


def _rating(date: str, agency: str, rating: str, action: str) -> CreditRatingEntry:
    y, m, d = (int(x) for x in date.split("-"))
    return CreditRatingEntry(
        source_date=datetime(y, m, d, tzinfo=timezone.utc),
        agency=agency, instrument="Long-term", rating=rating, action=action, outlook="stable",
    )


def _risk(period: str, text: str) -> RiskEntry:
    return RiskEntry(period=period, text=text, evidence_id="bse-ar-1")


def _profile(ratings: list[CreditRatingEntry], risks: list[RiskEntry],
             esg: list[CreditRatingEntry] | None = None) -> CompanyProfile:
    p = CompanyProfile(company_id="ACME")
    p.credit_history = CreditHistory(debt_ratings=ratings, esg_ratings=esg or [])
    p.governance = GovernanceProfile(risk_factors=risks)
    return p


# --- 1. Chronological ordering ------------------------------------------------
def test_actions_ordered_chronologically() -> None:
    prof = _profile(
        [_rating("2024-06-14", "S&P", "BBB-", "revised"),
         _rating("2021-07-08", "CARE", "AA+", "revised")],
        [],
    )
    rows = rating_risk_timeline(prof).sections[0].rows
    assert [r[0] for r in rows] == ["2021-07-08", "2024-06-14"]


# --- 2. Only preceding risk periods are linked --------------------------------
def test_only_preceding_period_linked_never_later() -> None:
    prof = _profile(
        [_rating("2023-01-01", "CARE", "AA", "reaffirmed")],
        [_risk("2022-03-31", "old risk"), _risk("2024-03-31", "future risk")],
    )
    rows = rating_risk_timeline(prof).sections[0].rows
    assert rows[0][4] == "Mar 2022"
    assert "old risk" in rows[0][5]
    assert "future risk" not in rows[0][5]


# --- 3. Most recent preceding period only (not cumulative) --------------------
def test_most_recent_preceding_period_only_not_cumulative() -> None:
    prof = _profile(
        [_rating("2025-01-01", "CARE", "AA", "reaffirmed")],
        [_risk("2021-03-31", "ancient risk"), _risk("2024-03-31", "recent risk")],
    )
    rows = rating_risk_timeline(prof).sections[0].rows
    assert rows[0][4] == "Mar 2024"
    assert "recent risk" in rows[0][5]
    assert "ancient risk" not in rows[0][5]  # not cumulative across all prior periods


# --- 4. No cross-agency downgrade inference -----------------------------------
def test_no_cross_agency_comparison_or_inference() -> None:
    # Two different agencies/scales on different dates -- each action must be
    # reported verbatim, never compared against the other to infer a trend.
    prof = _profile(
        [_rating("2021-07-08", "CARE Ratings", "AA+", "revised"),
         _rating("2024-06-14", "S&P Global Ratings", "BBB-", "revised")],
        [],
    )
    rows = rating_risk_timeline(prof).sections[0].rows
    assert rows[0][2] == "AA+" and rows[0][3] == "revised"
    assert rows[1][2] == "BBB-" and rows[1][3] == "revised"
    # No synthesized "downgrade"/"upgrade" verdict is ever introduced
    assert not any("downgrade" in " ".join(r).lower() or "upgrade" in " ".join(r).lower() for r in rows)


def test_action_is_agencys_own_stated_call() -> None:
    prof = _profile([_rating("2026-05-29", "Moody's", "Baa2", "upgraded")], [])
    rows = rating_risk_timeline(prof).sections[0].rows
    assert rows[0][3] == "upgraded"  # verbatim, not re-derived


# --- 5. Honest "no downgrade recorded" rendering ------------------------------
def test_no_downgrade_action_renders_honestly() -> None:
    # Corpus reality: reaffirmed/revised/upgraded actions exist; "downgraded"
    # may never appear. The query must not fabricate one.
    prof = _profile(
        [_rating("2025-09-30", "S&P Global", "BBB", "reaffirmed"),
         _rating("2026-05-29", "Moody's", "Baa2", "upgraded")],
        [],
    )
    rows = rating_risk_timeline(prof).sections[0].rows
    actions = {r[3] for r in rows}
    assert actions == {"reaffirmed", "upgraded"}
    assert "downgraded" not in actions


# --- 6. Companies with no debt ratings -----------------------------------------
def test_no_debt_ratings_returns_honest_empty_result() -> None:
    prof = _profile([], [_risk("2024-03-31", "some risk")])
    result = rating_risk_timeline(prof)
    assert result.sections[0].rows == []
    assert any("no debt rating actions" in n.lower() for n in result.notes)
    assert result.is_empty()


def test_no_preceding_period_notes_honestly_in_row() -> None:
    prof = _profile([_rating("2020-01-01", "CARE", "AA", "reaffirmed")],
                     [_risk("2024-03-31", "too-late risk")])
    rows = rating_risk_timeline(prof).sections[0].rows
    assert rows[0][4] == "-"
    assert "no preceding" in rows[0][5].lower()


# --- 7. ESG ratings excluded ---------------------------------------------------
def test_esg_ratings_never_included() -> None:
    prof = _profile(
        ratings=[],
        risks=[],
        esg=[_rating("2025-01-01", "NSE Sustainability", "Leader", "upgraded")],
    )
    result = rating_risk_timeline(prof)
    assert result.sections[0].rows == []  # ESG-only company -> empty, not ESG rows
    agencies = [r[1] for r in result.sections[0].rows]
    assert "NSE Sustainability" not in agencies


def test_esg_ratings_not_mixed_with_debt_ratings() -> None:
    prof = _profile(
        ratings=[_rating("2024-01-01", "CARE", "AA", "reaffirmed")],
        risks=[],
        esg=[_rating("2025-01-01", "NSE Sustainability", "Leader", "upgraded")],
    )
    rows = rating_risk_timeline(prof).sections[0].rows
    assert len(rows) == 1
    assert rows[0][1] == "CARE"


# --- Framing: never causation ---------------------------------------------------
def test_notes_state_temporal_association_not_causation() -> None:
    prof = _profile([_rating("2024-01-01", "CARE", "AA", "reaffirmed")],
                     [_risk("2023-03-31", "some risk")])
    notes = " ".join(rating_risk_timeline(prof).notes).lower()
    assert "temporal association" in notes
    assert "not a claimed cause" in notes or "not a cause" in notes


# --- 8. Existing query suite remains green (registration + dispatch) ----------
def test_query_registered_and_dispatchable() -> None:
    from atlas.query.engine import available_queries, run_query
    assert "rating_risk_timeline" in available_queries()
    prof = _profile([_rating("2024-01-01", "CARE", "AA", "reaffirmed")], [])
    result = run_query("rating_risk_timeline", prof)
    assert result.query == "rating_risk_timeline"
