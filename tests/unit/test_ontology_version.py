"""Pin the FactKind vocabulary to a checked-in snapshot.

The FactKind ontology is frozen (ADR-0012): members are admitted only against
an explicit test, and downstream layers key cached extraction results by the
ontology version that produced them. A member added without a version bump
leaves those caches stale with no signal that they are stale.

This test makes that impossible to do by accident. It deliberately offers no
--update-snapshot affordance: regenerating the snapshot must be a conscious
edit made alongside the version bump, not a reflex.
"""

from pathlib import Path

from atlas.analysis.base import ONTOLOGY_VERSION, FactKind

_SNAPSHOT = Path(__file__).parent / "data" / "factkind_snapshot.txt"

_MISMATCH_HELP = """
FactKind no longer matches the checked-in snapshot.

If this change is intentional, make BOTH edits in this commit:
  1. Bump ONTOLOGY_VERSION in src/atlas/analysis/base.py
     (currently {version!r})
  2. Update {snapshot}
     to the sorted list of FactKind values

Added members:   {added}
Removed members: {removed}
"""


def _snapshot_values() -> list[str]:
    text = _SNAPSHOT.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line]


def _live_values() -> list[str]:
    return sorted(member.value for member in FactKind)


def test_factkind_matches_snapshot() -> None:
    """Every FactKind member, and no others, appears in the snapshot."""
    live = _live_values()
    snapshot = _snapshot_values()

    added = sorted(set(live) - set(snapshot))
    removed = sorted(set(snapshot) - set(live))

    assert live == snapshot, _MISMATCH_HELP.format(
        version=ONTOLOGY_VERSION,
        snapshot=_SNAPSHOT,
        added=added or "(none)",
        removed=removed or "(none)",
    )


def test_snapshot_is_sorted_and_unique() -> None:
    """The snapshot itself is canonical: sorted, no duplicates.

    Guards the snapshot file against a hand-edit that appends a member at the
    end, which would pass a set comparison but leave the file non-canonical
    and make the next diff unreadable.
    """
    snapshot = _snapshot_values()
    assert snapshot == sorted(snapshot), "snapshot file is not sorted"
    assert len(snapshot) == len(set(snapshot)), "snapshot file has duplicates"


def test_ontology_version_is_a_nonempty_string() -> None:
    """ONTOLOGY_VERSION is present and usable as a fingerprint component."""
    assert isinstance(ONTOLOGY_VERSION, str)
    assert ONTOLOGY_VERSION.strip() == ONTOLOGY_VERSION
    assert ONTOLOGY_VERSION != ""
