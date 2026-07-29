"""#75: mention ids do not move when the corpus is traversed differently.

Two processes, two traversal orders, two hash seeds. Separate processes are
the point: ``PYTHONHASHSEED`` randomises set and frozenset iteration order per
process, so a same-process comparison cannot see an id that depends on it, and
``Entity.aliases`` is a frozenset that reaches the mention rows.

The teeth of the test are in the second assertion. ``EntityResolver`` genuinely
does hand out different ``entity_id`` values for the two orders -- that is
documented behaviour, since the id derives from the first observed name -- so
if ``mention_id`` were built from it, the first assertion would fail. A test
where both sides are trivially equal proves nothing; this one has a moving
part it deliberately does not depend on.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# Names chosen so resolution order changes the outcome: "K S Rao" and
# "K Srinivasa Rao" are person-compatible, so whichever is seen first supplies
# the canonical name and the id for the merged entity.
_SCRIPT = """
import json, sys
from atlas.analysis.base import EntityMention, Provenance
from atlas.assertions.model import Mention, assign_mention_ordinals
from atlas.knowledge.entities.resolver import EntityResolver

RAW = [
    ("K S Rao", "person"),
    ("Kotak Institutional Equities", "organization"),
    ("K Srinivasa Rao", "person"),
    ("N Chandrasekaran", "person"),
    ("K S Rao", "person"),
]

positions = list(range(len(RAW)))
if sys.argv[1] != "forward":
    positions = list(reversed(positions))

resolver = EntityResolver()
mentions = []
observed = {}
for position in positions:
    raw, kind = RAW[position]
    entity = resolver.resolve(raw, kind)
    # Captured at the moment of the mention and keyed by the position in the
    # document, not by traversal order: the resolver keeps upgrading
    # canonical_name as it sees longer forms, so reading it back afterwards
    # would show both orders converged and hide the divergence.
    observed[position] = entity.canonical_name
    mentions.append(
        EntityMention(
            entity=entity,
            role="analyst",
            provenance=Provenance(section="qa", char_offset=100),
        )
    )
rows = [
    Mention.from_mention(
        mention,
        evidence_id="ev-transcript-1",
        analyzer_version="1.0",
        fingerprint="fp",
        ordinal=ordinal,
    )
    for mention, ordinal in zip(mentions, assign_mention_ordinals(mentions))
]
resolution = [observed[position] for position in range(len(RAW))]
print(json.dumps({
    "mention_ids": sorted(row.mention_id for row in rows),
    "resolution": resolution,
}))
"""


def _run(direction: str, hash_seed: str) -> dict[str, list[str]]:
    environment = dict(os.environ, PYTHONHASHSEED=hash_seed)
    completed = subprocess.run(
        [sys.executable, "-c", _SCRIPT, direction],
        capture_output=True,
        text=True,
        env=environment,
        check=True,
    )
    result: dict[str, list[str]] = json.loads(completed.stdout)
    return result


def test_mention_ids_survive_a_reordered_traversal() -> None:
    forward = _run("forward", "0")
    reverse = _run("reverse", "1")

    assert forward["mention_ids"] == reverse["mention_ids"]


def test_the_test_has_teeth_resolution_does_move() -> None:
    """If this ever fails, the test above stopped proving anything.

    It would mean the resolver had become order-independent, and an id built
    from its output would pass the stability check while still being unsafe
    for the next resolver change.
    """
    forward = _run("forward", "0")
    reverse = _run("reverse", "1")

    assert forward["resolution"] != reverse["resolution"]
