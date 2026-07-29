"""canonical_for_hash: one exclusion list, applied at every depth.

The failure this prevents is subtle. If a wall-clock field reaches a hash,
the same input produces a different id on every run and nothing is ever
cache-hit. If it reaches a comparison, two identical builds never match. If
three callers each keep their own exclusion list, one of them eventually
forgets a field and only one of the three symptoms appears.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.assertions.hashing import (
    EXCLUDED_FROM_HASH,
    canonical_for_hash,
    strip_volatile,
)


def test_excluded_keys_are_dropped_not_blanked() -> None:
    """A blanked key still occupies a slot, which invites treating
    'recorded but ignored' and 'absent' as different. They are not."""
    stripped = strip_volatile({"kind": "revenue", "analyzed_at": "2024-01-01"})
    assert stripped == {"kind": "revenue"}


def test_excluded_keys_are_dropped_at_every_depth() -> None:
    """built_at sits on an envelope, analyzed_at inside each nested record.
    A top-level-only strip would miss the nested one."""
    payload = {
        "built_at": "2024-01-01",
        "ingested": [
            {"evidence_id": "a", "analyzed_at": "2024-01-02"},
            {"evidence_id": "b", "analyzed_at": "2024-01-03"},
        ],
        "nested": {"deep": {"created_at": "2024-01-04", "keep": 1}},
    }
    assert strip_volatile(payload) == {
        "ingested": [{"evidence_id": "a"}, {"evidence_id": "b"}],
        "nested": {"deep": {"keep": 1}},
    }


def test_key_order_does_not_change_the_canonical_form() -> None:
    forward = canonical_for_hash({"a": 1, "b": 2})
    reverse = canonical_for_hash({"b": 2, "a": 1})
    assert forward == reverse


def test_two_payloads_differing_only_in_timestamps_are_identical() -> None:
    """The whole point: same content, different run, same canonical form."""
    first = {"evidence_id": "ev-1", "analyzed_at": datetime(2024, 1, 1)}
    second = {"evidence_id": "ev-1", "analyzed_at": datetime(2025, 6, 6)}
    assert canonical_for_hash(first) == canonical_for_hash(second)


def test_a_real_content_difference_still_shows() -> None:
    """Excluding timestamps must not excuse an actual change."""
    first = {"evidence_id": "ev-1", "value": 100}
    second = {"evidence_id": "ev-1", "value": 101}
    assert canonical_for_hash(first) != canonical_for_hash(second)


def test_list_order_is_preserved() -> None:
    """Lists carry meaning here -- sources ordering is what M-PRE fixed --
    so canonicalisation must not sort them away."""
    forward = canonical_for_hash({"sources": ["a", "b"]})
    reverse = canonical_for_hash({"sources": ["b", "a"]})
    assert forward != reverse


def test_strings_are_not_treated_as_sequences() -> None:
    """str is a Sequence; recursing into it would explode every string
    into a list of characters."""
    assert strip_volatile({"kind": "revenue"}) == {"kind": "revenue"}


def test_non_json_types_are_stringified_rather_than_raising() -> None:
    """datetime and enum values appear in these payloads. Refusing to
    serialise them would make the helper unusable on real input."""
    moment = datetime(2024, 3, 31, tzinfo=timezone.utc)
    assert "2024-03-31" in canonical_for_hash({"period": moment})


def test_the_exclusion_list_is_the_documented_one() -> None:
    """Pinned so that adding or removing a field is a visible decision
    rather than a silent behaviour change in three callers at once."""
    assert EXCLUDED_FROM_HASH == frozenset({"analyzed_at", "built_at", "created_at"})
