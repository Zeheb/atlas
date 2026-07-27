"""HeuristicPlanner behavior (M1.7 commit 4).

Covers all 9 declared intents plus the general fallback, period/FY/quarter
extraction, the top_k adjustment rules, and the import-boundary + purity
guarantees the M1.7 design leans on: the planner must be a pure function with
zero KB/LLM/network dependency, enforced here by test rather than convention.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from atlas.reasoning.planner import HeuristicPlanner, plan_retrieval

_PLANNER = HeuristicPlanner()

# Disallowed import prefixes for plan.py / planner.py -- if any of these
# appear, the planner has stopped being a pure str -> SearchPlan function.
_FORBIDDEN_IMPORT_PREFIXES = (
    "atlas.knowledge",
    "atlas.reasoning.llm",
    "atlas.reasoning.ask",
    "atlas.reasoning.context",
    "atlas.acquisition.repository",
    "atlas.acquisition.downloader",
    "sqlite3",
    "requests",
    "httpx",
    "urllib",
    "socket",
)


def _imported_modules(module_name: str) -> list[str]:
    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


# --- Import boundary ----------------------------------------------------------
@pytest.mark.parametrize(
    "module_name", ["atlas.reasoning.plan", "atlas.reasoning.planner"]
)
def test_module_imports_no_forbidden_dependency(module_name: str) -> None:
    imports = _imported_modules(module_name)
    for imported in imports:
        for forbidden in _FORBIDDEN_IMPORT_PREFIXES:
            assert not imported.startswith(forbidden), (
                f"{module_name} imports {imported!r}, violating the planner's "
                "no-KB/no-LLM/no-network boundary"
            )


# --- Purity / determinism -----------------------------------------------------
def test_plan_is_pure_repeated_calls_produce_equal_plan() -> None:
    question = "What did management say about margins?"
    plans = [_PLANNER.plan(question) for _ in range(20)]
    assert all(p == plans[0] for p in plans)


def test_plan_retrieval_convenience_function_matches_direct_call() -> None:
    question = "What was the reported revenue for FY2024?"
    assert plan_retrieval(question) == _PLANNER.plan(question)


# --- Intent classification: one case per declared intent ----------------------
@pytest.mark.parametrize(
    "question,expected_intent",
    [
        ("Who was appointed to the board this quarter?", "governance"),
        ("When was the last dividend announced?", "capital_action"),
        ("What are the company's BRSR emissions disclosures?", "esg"),
        ("What is the promoter shareholding pattern?", "ownership"),
        ("What are the key risk factors disclosed?", "risk"),
        ("What is the management's guidance for FY25?", "guidance"),
        ("What did management say about margins?", "narrative"),
        ("What was the reported revenue for FY2024?", "financial_metric"),
        ("What is the weather like today?", "general"),
    ],
)
def test_intent_classification(question: str, expected_intent: str) -> None:
    plan = _PLANNER.plan(question)
    assert plan.intent == expected_intent


def test_narrative_wins_over_metric_word_in_management_said_question() -> None:
    # The M1.7 design's own calibration example: a "what did management SAY"
    # question must favor transcripts (narrative), not treat "margins" as a
    # bare financial-metric lookup that would favor financial_results instead.
    plan = _PLANNER.plan("What did management say about margins?")
    assert plan.intent == "narrative"
    kinds = {p.kind for p in plan.preferred_doc_types}
    assert "earnings_transcript" in kinds


def test_every_intent_decision_is_recorded() -> None:
    plan = _PLANNER.plan("What is the promoter shareholding pattern?")
    rules_fired = {d.rule for d in plan.decisions}
    assert "intent_keyword_match" in rules_fired


def test_fallback_intent_is_recorded_with_its_own_rule() -> None:
    plan = _PLANNER.plan("What is the weather like today?")
    rules_fired = {d.rule for d in plan.decisions}
    assert "intent_fallback" in rules_fired
    assert plan.preferred_doc_types == ()  # "general" has no table entry


# --- Period / FY / quarter extraction -----------------------------------------
@pytest.mark.parametrize(
    "question,expected_periods",
    [
        ("What was revenue in FY2024?", ("FY2024",)),
        ("What was revenue in FY24?", ("FY2024",)),
        ("What was revenue in FY 2024?", ("FY2024",)),
        ("How did Q3FY24 compare to Q3FY23?", ("Q3FY2024", "Q3FY2023")),
        ("How did Q3 FY24 perform?", ("Q3FY2024",)),
        ("How did Q3-FY2024 perform?", ("Q3FY2024",)),
        ("What is the weather like today?", ()),
    ],
)
def test_period_extraction(question: str, expected_periods: tuple[str, ...]) -> None:
    plan = _PLANNER.plan(question)
    assert plan.periods == expected_periods


def test_quarter_mention_not_double_counted_as_plain_fy() -> None:
    plan = _PLANNER.plan("How did Q3FY24 compare to last year?")
    assert plan.periods == ("Q3FY2024",)  # not also "FY2024"


# --- top_k adjustment rules ----------------------------------------------------
def test_top_k_default_for_ordinary_question() -> None:
    plan = _PLANNER.plan("What did management say about margins?")
    assert plan.top_k == 5
    assert any(d.rule == "top_k_default" for d in plan.decisions)


def test_top_k_broadens_for_list_style_question() -> None:
    plan = _PLANNER.plan("List all dividends paid in the last five years.")
    assert plan.top_k == 10
    assert any(d.rule == "top_k_broaden_list_query" for d in plan.decisions)


def test_top_k_narrows_for_pointed_metric_lookup() -> None:
    plan = _PLANNER.plan("What was Q3 revenue?")
    assert plan.intent == "financial_metric"
    assert plan.top_k == 3
    assert any(d.rule == "top_k_narrow_specific_metric" for d in plan.decisions)


def test_broaden_rule_takes_priority_over_narrow_rule() -> None:
    # Contains both a broadening word and a financial_metric intent; the
    # explicit "enumerate everything" signal should win.
    plan = _PLANNER.plan("List all revenue figures across every quarter.")
    assert plan.top_k == 10


# --- SearchPlan validity end-to-end --------------------------------------------
def test_every_intent_fixture_produces_a_valid_plan() -> None:
    # SearchPlan.__post_init__ would raise on anything malformed; simply
    # constructing across a spread of real questions is itself a test.
    questions = [
        "Who was appointed to the board this quarter?",
        "When was the last dividend announced?",
        "What are the company's BRSR emissions disclosures?",
        "What is the promoter shareholding pattern?",
        "What are the key risk factors disclosed?",
        "What is the management's guidance for FY25?",
        "What did management say about margins?",
        "What was the reported revenue for FY2024?",
        "What is the weather like today?",
    ]
    for q in questions:
        _PLANNER.plan(q)  # must not raise
