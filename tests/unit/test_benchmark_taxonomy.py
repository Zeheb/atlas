"""Benchmark taxonomies (M1.8.5 commit 1, ADR-0005; AtlasCapability, M-E.1)."""

from __future__ import annotations

from typing import get_args

from atlas.benchmark.taxonomy import (
    ALL_CAPABILITY_IDS,
    ALL_SCENARIO_IDS,
    CAPABILITY_DESCRIPTIONS,
    SCENARIO_DESCRIPTIONS,
    AtlasCapability,
    RetrievalScenario,
)


def test_all_scenario_ids_matches_the_literal_exactly() -> None:
    # The frozenset used for coverage-floor checks must never drift from the
    # Literal type itself -- the same discipline planner.ALL_RULE_IDS follows.
    assert ALL_SCENARIO_IDS == frozenset(get_args(RetrievalScenario))


def test_every_scenario_has_a_description() -> None:
    assert set(SCENARIO_DESCRIPTIONS) == ALL_SCENARIO_IDS


def test_six_scenarios_declared() -> None:
    assert len(ALL_SCENARIO_IDS) == 6


# --- AtlasCapability axis (M-E.1) -----------------------------------------


def test_all_capability_ids_matches_the_literal_exactly() -> None:
    # Same Literal<->frozenset parity discipline as the scenario axis, so the
    # coverage-facing set can never silently drift from the type.
    assert ALL_CAPABILITY_IDS == frozenset(get_args(AtlasCapability))


def test_every_capability_has_a_description() -> None:
    assert set(CAPABILITY_DESCRIPTIONS) == ALL_CAPABILITY_IDS


def test_twenty_four_capabilities_declared() -> None:
    # The admitted set from the Atlas Evaluation Matrix §6: six families,
    # 24 capabilities (retrieval family intentionally empty).
    assert len(ALL_CAPABILITY_IDS) == 24


def test_no_capability_restates_a_retrieval_scenario() -> None:
    # The admission rule's anti-restatement clause (§6): a capability that
    # merely renames a RetrievalScenario member double-counts retrieval. The
    # two axes must stay disjoint by id, which is what keeps the "retrieval"
    # capability family empty by construction.
    assert ALL_CAPABILITY_IDS.isdisjoint(ALL_SCENARIO_IDS)


def test_no_retrieval_capability_family() -> None:
    # Retrieval difficulty is measured wholly on axis 1; the capability axis
    # carries no `ret.*` member (see module docstring / §6 orthogonality).
    assert not any(c.startswith("ret.") for c in ALL_CAPABILITY_IDS)
