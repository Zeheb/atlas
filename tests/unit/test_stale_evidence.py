"""``AssertionStore.stale_evidence()`` — #48.

Staleness asked ahead of time, so a rebuild can act on it instead of failing
on it.

The property that matters is symmetry with the reader. A row this query
calls current must be one the reader will serve, and a row it calls stale
must be one the reader refuses. A query that disagreed with the reader in
either direction would be worse than no query: one direction hides work
that needs doing, the other schedules work that does not.

The question asked is the narrow one: not "did this build write the row" but
"could anything that reaches this kind's assertions have moved". The two
differ whenever a bump misses a kind — another analyzer, or the builder — and
that difference is the whole of selective invalidation.

The reader still asks the whole-build question. One test here holds the
symmetry under the narrow rule and is ``xfail(strict=True)`` until it does.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pytest

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.assertions.store import DB_FILENAME, AssertionStore, StaleRun
from atlas.assertions.writer import write_result
from atlas.provenance import current_fingerprint
from tests.support.roundtrip import (
    foreign_fingerprint,
    make_fact,
    make_result,
)

#: A real fingerprint from a build that is not this one, rather than an
#: invented digest string. An arbitrary string could never have been produced
#: by any build, so it cannot exercise the comparison the way a genuine
#: competing fingerprint does -- and since the writer now derives the whole
#: digest and the sub-digest from one object, there is no way to hand it a
#: bare string anyway.
_FOREIGN = foreign_fingerprint()


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


def _clear_sub_digests(root: Path) -> None:
    """Put the store back into its pre-migration-3 state.

    Through sqlite directly, because no writer produces such a row any more:
    this is what a repository analysed before migration 3 actually holds, and
    the query has to answer for it.
    """
    conn = sqlite3.connect(str(root / DB_FILENAME))
    try:
        with conn:
            conn.execute("UPDATE assertion_runs SET affects_digest = NULL")
    finally:
        conn.close()


# --- nothing stale -----------------------------------------------------------


def test_an_empty_store_has_nothing_stale(store: AssertionStore) -> None:
    assert store.stale_evidence() == ()


def test_rows_from_the_current_build_are_not_stale(store: AssertionStore) -> None:
    write_result(store, _result("ev-1"), fingerprint=current_fingerprint())

    assert store.stale_evidence() == ()


# --- something stale ---------------------------------------------------------


def test_rows_from_another_build_are_stale(store: AssertionStore) -> None:
    write_result(store, _result("ev-1"), fingerprint=_FOREIGN)

    stale = store.stale_evidence()

    assert len(stale) == 1
    assert stale[0].evidence_id == "ev-1"
    assert stale[0].stored_fingerprint == _FOREIGN.digest()


def test_a_stale_run_carries_what_re_analysis_needs(store: AssertionStore) -> None:
    """kind and analyzer_version, so the caller needs no second query."""
    write_result(store, _result("ev-1"), fingerprint=_FOREIGN)

    run = store.stale_evidence()[0]

    assert isinstance(run, StaleRun)
    assert run.kind == "financial_results"
    assert run.analyzer_version == "1.0"


def test_only_the_rows_from_another_build_are_returned(store: AssertionStore) -> None:
    write_result(store, _result("ev-old"), fingerprint=_FOREIGN)
    write_result(store, _result("ev-new"), fingerprint=current_fingerprint())

    assert [run.evidence_id for run in store.stale_evidence()] == ["ev-old"]


def test_results_are_sorted(store: AssertionStore) -> None:
    """Two callers, or one caller twice, must see the same order."""
    for evidence_id in ("ev-c", "ev-a", "ev-b"):
        write_result(store, _result(evidence_id), fingerprint=_FOREIGN)

    assert [run.evidence_id for run in store.stale_evidence()] == [
        "ev-a",
        "ev-b",
        "ev-c",
    ]


def test_an_explicit_fingerprint_overrides_the_current_build(
    store: AssertionStore,
) -> None:
    """So a caller can ask what some other build would consider stale."""
    write_result(store, _result("ev-1"), fingerprint=_FOREIGN)

    # The object, not a digest: the comparison is per-kind, so the query has
    # to be able to compute ``affects(kind)`` for the build being asked about.
    assert store.stale_evidence(fingerprint=_FOREIGN) == ()
    assert len(store.stale_evidence(fingerprint=current_fingerprint())) == 1


# --- narrowing: which bumps actually reach a row -----------------------------


def test_a_builder_bump_alone_leaves_nothing_stale(store: AssertionStore) -> None:
    """The case whole-digest comparison gets wrong, and the reason for D9.

    ``builder_version`` shapes Tier 2. An assertion row is Tier 1, written by
    the writer from analyzer output, so a builder bump provably cannot change
    one — but it does move the whole digest, and comparing that would re-run
    every analyzer in the repository to fix a profile-assembly change.
    """
    older = dataclasses.replace(current_fingerprint(), builder_version="0.9")
    write_result(store, _result("ev-1"), fingerprint=older)

    assert older.digest() != current_fingerprint().digest()
    assert store.stale_evidence() == ()


def test_another_kinds_analyzer_bump_leaves_this_row_alone(
    store: AssertionStore,
) -> None:
    """Selective invalidation, stated as a test."""
    current = current_fingerprint()
    older = dataclasses.replace(
        current,
        analyzer_versions={**current.analyzer_versions, "buyback": "0.9"},
    )
    write_result(store, _result("ev-fr", kind="financial_results"), fingerprint=older)
    write_result(store, _result("ev-bb", kind="buyback"), fingerprint=older)

    assert store.stale_evidence_ids() == ("ev-bb",)


def test_this_kinds_analyzer_bump_makes_the_row_stale(store: AssertionStore) -> None:
    current = current_fingerprint()
    older = dataclasses.replace(
        current,
        analyzer_versions={**current.analyzer_versions, "financial_results": "0.9"},
    )
    write_result(store, _result("ev-1"), fingerprint=older)

    assert store.stale_evidence_ids() == ("ev-1",)


def test_a_shared_parser_bump_makes_every_row_stale(store: AssertionStore) -> None:
    """``shared_parser_version`` is in every sub-digest, by design.

    It is the component a per-kind digest is most likely to omit, and the one
    whose omission would be hardest to notice: the helpers seven analyzers
    share change extracted values without moving any ANALYZER_VERSION.
    """
    older = dataclasses.replace(
        current_fingerprint(), shared_parser_version="helpers-from-elsewhere"
    )
    write_result(store, _result("ev-fr"), fingerprint=older)
    write_result(store, _result("ev-bb", kind="buyback"), fingerprint=older)

    assert store.stale_evidence_ids() == ("ev-bb", "ev-fr")


def test_a_row_with_no_sub_digest_is_stale(
    store: AssertionStore, tmp_path: Path
) -> None:
    """A row from before migration 3. Unknown reads as stale.

    Unknown cannot be resolved later, either: the versions the sub-digest
    would be derived from survive only inside the whole digest, and sha256
    does not invert. Guessing "probably fine" here would serve rows no
    running code can account for.
    """
    write_result(store, _result("ev-1"), fingerprint=current_fingerprint())
    _clear_sub_digests(tmp_path)

    stale = store.stale_evidence()

    assert [run.evidence_id for run in stale] == ["ev-1"]
    assert stale[0].stored_affects_digest is None


def test_a_kind_with_no_registered_analyzer_is_stale(store: AssertionStore) -> None:
    """A retired analyzer. Nothing can reproduce the row, so nothing serves it.

    ``affects()`` raises for an unregistered kind rather than returning a
    digest, and letting that escape would turn one retired analyzer into an
    exception from a whole-store query.
    """
    current = current_fingerprint()
    write_result(store, _result("ev-1"), fingerprint=current)
    retired = dataclasses.replace(
        current,
        analyzer_versions={
            kind: version
            for kind, version in current.analyzer_versions.items()
            if kind != "financial_results"
        },
    )

    assert store.stale_evidence_ids(fingerprint=retired) == ("ev-1",)


def test_a_stale_run_carries_the_sub_digest_it_was_stamped_with(
    store: AssertionStore,
) -> None:
    """So a caller can say which of the two comparisons condemned the row."""
    write_result(store, _result("ev-1"), fingerprint=_FOREIGN)

    run = store.stale_evidence()[0]

    assert run.stored_affects_digest == _FOREIGN.affects("financial_results")
    assert run.stored_affects_digest != current_fingerprint().affects(
        "financial_results"
    )


# --- evidence ids ------------------------------------------------------------


def test_stale_evidence_ids_are_distinct_and_sorted(store: AssertionStore) -> None:
    write_result(store, _result("ev-b"), fingerprint=_FOREIGN)
    write_result(store, _result("ev-a", kind="buyback"), fingerprint=_FOREIGN)

    assert store.stale_evidence_ids() == ("ev-a", "ev-b")


def test_one_stale_run_condemns_the_document(store: AssertionStore) -> None:
    """Re-analysis is per-document, so a partly stale document is stale."""
    write_result(store, _result("ev-1"), fingerprint=current_fingerprint())
    write_result(store, _result("ev-1", kind="buyback"), fingerprint=_FOREIGN)

    assert store.stale_evidence_ids() == ("ev-1",)


def test_a_clean_store_reports_no_stale_ids(store: AssertionStore) -> None:
    write_result(store, _result("ev-1"), fingerprint=current_fingerprint())

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

    write_result(store, _result("ev-old"), fingerprint=_FOREIGN)
    write_result(store, _result("ev-new"), fingerprint=current_fingerprint())

    with pytest.raises(StaleAssertionsError):
        results_for(tmp_path)
    assert store.stale_evidence_ids() == ("ev-old",)


def test_a_store_this_reports_clean_reads_without_raising(
    store: AssertionStore, tmp_path: Path
) -> None:
    """The other direction: no stale rows must mean no refusal."""
    from atlas.assertions.reader import results_for

    write_result(store, _result("ev-1"), fingerprint=current_fingerprint())

    assert store.stale_evidence_ids() == ()
    assert [result.evidence_id for result in results_for(tmp_path)] == ["ev-1"]


def test_the_reader_serves_every_row_this_calls_current(
    store: AssertionStore, tmp_path: Path
) -> None:
    """The symmetry, under the narrow rule.

    A builder bump moves the whole digest and no sub-digest. This query
    reports nothing to re-analyse — correctly, since re-analysing would
    rewrite the rows byte for byte — and ``select_run`` now asks the same
    question, so the row it calls current is one the reader serves.

    If the two disagreed, ``--stale-only`` would re-analyse the narrow set
    and leave the rest unreadable, which is under-invalidation wearing the
    costume of a fix.
    """
    from atlas.assertions.reader import results_for

    older = dataclasses.replace(current_fingerprint(), builder_version="0.9")
    write_result(store, _result("ev-1"), fingerprint=older)

    assert store.stale_evidence_ids() == ()
    assert [result.evidence_id for result in results_for(tmp_path)] == ["ev-1"]


def test_failed_runs_are_still_subject_to_staleness(store: AssertionStore) -> None:
    """A failure recorded by an old build says nothing about the new one."""
    failing = _result("ev-1")
    failing.warnings = ["analyzer raised"]
    write_result(store, failing, fingerprint=_FOREIGN)

    assert store.stale_evidence_ids() == ("ev-1",)
