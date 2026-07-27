"""The Person/Organization entity model (M-P1.1, ADR-0013).

A resolvable domain entity — the node type of the knowledge graph whose
scaffold (``knowledge/entities``, ``events``, ``timeline``, ``relationships``)
was laid down at project start and is re-activated here. An Entity is a domain
object, not a fact and not a pipeline artifact, which is why it lives in the
knowledge layer rather than beside ``FactKind`` in ``analysis``.

M-P1.1 delivers identity only. Attributes (role, affiliation, tenure) arrive
with the emission milestones (M-P1.2+); persistence arrives later still. This
module carries no such fields.

Two invariants govern ``entity_id`` (both test-enforced):

- **Stability.** An entity's ``entity_id`` is assigned once, at creation, and
  never changes — not when a fuller ``canonical_name`` is discovered, not when
  aliases accrue. It is therefore derived from the *first observed* name, never
  from the mutable ``canonical_name``.
- **Uniqueness.** No two distinct entities ever share an ``entity_id``. The
  resolver guarantees this with a disambiguation suffix when a distinct entity
  would otherwise collide (see ``resolver.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EntityKind = Literal["person", "organization"]


@dataclass(frozen=True)
class Entity:
    """One resolved person or organization.

    Frozen: the resolver represents an update (a longer canonical name, a new
    alias) by constructing a *replacement* Entity that carries the SAME
    ``entity_id``. Immutability is what makes the stability invariant checkable
    — a mutated ``canonical_name`` can never drag the id with it, because the
    id is a separate, already-frozen field.
    """

    entity_id: str  # immutable; independent of canonical_name (see module docstring)
    kind: EntityKind
    canonical_name: str  # most complete display form seen so far
    aliases: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("Entity.entity_id must be non-empty")
        if self.kind not in ("person", "organization"):
            raise ValueError(
                f"Entity.kind {self.kind!r} must be 'person' or 'organization'"
            )
        if not self.canonical_name.strip():
            raise ValueError("Entity.canonical_name must be non-empty")
