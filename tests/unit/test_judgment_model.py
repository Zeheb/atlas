"""The Judgment model: content addressing, canonicalization, invariants.

Four properties, each guarding a distinct silent failure:

Determinism   -- an id that varies between processes makes the append-only
                 store useless: the same conclusion re-entered would append
                 instead of being rejected as a duplicate.
Distinctness  -- two judgments differing in any hashed component must get
                 different ids, or one silently shadows the other and a
                 recorded human belief disappears.
Time-blindness-- ``asserted_at`` must NOT reach the id, or every re-entry is
                 a new judgment and the duplicate check never fires.
Canonical set -- ``evidence_ids`` carries no order; two orderings of one set
                 must not produce two ids.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from atlas.judgment.model import Judgment, canonical_evidence_ids, judgment_id
from atlas.reasoning.contracts import SubjectRef

_SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")
_AT = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
_FP = "fingerprint-abc"


def _judgment(**overrides: object) -> Judgment:
    kwargs: dict[str, object] = {
        "subject": _SUBJECT,
        "statement": "Margin compression is structural, not cyclical.",
        "rationale": "Four consecutive quarters of wage inflation.",
        "evidence_ids": ("ev-002", "ev-001"),
        "asserted_at": _AT,
        "fingerprint": _FP,
    }
    kwargs.update(overrides)
    return Judgment.create(**kwargs)  # type: ignore[arg-type]


# --- determinism -------------------------------------------------------------


def test_same_content_gives_same_id() -> None:
    assert _judgment().judgment_id == _judgment().judgment_id


def test_id_is_a_16_char_hex_string() -> None:
    jid = _judgment().judgment_id
    assert len(jid) == 16
    int(jid, 16)  # raises if not hex


def test_id_does_not_depend_on_asserted_at() -> None:
    """The whole point of excluding the timestamp — see the module docstring."""
    later = _judgment(asserted_at=_AT + timedelta(days=365))
    assert later.judgment_id == _judgment().judgment_id


def test_id_does_not_depend_on_subject_display() -> None:
    renamed = SubjectRef(subject_id="TCS", display="TCS Ltd.", aliases=("Tata Consy",))
    assert _judgment(subject=renamed).judgment_id == _judgment().judgment_id


# --- distinctness ------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"statement": "Margin compression is cyclical."},
        {"rationale": "Different reasoning entirely."},
        {"evidence_ids": ("ev-001", "ev-003")},
        {"fingerprint": "fingerprint-xyz"},
        {"supersedes": "0123456789abcdef"},
        {"subject": SubjectRef(subject_id="INFY", display="Infosys")},
    ],
)
def test_each_hashed_component_changes_the_id(override: dict[str, object]) -> None:
    assert _judgment(**override).judgment_id != _judgment().judgment_id


def test_subject_type_changes_the_id() -> None:
    person = SubjectRef(subject_id="TCS", display="TCS", subject_type="person")
    assert _judgment(subject=person).judgment_id != _judgment().judgment_id


def test_reasserting_against_a_new_fingerprint_is_a_new_judgment() -> None:
    """Re-affirming a belief on fresh data is a distinct historical fact."""
    original = _judgment()
    reaffirmed = _judgment(fingerprint="fingerprint-after-q4")
    assert reaffirmed.judgment_id != original.judgment_id


# --- canonical evidence_ids --------------------------------------------------


def test_evidence_ids_are_sorted_and_deduplicated() -> None:
    judgment = _judgment(evidence_ids=["ev-003", "ev-001", "ev-003"])
    assert judgment.evidence_ids == ("ev-001", "ev-003")


def test_evidence_id_order_does_not_change_the_id() -> None:
    forward = _judgment(evidence_ids=("ev-001", "ev-002"))
    reverse = _judgment(evidence_ids=("ev-002", "ev-001"))
    assert forward.judgment_id == reverse.judgment_id


def test_duplicate_evidence_id_does_not_change_the_id() -> None:
    plain = _judgment(evidence_ids=("ev-001",))
    doubled = _judgment(evidence_ids=("ev-001", "ev-001"))
    assert doubled.judgment_id == plain.judgment_id


def test_canonical_evidence_ids_on_empty_input() -> None:
    assert canonical_evidence_ids(()) == ()


def test_evidence_ids_may_be_empty() -> None:
    """A judgment resting on no cited document is still a judgment."""
    assert _judgment(evidence_ids=()).evidence_ids == ()


# --- invariants --------------------------------------------------------------


def test_empty_statement_is_rejected() -> None:
    with pytest.raises(ValueError, match="statement must be non-empty"):
        _judgment(statement="   ")


def test_empty_judgment_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="judgment_id must be non-empty"):
        Judgment(
            judgment_id="",
            subject=_SUBJECT,
            statement="Something.",
            rationale="",
            evidence_ids=(),
            asserted_at=_AT,
            fingerprint=_FP,
        )


def test_self_supersede_is_rejected() -> None:
    existing = _judgment()
    with pytest.raises(ValueError, match="supersedes itself"):
        Judgment(
            judgment_id=existing.judgment_id,
            subject=_SUBJECT,
            statement=existing.statement,
            rationale=existing.rationale,
            evidence_ids=existing.evidence_ids,
            asserted_at=_AT,
            fingerprint=_FP,
            supersedes=existing.judgment_id,
        )


def test_supersedes_defaults_to_none() -> None:
    assert _judgment().supersedes is None


def test_judgment_is_frozen() -> None:
    judgment = _judgment()
    with pytest.raises(AttributeError):
        judgment.statement = "revised"  # type: ignore[misc]


def test_rationale_may_be_empty() -> None:
    """Not every conclusion comes with an argument; only the claim is required."""
    assert _judgment(rationale="").rationale == ""


# --- the standalone id function ----------------------------------------------


def test_judgment_id_function_matches_create() -> None:
    direct = judgment_id(
        subject_id="TCS",
        subject_type="company",
        statement="Margin compression is structural, not cyclical.",
        rationale="Four consecutive quarters of wage inflation.",
        evidence_ids=("ev-001", "ev-002"),
        fingerprint=_FP,
        supersedes=None,
    )
    assert direct == _judgment().judgment_id
