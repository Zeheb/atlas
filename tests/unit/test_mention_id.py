"""``mention_id`` and the entity_mentions schema.

The one claim worth testing hardest: a mention's id must not move when the
corpus is traversed in a different order. ``Entity.entity_id`` does move --
by design, since it derives from the first observed name and gains a
disambiguation suffix on collision -- so an id built from it would make a
backfill mint new ids for mentions that had not changed, and set equality
between a full and an incremental build would stop meaning anything.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from atlas.analysis.base import EntityMention, Provenance
from atlas.assertions.model import assign_mention_ordinals, mention_id
from atlas.assertions.store import STORE_VERSION, AssertionStore
from atlas.knowledge.entities.model import Entity

_EVIDENCE = "ev-transcript-1"


def _mention(
    name: str = "K S Rao",
    *,
    entity_id: str = "person-ksrao",
    section: str | None = "qa",
    char_offset: int | None = 100,
    role: str | None = "analyst",
) -> EntityMention:
    return EntityMention(
        entity=Entity(entity_id=entity_id, kind="person", canonical_name=name),
        role=role,
        provenance=(
            None
            if section is None
            else Provenance(section=section, char_offset=char_offset)
        ),
    )


def _id(**overrides: object) -> str:
    kwargs: dict[str, object] = {
        "evidence_id": _EVIDENCE,
        "section": "qa",
        "char_offset": 100,
        "analyzer_version": "1.0",
        "ordinal": 0,
    }
    kwargs.update(overrides)
    return mention_id(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def test_id_is_deterministic() -> None:
    assert _id() == _id()


def test_no_resolver_output_reaches_the_id() -> None:
    """The whole point of #74, made structural.

    Both of the resolver's outputs move with corpus traversal order --
    entity_id from the first observed name, canonical_name upgraded to the
    most complete form seen so far -- so neither may be a parameter. Checking
    the signature rather than the behaviour means a future change that
    reintroduces one fails here rather than in a rare ordering.
    """
    parameters = set(mention_id.__code__.co_varnames)
    assert "entity_id" not in parameters
    assert "canonical_name" not in parameters


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_id", "ev-other"),
        ("section", "prepared_remarks"),
        ("char_offset", 101),
        ("analyzer_version", "2.0"),
        ("ordinal", 1),
    ],
)
def test_every_component_changes_the_id(field: str, value: object) -> None:
    """A component that cannot change the id is a component not in the hash."""
    assert _id(**{field: value}) != _id()


def test_absent_section_and_offset_are_hashable() -> None:
    """Mentions legitimately arrive with no provenance at all."""
    assert _id(section=None, char_offset=None) != _id()


def test_id_is_sixteen_hex_characters() -> None:
    value = _id()
    assert len(value) == 16
    assert int(value, 16) >= 0


# ---------------------------------------------------------------------------
# Ordinals
# ---------------------------------------------------------------------------


def test_repeated_mention_in_one_section_gets_distinct_ordinals() -> None:
    """Same analyst, same section, same section-level offset."""
    mentions = [_mention(), _mention()]

    assert assign_mention_ordinals(mentions) == [0, 1]


def test_ordinals_count_within_a_section_regardless_of_name() -> None:
    """Grouping by name would put resolution order back into the id through
    the ordinal, after mention_id was built to keep it out."""
    mentions = [_mention(), _mention("Other Person"), _mention()]

    assert assign_mention_ordinals(mentions) == [0, 1, 2]


def test_ordinals_separate_sections() -> None:
    mentions = [_mention(section="qa"), _mention(section="prepared_remarks")]

    assert assign_mention_ordinals(mentions) == [0, 0]


def test_mentions_without_provenance_share_a_group() -> None:
    mentions = [_mention(section=None), _mention(section=None)]

    assert assign_mention_ordinals(mentions) == [0, 1]


def test_duplicate_mentions_get_different_ids() -> None:
    """Two identical mentions must be two rows, not one silently."""
    mentions = [_mention(), _mention()]
    ordinals = assign_mention_ordinals(mentions)

    ids = {_id(ordinal=ordinal) for ordinal in ordinals}

    assert len(ids) == 2


def test_a_rename_by_the_resolver_does_not_move_the_ids() -> None:
    """The backfill case. A later document can upgrade an entity's canonical
    name from "K S Rao" to "K Srinivasa Rao"; the ids of mentions already
    stored must not follow it."""
    before = [_mention("K S Rao", entity_id="person-1"), _mention("Other")]
    after = [_mention("K Srinivasa Rao", entity_id="person-9"), _mention("Other")]

    def ids(mentions: list[EntityMention]) -> list[str]:
        return [
            mention_id(
                evidence_id=_EVIDENCE,
                section=mention.provenance.section if mention.provenance else None,
                char_offset=(
                    mention.provenance.char_offset if mention.provenance else None
                ),
                analyzer_version="1.0",
                ordinal=ordinal,
            )
            for mention, ordinal in zip(
                mentions, assign_mention_ordinals(mentions), strict=True
            )
        ]

    assert ids(before) == ids(after)


# ---------------------------------------------------------------------------
# Migration 2
# ---------------------------------------------------------------------------

_MENTION_COLUMNS = (
    "mention_id",
    "evidence_id",
    "entity_id",
    "entity_kind",
    "canonical_name",
    "aliases_json",
    "role",
    "affiliation",
    "identifier",
    "question_text",
    "section",
    "char_offset",
    "excerpt",
    "ordinal",
    "analyzer_version",
    "fingerprint",
)


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(path))


def test_the_mentions_table_arrives_at_migration_two(tmp_path: Path) -> None:
    """Pinned to migration 2 itself, not to the migration count.

    This asserted ``STORE_VERSION == 2`` until migration 3 was appended, which
    made it a test of how many migrations exist rather than of where
    ``entity_mentions`` comes from. The version a fresh store reports is
    covered by ``test_assertion_store``; what belongs here is that this
    table is migration 2's contribution and stays that way.
    """
    from atlas.assertions.store import MIGRATIONS, apply_migrations

    connection = _connect(tmp_path / "assertions.db")
    try:
        assert apply_migrations(connection, MIGRATIONS[:2]) == 2
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert "entity_mentions" in tables
    assert AssertionStore(tmp_path).schema_version() == STORE_VERSION


def test_table_and_indices_exist(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    connection = _connect(store.path)
    try:
        objects = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master").fetchall()
        }
    finally:
        connection.close()

    assert "entity_mentions" in objects
    assert {"idx_mentions_evidence", "idx_mentions_entity"} <= objects


def test_columns_match_the_specified_schema(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    connection = _connect(store.path)
    try:
        rows = connection.execute("PRAGMA table_info(entity_mentions)").fetchall()
    finally:
        connection.close()

    assert tuple(row[1] for row in rows) == _MENTION_COLUMNS


def test_migration_is_additive(tmp_path: Path) -> None:
    """M1's tables must survive it untouched -- that is the whole promise of
    an append-only migration list."""
    store = AssertionStore(tmp_path)

    connection = _connect(store.path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert {"assertions", "assertion_runs", "entity_mentions"} <= tables


def test_a_version_one_database_upgrades_in_place(tmp_path: Path) -> None:
    """The case the runner exists for: a store created before M2 gains the new
    table without losing what it held."""
    from atlas.assertions.store import MIGRATIONS, apply_migrations

    path = tmp_path / "assertions.db"
    connection = _connect(path)
    try:
        apply_migrations(connection, MIGRATIONS[:1])
        connection.execute(
            "INSERT INTO assertion_runs "
            "(evidence_id, kind, analyzer_version, fingerprint, result_confidence,"
            " source_date, analyzed_at, warnings_json, status, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("ev-1", "annual_report", "1.0", "fp", "high", "d", "d", "[]", "ok", None),
        )
        connection.commit()
    finally:
        connection.close()

    store = AssertionStore(tmp_path)

    # Opening applies every outstanding migration, not just the next one, so
    # this is STORE_VERSION rather than 2 -- a v1 database opened by a build
    # with three migrations must end up at three.
    assert store.schema_version() == STORE_VERSION
    assert store.evidence_ids() == ("ev-1",)


def test_duplicate_mention_id_raises(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    insert = (
        "INSERT INTO entity_mentions "
        "(mention_id, evidence_id, entity_id, entity_kind, canonical_name, "
        " aliases_json, ordinal, analyzer_version, fingerprint) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    row = ("m1", _EVIDENCE, "person-1", "person", "K S Rao", "[]", 0, "1.0", "fp")

    connection = _connect(store.path)
    try:
        connection.execute(insert, row)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert, row)
    finally:
        connection.close()
