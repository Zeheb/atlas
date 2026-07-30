"""Round trip, idempotency, value fidelity, store size — the CI variant.

Synthetic inputs, one result per registered analyzer kind. Per D1 this is the
gate: it runs on every push, where the golden-corpus variant in
``tests/integration/`` does not, because CI deselects that marker.

Synthetic is not a weaker check of *this* invariant. What the round trip has
to survive is structural -- duplicate facts, absent offsets, numeric types,
nulls -- and those are constructed here on purpose rather than hoped for in
a real document. What the corpus variant adds is that real analyzers actually
emit those shapes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.analysis.base import FactKind, FactUnit
from atlas.analysis.registry import supported_kinds
from atlas.assertions.reader import read_result
from atlas.assertions.store import AssertionStore
from atlas.assertions.writer import result_to_rows, write_result
from tests.support.roundtrip import (
    FINGERPRINT,
    assert_round_trip,
    fact_multiset,
    make_fact,
    make_result,
)


@pytest.mark.parametrize("evidence_kind", supported_kinds())
def test_every_analyzer_kind_round_trips(tmp_path: Path, evidence_kind: str) -> None:
    assert_round_trip(tmp_path, make_result(evidence_kind))


def test_all_eleven_kinds_are_covered() -> None:
    """If an analyzer is registered and this suite does not exercise it, the
    parametrize above is silently narrower than it claims."""
    assert len(supported_kinds()) == 11


# ---------------------------------------------------------------------------
# Idempotency and version bump (#14)
# ---------------------------------------------------------------------------


def _row_counts(store: AssertionStore) -> tuple[int, int]:
    import sqlite3

    connection = sqlite3.connect(str(store.path))
    try:
        runs = connection.execute("SELECT COUNT(*) FROM assertion_runs").fetchone()[0]
        facts = connection.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]
    finally:
        connection.close()
    return runs, facts


def test_writing_twice_yields_no_new_rows(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    result = make_result("annual_report")

    write_result(store, result, fingerprint=FINGERPRINT)
    before = _row_counts(store)
    write_result(store, result, fingerprint=FINGERPRINT)

    assert _row_counts(store) == before


def test_writing_twice_yields_identical_ids(tmp_path: Path) -> None:
    """Set equality of ids is what makes full-vs-incremental comparable."""
    result = make_result("annual_report")

    _, first = result_to_rows(result, fingerprint=FINGERPRINT)
    _, second = result_to_rows(result, fingerprint=FINGERPRINT)

    assert {item.assertion_id for item in first} == {
        item.assertion_id for item in second
    }


def test_version_bump_adds_rows_and_keeps_the_old(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    original = make_result("annual_report", analyzer_version="1.0")
    bumped = make_result("annual_report", analyzer_version="2.0")

    write_result(store, original, fingerprint=FINGERPRINT)
    runs_before, facts_before = _row_counts(store)
    write_result(store, bumped, fingerprint=FINGERPRINT)

    runs_after, facts_after = _row_counts(store)
    assert runs_after == runs_before + 1
    assert facts_after == facts_before * 2
    assert store.read_run(original.evidence_id, "1.0") is not None


def test_version_bump_yields_different_ids(tmp_path: Path) -> None:
    _, first = result_to_rows(
        make_result("annual_report", analyzer_version="1.0"), fingerprint=FINGERPRINT
    )
    _, second = result_to_rows(
        make_result("annual_report", analyzer_version="2.0"), fingerprint=FINGERPRINT
    )

    assert {item.assertion_id for item in first}.isdisjoint(
        item.assertion_id for item in second
    )


def test_reading_after_a_bump_returns_the_newer_version(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    write_result(
        store,
        make_result("annual_report", analyzer_version="1.0"),
        fingerprint=FINGERPRINT,
    )
    write_result(
        store,
        make_result("annual_report", analyzer_version="2.0"),
        fingerprint=FINGERPRINT,
    )

    restored = read_result(store, "ev-annual_report", fingerprint=FINGERPRINT.digest())

    assert restored.analyzer_version == "2.0"


# ---------------------------------------------------------------------------
# Value-type fidelity (#15)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["64988", 64988, 64988.0, 24.5, 0.1 + 0.2, -0.0, 0, None],
    ids=[
        "str",
        "int",
        "float-integral",
        "float",
        "inexact",
        "neg-zero",
        "zero",
        "none",
    ],
)
def test_quantitative_values_keep_their_type(
    tmp_path: Path, value: str | int | float | None
) -> None:
    """5, 5.0 and "5" are three different assertions, and must stay three."""
    result = make_result(
        "financial_results",
        facts=[make_fact(FactKind.FINANCIAL_REVENUE, value, unit=FactUnit.CRORE_INR)],
    )

    restored = assert_round_trip(tmp_path, result)

    assert type(restored.facts[0].value) is type(value)


def test_duplicate_facts_both_survive(tmp_path: Path) -> None:
    """Without ordinal these collapse to one row and one fact disappears."""
    duplicate = make_fact(FactKind.RISK_FACTOR, "Same risk", section="mda_risk")
    result = make_result("annual_report", facts=[duplicate, duplicate])

    restored = assert_round_trip(tmp_path, result)

    assert len(restored.facts) == 2


def test_provenance_survives(tmp_path: Path) -> None:
    result = make_result("annual_report")

    restored = assert_round_trip(tmp_path, result)

    assert fact_multiset(restored.facts) == fact_multiset(result.facts)
    assert {fact.provenance.section for fact in restored.facts} == {
        fact.provenance.section for fact in result.facts
    }


# ---------------------------------------------------------------------------
# Store size (#17)
# ---------------------------------------------------------------------------


def test_store_size_is_recorded_for_a_full_kind_sweep(tmp_path: Path) -> None:
    """A number nobody has looked at is how a store quietly becomes a problem.

    Eleven documents at five facts each is the synthetic stand-in; the real
    figure for a full TCS repository is asserted in the integration variant.
    """
    store = AssertionStore(tmp_path)
    for evidence_kind in supported_kinds():
        write_result(store, make_result(evidence_kind), fingerprint=FINGERPRINT)

    runs, facts = _row_counts(store)

    assert runs == len(supported_kinds())
    assert facts == len(supported_kinds()) * 5
    assert store.path.stat().st_size < 200_000
