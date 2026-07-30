"""Backfilling the assertion store for a repository that predates it.

Every company repository built before M1 has a profile and no assertions. The
store is now what profiles are built from (#35), so those repositories are one
step away from being unreadable by the current code: nothing in the store means
``results_for`` returns nothing, and a profile rebuilt from nothing is empty.

This module fills the gap by re-running the analyzers over evidence that is
already acquired and writing what they produce into the store.

Why a temporary database, then a move
-------------------------------------
Backfilling a repository of ninety filings is minutes of work, and the process
can die in the middle of it: a keyboard interrupt, a full disk, one analyzer
raising on document sixty. Writing into the live ``assertions.db`` would leave
a store holding some documents and not others, which is indistinguishable from
a store that was always partial -- and the reader cannot tell, because every
row in it is individually valid.

So the whole backfill goes into a temporary database, and only a complete one
replaces the real file. The move is the commit point. Before it, the repository
is exactly as it was; after it, the store is whole. There is no state in
between that anyone can observe, which is the property that makes an
interrupted migration a non-event rather than a cleanup job.

``os.replace`` is what does it: atomic within a filesystem, and the temporary
file is created inside the repository so it is on the same one. A move across
filesystems degrades to copy-then-delete, which is exactly the partial state
this design exists to avoid.

What is checked before the move
-------------------------------
A store that is complete is not necessarily a store that is *right*. The
backfill re-runs today's analyzers over evidence whose profile may have been
written by older ones, so the rows can all be present and still project a
different profile than the repository holds -- and replacing the store would
then silently change every number downstream of it.

So the profile is built from the staged store and compared against the stored
one, through ``rebuild.profiles_match``, immediately before the move. A
mismatch refuses the migration and keeps the staged store, which is the only
artifact that can say which document moved.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from atlas.assertions.store import DB_FILENAME, AssertionStore
from atlas.company.store import load_results


class MigrationVerificationError(RuntimeError):
    """The migrated store would not rebuild the profile the repository holds.

    Named, and carrying both the staged path and the differences, because the
    operator's next action depends on which it is. A difference in one
    document's facts means an analyzer changed since the profile was written;
    a difference everywhere means the profile predates something larger. The
    refusal alone distinguishes neither.

    Raised instead of returning a report because the caller asked for a
    migration and did not get one. A report with ``committed=False`` reads the
    same as a dry run, and the one thing that must not happen here is a failed
    migration being mistaken for a successful no-op.
    """

    def __init__(
        self, message: str, *, staged_root: Path, differences: tuple[str, ...]
    ) -> None:
        super().__init__(message)
        self.staged_root = staged_root
        self.differences = differences


@dataclass(frozen=True)
class MigrationReport:
    """What a backfill found, wrote, and whether it kept it.

    ``committed`` is the only field that says whether the repository changed.
    A dry run produces a report with every count filled in and
    ``committed=False``, which is the point: the operator sees the whole shape
    of the work before authorising it.

    ``existing_runs`` is what the store held before. Non-zero means this is a
    re-run rather than a first migration, which is a different situation and
    should not look the same on screen.

    ``verified`` is ``None`` when the repository held no profile to compare
    against -- a first build, not a passing check. ``False`` only ever reaches
    a caller from a dry run; a real migration raises instead, because a
    refused migration must not read like a successful one.
    """

    company_id: str
    documents: int
    runs_written: int
    assertions_written: int
    existing_runs: int
    committed: bool
    verified: bool | None = None
    differences: tuple[str, ...] = ()
    failed_parse: int = 0
    failed_analyze: int = 0
    notes: tuple[str, ...] = ()

    @property
    def is_noop(self) -> bool:
        """Whether this migration had nothing to add.

        A re-run over an unchanged repository writes the same rows it wrote
        last time -- the ids are content addresses -- so "nothing changed" is
        the expected second answer, not a failure.
        """
        return self.existing_runs > 0 and self.runs_written == self.existing_runs


def migrate_assertions(
    root: Path,
    company_id: str,
    *,
    dry_run: bool = False,
    on_error: Callable[[str], None] | None = None,
) -> MigrationReport:
    """Backfill *root*'s assertion store from its acquired evidence.

    Builds the whole store in a temporary file beside the real one and moves it
    into place only if every stage completed. With ``dry_run=True`` the
    temporary file is built and then discarded, so the counts are real work
    rather than an estimate -- an estimate is the thing an operator cannot act
    on, because the failure it needs to know about is the one that only shows
    up when the analyzers actually run.

    Re-running is safe. The temporary store is built from scratch every time,
    so a second run over unchanged evidence produces the same content
    addresses and replaces the file with an equivalent one.
    """
    from atlas.assertions.writer import write_result
    from atlas.provenance import current_fingerprint

    target = root / DB_FILENAME
    existing_runs = _existing_runs(root)
    report = load_results(root, source="analyzers", on_error=on_error)
    fingerprint = current_fingerprint()

    # A directory, because AssertionStore owns the filename inside one, and
    # inside the repository so os.replace() below stays on a single
    # filesystem. A cross-filesystem move is a copy plus a delete, which
    # reintroduces the half-written store this design exists to prevent.
    root.mkdir(parents=True, exist_ok=True)
    staged_root = Path(tempfile.mkdtemp(prefix=".assertions-migrate-", dir=root))

    keep_staging = False
    try:
        store = AssertionStore(staged_root)
        runs = assertions = 0
        for result in report.results:
            write_result(store, result, fingerprint=fingerprint)
            runs += 1
            assertions += len(result.facts)

        verified, differences = _verify(staged_root, root, company_id)

        if dry_run:
            return MigrationReport(
                company_id=company_id,
                documents=len(report.results),
                runs_written=runs,
                assertions_written=assertions,
                existing_runs=existing_runs,
                committed=False,
                verified=verified,
                differences=differences,
                failed_parse=report.failed_parse,
                failed_analyze=report.failed_analyze,
                notes=("dry run: nothing was written",),
            )

        if verified is False:
            keep_staging = True
            raise MigrationVerificationError(
                f"the profile built from the migrated store differs from "
                f"{company_id}'s stored profile in {len(differences)} place(s); "
                f"the store was left unchanged and the staged store kept at "
                f"{staged_root}",
                staged_root=staged_root,
                differences=differences,
            )

        os.replace(store.path, target)
        return MigrationReport(
            company_id=company_id,
            documents=len(report.results),
            runs_written=runs,
            assertions_written=assertions,
            existing_runs=existing_runs,
            committed=True,
            verified=verified,
            differences=differences,
            failed_parse=report.failed_parse,
            failed_analyze=report.failed_analyze,
        )
    finally:
        # Reached on the dry-run return, on an exception, and after a
        # successful move (where the database file is already gone). Leaving a
        # stray .assertions-migrate-*/ in a company repository would hold
        # something shaped exactly like a store that nothing reads.
        #
        # The exception is a verification failure, which is the one case where
        # the staged store is the evidence: it is what the operator diffs
        # against the live one to find out which document moved. Deleting it
        # would leave them with a refusal and nothing to act on.
        if not keep_staging:
            shutil.rmtree(staged_root, ignore_errors=True)


def _verify(
    staged_root: Path, root: Path, company_id: str
) -> tuple[bool | None, tuple[str, ...]]:
    """Whether a profile built from the staged store matches the stored one.

    ``None`` when there is no stored profile to compare against, which is a
    first build rather than a passing check -- the same distinction
    ``RebuildResult.changed`` draws, and for the same reason: "it matches" and
    "there was nothing to match" must not read alike.

    The comparison is ``rebuild.profiles_match``, the canonical one from #31.
    Not a fresh equality test: that helper already strips the wall-clock
    fields (``built_at``, ``analyzed_at``, ``created_at``) that differ between
    any two builds by construction, and a second implementation would drift
    from the one the rebuild gate uses -- leaving migration and rebuild
    disagreeing about whether a profile moved.

    The candidate goes through ``CompanyStore.save`` into the staging
    directory rather than through the private serialiser, so what is compared
    is what a later ``atlas rebuild`` would actually write.
    """
    from atlas.company.builder import build_profile
    from atlas.company.store import CompanyStore, load_profile_payload
    from atlas.rebuild import PROFILE_FILENAME, explain_difference, profiles_match

    stored_path = root / PROFILE_FILENAME
    if not stored_path.exists():
        return None, ()

    from atlas.assertions.reader import results_for

    results = results_for(staged_root)
    candidate_path = staged_root / PROFILE_FILENAME
    CompanyStore(candidate_path, company_id).save(
        build_profile(company_id, results), results
    )

    stored = load_profile_payload(stored_path)
    candidate = load_profile_payload(candidate_path)
    if profiles_match(stored, candidate):
        return True, ()
    return False, tuple(explain_difference(stored, candidate))


def _existing_runs(root: Path) -> int:
    """How many runs the live store already holds, or 0 if there is none.

    Opening ``AssertionStore`` would create the database as a side effect,
    which would turn "this repository has no store" into "this repository has
    an empty store" -- and a dry run must not change the thing it is
    inspecting.
    """
    if not (root / DB_FILENAME).exists():
        return 0
    return AssertionStore(root).stats().runs
