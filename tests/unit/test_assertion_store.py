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
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from atlas.assertions.store import (
    MIGRATIONS,
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
