"""RetrievalScenario taxonomy (M1.8.5 commit 1, ADR-0005)."""
from __future__ import annotations

from typing import get_args

from atlas.benchmark.taxonomy import ALL_SCENARIO_IDS, RetrievalScenario, SCENARIO_DESCRIPTIONS


def test_all_scenario_ids_matches_the_literal_exactly() -> None:
    # The frozenset used for coverage-floor checks must never drift from the
    # Literal type itself -- the same discipline planner.ALL_RULE_IDS follows.
    assert ALL_SCENARIO_IDS == frozenset(get_args(RetrievalScenario))


def test_every_scenario_has_a_description() -> None:
    assert set(SCENARIO_DESCRIPTIONS) == ALL_SCENARIO_IDS


def test_six_scenarios_declared() -> None:
    assert len(ALL_SCENARIO_IDS) == 6
