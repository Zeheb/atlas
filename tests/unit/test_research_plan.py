"""ResearchPlan data model (M2.2.5 commit 1).

The load-bearing test here is test_dimensions_match_report_section_keys: the
research planner and the deterministic report must name the same nine things
the same way, and that is asserted against the REAL section builders rather
than a copied list, so the two cannot drift.
"""
from __future__ import annotations

import pytest

from atlas.research.plan import (
    MAX_INVESTIGATIONS,
    Investigation,
    ResearchDecision,
    ResearchPlan,
)


def _inv(dimension: str = "business_quality", **overrides: object) -> Investigation:
    kwargs: dict[str, object] = {
        "dimension": dimension,
        "question": f"What does {dimension} look like?",
        "subjects": ("TCS",),
        "rationale": "because the design says every dimension explains itself",
        "priority": 5,
    }
    kwargs.update(overrides)
    return Investigation(**kwargs)  # type: ignore[arg-type]


def _plan(**overrides: object) -> ResearchPlan:
    kwargs: dict[str, object] = {
        "raw_question": "Should I invest in TCS?",
        "intent": "invest_decision",
        "subjects": ("TCS",),
        "investigations": (_inv(),),
    }
    kwargs.update(overrides)
    return ResearchPlan(**kwargs)  # type: ignore[arg-type]


# --- The vocabulary drift guard (acceptance criterion 2) ----------------------------
def test_dimensions_match_report_section_keys() -> None:
    """Every ResearchDimension is a real report body-section key, and every
    report body-section key is a ResearchDimension. Asserted against the
    actual builders in report.py, not a hand-copied list.
    """
    from atlas.research.plan import _VALID_DIMENSIONS
    from atlas.research.report import _BODY_BUILDERS

    builder_keys = set()
    for module in _BODY_BUILDERS:
        # Each builder module names its section key in its build() return; the
        # module's own filename is that key by convention across all nine.
        builder_keys.add(module.__name__.rsplit(".", 1)[-1])

    assert builder_keys == set(_VALID_DIMENSIONS)


def test_every_dimension_is_individually_constructible() -> None:
    from atlas.research.plan import _VALID_DIMENSIONS

    for dimension in _VALID_DIMENSIONS:
        _inv(dimension)  # must not raise


# --- Investigation validation --------------------------------------------------------
def test_investigation_rejects_unknown_dimension() -> None:
    with pytest.raises(ValueError, match="not a valid ResearchDimension"):
        _inv("capital_allocation")  # the known blind spot -- must not silently pass


def test_investigation_requires_non_empty_question() -> None:
    with pytest.raises(ValueError, match="question must be non-empty"):
        _inv(question="   ")


def test_investigation_requires_rationale() -> None:
    # A dimension that cannot say why it belongs is a checklist entry.
    with pytest.raises(ValueError, match="rationale must be non-empty"):
        _inv(rationale="")


def test_investigation_requires_at_least_one_subject() -> None:
    with pytest.raises(ValueError, match="must name at least one subject"):
        _inv(subjects=())


def test_investigation_rejects_out_of_range_priority() -> None:
    with pytest.raises(ValueError, match="priority must be in 1..10"):
        _inv(priority=0)
    with pytest.raises(ValueError, match="priority must be in 1..10"):
        _inv(priority=11)


def test_investigation_coerces_subjects_to_tuple() -> None:
    inv = _inv(subjects=["TCS", "INFY"])
    assert inv.subjects == ("TCS", "INFY")


# --- ResearchPlan validation ---------------------------------------------------------
def test_plan_rejects_empty_question() -> None:
    with pytest.raises(ValueError, match="raw_question must be non-empty"):
        _plan(raw_question="")


def test_plan_rejects_unknown_intent() -> None:
    with pytest.raises(ValueError, match="not a valid ResearchIntent"):
        _plan(intent="vibes")


def test_plan_rejects_no_subjects() -> None:
    with pytest.raises(ValueError, match="subjects must name at least one subject"):
        _plan(subjects=())


def test_plan_rejects_zero_investigations() -> None:
    # A plan that investigates nothing cannot ground a view.
    with pytest.raises(ValueError, match="investigations must not be empty"):
        _plan(investigations=())


def test_plan_rejects_duplicate_dimensions() -> None:
    with pytest.raises(ValueError, match="duplicate dimension"):
        _plan(investigations=(_inv("risks"), _inv("risks")))


def test_plan_rejects_checklist_width() -> None:
    """The structural anti-checklist guard: a plan naming more dimensions than
    MAX_INVESTIGATIONS is rejected at construction.
    """
    from atlas.research.plan import _VALID_DIMENSIONS

    too_many = tuple(_inv(d) for d in sorted(_VALID_DIMENSIONS))
    assert len(too_many) > MAX_INVESTIGATIONS
    with pytest.raises(ValueError, match="is a checklist, not a research judgment"):
        _plan(investigations=too_many)


def test_plan_accepts_exactly_max_investigations() -> None:
    from atlas.research.plan import _VALID_DIMENSIONS

    at_cap = tuple(_inv(d) for d in sorted(_VALID_DIMENSIONS)[:MAX_INVESTIGATIONS])
    plan = _plan(investigations=at_cap)
    assert len(plan.investigations) == MAX_INVESTIGATIONS


# --- Derived accessors ----------------------------------------------------------------
def test_dimensions_property_preserves_plan_order() -> None:
    plan = _plan(investigations=(_inv("risks"), _inv("valuation"), _inv("catalysts")))
    assert plan.dimensions == ("risks", "valuation", "catalysts")


def test_ordered_investigations_sorts_by_priority_descending() -> None:
    plan = _plan(investigations=(
        _inv("risks", priority=3),
        _inv("valuation", priority=9),
        _inv("catalysts", priority=6),
    ))
    assert [i.dimension for i in plan.ordered_investigations()] == [
        "valuation", "catalysts", "risks",
    ]


def test_ordered_investigations_is_stable_within_equal_priority() -> None:
    # Equal priorities keep the planner's own emission order -- never
    # re-sorted alphabetically, since emission order is itself a judgment.
    plan = _plan(investigations=(
        _inv("valuation", priority=5),
        _inv("business_quality", priority=5),
        _inv("risks", priority=5),
    ))
    assert [i.dimension for i in plan.ordered_investigations()] == [
        "valuation", "business_quality", "risks",
    ]


# --- Serialization ----------------------------------------------------------------------
def test_to_dict_round_trips_nested_dataclasses() -> None:
    plan = _plan(
        investigations=(_inv("risks", priority=7),),
        decisions=(ResearchDecision(rule="intent_keyword_match", input="invest", output="invest_decision"),),
    )
    d = plan.to_dict()

    assert d["intent"] == "invest_decision"
    assert d["investigations"][0]["dimension"] == "risks"
    assert d["investigations"][0]["priority"] == 7
    assert d["investigations"][0]["rationale"]
    assert d["decisions"][0]["rule"] == "intent_keyword_match"


def test_to_dict_is_json_serializable() -> None:
    import json

    json.dumps(_plan().to_dict())  # must not raise


def test_research_decision_requires_rule() -> None:
    with pytest.raises(ValueError, match="rule must be non-empty"):
        ResearchDecision(rule="", input="x", output="y")
