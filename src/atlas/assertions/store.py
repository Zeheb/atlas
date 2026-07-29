"""The assertion store: its schema, its migrations, and one run at a time.

The store's schema will churn. M2 adds ``entity_mentions``, later milestones
add columns and indices, and every one of those changes has to land on
databases that already exist in a company repository without destroying what
is in them. That requires knowing which changes a given database has already
seen, which is what ``PRAGMA user_version`` records.

Why not the pattern already in the repository
---------------------------------------------
``knowledge/base.py`` runs every ``ALTER`` unconditionally inside
``try: ... except sqlite3.OperationalError: pass`` (``base.py:180-186``). It
works for what it does today, and it is left alone. It is not extended here
for three reasons:

* it has no version marker, so "already applied" and "failed for a real
  reason" are the same observation -- a typo in the SQL, a read-only file, a
  full disk all look exactly like success;
* it can only express ``ADD COLUMN``, because that is the one statement whose
  failure is safely ignorable. Renames, backfills and index changes are not;
* every migration re-runs on every open, so cost grows with schema history.

Here a failure raises. A store that cannot migrate is a store that must not
be written to, and the loudest possible failure is the cheapest one.

Shape of a migration
--------------------
A migration is a callable taking an open connection and issuing statements
against it. ``MIGRATIONS`` is an append-only tuple: its index (1-based) is
the ``user_version`` a database has once that migration has been applied.
Adding a schema change means appending one function. Existing entries are
never edited, never reordered, never removed -- a database in the wild has
already run them, and changing one silently gives two databases the same
version number with different schemas.

Atomicity
---------
Each migration runs in its own transaction together with its version bump,
so the two cannot disagree. SQLite makes DDL transactional and rolls back a
``PRAGMA user_version`` write with everything else, so an interrupted or
failing migration leaves the database at the version it had before -- never
half-migrated at a version claiming otherwise.

The schema itself
-----------------
``assertions`` holds one row per fact, keyed by its content address, with
``value`` and ``value_type`` as separate columns so ``5``, ``5.0`` and
``"5"`` survive the round trip as three different things.

``assertion_runs`` holds everything on the ``AnalysisResult`` envelope that
is not a fact -- result-level confidence, warnings, source date, status --
which is what lets a reader reconstruct a faithful result later without
re-reading the document. Its key is ``(evidence_id, analyzer_version)``, so
several analyzer versions of one document coexist; choosing between them is
a read-time rule, not a write-time deletion.

The unit of work
----------------
One analyzer run over one document, written whole. ``write_run`` puts the
envelope and every fact in a single transaction, because a run row without
its facts is not a visible error -- it reads as a document that was analyzed
and yielded little, which is exactly what a document that genuinely yielded
little also reads as.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from atlas.assertions.model import Assertion, AssertionRun

#: A schema change: statements issued against an open connection. It must not
#: commit, roll back, or touch ``user_version`` -- the runner owns both.
Migration = Callable[[sqlite3.Connection], None]

#: Filename inside a company repository, beside ``knowledge.db``. Separate
#: file, not a second set of tables in the knowledge DB: the two layers are
#: rebuilt on different triggers -- re-parsing a document versus re-running an
#: analyzer -- and either must be discardable without disturbing the other.
DB_FILENAME = "assertions.db"

#: Statement per entry, deliberately not one ``executescript`` blob:
#: ``executescript`` commits any pending transaction before it runs, which
#: would take the schema outside the transaction holding its version bump.
_CREATE_TABLES: tuple[str, ...] = (
    """
    CREATE TABLE assertions (
        -- NOT NULL is not redundant beside PRIMARY KEY: SQLite permits NULLs
        -- in a non-INTEGER primary key, and permits several of them, so
        -- without it a content address that failed to compute becomes rows
        -- that collide with nothing and are found by nothing.
        assertion_id     TEXT PRIMARY KEY NOT NULL,
        evidence_id      TEXT NOT NULL,
        kind             TEXT NOT NULL,
        value            TEXT,
        value_type       TEXT NOT NULL,
        unit             TEXT,
        period           TEXT,
        confidence       TEXT NOT NULL,
        section          TEXT NOT NULL,
        char_offset      INTEGER,
        -- An input to assertion_id, and recoverable from nothing else: it is
        -- the fact's position in analyzer emission order, which stored rows
        -- do not preserve. Unstored, a row read back could never have its own
        -- id re-derived without re-running the analyzer -- the one thing the
        -- store exists to make unnecessary.
        ordinal          INTEGER NOT NULL,
        excerpt          TEXT,
        analyzer_version TEXT NOT NULL,
        fingerprint      TEXT NOT NULL,
        created_at       TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_assertions_evidence ON assertions(evidence_id)",
    "CREATE INDEX idx_assertions_kind ON assertions(kind, period)",
    """
    CREATE TABLE assertion_runs (
        evidence_id       TEXT NOT NULL,
        -- EvidenceKind of the document, required to rebuild AnalysisResult
        -- and held nowhere else in this database. Reading it out of
        -- knowledge.db instead would make a store that is supposed to be
        -- independently rebuildable depend on a second file.
        kind              TEXT NOT NULL,
        analyzer_version  TEXT NOT NULL,
        fingerprint       TEXT NOT NULL,
        result_confidence TEXT NOT NULL,
        source_date       TEXT NOT NULL,
        analyzed_at       TEXT NOT NULL,
        warnings_json     TEXT NOT NULL,
        status            TEXT NOT NULL,
        error             TEXT,
        PRIMARY KEY (evidence_id, analyzer_version)
    )
    """,
)


def _migration_001_initial_schema(conn: sqlite3.Connection) -> None:
    """Create ``assertions`` and ``assertion_runs`` with their indices.

    No ``IF NOT EXISTS``. The runner guarantees this body runs once per
    database; if it ever runs against a database that already has the tables,
    that is a broken version marker and the resulting error is the report.
    """
    for statement in _CREATE_TABLES:
        conn.execute(statement)


#: Append-only. Index + 1 is the ``user_version`` implied by that migration.
#: Never edit, reorder or delete an entry; databases in the wild have run it.
MIGRATIONS: tuple[Migration, ...] = (_migration_001_initial_schema,)

#: Derived, never hand-maintained: the schema version a current build writes.
#: ``knowledge/base.py`` keeps a literal ``PARSER_VERSION`` next to its
#: migration list, which is two things to update and one to forget.
STORE_VERSION = len(MIGRATIONS)


class MigrationError(RuntimeError):
    """A migration could not be applied, or the database is unusable.

    Named rather than a bare ``Exception`` so a caller can distinguish "this
    store cannot be opened" from any other failure and refuse to write,
    instead of proceeding against a schema it has not verified.
    """


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the number of migrations *conn*'s database has applied.

    Zero for a database no migration has touched, which is also what an
    empty file reports -- a fresh database and an unmigrated one are the
    same starting point by construction.
    """
    row = conn.execute("PRAGMA user_version").fetchone()
    version: int = row[0]
    return version


def apply_migrations(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> int:
    """Bring *conn*'s database up to date and return its schema version.

    Applies only the migrations the database has not yet seen, in order, and
    returns the resulting version. Re-running against an up-to-date database
    applies nothing and is not an error: that is the normal case on every
    open after the first.

    Raises:
        MigrationError: if a migration fails, or if the database was written
            by a build with more migrations than this one has. The second
            case is a downgrade -- the schema on disk is one this code has
            never seen, and guessing at it is how data gets lost.
    """
    current = schema_version(conn)
    if current > len(migrations):
        raise MigrationError(
            f"database is at schema version {current} but this build knows "
            f"only {len(migrations)}; it was written by a newer Atlas"
        )

    previous_autocommit = conn.autocommit
    # PEP 249 mode: one transaction per migration, closed explicitly below.
    conn.autocommit = False
    try:
        for version, migration in enumerate(migrations[current:], start=current + 1):
            _apply_one(conn, migration, version)
    finally:
        conn.autocommit = previous_autocommit

    return len(migrations)


def _apply_one(conn: sqlite3.Connection, migration: Migration, version: int) -> None:
    """Apply one migration and its version bump as a single transaction.

    Only ``sqlite3.Error`` is caught and translated; a migration body is
    ordinary Python and may fail in ordinary ways, and those failures are the
    caller's to see unchanged. The rollback lives in ``finally`` so it covers
    both -- an open transaction that outlived its migration would otherwise
    hand a partial schema to whatever ran next on this connection.
    """
    try:
        migration(conn)
        # Not parameterizable: SQLite pragmas take literals only. The value is
        # a loop counter over MIGRATIONS, never external input.
        conn.execute(f"PRAGMA user_version = {version:d}")
        conn.commit()
    except sqlite3.Error as exc:
        raise MigrationError(
            f"migration {version} failed; database left at version {version - 1}"
        ) from exc
    finally:
        if conn.in_transaction:
            conn.rollback()


_INSERT_RUN = (
    "INSERT INTO assertion_runs "
    "(evidence_id, kind, analyzer_version, fingerprint, result_confidence, "
    " source_date, analyzed_at, warnings_json, status, error) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

_INSERT_ASSERTION = (
    "INSERT INTO assertions "
    "(assertion_id, evidence_id, kind, value, value_type, unit, period, "
    " confidence, section, char_offset, ordinal, excerpt, analyzer_version, "
    " fingerprint, created_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


@dataclass(frozen=True)
class StoredRun:
    """One run as it came back off disk: the envelope and its facts."""

    run: AssertionRun
    assertions: tuple[Assertion, ...]


def _run_row(run: AssertionRun) -> tuple[object, ...]:
    return (
        run.evidence_id,
        run.kind,
        run.analyzer_version,
        run.fingerprint,
        run.result_confidence,
        run.source_date.isoformat(),
        run.analyzed_at.isoformat(),
        json.dumps(list(run.warnings)),
        run.status,
        run.error,
    )


def _assertion_row(item: Assertion, created_at: str) -> tuple[object, ...]:
    return (
        item.assertion_id,
        item.evidence_id,
        item.kind,
        item.value,
        item.value_type,
        item.unit,
        item.period,
        item.confidence,
        item.section,
        item.char_offset,
        item.ordinal,
        item.excerpt,
        item.analyzer_version,
        item.fingerprint,
        created_at,
    )


def _row_to_run(row: sqlite3.Row) -> AssertionRun:
    return AssertionRun(
        evidence_id=row["evidence_id"],
        kind=row["kind"],
        analyzer_version=row["analyzer_version"],
        fingerprint=row["fingerprint"],
        result_confidence=row["result_confidence"],
        source_date=datetime.fromisoformat(row["source_date"]),
        analyzed_at=datetime.fromisoformat(row["analyzed_at"]),
        warnings=tuple(json.loads(row["warnings_json"])),
        status=row["status"],
        error=row["error"],
    )


def _row_to_assertion(row: sqlite3.Row) -> Assertion:
    return Assertion(
        assertion_id=row["assertion_id"],
        evidence_id=row["evidence_id"],
        kind=row["kind"],
        value=row["value"],
        value_type=row["value_type"],
        unit=row["unit"],
        period=row["period"],
        confidence=row["confidence"],
        section=row["section"],
        char_offset=row["char_offset"],
        excerpt=row["excerpt"],
        analyzer_version=row["analyzer_version"],
        fingerprint=row["fingerprint"],
        ordinal=row["ordinal"],
    )


def _reject_foreign_assertions(
    run: AssertionRun, assertions: Sequence[Assertion]
) -> None:
    """Refuse assertions that do not belong to *run*.

    A row whose ``(evidence_id, analyzer_version)`` differs from its run's is
    unreachable: ``read_run`` selects on that pair, and a later re-write of
    the run it claims to belong to deletes it. Storing it would be storing a
    fact that no read ever returns and no delete ever explains.
    """
    for item in assertions:
        if (
            item.evidence_id != run.evidence_id
            or item.analyzer_version != run.analyzer_version
        ):
            raise ValueError(
                f"assertion {item.assertion_id} belongs to "
                f"({item.evidence_id}, {item.analyzer_version}), not to run "
                f"({run.evidence_id}, {run.analyzer_version})"
            )


class AssertionStore:
    """The assertion database for one company repository.

    Opening is creating: a repository that has never been analyzed has no
    file, and the first open migrates one into existence. There is no
    separate "initialize the store" step to forget, and no state where the
    file exists at a version the code does not understand -- that is refused
    by the migration runner rather than papered over.

    The store is a rebuildable cache over Tier 0 evidence. Deleting the file
    loses nothing that cannot be regenerated by re-running the analyzers,
    which is why it is a separate file from ``knowledge.db``.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._db_path = root / DB_FILENAME
        self._init_db()

    @property
    def path(self) -> Path:
        """Location of the database file."""
        return self._db_path

    @property
    def root(self) -> Path:
        """Repository root the store belongs to."""
        return self._root

    def schema_version(self) -> int:
        """Return the schema version currently on disk."""
        with self._db_conn() as conn:
            return schema_version(conn)

    # ------------------------------------------------------------------
    # Reading and writing one analyzer run
    # ------------------------------------------------------------------

    def write_run(self, run: AssertionRun, assertions: Sequence[Assertion]) -> None:
        """Persist one analyzer pass over one document, atomically.

        The run row and its assertions land together or not at all. A partial
        write is the worst outcome available here: a run row with missing
        facts reads as a document that was analyzed and found little, which is
        indistinguishable from the truth at every layer above.

        Re-writing the same ``(evidence_id, analyzer_version)`` replaces it.
        That is what makes re-running an analyzer safe, and it is scoped to
        that pair, so a bumped version adds rows beside the old ones instead
        of destroying them. Note what this is *not*: within a single write the
        inserts are plain ``INSERT``, so two assertions sharing an id raise
        rather than one silently overwriting the other.
        """
        _reject_foreign_assertions(run, assertions)
        created_at = datetime.now(timezone.utc).isoformat()
        key = (run.evidence_id, run.analyzer_version)

        with self._db_conn() as conn:
            conn.execute(
                "DELETE FROM assertions "
                "WHERE evidence_id = ? AND analyzer_version = ?",
                key,
            )
            conn.execute(
                "DELETE FROM assertion_runs "
                "WHERE evidence_id = ? AND analyzer_version = ?",
                key,
            )
            conn.execute(_INSERT_RUN, _run_row(run))
            conn.executemany(
                _INSERT_ASSERTION,
                [_assertion_row(item, created_at) for item in assertions],
            )

    def read_run(self, evidence_id: str, analyzer_version: str) -> StoredRun | None:
        """Return the stored run and its assertions, or None if absent.

        None rather than an exception: "this document was never analyzed by
        this version" is an ordinary answer that callers act on by analyzing
        it. A run that was attempted and failed is *not* this case -- it comes
        back with ``status='failed'`` and no assertions, because retrying a
        known failure and retrying an untried document are different
        decisions.

        Assertions come back ordered by id, which is arbitrary but fixed. The
        source-order rule that reconstruction needs belongs to the reader, not
        here.
        """
        with self._db_conn() as conn:
            run_row = conn.execute(
                "SELECT * FROM assertion_runs "
                "WHERE evidence_id = ? AND analyzer_version = ?",
                (evidence_id, analyzer_version),
            ).fetchone()
            if run_row is None:
                return None
            assertion_rows = conn.execute(
                "SELECT * FROM assertions "
                "WHERE evidence_id = ? AND analyzer_version = ? "
                "ORDER BY assertion_id",
                (evidence_id, analyzer_version),
            ).fetchall()

        return StoredRun(
            run=_row_to_run(run_row),
            assertions=tuple(_row_to_assertion(row) for row in assertion_rows),
        )

    def runs_for(self, evidence_id: str) -> tuple[AssertionRun, ...]:
        """Return every stored run for *evidence_id*, envelopes only.

        Every version, including failed ones: choosing between them is the
        reader's rule, and a rule that cannot see the failed attempts would
        answer "nothing here" for a document that was tried and broke.
        """
        with self._db_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM assertion_runs WHERE evidence_id = ? "
                "ORDER BY analyzer_version",
                (evidence_id,),
            ).fetchall()
        return tuple(_row_to_run(row) for row in rows)

    def evidence_ids(self) -> tuple[str, ...]:
        """Return every evidence_id with a run, sorted."""
        with self._db_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT evidence_id FROM assertion_runs "
                "ORDER BY evidence_id"
            ).fetchall()
        return tuple(row[0] for row in rows)

    @contextmanager
    def _db_conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a connection whose work commits on a clean exit.

        Same shape as ``knowledge/base.py`` -- ``with conn`` commits or rolls
        back, ``finally`` closes -- so both stores behave identically at the
        connection level even though their migration mechanisms differ.
        """
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create the file if absent and bring its schema up to date.

        Migration failures propagate: a store whose schema could not be
        established must not be handed out, because every write against it
        would be a write against an unknown shape.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            apply_migrations(conn)
        finally:
            conn.close()
