"""Entity mentions travel with the facts, or not at all.

The reason they share a transaction is not tidiness. A fact stored without the
entity it named is a fact whose subject vanished -- "the CFO said X" with no
CFO -- and nothing downstream can detect that, because a document with no
entities is a legitimate state. So the tests here are mostly about what
survives a failure: a write that raises must leave neither half.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    EntityMention,
    FactKind,
    Provenance,
)
from atlas.assertions.model import Assertion, AssertionRun, Mention
from atlas.assertions.store import AssertionStore
from atlas.assertions.writer import result_to_mentions, write_result
from atlas.knowledge.entities.model import Entity

_EVIDENCE = "ev-transcript-1"
_VERSION = "1.0"
_FINGERPRINT = "fp-abc"


def _entity_mention(
    name: str = "K S Rao",
    *,
    entity_id: str = "person-1",
    role: str | None = "analyst",
    affiliation: str | None = "Kotak Institutional Equities",
    identifier: str | None = None,
    question_text: str | None = "What drove the margin expansion?",
    aliases: frozenset[str] = frozenset({"KS Rao", "Rao"}),
    provenance: Provenance | None = None,
) -> EntityMention:
    return EntityMention(
        entity=Entity(
            entity_id=entity_id,
            kind="person",
            canonical_name=name,
            aliases=aliases,
        ),
        role=role,
        affiliation=affiliation,
        identifier=identifier,
        question_text=question_text,
        provenance=(
            provenance
            if provenance is not None
            else Provenance(section="qa", char_offset=1200, excerpt="K S Rao asked")
        ),
    )


def _result(
    entities: list[EntityMention] | None = None,
    *,
    analyzer_version: str = _VERSION,
) -> AnalysisResult:
    return AnalysisResult(
        evidence_id=_EVIDENCE,
        kind="earnings_transcript",
        analyzer_version=analyzer_version,
        confidence="high",
        source_date=datetime(2026, 4, 9, tzinfo=timezone.utc),
        analyzed_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        facts=[
            AnalysisFact(
                kind=FactKind.RISK_FACTOR,
                value="Currency volatility",
                unit=None,
                period="2026-03-31",
                confidence="high",
                provenance=Provenance(section="qa", char_offset=1200),
            )
        ],
        entities=entities if entities is not None else [_entity_mention()],
    )


def _counts(store: AssertionStore) -> tuple[int, int, int]:
    connection = sqlite3.connect(str(store.path))
    try:
        return (
            connection.execute("SELECT COUNT(*) FROM assertion_runs").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM assertions").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM entity_mentions").fetchone()[0],
        )
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_mentions_are_written_with_the_facts(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    write_result(store, _result(), fingerprint=_FINGERPRINT)

    assert _counts(store) == (1, 1, 1)


def test_every_context_field_survives(tmp_path: Path) -> None:
    """role, affiliation, identifier and question_text are the whole reason
    EntityMention exists as a wrapper around Entity."""
    store = AssertionStore(tmp_path)
    original = _entity_mention(identifier="DIN-00121863")

    write_result(store, _result([original]), fingerprint=_FINGERPRINT)

    stored = store.read_run(_EVIDENCE, _VERSION)
    assert stored is not None
    assert stored.mentions[0].to_mention() == original


def test_aliases_are_stored_sorted(tmp_path: Path) -> None:
    """frozenset iteration order is not stable across processes; an unsorted
    list would make two identical stores differ byte for byte."""
    store = AssertionStore(tmp_path)

    write_result(
        store,
        _result([_entity_mention(aliases=frozenset({"Zed", "Alpha", "Mid"}))]),
        fingerprint=_FINGERPRINT,
    )

    stored = store.read_run(_EVIDENCE, _VERSION)
    assert stored is not None
    assert stored.mentions[0].aliases == ("Alpha", "Mid", "Zed")


def test_mention_without_provenance_round_trips_as_none(tmp_path: Path) -> None:
    """ "Not recorded" and "recorded as blank" are different claims."""
    store = AssertionStore(tmp_path)
    original = _entity_mention(provenance=None)
    # Constructed directly: the helper substitutes a default when passed None.
    original = EntityMention(entity=original.entity, role=original.role)

    write_result(store, _result([original]), fingerprint=_FINGERPRINT)

    stored = store.read_run(_EVIDENCE, _VERSION)
    assert stored is not None
    assert stored.mentions[0].section is None
    assert stored.mentions[0].to_mention().provenance is None


def test_repeated_mentions_are_two_rows(tmp_path: Path) -> None:
    """One analyst asking twice in one section is the case ordinals exist for."""
    store = AssertionStore(tmp_path)

    write_result(
        store, _result([_entity_mention(), _entity_mention()]), fingerprint=_FINGERPRINT
    )

    stored = store.read_run(_EVIDENCE, _VERSION)
    assert stored is not None
    assert len(stored.mentions) == 2
    assert {item.mention_id for item in stored.mentions} != {
        stored.mentions[0].mention_id
    }


def test_entity_id_is_stored_as_data(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    write_result(
        store,
        _result([_entity_mention(entity_id="person-42")]),
        fingerprint=_FINGERPRINT,
    )

    stored = store.read_run(_EVIDENCE, _VERSION)
    assert stored is not None
    assert stored.mentions[0].entity_id == "person-42"


def test_a_result_with_no_entities_writes_no_mentions(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    write_result(store, _result([]), fingerprint=_FINGERPRINT)

    assert _counts(store) == (1, 1, 0)


def test_rewriting_replaces_mentions(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    write_result(
        store, _result([_entity_mention("Old Name")]), fingerprint=_FINGERPRINT
    )

    write_result(
        store, _result([_entity_mention("New Name")]), fingerprint=_FINGERPRINT
    )

    stored = store.read_run(_EVIDENCE, _VERSION)
    assert stored is not None
    assert [item.canonical_name for item in stored.mentions] == ["New Name"]


def test_a_bumped_version_keeps_the_old_mentions(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    write_result(store, _result(), fingerprint=_FINGERPRINT)

    write_result(store, _result(analyzer_version="2.0"), fingerprint=_FINGERPRINT)

    assert _counts(store) == (2, 2, 2)


# ---------------------------------------------------------------------------
# Atomicity (#22)
# ---------------------------------------------------------------------------


def _assertion(assertion_id: str = "a1") -> Assertion:
    return Assertion(
        assertion_id=assertion_id,
        evidence_id=_EVIDENCE,
        kind="risk_factor",
        value="x",
        value_type="str",
        unit=None,
        period=None,
        confidence="high",
        section="qa",
        char_offset=1,
        excerpt=None,
        analyzer_version=_VERSION,
        fingerprint=_FINGERPRINT,
        ordinal=0,
    )


def _run() -> AssertionRun:
    return AssertionRun(
        evidence_id=_EVIDENCE,
        kind="earnings_transcript",
        analyzer_version=_VERSION,
        fingerprint=_FINGERPRINT,
        result_confidence="high",
        source_date=datetime(2026, 4, 9, tzinfo=timezone.utc),
        analyzed_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        warnings=(),
        status="ok",
        error=None,
    )


def _mention_row(mention_id: str = "m1", *, evidence_id: str = _EVIDENCE) -> Mention:
    return Mention(
        mention_id=mention_id,
        evidence_id=evidence_id,
        entity_id="person-1",
        entity_kind="person",
        canonical_name="K S Rao",
        aliases=(),
        role=None,
        affiliation=None,
        identifier=None,
        question_text=None,
        section="qa",
        char_offset=1,
        excerpt=None,
        ordinal=0,
        analyzer_version=_VERSION,
        fingerprint=_FINGERPRINT,
    )


def test_a_failing_mention_insert_writes_no_facts(tmp_path: Path) -> None:
    """The injected failure: two mentions sharing an id. Neither the facts nor
    the run row may survive it."""
    store = AssertionStore(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        store.write_run(_run(), [_assertion()], [_mention_row(), _mention_row()])

    assert _counts(store) == (0, 0, 0)


def test_a_failing_rewrite_restores_the_previous_mentions(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    store.write_run(_run(), [_assertion()], [_mention_row("original")])

    with pytest.raises(sqlite3.IntegrityError):
        store.write_run(
            _run(), [_assertion()], [_mention_row("dup"), _mention_row("dup")]
        )

    stored = store.read_run(_EVIDENCE, _VERSION)
    assert stored is not None
    assert [item.mention_id for item in stored.mentions] == ["original"]


def test_a_failing_fact_insert_writes_no_mentions(tmp_path: Path) -> None:
    """Failure on the other side of the transaction, same requirement."""
    store = AssertionStore(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        store.write_run(_run(), [_assertion(), _assertion()], [_mention_row()])

    assert _counts(store) == (0, 0, 0)


def test_a_mention_from_another_run_is_refused(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    with pytest.raises(ValueError, match="belongs to"):
        store.write_run(_run(), [], [_mention_row(evidence_id="ev-other")])

    assert _counts(store) == (0, 0, 0)


def test_mapping_is_deterministic(tmp_path: Path) -> None:
    result = _result([_entity_mention(), _entity_mention("Other")])

    first = result_to_mentions(result, fingerprint=_FINGERPRINT)
    second = result_to_mentions(result, fingerprint=_FINGERPRINT)

    assert [item.mention_id for item in first] == [item.mention_id for item in second]
