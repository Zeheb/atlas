"""Migration 3: ``assertion_runs.affects_digest``.

A migration is judged on what happens to a database that already exists, not
on what a fresh one looks like. So the tests that matter here build a genuine
version-2 database, put rows in it, migrate it, and check that every value
survived.

Two properties are load-bearing.

A migrated database and a fresh one must be indistinguishable. ``ADD COLUMN``
can only append, so if the fresh schema ever gains the column anywhere but
last, the two diverge and every ``SELECT *`` consumer starts reading
different shapes depending on the database's history.

NULL must mean unknown, and unknown must not be mistaken for current. Old
rows cannot be backfilled: the sub-digest would have to be recomputed from
the ontology, parser, shared-parser and analyzer versions in force when the
row was written, and the only surviving record of those is the whole digest
they were folded into. sha256 does not invert, so the honest value is NULL.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from atlas.assertions.store import (
    MIGRATIONS,
    STORE_VERSION,
    AssertionStore,
    apply_migrations,
    schema_version,
)

#: Everything before migration 3 — the schema a database in the wild has.
_V2_MIGRATIONS = MIGRATIONS[:2]

_RUN_VALUES = (
    "ev-1",
    "annual_report",
    "3.4",
    "whole-build-digest",
    "high",
    "2026-01-01",
    "2026-01-02",
    '["one warning"]',
    "ok",
    None,
)


def _v2_database(path: Path) -> None:
    """Create a database at exactly version 2, holding one run and one fact."""
    conn = sqlite3.connect(str(path))
    try:
        applied = apply_migrations(conn, _V2_MIGRATIONS)
        assert applied == 2
        conn.execute(
            "INSERT INTO assertion_runs "
            "(evidence_id, kind, analyzer_version, fingerprint, "
            " result_confidence, source_date, analyzed_at, warnings_json, "
            " status, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _RUN_VALUES,
        )
        conn.execute(
            "INSERT INTO assertions "
            "(assertion_id, evidence_id, kind, value, value_type, confidence, "
            " section, ordinal, analyzer_version, fingerprint, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "a1",
                "ev-1",
                "risk_factor",
                "Cyber risk",
                "str",
                "high",
                "mda_risk",
                0,
                "3.4",
                "whole-build-digest",
                "2026-01-01T00:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _columns(path: Path, table: str) -> tuple[str, ...]:
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    finally:
        conn.close()
    return tuple(row[1] for row in rows)


# ---------------------------------------------------------------------------
# The migration list itself
# ---------------------------------------------------------------------------


def test_there_are_now_three_migrations() -> None:
    assert len(MIGRATIONS) == 3
    assert STORE_VERSION == 3


def test_the_first_two_migrations_are_untouched() -> None:
    """Append-only. A database in the wild has already run these two."""
    assert MIGRATIONS[0].__name__ == "_migration_001_initial_schema"
    assert MIGRATIONS[1].__name__ == "_migration_002_entity_mentions"
    assert MIGRATIONS[2].__name__ == "_migration_003_affects_digest"


# ---------------------------------------------------------------------------
# A fresh database
# ---------------------------------------------------------------------------


def test_a_fresh_store_has_the_column(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    assert "affects_digest" in _columns(store.path, "assertion_runs")


def test_a_fresh_store_is_at_version_three(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    assert store.schema_version() == 3


def test_the_column_is_nullable(tmp_path: Path) -> None:
    """SQLite cannot ADD COLUMN NOT NULL without a default, and no honest
    default exists — an old row's sub-digest is unrecoverable."""
    store = AssertionStore(tmp_path)

    conn = sqlite3.connect(str(store.path))
    try:
        rows = conn.execute("PRAGMA table_info(assertion_runs)").fetchall()
    finally:
        conn.close()

    not_null = {row[1] for row in rows if row[3]}
    assert "affects_digest" not in not_null


# ---------------------------------------------------------------------------
# Upgrading a database that already exists
# ---------------------------------------------------------------------------


def test_a_version_two_database_upgrades_in_place(tmp_path: Path) -> None:
    path = tmp_path / "assertions.db"
    _v2_database(path)

    conn = sqlite3.connect(str(path))
    try:
        assert schema_version(conn) == 2
        assert apply_migrations(conn) == 3
        assert schema_version(conn) == 3
    finally:
        conn.close()


def test_upgrading_preserves_every_stored_run_value(tmp_path: Path) -> None:
    """The failure that would matter: a migration that loses a column."""
    path = tmp_path / "assertions.db"
    _v2_database(path)

    conn = sqlite3.connect(str(path))
    try:
        apply_migrations(conn)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM assertion_runs").fetchone()
    finally:
        conn.close()

    assert row["evidence_id"] == "ev-1"
    assert row["kind"] == "annual_report"
    assert row["analyzer_version"] == "3.4"
    assert row["fingerprint"] == "whole-build-digest"
    assert row["result_confidence"] == "high"
    assert row["source_date"] == "2026-01-01"
    assert row["analyzed_at"] == "2026-01-02"
    assert row["warnings_json"] == '["one warning"]'
    assert row["status"] == "ok"
    assert row["error"] is None


def test_upgrading_leaves_old_rows_with_an_unknown_sub_digest(
    tmp_path: Path,
) -> None:
    path = tmp_path / "assertions.db"
    _v2_database(path)

    conn = sqlite3.connect(str(path))
    try:
        apply_migrations(conn)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM assertion_runs").fetchone()
    finally:
        conn.close()

    assert row["affects_digest"] is None


def test_upgrading_does_not_touch_the_assertions_table(tmp_path: Path) -> None:
    path = tmp_path / "assertions.db"
    _v2_database(path)

    conn = sqlite3.connect(str(path))
    try:
        apply_migrations(conn)
        count = conn.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]
    finally:
        conn.close()

    assert count == 1


def test_a_migrated_database_matches_a_fresh_one_column_for_column(
    tmp_path: Path,
) -> None:
    """ADD COLUMN can only append, so a divergence here means the fresh DDL
    put the column somewhere ALTER cannot reach — and then ``SELECT *``
    returns different shapes depending on the database's history."""
    migrated = tmp_path / "migrated" / "assertions.db"
    migrated.parent.mkdir()
    _v2_database(migrated)
    conn = sqlite3.connect(str(migrated))
    try:
        apply_migrations(conn)
    finally:
        conn.close()

    fresh = AssertionStore(tmp_path / "fresh")

    assert _columns(migrated, "assertion_runs") == _columns(
        fresh.path, "assertion_runs"
    )


def test_re_running_the_migration_is_a_no_op(tmp_path: Path) -> None:
    path = tmp_path / "assertions.db"
    _v2_database(path)

    conn = sqlite3.connect(str(path))
    try:
        apply_migrations(conn)
        # A second ALTER of the same column would raise "duplicate column".
        assert apply_migrations(conn) == 3
        columns = tuple(
            row[1]
            for row in conn.execute("PRAGMA table_info(assertion_runs)").fetchall()
        )
    finally:
        conn.close()

    assert columns.count("affects_digest") == 1


def test_opening_a_version_two_store_migrates_it(tmp_path: Path) -> None:
    """The path a real repository takes: an old DB, opened by a new build."""
    _v2_database(tmp_path / "assertions.db")

    store = AssertionStore(tmp_path)

    assert store.schema_version() == 3
    assert "affects_digest" in _columns(store.path, "assertion_runs")


# ---------------------------------------------------------------------------
# Reading a migrated row back through the model
# ---------------------------------------------------------------------------


def test_a_pre_migration_run_reads_back_with_no_sub_digest(tmp_path: Path) -> None:
    """``_row_to_run`` must survive the NULL rather than raising on it."""
    _v2_database(tmp_path / "assertions.db")
    store = AssertionStore(tmp_path)

    runs = store.runs_for("ev-1")

    assert len(runs) == 1
    assert runs[0].fingerprint == "whole-build-digest"
    assert runs[0].affects_digest is None


def test_read_run_also_survives_the_null(tmp_path: Path) -> None:
    _v2_database(tmp_path / "assertions.db")
    store = AssertionStore(tmp_path)

    stored = store.read_run("ev-1", "3.4")

    assert stored is not None
    assert stored.run.affects_digest is None
    assert len(stored.assertions) == 1


def test_the_model_defaults_the_sub_digest_to_none() -> None:
    """Every existing AssertionRun construction site omits it."""
    from datetime import datetime, timezone

    from atlas.assertions.model import AssertionRun

    run = AssertionRun(
        evidence_id="ev-1",
        kind="annual_report",
        analyzer_version="3.4",
        fingerprint="fp",
        result_confidence="high",
        source_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        analyzed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        warnings=(),
        status="ok",
    )

    assert run.affects_digest is None


def test_a_sub_digest_round_trips_when_supplied(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from atlas.assertions.model import AssertionRun

    store = AssertionStore(tmp_path)
    store.write_run(
        AssertionRun(
            evidence_id="ev-2",
            kind="annual_report",
            analyzer_version="3.4",
            fingerprint="whole",
            result_confidence="high",
            source_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            analyzed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            warnings=(),
            status="ok",
            affects_digest="per-kind-digest",
        ),
        (),
    )

    assert store.runs_for("ev-2")[0].affects_digest == "per-kind-digest"


def test_rewriting_a_run_replaces_its_sub_digest(tmp_path: Path) -> None:
    """write_run deletes by (evidence_id, analyzer_version) before inserting,
    so a re-analysis must not leave the previous sub-digest behind."""
    from datetime import datetime, timezone

    from atlas.assertions.model import AssertionRun

    def _run(affects: str | None) -> AssertionRun:
        return AssertionRun(
            evidence_id="ev-3",
            kind="annual_report",
            analyzer_version="3.4",
            fingerprint="whole",
            result_confidence="high",
            source_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            analyzed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            warnings=(),
            status="ok",
            affects_digest=affects,
        )

    store = AssertionStore(tmp_path)
    store.write_run(_run(None), ())
    store.write_run(_run("fresh-digest"), ())

    runs = store.runs_for("ev-3")
    assert len(runs) == 1
    assert runs[0].affects_digest == "fresh-digest"


@pytest.mark.parametrize("version", [4, 9])
def test_a_newer_database_is_still_refused(tmp_path: Path, version: int) -> None:
    """The downgrade guard must keep working past the new migration count."""
    from atlas.assertions.store import MigrationError

    path = tmp_path / "assertions.db"
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
        with pytest.raises(MigrationError, match="newer Atlas"):
            apply_migrations(conn)
    finally:
        conn.close()
