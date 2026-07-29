"""The migration runner: what it applies, what it skips, what it refuses.

The runner exists because the alternative already in the repository
(``knowledge/base.py``) cannot tell a migration that was already applied from
one that failed. So the tests that matter are the ones about that
distinction:

Applied once  -- a re-open must not re-run work that is already on disk, and
                 must not report an error for having nothing to do.
Failure raises -- a broken migration must stop the open, not be swallowed
                 into a database that then looks migrated.
Atomic        -- a failed migration must leave neither its schema changes nor
                 its version bump behind, or the next open trusts a version
                 number that describes a schema that is not there.

The schema tests below are of the same kind. Columns are asserted against a
list written out by hand, not derived from the DDL, because a check derived
from the thing it checks agrees with every rename. And the key constraints
are exercised with real inserts, since a primary key that fails to reject a
duplicate loses a fact with no error at any layer above it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.assertions.model import Assertion, AssertionRun, RunStatus, ValueType
from atlas.assertions.store import (
    MIGRATIONS,
    STORE_VERSION,
    AssertionStore,
    Migration,
    MigrationError,
    apply_migrations,
    schema_version,
)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """An on-disk database, so version and schema survive a reconnect."""
    connection = sqlite3.connect(str(tmp_path / "assertions.db"))
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open, commit on clean exit, always close.

    Bare ``with sqlite3.connect(...)`` commits but never closes, which leaves
    a file handle open on Windows and the next assertion reading a database
    another connection still holds.
    """
    connection = sqlite3.connect(str(path))
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _create_widgets(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE widgets (id TEXT PRIMARY KEY)")


def _add_widget_colour(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE widgets ADD COLUMN colour TEXT")


def _broken(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE nonsense (")


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row[0] for row in rows}


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


# ---------------------------------------------------------------------------
# Fresh create
# ---------------------------------------------------------------------------


def test_fresh_database_starts_at_version_zero(conn: sqlite3.Connection) -> None:
    assert schema_version(conn) == 0


def test_applies_every_migration_to_a_fresh_database(
    conn: sqlite3.Connection,
) -> None:
    version = apply_migrations(conn, [_create_widgets, _add_widget_colour])

    assert version == 2
    assert schema_version(conn) == 2
    assert "widgets" in _table_names(conn)
    assert _column_names(conn, "widgets") == {"id", "colour"}


def test_empty_migration_list_leaves_version_zero(conn: sqlite3.Connection) -> None:
    assert apply_migrations(conn, []) == 0
    assert schema_version(conn) == 0


def test_registry_default_is_applied_when_no_list_is_given(
    conn: sqlite3.Connection,
) -> None:
    """The module-level registry is the default, not a separate code path."""
    assert apply_migrations(conn) == len(MIGRATIONS)
    assert schema_version(conn) == len(MIGRATIONS)


# ---------------------------------------------------------------------------
# Idempotent re-run
# ---------------------------------------------------------------------------


def test_second_run_applies_nothing(conn: sqlite3.Connection) -> None:
    calls: list[str] = []

    def recording(connection: sqlite3.Connection) -> None:
        calls.append("ran")
        _create_widgets(connection)

    migrations: list[Migration] = [recording]

    assert apply_migrations(conn, migrations) == 1
    assert apply_migrations(conn, migrations) == 1
    assert calls == ["ran"]


def test_reopened_database_applies_nothing(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Version is read from the file, not from process state."""
    apply_migrations(conn, [_create_widgets])
    conn.close()

    reopened = sqlite3.connect(str(tmp_path / "assertions.db"))
    try:
        assert schema_version(reopened) == 1
        # Re-running the same migration would raise "table widgets already
        # exists"; that it does not is the proof it was skipped.
        assert apply_migrations(reopened, [_create_widgets]) == 1
    finally:
        reopened.close()


def test_appended_migration_applies_only_the_new_one(
    conn: sqlite3.Connection,
) -> None:
    """Extending the registry must not re-run history.

    This is the property that lets M2 add ``entity_mentions`` by appending one
    function, without touching anything that shipped before it.
    """
    apply_migrations(conn, [_create_widgets])

    assert apply_migrations(conn, [_create_widgets, _add_widget_colour]) == 2
    assert _column_names(conn, "widgets") == {"id", "colour"}


# ---------------------------------------------------------------------------
# Failure raises
# ---------------------------------------------------------------------------


def test_failing_migration_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(MigrationError) as excinfo:
        apply_migrations(conn, [_broken])

    assert "migration 1 failed" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, sqlite3.Error)


def test_failing_migration_leaves_version_unchanged(
    conn: sqlite3.Connection,
) -> None:
    apply_migrations(conn, [_create_widgets])

    with pytest.raises(MigrationError):
        apply_migrations(conn, [_create_widgets, _broken])

    assert schema_version(conn) == 1


def test_failed_migration_rolls_back_its_own_partial_work(
    conn: sqlite3.Connection,
) -> None:
    """A migration is one transaction: its statements land together or not."""

    def partial(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE first (id TEXT)")
        connection.execute("CREATE TABLE first (id TEXT)")  # duplicate

    with pytest.raises(MigrationError):
        apply_migrations(conn, [partial])

    assert "first" not in _table_names(conn)
    assert schema_version(conn) == 0


def test_later_migrations_are_not_attempted_after_a_failure(
    conn: sqlite3.Connection,
) -> None:
    calls: list[str] = []

    def never_runs(connection: sqlite3.Connection) -> None:
        calls.append("ran")

    with pytest.raises(MigrationError):
        apply_migrations(conn, [_broken, never_runs])

    assert calls == []


def test_non_sqlite_failure_propagates_unchanged(conn: sqlite3.Connection) -> None:
    """A bug in a migration body is not a migration error; it is a bug."""

    def raises_value_error(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE half (id TEXT)")
        raise ValueError("computed a bad column name")

    with pytest.raises(ValueError, match="bad column name"):
        apply_migrations(conn, [raises_value_error])

    assert "half" not in _table_names(conn)
    assert schema_version(conn) == 0


def test_database_from_a_newer_build_refuses_to_open(
    conn: sqlite3.Connection,
) -> None:
    """Downgrade is a refusal, not a best effort.

    A database at a version this build has never seen has a schema this build
    cannot describe. Running the migrations it does know would write against
    assumptions that no longer hold.
    """
    apply_migrations(conn, [_create_widgets, _add_widget_colour])

    with pytest.raises(MigrationError) as excinfo:
        apply_migrations(conn, [_create_widgets])

    assert "newer Atlas" in str(excinfo.value)
    assert schema_version(conn) == 2


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------


def test_autocommit_mode_is_restored(conn: sqlite3.Connection) -> None:
    """The runner borrows the connection; it does not keep the settings."""
    before = conn.autocommit

    apply_migrations(conn, [_create_widgets])

    assert conn.autocommit == before


def test_autocommit_mode_is_restored_after_a_failure(
    conn: sqlite3.Connection,
) -> None:
    before = conn.autocommit

    with pytest.raises(MigrationError):
        apply_migrations(conn, [_broken])

    assert conn.autocommit == before


# ---------------------------------------------------------------------------
# Schema and open/create
# ---------------------------------------------------------------------------

#: The columns the writer, reader and every later migration are written
#: against. Spelled out here rather than derived from the DDL so that a
#: rename or a dropped column fails this test instead of silently agreeing
#: with itself.
_ASSERTION_COLUMNS = (
    "assertion_id",
    "evidence_id",
    "kind",
    "value",
    "value_type",
    "unit",
    "period",
    "confidence",
    "section",
    "char_offset",
    "ordinal",
    "excerpt",
    "analyzer_version",
    "fingerprint",
    "created_at",
)

_RUN_COLUMNS = (
    "evidence_id",
    "kind",
    "analyzer_version",
    "fingerprint",
    "result_confidence",
    "source_date",
    "analyzed_at",
    "warnings_json",
    "status",
    "error",
)

_NOT_NULL_ASSERTION_COLUMNS = frozenset(
    {
        "evidence_id",
        "kind",
        "value_type",
        "confidence",
        "section",
        "ordinal",
        "analyzer_version",
        "fingerprint",
        "created_at",
    }
)


def _insert_assertion(
    connection: sqlite3.Connection,
    *,
    assertion_id: str | None,
    ordinal: int | None = 0,
) -> None:
    """Insert a minimal row, naming columns so order changes cannot hide."""
    connection.execute(
        "INSERT INTO assertions "
        "(assertion_id, evidence_id, kind, value, value_type, confidence, "
        " section, ordinal, analyzer_version, fingerprint, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            assertion_id,
            "ev-1",
            "risk_factor",
            "x",
            "str",
            "high",
            "mda_risk",
            ordinal,
            "1.0",
            "fp",
            "2026-01-01T00:00:00",
        ),
    )


def _insert_run(
    connection: sqlite3.Connection,
    *,
    kind: str | None = "annual_report",
    analyzer_version: str = "1.0",
) -> None:
    connection.execute(
        "INSERT INTO assertion_runs "
        "(evidence_id, kind, analyzer_version, fingerprint, result_confidence, "
        " source_date, analyzed_at, warnings_json, status, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "ev-1",
            kind,
            analyzer_version,
            "fp",
            "high",
            "2026-01-01",
            "2026-01-02",
            "[]",
            "ok",
            None,
        ),
    )


def _ordered_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return tuple(row[1] for row in rows)


def test_opening_creates_the_database_file(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    assert store.path == tmp_path / "assertions.db"
    assert store.path.exists()
    assert store.root == tmp_path


def test_opening_creates_a_missing_repository_root(tmp_path: Path) -> None:
    root = tmp_path / "companies" / "TCS"

    store = AssertionStore(root)

    assert store.path.exists()


def test_store_is_a_separate_file_from_the_knowledge_database(
    tmp_path: Path,
) -> None:
    """Different rebuild triggers; either must be discardable alone."""
    store = AssertionStore(tmp_path)

    assert store.path.name != "knowledge.db"


def test_new_store_is_at_the_current_schema_version(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    assert store.schema_version() == STORE_VERSION
    assert STORE_VERSION == len(MIGRATIONS)


def test_schema_has_both_tables_and_both_indices(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    with _connect(store.path) as connection:
        tables = _table_names(connection)
        index_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()

    assert {"assertions", "assertion_runs"} <= tables
    assert {"idx_assertions_evidence", "idx_assertions_kind"} <= {
        row[0] for row in index_rows
    }


def test_assertion_columns_match_the_specified_schema(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    with _connect(store.path) as connection:
        assert _ordered_columns(connection, "assertions") == _ASSERTION_COLUMNS
        assert _ordered_columns(connection, "assertion_runs") == _RUN_COLUMNS


def test_nullable_columns_are_exactly_the_optional_ones(tmp_path: Path) -> None:
    """``value``, ``unit``, ``period``, ``char_offset``, ``excerpt`` may be
    absent; a fact legitimately has no unit or no offset. Nothing else may."""
    store = AssertionStore(tmp_path)

    with _connect(store.path) as connection:
        rows = connection.execute("PRAGMA table_info(assertions)").fetchall()

    not_null = {row[1] for row in rows if row[3]}
    assert not_null == _NOT_NULL_ASSERTION_COLUMNS | {"assertion_id"}


def test_null_assertion_id_is_rejected(tmp_path: Path) -> None:
    """SQLite lets a non-INTEGER primary key hold NULL, and hold it twice.

    So the constraint has to be spelled out. Without it, an id that failed to
    compute produces rows no lookup ever returns.
    """
    store = AssertionStore(tmp_path)

    with _connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_assertion(connection, assertion_id=None)


def test_duplicate_assertion_id_raises(tmp_path: Path) -> None:
    """A conflicting id must raise, never replace.

    ``INSERT OR REPLACE`` here would let a second fact overwrite a first with
    no error at any layer, which is the exact silent-loss failure the content
    addressing exists to make impossible.
    """
    store = AssertionStore(tmp_path)

    with _connect(store.path) as connection:
        _insert_assertion(connection, assertion_id="a1")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_assertion(connection, assertion_id="a1")


def test_assertion_ordinal_is_required(tmp_path: Path) -> None:
    """Emission order is an input to the id and survives nowhere else."""
    store = AssertionStore(tmp_path)

    with _connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_assertion(connection, assertion_id="a1", ordinal=None)


def test_run_kind_is_required(tmp_path: Path) -> None:
    """AnalysisResult cannot be rebuilt without the document's kind."""
    store = AssertionStore(tmp_path)

    with _connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_run(connection, kind=None)


def test_run_key_is_evidence_and_analyzer_version(tmp_path: Path) -> None:
    """Two versions of one document coexist; the same version twice does not."""
    store = AssertionStore(tmp_path)

    with _connect(store.path) as connection:
        _insert_run(connection, analyzer_version="1.0")
        _insert_run(connection, analyzer_version="2.0")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_run(connection, analyzer_version="1.0")


def test_reopening_preserves_rows_and_version(tmp_path: Path) -> None:
    """The second open migrates nothing and destroys nothing."""
    store = AssertionStore(tmp_path)
    with _connect(store.path) as connection:
        _insert_run(connection)

    reopened = AssertionStore(tmp_path)

    assert reopened.schema_version() == STORE_VERSION
    with _connect(reopened.path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM assertion_runs").fetchone()
    assert count[0] == 1


def test_opening_a_database_from_a_newer_build_raises(tmp_path: Path) -> None:
    path = tmp_path / "assertions.db"
    with _connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {STORE_VERSION + 1}")

    with pytest.raises(MigrationError):
        AssertionStore(tmp_path)


# ---------------------------------------------------------------------------
# write_run / read_run
# ---------------------------------------------------------------------------

_EVIDENCE = "ev-2024-ar"
_VERSION = "1.0"
_FINGERPRINT = "fp-abc"


def _assertion(
    *,
    assertion_id: str = "a1",
    value: str | None = "Cyber security risk",
    value_type: ValueType = "str",
    unit: str | None = None,
    period: str | None = "2024-03-31",
    char_offset: int | None = 100,
    excerpt: str | None = "the excerpt",
    ordinal: int = 0,
    evidence_id: str = _EVIDENCE,
    analyzer_version: str = _VERSION,
) -> Assertion:
    return Assertion(
        assertion_id=assertion_id,
        evidence_id=evidence_id,
        kind="risk_factor",
        value=value,
        value_type=value_type,
        unit=unit,
        period=period,
        confidence="high",
        section="mda_risk",
        char_offset=char_offset,
        excerpt=excerpt,
        analyzer_version=analyzer_version,
        fingerprint=_FINGERPRINT,
        ordinal=ordinal,
    )


def _run(
    *,
    analyzer_version: str = _VERSION,
    status: RunStatus = "ok",
    error: str | None = None,
    warnings: tuple[str, ...] = ("page 3 unreadable",),
) -> AssertionRun:
    return AssertionRun(
        evidence_id=_EVIDENCE,
        kind="annual_report",
        analyzer_version=analyzer_version,
        fingerprint=_FINGERPRINT,
        result_confidence="high",
        source_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        analyzed_at=datetime(2026, 7, 29, 10, 30, tzinfo=timezone.utc),
        warnings=warnings,
        status=status,
        error=error,
    )


def _row_counts(store: AssertionStore) -> tuple[int, int]:
    with _connect(store.path) as connection:
        runs = connection.execute("SELECT COUNT(*) FROM assertion_runs").fetchone()
        facts = connection.execute("SELECT COUNT(*) FROM assertions").fetchone()
    return runs[0], facts[0]


def test_round_trip_returns_what_was_written(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    run = _run()
    written = (_assertion(assertion_id="a1"), _assertion(assertion_id="a2", ordinal=1))

    store.write_run(run, written)
    stored = store.read_run(_EVIDENCE, _VERSION)

    assert stored is not None
    assert stored.run == run
    assert stored.assertions == written


def test_round_trip_preserves_nulls_and_ordinal(tmp_path: Path) -> None:
    """Every nullable column, and the one column no other layer can rebuild."""
    store = AssertionStore(tmp_path)
    sparse = _assertion(
        value=None,
        value_type="null",
        unit=None,
        period=None,
        char_offset=None,
        excerpt=None,
        ordinal=7,
    )

    store.write_run(_run(), [sparse])
    stored = store.read_run(_EVIDENCE, _VERSION)

    assert stored is not None
    assert stored.assertions == (sparse,)


def test_unknown_run_reads_as_none(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    assert store.read_run(_EVIDENCE, _VERSION) is None


def test_failed_run_is_recorded_with_no_assertions(tmp_path: Path) -> None:
    """Tried and failed is not the same state as never tried."""
    store = AssertionStore(tmp_path)
    failed = _run(status="failed", error="pdfminer raised", warnings=())

    store.write_run(failed, [])
    stored = store.read_run(_EVIDENCE, _VERSION)

    assert stored is not None
    assert stored.run.status == "failed"
    assert stored.run.error == "pdfminer raised"
    assert stored.assertions == ()


def test_rewriting_the_same_run_adds_no_rows(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    assertions = [_assertion()]

    store.write_run(_run(), assertions)
    store.write_run(_run(), assertions)

    assert _row_counts(store) == (1, 1)


def test_rewriting_replaces_the_previous_assertions(tmp_path: Path) -> None:
    """Re-running a fixed analyzer must not leave its old output behind."""
    store = AssertionStore(tmp_path)
    store.write_run(_run(), [_assertion(assertion_id="stale")])

    store.write_run(_run(), [_assertion(assertion_id="fresh")])

    stored = store.read_run(_EVIDENCE, _VERSION)
    assert stored is not None
    assert [item.assertion_id for item in stored.assertions] == ["fresh"]


def test_bumped_version_keeps_the_older_rows(tmp_path: Path) -> None:
    """The PK admits several versions per document; a write must not prune."""
    store = AssertionStore(tmp_path)
    store.write_run(_run(), [_assertion(assertion_id="old")])

    store.write_run(
        _run(analyzer_version="2.0"),
        [_assertion(assertion_id="new", analyzer_version="2.0")],
    )

    first = store.read_run(_EVIDENCE, "1.0")
    second = store.read_run(_EVIDENCE, "2.0")
    assert first is not None and second is not None
    assert [item.assertion_id for item in first.assertions] == ["old"]
    assert [item.assertion_id for item in second.assertions] == ["new"]


def test_assertions_come_back_in_a_fixed_order(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    store.write_run(
        _run(),
        [
            _assertion(assertion_id="c", ordinal=0),
            _assertion(assertion_id="a", ordinal=1),
            _assertion(assertion_id="b", ordinal=2),
        ],
    )

    stored = store.read_run(_EVIDENCE, _VERSION)

    assert stored is not None
    assert [item.assertion_id for item in stored.assertions] == ["a", "b", "c"]


def test_duplicate_id_within_one_write_writes_nothing(tmp_path: Path) -> None:
    """The whole run is one transaction, including the run row itself."""
    store = AssertionStore(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        store.write_run(_run(), [_assertion(), _assertion()])

    assert _row_counts(store) == (0, 0)
    assert store.read_run(_EVIDENCE, _VERSION) is None


def test_a_failed_rewrite_leaves_the_previous_run_intact(tmp_path: Path) -> None:
    """Rollback restores the rows the rewrite had already deleted."""
    store = AssertionStore(tmp_path)
    store.write_run(_run(), [_assertion(assertion_id="original")])

    with pytest.raises(sqlite3.IntegrityError):
        store.write_run(_run(), [_assertion(assertion_id="dup")] * 2)

    stored = store.read_run(_EVIDENCE, _VERSION)
    assert stored is not None
    assert [item.assertion_id for item in stored.assertions] == ["original"]


def test_assertion_from_another_run_is_refused(tmp_path: Path) -> None:
    """Such a row is unreachable: no read returns it, no rewrite explains it."""
    store = AssertionStore(tmp_path)

    with pytest.raises(ValueError, match="belongs to"):
        store.write_run(_run(), [_assertion(evidence_id="ev-other")])

    assert _row_counts(store) == (0, 0)


def test_assertion_from_another_version_is_refused(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    with pytest.raises(ValueError, match="belongs to"):
        store.write_run(_run(), [_assertion(analyzer_version="9.9")])

    assert _row_counts(store) == (0, 0)
