"""Backfilling the assertion store — #54, with #58's safety properties.

The migration exists for repositories built before the store did. What makes
it safe to run against one of those is not that it succeeds; it is what is
true when it does not:

Dry run       -- does the whole job and keeps none of it. The counts are real
                 work, because the failures worth knowing about only appear
                 when the analyzers actually run.
Interruption  -- a run that dies part way leaves the repository byte for byte
                 as it was. The move is the commit point, and there is no
                 observable state between "untouched" and "whole".
Re-run        -- running it twice is not an error and does not accumulate.
                 Assertion ids are content addresses, so the second run
                 writes the same rows.

Verified    -- #55. A store can be complete and still wrong: the backfill runs
               today's analyzers over evidence whose profile may predate them.
               The move happens only if the staged store rebuilds the profile
               the repository already holds.

The interruption test injects a failure rather than simulating one: a writer
that raises on the second document is the same shape as a full disk, a
keyboard interrupt, or one analyzer breaking on document sixty.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.assertions.store import DB_FILENAME, AssertionStore

#: Bound before any monkeypatching, so the injected failure can still write
#: the documents it is not failing on.
from atlas.assertions.writer import write_result as _real_write
from atlas.company.store import LoadReport
from atlas.migrate import MigrationVerificationError, migrate_assertions
from tests.support.roundtrip import make_fact, make_result

_COMPANY = "TCS"


def _result(evidence_id: str, kind: str = "financial_results") -> AnalysisResult:
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
    result.source_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
    return result


def _stale_result(evidence_id: str) -> AnalysisResult:
    """The same document with a different number in it.

    What "the profile was written by an older analyzer" looks like from the
    migration's side: the store is complete and still projects a profile the
    repository does not hold.
    """
    result = _result(evidence_id)
    result.facts[0].value = 70000
    return result


@pytest.fixture
def analyzer_output(monkeypatch: pytest.MonkeyPatch) -> list[AnalysisResult]:
    """Stand in for parse+analyze; the migration is what is under test."""
    results = [_result("ev-1"), _result("ev-2", kind="buyback")]

    def _load(
        root: Path,
        *,
        source: object = None,
        on_error: object = None,
        only: object = None,
    ) -> LoadReport:
        return LoadReport(
            results=list(results), source="analyzers", parsed=len(results)
        )

    monkeypatch.setattr("atlas.migrate.load_results", _load)
    return results


def _staging_leftovers(root: Path) -> list[Path]:
    return list(root.glob(".assertions-migrate-*"))


# --- the happy path ----------------------------------------------------------


def test_a_migration_fills_an_empty_repository(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    report = migrate_assertions(tmp_path, _COMPANY)

    assert report.committed is True
    assert report.documents == 2
    assert AssertionStore(tmp_path).evidence_ids() == ("ev-1", "ev-2")


def test_the_migrated_store_is_readable_by_this_build(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """The point of the exercise: a profile can be built from it afterwards."""
    from atlas.assertions.reader import results_for

    migrate_assertions(tmp_path, _COMPANY)

    assert [result.evidence_id for result in results_for(tmp_path)] == ["ev-1", "ev-2"]


def test_staging_leaves_nothing_behind(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """A stray staging directory holds something shaped exactly like a store."""
    migrate_assertions(tmp_path, _COMPANY)

    assert _staging_leftovers(tmp_path) == []


# --- dry run (#58) -----------------------------------------------------------


def test_a_dry_run_writes_nothing(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    report = migrate_assertions(tmp_path, _COMPANY, dry_run=True)

    assert report.committed is False
    assert not (tmp_path / DB_FILENAME).exists()
    assert _staging_leftovers(tmp_path) == []


def test_a_dry_run_reports_the_real_counts(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """Real work, not an estimate, so the numbers can be acted on."""
    dry = migrate_assertions(tmp_path, _COMPANY, dry_run=True)
    wet = migrate_assertions(tmp_path, _COMPANY)

    assert dry.documents == wet.documents
    assert dry.runs_written == wet.runs_written
    assert dry.assertions_written == wet.assertions_written


def test_a_dry_run_does_not_create_a_store_to_inspect_one(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """Opening AssertionStore creates the file, so counting must not open it.

    Otherwise "this repository has no store" silently becomes "this repository
    has an empty store", and the dry run has changed the thing it inspected.
    """
    migrate_assertions(tmp_path, _COMPANY, dry_run=True)

    assert not (tmp_path / DB_FILENAME).exists()


# --- interruption (#58) ------------------------------------------------------


def test_an_interrupted_migration_leaves_an_existing_store_untouched(
    tmp_path: Path,
    analyzer_output: list[AnalysisResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The move is the commit point; before it, nothing is observable."""
    migrate_assertions(tmp_path, _COMPANY)
    before = (tmp_path / DB_FILENAME).read_bytes()

    calls = {"n": 0}

    def _explode(store: object, result: object, *, fingerprint: object) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("no space left on device")
        _real_write(store, result, fingerprint=fingerprint)  # type: ignore[arg-type]

    monkeypatch.setattr("atlas.assertions.writer.write_result", _explode)

    with pytest.raises(OSError, match="no space left"):
        migrate_assertions(tmp_path, _COMPANY)

    assert (tmp_path / DB_FILENAME).read_bytes() == before
    assert _staging_leftovers(tmp_path) == []


def test_an_interrupted_first_migration_leaves_no_store_at_all(
    tmp_path: Path,
    analyzer_output: list[AnalysisResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half a store is worse than none: every row in it is individually valid."""

    def _explode(store: object, result: object, *, fingerprint: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr("atlas.assertions.writer.write_result", _explode)

    with pytest.raises(OSError):
        migrate_assertions(tmp_path, _COMPANY)

    assert not (tmp_path / DB_FILENAME).exists()
    assert _staging_leftovers(tmp_path) == []


# --- re-run (#58) ------------------------------------------------------------


def test_re_running_does_not_accumulate_rows(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """Assertion ids are content addresses, so the second run writes the same rows."""
    migrate_assertions(tmp_path, _COMPANY)
    first = AssertionStore(tmp_path).stats()

    migrate_assertions(tmp_path, _COMPANY)
    second = AssertionStore(tmp_path).stats()

    assert (second.runs, second.assertions) == (first.runs, first.assertions)


def test_a_re_run_says_it_is_one(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """A first migration and a repeat are different situations on screen."""
    first = migrate_assertions(tmp_path, _COMPANY)
    second = migrate_assertions(tmp_path, _COMPANY)

    assert first.existing_runs == 0
    assert first.is_noop is False
    assert second.existing_runs == 2
    assert second.is_noop is True


# --- verification before the move (#55) --------------------------------------


def _write_profile(root: Path, results: list[AnalysisResult]) -> None:
    """Store a profile the way a repository already holds one."""
    from atlas.company.builder import build_profile
    from atlas.company.store import CompanyStore
    from atlas.rebuild import PROFILE_FILENAME

    CompanyStore(root / PROFILE_FILENAME, _COMPANY).save(
        build_profile(_COMPANY, results), results
    )


def test_a_matching_profile_lets_the_migration_through(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    _write_profile(tmp_path, analyzer_output)

    report = migrate_assertions(tmp_path, _COMPANY)

    assert report.verified is True
    assert report.differences == ()
    assert report.committed is True


def test_no_stored_profile_verifies_as_none_not_true(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """ "It matches" and "there was nothing to match" must not read alike."""
    report = migrate_assertions(tmp_path, _COMPANY)

    assert report.verified is None
    assert report.committed is True


def test_a_differing_profile_refuses_the_move(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """The failure the gate exists for: a complete store that is not the right one.

    The stored profile was built from a different revenue figure, which is
    what an analyzer changing since the profile was written looks like from
    here.
    """
    _write_profile(tmp_path, [_stale_result("ev-1"), _result("ev-2", kind="buyback")])

    with pytest.raises(MigrationVerificationError) as caught:
        migrate_assertions(tmp_path, _COMPANY)

    assert caught.value.differences
    assert not (tmp_path / DB_FILENAME).exists()


def test_a_refusal_keeps_the_staged_store_for_inspection(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """The staged store is the evidence: it is what the operator diffs."""
    _write_profile(tmp_path, [_stale_result("ev-1"), _result("ev-2", kind="buyback")])

    with pytest.raises(MigrationVerificationError) as caught:
        migrate_assertions(tmp_path, _COMPANY)

    staged = caught.value.staged_root
    assert staged.exists()
    assert (staged / DB_FILENAME).exists()
    assert _staging_leftovers(tmp_path) == [staged]


def test_a_refusal_leaves_an_existing_store_byte_identical(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """Atomicity is not weakened by the gate: the move simply does not happen."""
    migrate_assertions(tmp_path, _COMPANY)
    before = (tmp_path / DB_FILENAME).read_bytes()
    _write_profile(tmp_path, [_stale_result("ev-1"), _result("ev-2", kind="buyback")])

    with pytest.raises(MigrationVerificationError):
        migrate_assertions(tmp_path, _COMPANY)

    assert (tmp_path / DB_FILENAME).read_bytes() == before


def test_a_dry_run_reports_a_mismatch_without_raising(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """A dry run answers the question; it does not refuse a job nobody asked for."""
    _write_profile(tmp_path, [_stale_result("ev-1"), _result("ev-2", kind="buyback")])

    report = migrate_assertions(tmp_path, _COMPANY, dry_run=True)

    assert report.verified is False
    assert report.differences
    assert report.committed is False
    assert _staging_leftovers(tmp_path) == []


def test_the_comparison_ignores_wall_clock_fields(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """Otherwise every migration fails on built_at, which differs by construction.

    Delegating to rebuild.profiles_match is what buys this; a fresh equality
    check here would have to restate the exclusion list and would drift from
    the one the rebuild gate uses.
    """
    _write_profile(tmp_path, analyzer_output)

    report = migrate_assertions(tmp_path, _COMPANY)

    assert report.verified is True
