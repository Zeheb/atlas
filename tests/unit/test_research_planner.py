"""HeuristicResearchPlanner (M2.2.5 commit 2).

Two tests here are architectural gates rather than behavior checks:

- test_planner_imports_no_forbidden_module: the layering boundary. The
  research planner must not reach into retrieval, knowledge, or I/O -- the
  same assertion test_reasoning_planner.py makes for the retrieval planner.
- test_plans_differ_across_intents: the anti-checklist gate in its unit
  form. The suite-level entropy version lands in commit 5; this is the
  minimum bar that must hold from the moment the planner exists.
"""

from __future__ import annotations

import pytest

from atlas.research.plan import MAX_INVESTIGATIONS, ResearchPlan
from atlas.research.planner import (
    ALL_RESEARCH_RULE_IDS,
    HeuristicResearchPlanner,
    plan_research,
)

_TCS = ("TCS",)


def _plan(question: str, subjects: tuple[str, ...] = _TCS) -> ResearchPlan:
    return plan_research(question, subjects)


# --- Architectural gate: import boundary -----------------------------------------
def _imported_modules(module: object) -> set[str]:
    """Every module name imported by *module*, parsed from its AST.

    Deliberately AST-based rather than a substring grep of the source: the
    module docstring legitimately *names* atlas.reasoning when explaining the
    layering, and a boundary test that a comment can break is worse than no
    test at all.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))  # type: ignore[arg-type]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_planner_imports_no_forbidden_module() -> None:
    """The research planner plans only. It must not import retrieval, the
    knowledge base, an LLM client, or any network/filesystem module.
    """
    from atlas.research import planner as planner_mod

    forbidden_prefixes = (
        "atlas.knowledge",
        "atlas.reasoning",
        "atlas.acquisition",
        "atlas.eval",
        "requests",
        "httpx",
        "sqlite3",
        "pathlib",
        "os",
        "subprocess",
    )
    for name in _imported_modules(planner_mod):
        for prefix in forbidden_prefixes:
            assert not (
                name == prefix or name.startswith(prefix + ".")
            ), f"research/planner.py must not import {name!r}"


def test_planner_only_imports_plan_from_atlas() -> None:
    from atlas.research import planner as planner_mod

    atlas_imports = {n for n in _imported_modules(planner_mod) if n.startswith("atlas")}
    assert atlas_imports == {"atlas.research.plan"}


# --- Architectural gate: plans must differ (anti-checklist, unit form) -----------
def test_plans_differ_across_intents() -> None:
    """A planner emitting the same dimensions for every question is dead in
    exactly the way a never-firing rule is dead.
    """
    invest = _plan("Should I invest in TCS?").dimensions
    risk = _plan("What are the key risks to TCS?").dimensions
    thematic = _plan("How exposed is TCS to currency movements?").dimensions
    targeted = _plan("What was the FY24 dividend?").dimensions

    distinct = {invest, risk, thematic, targeted}
    assert len(distinct) == 4, f"expected 4 distinct dimension sets, got {distinct}"


def test_no_plan_is_the_full_checklist() -> None:
    for question in (
        "Should I invest in TCS?",
        "What are the key risks to TCS?",
        "How exposed is TCS to input costs?",
        "What was revenue?",
    ):
        plan = _plan(question)
        assert len(plan.investigations) <= MAX_INVESTIGATIONS


# --- Intent classification -------------------------------------------------------
@pytest.mark.parametrize(
    "question,expected",
    [
        ("Should I invest in TCS?", "invest_decision"),
        ("Is TCS worth buying at this level?", "invest_decision"),
        ("What are the key risks to SBI?", "risk_assessment"),
        ("What could go wrong with this company?", "risk_assessment"),
        ("Compare Tata Steel with JSW Steel.", "comparison"),
        ("How does TCS look relative to its peers?", "comparison"),
        ("How exposed is TCS to currency movements?", "thematic"),
        ("What was the dividend in FY24?", "targeted"),
    ],
)
def test_intent_classification(question: str, expected: str) -> None:
    assert _plan(question).intent == expected


def test_invest_decision_beats_risk_marker_when_both_present() -> None:
    # "Should I invest in X, and what are the risks?" is an invest_decision
    # whose risk clause is one of its dimensions -- not a risk_assessment.
    plan = _plan("Should I invest in TCS, and what are the risks?")
    assert plan.intent == "invest_decision"
    assert "risks" in plan.dimensions


def test_unmatched_question_falls_back_to_targeted() -> None:
    plan = _plan("What is the registered office address?")
    assert plan.intent == "targeted"
    assert [d.rule for d in plan.decisions if d.rule == "research_intent_fallback"]


# --- Multi-subject handling ------------------------------------------------------
def test_multiple_subjects_force_comparison_intent() -> None:
    # Names no comparison marker, but two subjects make it unambiguous.
    plan = _plan("What are the margins?", ("TATASTEEL", "JSWSTEEL"))
    assert plan.intent == "comparison"
    assert [d.rule for d in plan.decisions if d.rule == "comparison_subjects_detected"]


def test_comparison_question_names_every_subject_once() -> None:
    plan = _plan("Compare Tata Steel with JSW Steel.", ("TATASTEEL", "JSWSTEEL"))
    for inv in plan.investigations:
        assert "TATASTEEL and JSWSTEEL" in inv.question
        assert inv.subjects == ("TATASTEEL", "JSWSTEEL")


def test_multi_subject_questions_use_plural_agreement() -> None:
    """These questions are read by a user AND consumed verbatim by
    plan_retrieval() -- "How does X and Y describe its position" is wrong on
    both verb and pronoun, and a research product should not emit it.
    """
    plan = _plan("Compare Tata Steel with JSW Steel.", ("TATASTEEL", "JSWSTEEL"))
    questions = [i.question for i in plan.investigations]

    competitive = next(q for q in questions if "competitive" in q)
    assert "How do " in competitive
    assert "their competitive positions" in competitive
    assert " its " not in competitive

    for q in questions:
        assert "has TATASTEEL and JSWSTEEL" not in q  # singular verb, plural subject


def test_single_subject_questions_use_singular_agreement() -> None:
    for inv in _plan("Should I invest in TCS?").investigations:
        assert " have TCS " not in inv.question
        assert " do TCS " not in inv.question


def test_every_dimension_has_both_question_forms() -> None:
    from atlas.research.plan import _VALID_DIMENSIONS
    from atlas.research.planner import _DIMENSION_QUESTIONS

    assert set(_DIMENSION_QUESTIONS) == set(_VALID_DIMENSIONS)
    for dimension, forms in _DIMENSION_QUESTIONS.items():
        assert len(forms) == 2, dimension
        singular, plural = forms
        assert singular != plural, f"{dimension} has identical singular/plural forms"
        assert "{subject}" in singular and "{subject}" in plural


def test_competitive_position_dropped_for_single_subject() -> None:
    """It compares against peers; with one subject it cannot be answered, so
    it is dropped with an audited decision rather than emitted unanswerable.
    """
    single = _plan("Compare TCS against its peers.", ("TCS",))
    assert "competitive_position" not in single.dimensions
    assert [
        d.rule for d in single.decisions if d.rule == "dimension_dropped_single_subject"
    ]


def test_competitive_position_kept_for_multi_subject() -> None:
    pair = _plan("Compare Tata Steel with JSW Steel.", ("TATASTEEL", "JSWSTEEL"))
    assert "competitive_position" in pair.dimensions


def test_planner_requires_at_least_one_subject() -> None:
    with pytest.raises(ValueError, match="requires at least one subject"):
        HeuristicResearchPlanner().plan("Should I invest?", ())


# --- Plan content ----------------------------------------------------------------
def test_invest_decision_covers_the_core_dimensions() -> None:
    dims = set(_plan("Should I invest in TCS?").dimensions)
    assert {"business_quality", "valuation", "balance_sheet", "risks"} <= dims


def test_risk_assessment_leads_with_risks() -> None:
    plan = _plan("What are the key risks to SBI?", ("SBIN",))
    assert plan.ordered_investigations()[0].dimension == "risks"


def test_every_investigation_carries_a_real_question_not_a_label() -> None:
    for inv in _plan("Should I invest in TCS?").investigations:
        assert inv.question.endswith("?")
        assert "TCS" in inv.question
        assert len(inv.question.split()) > 4  # a question, not a topic label


def test_every_investigation_explains_itself() -> None:
    for inv in _plan("Should I invest in TCS?").investigations:
        assert len(inv.rationale.split()) >= 8


def test_targeted_plan_is_a_single_investigation() -> None:
    plan = _plan("What was the FY24 dividend?")
    assert len(plan.investigations) == 1


# --- Determinism and rule bookkeeping --------------------------------------------
def test_planner_is_deterministic() -> None:
    a = _plan("Should I invest in TCS?")
    b = _plan("Should I invest in TCS?")
    assert a.to_dict() == b.to_dict()


def test_declared_rule_ids_match_what_the_planner_can_emit() -> None:
    """ALL_RESEARCH_RULE_IDS must not drift from the rules actually emitted --
    the same contract reasoning/planner.py's ALL_RULE_IDS has, and the input
    the dead-rule aggregate depends on.
    """
    fired: set[str] = set()
    for question, subjects in (
        ("Should I invest in TCS?", ("TCS",)),
        ("What are the key risks to SBI?", ("SBIN",)),
        ("Compare Tata Steel with JSW Steel.", ("TATASTEEL", "JSWSTEEL")),
        ("How exposed is TCS to input costs?", ("TCS",)),
        ("What was the FY24 dividend?", ("TCS",)),
        ("What are the margins?", ("TATASTEEL", "JSWSTEEL")),
        ("Compare TCS against its peers.", ("TCS",)),
    ):
        fired.update(d.rule for d in plan_research(question, subjects).decisions)

    assert fired == ALL_RESEARCH_RULE_IDS, (
        f"declared but never fired: {sorted(ALL_RESEARCH_RULE_IDS - fired)}; "
        f"fired but undeclared: {sorted(fired - ALL_RESEARCH_RULE_IDS)}"
    )


def test_plan_is_json_serializable() -> None:
    import json

    json.dumps(_plan("Should I invest in TCS?").to_dict())
