"""SearchPlan invariants (M1.7 commit 3).

Mirrors the discipline test_reasoning_contracts.py applies to the §10 types:
every invariant is pinned by a test, so a future relaxation breaks loudly
rather than silently.
"""
from __future__ import annotations

import json

import pytest

from atlas.reasoning.plan import (
    DateWindow,
    DocTypePreference,
    PlanningDecision,
    RerankHints,
    SearchPlan,
)


def _plan(**overrides: object) -> SearchPlan:
    defaults: dict[str, object] = dict(
        raw_question="What did management say about margins?",
        intent="narrative",
        query_terms=("management", "margins"),
    )
    defaults.update(overrides)
    return SearchPlan(**defaults)  # type: ignore[arg-type]


# --- SearchPlan.raw_question --------------------------------------------------
def test_raw_question_must_be_non_empty() -> None:
    with pytest.raises(ValueError):
        _plan(raw_question="")


def test_raw_question_whitespace_only_rejected() -> None:
    with pytest.raises(ValueError):
        _plan(raw_question="   ")


# --- SearchPlan.intent ---------------------------------------------------------
def test_intent_must_be_valid() -> None:
    with pytest.raises(ValueError):
        _plan(intent="not_a_real_intent")


@pytest.mark.parametrize("intent", [
    "financial_metric", "guidance", "risk", "governance", "capital_action",
    "esg", "ownership", "narrative", "general",
])
def test_every_declared_intent_is_accepted(intent: str) -> None:
    _plan(intent=intent)  # must not raise


# --- SearchPlan.top_k ----------------------------------------------------------
@pytest.mark.parametrize("top_k", [0, -1, 51, 1000])
def test_top_k_out_of_range_rejected(top_k: int) -> None:
    with pytest.raises(ValueError):
        _plan(top_k=top_k)


@pytest.mark.parametrize("top_k", [1, 5, 50])
def test_top_k_in_range_accepted(top_k: int) -> None:
    _plan(top_k=top_k)  # must not raise


# --- SearchPlan.preferred_doc_types --------------------------------------------
def test_preferred_doc_types_rejects_duplicate_kinds() -> None:
    with pytest.raises(ValueError):
        _plan(preferred_doc_types=(
            DocTypePreference(kind="annual_report", weight=10),
            DocTypePreference(kind="annual_report", weight=20),
        ))


def test_preferred_doc_types_accepts_distinct_kinds() -> None:
    plan = _plan(preferred_doc_types=(
        DocTypePreference(kind="annual_report", weight=10),
        DocTypePreference(kind="earnings_transcript", weight=20),
    ))
    assert len(plan.preferred_doc_types) == 2


# --- DocTypePreference ----------------------------------------------------------
def test_doctype_preference_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        DocTypePreference(kind="not_a_real_evidence_kind", weight=10)


@pytest.mark.parametrize("weight", [0, -1, 101, 1000])
def test_doctype_preference_weight_out_of_range_rejected(weight: int) -> None:
    with pytest.raises(ValueError):
        DocTypePreference(kind="annual_report", weight=weight)


@pytest.mark.parametrize("weight", [1, 50, 100])
def test_doctype_preference_weight_in_range_accepted(weight: int) -> None:
    DocTypePreference(kind="annual_report", weight=weight)  # must not raise


# --- DateWindow -----------------------------------------------------------------
def test_date_window_rejects_inverted_range() -> None:
    with pytest.raises(ValueError):
        DateWindow(start="2024-06-01", end="2024-01-01")


def test_date_window_accepts_equal_bounds() -> None:
    DateWindow(start="2024-01-01", end="2024-01-01")  # must not raise


def test_date_window_accepts_open_ended() -> None:
    DateWindow(start=None, end="2024-01-01")
    DateWindow(start="2024-01-01", end=None)
    DateWindow(start=None, end=None)


# --- RerankHints ------------------------------------------------------------
def test_rerank_hints_rejects_non_positive_max_per_document() -> None:
    with pytest.raises(ValueError):
        RerankHints(max_per_document=0)


def test_rerank_hints_defaults_are_inert() -> None:
    hints = RerankHints()
    assert hints.prefer_recent is False
    assert hints.prefer_numeric is False
    assert hints.max_per_document is None


# --- PlanningDecision ------------------------------------------------------------
def test_planning_decision_requires_rule() -> None:
    with pytest.raises(ValueError):
        PlanningDecision(rule="", input="x", output="y")


def test_planning_decision_has_no_confidence_field() -> None:
    # Deliberate: a deterministic rule engine has no meaningful confidence.
    decision = PlanningDecision(rule="intent_keyword_match", input="margins", output="narrative")
    assert not hasattr(decision, "confidence")


# --- Immutability & tuple coercion ------------------------------------------------
def test_plan_is_frozen() -> None:
    plan = _plan()
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        plan.top_k = 10  # type: ignore[misc]


def test_query_terms_coerced_to_tuple_from_list() -> None:
    plan = _plan(query_terms=["management", "margins"])
    assert plan.query_terms == ("management", "margins")
    assert isinstance(plan.query_terms, tuple)


def test_decisions_default_empty_tuple() -> None:
    assert _plan().decisions == ()


def test_preferred_doc_types_coerced_to_tuple_from_list() -> None:
    plan = _plan(preferred_doc_types=[DocTypePreference(kind="annual_report", weight=10)])
    assert isinstance(plan.preferred_doc_types, tuple)


# --- to_dict / serialization ------------------------------------------------------
def test_to_dict_round_trips_through_json() -> None:
    plan = _plan(
        preferred_doc_types=(DocTypePreference(kind="annual_report", weight=40),),
        date_window=DateWindow(start="2024-01-01", end="2024-12-31"),
        periods=("FY2024",),
        rerank=RerankHints(prefer_recent=True, max_per_document=2),
        decisions=(PlanningDecision(rule="intent_keyword_match", input="margins", output="narrative"),),
    )
    as_dict = plan.to_dict()
    # Must be JSON-serializable with no custom encoder.
    encoded = json.dumps(as_dict)
    decoded = json.loads(encoded)
    assert decoded["raw_question"] == plan.raw_question
    assert decoded["intent"] == "narrative"
    assert decoded["preferred_doc_types"][0]["kind"] == "annual_report"
    assert decoded["date_window"]["start"] == "2024-01-01"
    assert decoded["rerank"]["prefer_recent"] is True
    assert decoded["decisions"][0]["rule"] == "intent_keyword_match"


def test_to_dict_has_no_strategy_key() -> None:
    # Deliberate omission: retrieval mechanism is deployment config, not plan data.
    assert "strategy" not in _plan().to_dict()
