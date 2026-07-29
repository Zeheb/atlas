"""``AssertionStore.stale_evidence()`` — #48.

Staleness asked ahead of time. The reader already refuses rows written by a
build that is no longer running; this is the same judgement made early, so a
rebuild can act on it instead of failing on it.

The property that matters is symmetry with the reader. A row this query
calls current must be one the reader will serve, and a row it calls stale
must be one the reader refuses. A query that disagreed with the reader in
either direction would be worse than no query: one direction hides work
that needs doing, the other schedules work that does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.assertions.store import AssertionStore, StaleRun
from atlas.assertions.writer import write_result
from atlas.provenance import current_fingerprint
from tests.support.roundtrip import make_fact, make_result

_OTHER = "a-digest-from-another-build"


def _result(evidence_id: str, *, kind: str = "financial_results") -> AnalysisResult:
    result = make_result(
        kind,
        facts=[
            make_fact(
                FactKind.FINANCIAL_REVENUE,
                64988,
                unit=FactUnit.CRORE_INR,
                period="2026-03-31",
                section="consolidated_p_and_l",
            )
        ],
        entities=[],
    )
    result.evidence_id = evidence_id
    return result


@pytest.fixture
def store(tmp_path: Path) -> AssertionStore:
    return AssertionStore(tmp_path)


# --- nothing stale -----------------------------------------------------------


def test_an_empty_store_has_nothing_stale(store: AssertionStore) -> None:
    assert store.stale_evidence() == ()


def test_rows_from_the_current_build_are_not_stale(store: AssertionStore) -> None:
    write_result(store, _result("ev-1"), fingerprint=current_fingerprint().digest())

    assert store.stale_evidence() == ()


# --- something stale ---------------------------------------------------------


def test_rows_from_another_build_are_stale(store: AssertionStore) -> None:
    write_result(store, _result("ev-1"), fingerprint=_OTHER)

    stale = store.stale_evidence()

    assert len(stale) == 1
    assert stale[0].evidence_id == "ev-1"
    assert stale[0].stored_fingerprint == _OTHER


def test_a_stale_run_carries_what_re_analysis_needs(store: AssertionStore) -> None:
    """kind and analyzer_version, so the caller needs no second query."""
    write_result(store, _result("ev-1"), fingerprint=_OTHER)

    run = store.stale_evidence()[0]

    assert isinstance(run, StaleRun)
    assert run.kind == "financial_results"
    assert run.analyzer_version == "1.0"


def test_only_the_rows_from_another_build_are_returned(store: AssertionStore) -> None:
    write_result(store, _result("ev-old"), fingerprint=_OTHER)
    write_result(store, _result("ev-new"), fingerprint=current_fingerprint().digest())

    assert [run.evidence_id for run in store.stale_evidence()] == ["ev-old"]


def test_results_are_sorted(store: AssertionStore) -> None:
    """Two callers, or one caller twice, must see the same order."""
    for evidence_id in ("ev-c", "ev-a", "ev-b"):
        write_result(store, _result(evidence_id), fingerprint=_OTHER)

    assert [run.evidence_id for run in store.stale_evidence()] == [
        "ev-a",
        "ev-b",
        "ev-c",
    ]


def test_an_explicit_fingerprint_overrides_the_current_build(
    store: AssertionStore,
) -> None:
    """So a caller can ask what some other build would consider stale."""
    write_result(store, _result("ev-1"), fingerprint=_OTHER)

    assert store.stale_evidence(fingerprint=_OTHER) == ()
    assert len(store.stale_evidence(fingerprint="a-third-build")) == 1


# --- evidence ids ------------------------------------------------------------


def test_stale_evidence_ids_are_distinct_and_sorted(store: AssertionStore) -> None:
    write_result(store, _result("ev-b"), fingerprint=_OTHER)
    write_result(store, _result("ev-a", kind="buyback"), fingerprint=_OTHER)

    assert store.stale_evidence_ids() == ("ev-a", "ev-b")


def test_one_stale_run_condemns_the_document(store: AssertionStore) -> None:
    """Re-analysis is per-document, so a partly stale document is stale."""
    write_result(store, _result("ev-1"), fingerprint=current_fingerprint().digest())
    write_result(store, _result("ev-1", kind="buyback"), fingerprint=_OTHER)

    assert store.stale_evidence_ids() == ("ev-1",)


def test_a_clean_store_reports_no_stale_ids(store: AssertionStore) -> None:
    write_result(store, _result("ev-1"), fingerprint=current_fingerprint().digest())

    assert store.stale_evidence_ids() == ()


# --- agreement with the reader ----------------------------------------------


def test_this_predicts_the_reader_refusing(
    store: AssertionStore, tmp_path: Path
) -> None:
    """The invariant the query exists to serve.

    ``results_for`` does not skip a stale document — it raises, because
    serving a profile silently missing one document is the failure this
    project exists to prevent. So the useful question is whether the query
    predicts that refusal before it happens, and names the document that
    caused it.
    """
    from atlas.assertions.reader import StaleAssertionsError, results_for

    write_result(store, _result("ev-old"), fingerprint=_OTHER)
    write_result(store, _result("ev-new"), fingerprint=current_fingerprint().digest())

    with pytest.raises(StaleAssertionsError):
        results_for(tmp_path)
    assert store.stale_evidence_ids() == ("ev-old",)


def test_a_store_this_reports_clean_reads_without_raising(
    store: AssertionStore, tmp_path: Path
) -> None:
    """The other direction: no stale rows must mean no refusal."""
    from atlas.assertions.reader import results_for

    write_result(store, _result("ev-1"), fingerprint=current_fingerprint().digest())

    assert store.stale_evidence_ids() == ()
    assert [result.evidence_id for result in results_for(tmp_path)] == ["ev-1"]


def test_failed_runs_are_still_subject_to_staleness(store: AssertionStore) -> None:
    """A failure recorded by an old build says nothing about the new one."""
    failing = _result("ev-1")
    failing.warnings = ["analyzer raised"]
    write_result(store, failing, fingerprint=_OTHER)

    assert store.stale_evidence_ids() == ("ev-1",)
