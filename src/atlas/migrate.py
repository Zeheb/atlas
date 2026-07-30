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

What this module does not do
----------------------------
It does not compare the resulting profile against the stored one. Gating the
move on that comparison is #55, the next commit; until it lands, a caller who
wants that check runs ``atlas rebuild --verify`` after migrating.
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
    """

    company_id: str
    documents: int
    runs_written: int
    assertions_written: int
    existing_runs: int
    committed: bool
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

    try:
        store = AssertionStore(staged_root)
        runs = assertions = 0
        for result in report.results:
            write_result(store, result, fingerprint=fingerprint)
            runs += 1
            assertions += len(result.facts)

        if dry_run:
            return MigrationReport(
                company_id=company_id,
                documents=len(report.results),
                runs_written=runs,
                assertions_written=assertions,
                existing_runs=existing_runs,
                committed=False,
                failed_parse=report.failed_parse,
                failed_analyze=report.failed_analyze,
                notes=("dry run: nothing was written",),
            )

        os.replace(store.path, target)
        return MigrationReport(
            company_id=company_id,
            documents=len(report.results),
            runs_written=runs,
            assertions_written=assertions,
            existing_runs=existing_runs,
            committed=True,
            failed_parse=report.failed_parse,
            failed_analyze=report.failed_analyze,
        )
    finally:
        # Reached on the dry-run return, on an exception, and after a
        # successful move (where the database file is already gone). Leaving a
        # stray .assertions-migrate-*/ in a company repository would hold
        # something shaped exactly like a store that nothing reads.
        shutil.rmtree(staged_root, ignore_errors=True)


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
