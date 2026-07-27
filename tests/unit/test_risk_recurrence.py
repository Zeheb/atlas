"""Cross-year risk-factor recurrence (M-P2.6, Q22).

Derived query only: groups RiskEntry.text by PRESENTATION normalization
(case/punctuation/whitespace) -- no stemming, synonym expansion, fuzzy
matching, or semantic grouping. Counts DISTINCT reporting periods, not raw
rows. risks() is untouched.
"""

from __future__ import annotations

from atlas.company.model import CompanyProfile, GovernanceProfile, RiskEntry
from atlas.query.engine import risk_recurrence, risks


def _risk(period: str, text: str) -> RiskEntry:
    return RiskEntry(period=period, text=text, evidence_id="bse-ar-1")


def _profile(entries: list[RiskEntry]) -> CompanyProfile:
    p = CompanyProfile(company_id="ACME")
    p.governance = GovernanceProfile(risk_factors=entries)
    return p


# --- punctuation / case / whitespace normalization ----------------------------
def test_punctuation_normalized() -> None:
    prof = _profile(
        [
            _risk("2022-03-31", "Currency fluctuation risk."),
            _risk("2023-03-31", "Currency fluctuation risk"),
        ]
    )
    rows = risk_recurrence(prof).sections[0].rows
    assert len(rows) == 1
    assert rows[0][0] == "2"


def test_case_normalized() -> None:
    prof = _profile(
        [
            _risk("2022-03-31", "Market Risk"),
            _risk("2023-03-31", "market risk"),
        ]
    )
    rows = risk_recurrence(prof).sections[0].rows
    assert len(rows) == 1 and rows[0][0] == "2"


def test_whitespace_normalized() -> None:
    prof = _profile(
        [
            _risk("2022-03-31", "Compliance  risk"),
            _risk("2023-03-31", "Compliance risk"),
            _risk("2024-03-31", "  Compliance risk  "),
        ]
    )
    rows = risk_recurrence(prof).sections[0].rows
    assert len(rows) == 1 and rows[0][0] == "3"


def test_no_stemming_or_fuzzy_matching() -> None:
    # "Market risk" and "Market risks" must NOT be grouped -- no stemming.
    prof = _profile(
        [
            _risk("2022-03-31", "Market risk"),
            _risk("2023-03-31", "Market risks"),
        ]
    )
    rows = risk_recurrence(prof).sections[0].rows
    assert rows == []  # each seen once -> neither is "recurring"


def test_no_synonym_or_semantic_grouping() -> None:
    prof = _profile(
        [
            _risk("2022-03-31", "Currency risk"),
            _risk("2023-03-31", "Foreign exchange risk"),
        ]
    )
    assert risk_recurrence(prof).sections[0].rows == []


# --- recurrence counting: distinct periods, not raw rows ----------------------
def test_duplicate_rows_same_period_do_not_inflate_recurrence() -> None:
    prof = _profile(
        [
            _risk("2023-03-31", "Market risk"),
            _risk("2023-03-31", "Market risk"),
            _risk("2023-03-31", "market risk."),  # same period, normalized-identical
        ]
    )
    rows = risk_recurrence(prof).sections[0].rows
    assert rows == []  # only ONE distinct period -> not recurring


def test_periods_listed_correctly_most_recent_shown() -> None:
    prof = _profile(
        [
            _risk("2021-03-31", "Interest rate risk"),
            _risk("2023-03-31", "Interest rate risk"),
            _risk("2025-03-31", "Interest rate risk"),
        ]
    )
    rows = risk_recurrence(prof).sections[0].rows
    assert len(rows) == 1
    assert rows[0][0] == "3"
    assert rows[0][1] == "Mar 2025"  # most recent period


def test_single_occurrence_risks_excluded() -> None:
    prof = _profile(
        [
            _risk("2022-03-31", "Market risk"),
            _risk("2023-03-31", "Market risk"),
            _risk("2023-03-31", "One-off litigation risk"),
        ]
    )
    rows = risk_recurrence(prof).sections[0].rows
    assert len(rows) == 1
    assert "market risk" in rows[0][2].lower()


# --- ordering: count desc, then most-recent-period desc, then text asc -------
def test_ordering_count_desc_then_recency_desc_then_text_asc() -> None:
    prof = _profile(
        [
            # "alpha risk": 3 occurrences, most recent 2024
            _risk("2020-03-31", "Alpha risk"),
            _risk("2022-03-31", "Alpha risk"),
            _risk("2024-03-31", "Alpha risk"),
            # "beta risk": 2 occurrences, most recent 2025 (more recent than alpha, but fewer occurrences)
            _risk("2023-03-31", "Beta risk"),
            _risk("2025-03-31", "Beta risk"),
            # "gamma risk": 2 occurrences, most recent 2021 (least recent)
            _risk("2019-03-31", "Gamma risk"),
            _risk("2021-03-31", "Gamma risk"),
        ]
    )
    rows = risk_recurrence(prof).sections[0].rows
    texts = [r[2].lower() for r in rows]
    assert texts[0] == "alpha risk"  # count=3 wins over count=2 regardless of recency
    assert texts[1] == "beta risk"  # among count=2, more recent (2025) first
    assert texts[2] == "gamma risk"


def test_text_tiebreak_when_count_and_recency_equal() -> None:
    prof = _profile(
        [
            _risk("2022-03-31", "Zeta risk"),
            _risk("2023-03-31", "Zeta risk"),
            _risk("2022-03-31", "Alpha risk"),
            _risk("2023-03-31", "Alpha risk"),
        ]
    )
    rows = risk_recurrence(prof).sections[0].rows
    texts = [r[2].lower() for r in rows]
    assert texts == ["alpha risk", "zeta risk"]  # same count+recency -> text asc


# --- no-recurring-risk companies -----------------------------------------------
def test_no_recurring_risks_honest_empty_result() -> None:
    prof = _profile([_risk("2023-03-31", "One-off risk")])
    result = risk_recurrence(prof)
    assert result.sections[0].rows == []
    assert result.is_empty()
    assert any("no risk factor recurs" in n.lower() for n in result.notes)


def test_no_risk_factors_at_all() -> None:
    result = risk_recurrence(_profile([]))
    assert result.sections[0].rows == []
    assert result.is_empty()


# --- risks() unchanged (regression) --------------------------------------------
def test_existing_risks_query_behavior_unchanged() -> None:
    prof = _profile(
        [
            _risk("2022-03-31", "Market risk"),
            _risk("2023-03-31", "Market risk"),
            _risk("2023-03-31", "Currency risk"),
        ]
    )
    result = risks(prof)
    assert result.query == "risks"
    assert result.title == "Recurring Risk Factors"
    # risks() still dedupes to ONE row per unique text, latest period, no count column
    assert result.sections[0].columns == ["Period", "Risk Factor"]
    texts = {row[1] for row in result.sections[0].rows}
    assert texts == {"Market risk", "Currency risk"}
    assert len(result.sections[0].rows) == 2


# --- dispatch registration ------------------------------------------------------
def test_query_registered_and_dispatchable() -> None:
    from atlas.query.engine import available_queries, run_query

    assert "risk_recurrence" in available_queries()
    prof = _profile(
        [_risk("2022-03-31", "Market risk"), _risk("2023-03-31", "Market risk")]
    )
    result = run_query("risk_recurrence", prof)
    assert result.query == "risk_recurrence"
    assert result.sections[0].rows[0][0] == "2"
