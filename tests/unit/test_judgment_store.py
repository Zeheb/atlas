"""JudgmentStore: append-only persistence, supersede chains, cycle rejection.

The store's job is to make three failures impossible rather than merely
unlikely:

Silent duplication -- a second write of the same judgment must raise, not
                      no-op. Unlike a Thesis, a Judgment is not derived, so
                      "you already recorded this" is a caller bug and the
                      store is the last layer that can say so.
Silent truncation  -- a supersedes link pointing at nothing would make
                      ``chain`` return a partial history that looks whole.
Non-termination    -- a cycle in a hand-edited file must raise, not hang.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from atlas.judgment.model import Judgment
from atlas.judgment.store import (
    STORE_VERSION,
    DuplicateJudgmentError,
    IncompatibleStoreVersionError,
    JudgmentNotFoundError,
    JudgmentStore,
    SupersedeCycleError,
)
from atlas.reasoning.contracts import SubjectRef

_SUBJECT = SubjectRef(
    subject_id="TCS",
    display="Tata Consultancy Services",
    aliases=("TCS Ltd.",),
)
_AT = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
_FP = "fingerprint-abc"


def _store(tmp_path: Path, subject: str = "TCS") -> JudgmentStore:
    return JudgmentStore(tmp_path / subject / "judgments.json", subject)


def _judgment(**overrides: object) -> Judgment:
    kwargs: dict[str, object] = {
        "subject": _SUBJECT,
        "statement": "Margin compression is structural.",
        "rationale": "Four consecutive quarters of wage inflation.",
        "evidence_ids": ("ev-001", "ev-002"),
        "asserted_at": _AT,
        "fingerprint": _FP,
    }
    kwargs.update(overrides)
    return Judgment.create(**kwargs)  # type: ignore[arg-type]


def _forged(judgment_id: str, supersedes: str | None = None) -> Judgment:
    """A Judgment with a hand-assigned id.

    Cycles are unreachable through ``Judgment.create`` — ``supersedes`` is
    inside the content hash — so forging ids is the only way to build the
    corrupt input the store has to reject.
    """
    return Judgment(
        judgment_id=judgment_id,
        subject=_SUBJECT,
        statement=f"Statement {judgment_id}.",
        rationale="",
        evidence_ids=(),
        asserted_at=_AT,
        fingerprint=_FP,
        supersedes=supersedes,
    )


# --- empty store -------------------------------------------------------------


def test_missing_store_does_not_exist(tmp_path: Path) -> None:
    assert not _store(tmp_path).exists()


def test_missing_store_lists_nothing(tmp_path: Path) -> None:
    """A store never written holds nothing; that is not an error."""
    assert _store(tmp_path).list() == ()


def test_get_on_missing_store_raises(tmp_path: Path) -> None:
    with pytest.raises(JudgmentNotFoundError):
        _store(tmp_path).get("nope")


def test_chain_on_missing_store_raises(tmp_path: Path) -> None:
    with pytest.raises(JudgmentNotFoundError):
        _store(tmp_path).chain("nope")


# --- append and round-trip ---------------------------------------------------


def test_append_then_get_round_trips_every_field(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _judgment(supersedes=None)
    store.append(original)
    assert store.get(original.judgment_id) == original


def test_append_creates_the_file_and_parent_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(_judgment())
    assert store.exists()


def test_stored_envelope_carries_the_store_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(_judgment())
    envelope = json.loads((tmp_path / "TCS" / "judgments.json").read_text("utf-8"))
    assert envelope["store_version"] == STORE_VERSION
    assert envelope["subject"] == "TCS"


def test_round_trip_preserves_subject_type_and_aliases(tmp_path: Path) -> None:
    subject = SubjectRef(
        subject_id="TCS", display="TCS", subject_type="company", aliases=("a", "b")
    )
    store = _store(tmp_path)
    original = _judgment(subject=subject)
    store.append(original)
    assert store.get(original.judgment_id).subject == subject


def test_round_trip_preserves_timezone_aware_asserted_at(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _judgment()
    store.append(original)
    assert store.get(original.judgment_id).asserted_at == _AT


def test_list_is_in_append_order(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _judgment(statement="First.")
    second = _judgment(statement="Second.")
    store.append(first)
    store.append(second)
    assert [j.statement for j in store.list()] == ["First.", "Second."]


def test_get_raises_for_an_unknown_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(_judgment())
    with pytest.raises(JudgmentNotFoundError):
        store.get("0000000000000000")


# --- append-only -------------------------------------------------------------


def test_appending_the_same_judgment_twice_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    judgment = _judgment()
    store.append(judgment)
    with pytest.raises(DuplicateJudgmentError, match="append-only"):
        store.append(judgment)


def test_re_entering_identical_content_raises(tmp_path: Path) -> None:
    """Same content means same content address means duplicate, not a new row."""
    store = _store(tmp_path)
    store.append(_judgment())
    with pytest.raises(DuplicateJudgmentError):
        store.append(_judgment(asserted_at=_AT + timedelta(days=30)))


def test_a_rejected_duplicate_leaves_the_store_unchanged(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(_judgment())
    before = (tmp_path / "TCS" / "judgments.json").read_text("utf-8")
    with pytest.raises(DuplicateJudgmentError):
        store.append(_judgment())
    assert (tmp_path / "TCS" / "judgments.json").read_text("utf-8") == before


def test_superseding_never_removes_the_superseded_judgment(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _judgment()
    store.append(original)
    revision = _judgment(
        statement="Margin compression is cyclical after all.",
        supersedes=original.judgment_id,
    )
    store.append(revision)
    assert {j.judgment_id for j in store.list()} == {
        original.judgment_id,
        revision.judgment_id,
    }


# --- subject binding ---------------------------------------------------------


def test_appending_another_subjects_judgment_raises(tmp_path: Path) -> None:
    store = _store(tmp_path, "SBIN")
    with pytest.raises(ValueError, match="does not match store subject"):
        store.append(_judgment())


def test_subject_mismatch_is_checked_before_anything_is_written(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, "SBIN")
    with pytest.raises(ValueError):
        store.append(_judgment())
    assert not store.exists()


# --- supersede chains --------------------------------------------------------


def test_chain_of_one_for_a_judgment_that_supersedes_nothing(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    judgment = _judgment()
    store.append(judgment)
    assert store.chain(judgment.judgment_id) == (judgment,)


def test_chain_resolves_full_history_newest_first(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _judgment(statement="v1.")
    store.append(first)
    second = _judgment(statement="v2.", supersedes=first.judgment_id)
    store.append(second)
    third = _judgment(statement="v3.", supersedes=second.judgment_id)
    store.append(third)
    assert [j.statement for j in store.chain(third.judgment_id)] == [
        "v3.",
        "v2.",
        "v1.",
    ]


def test_chain_from_the_middle_stops_at_that_link(tmp_path: Path) -> None:
    """A chain is the history *below* its head, not the whole file."""
    store = _store(tmp_path)
    first = _judgment(statement="v1.")
    store.append(first)
    second = _judgment(statement="v2.", supersedes=first.judgment_id)
    store.append(second)
    third = _judgment(statement="v3.", supersedes=second.judgment_id)
    store.append(third)
    assert [j.statement for j in store.chain(second.judgment_id)] == ["v2.", "v1."]


def test_appending_a_dangling_supersedes_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(JudgmentNotFoundError, match="not stored for subject"):
        store.append(_judgment(supersedes="0000000000000000"))


def test_a_dangling_supersedes_writes_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(JudgmentNotFoundError):
        store.append(_judgment(supersedes="0000000000000000"))
    assert not store.exists()


def test_forged_ids_still_chain(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(_forged("aaa"))
    store.append(_forged("bbb", supersedes="aaa"))
    assert [j.judgment_id for j in store.chain("bbb")] == ["bbb", "aaa"]


# --- cycles ------------------------------------------------------------------


def _corrupt_with_a_cycle(store_path: Path) -> None:
    """Point ``aaa`` back at ``bbb``, which already supersedes ``aaa``."""
    envelope: dict[str, Any] = json.loads(store_path.read_text("utf-8"))
    for raw in envelope["judgments"]:
        if raw["judgment_id"] == "aaa":
            raw["supersedes"] = "bbb"
    store_path.write_text(json.dumps(envelope), encoding="utf-8")


def test_chain_raises_on_a_cycle_rather_than_looping(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(_forged("aaa"))
    store.append(_forged("bbb", supersedes="aaa"))
    _corrupt_with_a_cycle(tmp_path / "TCS" / "judgments.json")
    with pytest.raises(SupersedeCycleError, match="revisits"):
        store.chain("bbb")


def test_append_onto_a_corrupt_cycle_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(_forged("aaa"))
    store.append(_forged("bbb", supersedes="aaa"))
    _corrupt_with_a_cycle(tmp_path / "TCS" / "judgments.json")
    with pytest.raises(SupersedeCycleError):
        store.append(_forged("ccc", supersedes="bbb"))


def test_chain_raises_when_a_link_dangles_in_a_corrupt_file(tmp_path: Path) -> None:
    """``append`` cannot create this; a hand-edited file can."""
    store = _store(tmp_path)
    store.append(_forged("aaa"))
    store.append(_forged("bbb", supersedes="aaa"))
    path = tmp_path / "TCS" / "judgments.json"
    envelope: dict[str, Any] = json.loads(path.read_text("utf-8"))
    envelope["judgments"] = [
        raw for raw in envelope["judgments"] if raw["judgment_id"] != "aaa"
    ]
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(JudgmentNotFoundError):
        store.chain("bbb")


def test_self_supersede_is_rejected_before_it_reaches_the_store(
    tmp_path: Path,
) -> None:
    """The model rejects the one cycle a single object can see."""
    with pytest.raises(ValueError, match="supersedes itself"):
        _forged("aaa", supersedes="aaa")


# --- store version -----------------------------------------------------------


def test_unknown_store_version_raises_on_read(tmp_path: Path) -> None:
    path = tmp_path / "TCS" / "judgments.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"store_version": "99", "subject": "TCS", "judgments": []}),
        encoding="utf-8",
    )
    with pytest.raises(IncompatibleStoreVersionError, match="99"):
        JudgmentStore(path, "TCS").list()


def test_unknown_store_version_raises_on_append(tmp_path: Path) -> None:
    """A version guard that only covered reads would let a write clobber."""
    path = tmp_path / "TCS" / "judgments.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"store_version": "99", "subject": "TCS", "judgments": []}),
        encoding="utf-8",
    )
    with pytest.raises(IncompatibleStoreVersionError):
        JudgmentStore(path, "TCS").append(_judgment())
