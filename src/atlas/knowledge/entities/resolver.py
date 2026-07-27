"""In-memory, deterministic entity resolution (M-P1.1, ADR-0013).

Maps observed name strings to :class:`Entity` objects, merging variants of the
same person while refusing to guess under ambiguity. The deterministic rule is
the required baseline (per the planner-invariant discipline, ADR-0007); an LLM
resolver may later sit behind the same surface, but the deterministic floor
remains.

Design commitments (from the M-P1.1 review):

- **Conservative — prefer under-merging.** Over-merging silently corrupts
  attribution in a provenance-first system (two people fused into one); under-
  merging leaves two recoverable records. So a candidate merges into an
  existing entity only when it matches *exactly one*. Zero matches → a new
  entity; two or more → a new (separate) entity, never a guessed merge.
- **Match against canonical form only.** A candidate is compared to each
  entity's most-complete ``canonical_name``, never to its initial-bearing
  aliases — otherwise an absorbed initials form ("K S Rao") would act as a
  promiscuous matcher for later distinct names ("Krishna S Rao").
- **In-memory only.** No persistence in M-P1.1 (deferred). Ids are stable and
  unique within a resolver's lifetime.

Person matching uses surname + positional initial-expansion. Organization
matching is exact normalized-token equality only (suffix handling like
"Ltd"/"Limited" is deliberately deferred — collapsing it risks over-merging
"Acme Ltd" with "Acme Services Ltd").
"""

from __future__ import annotations

import re

from atlas.knowledge.entities.model import Entity, EntityKind

_HONORIFICS = frozenset({"mr", "mrs", "ms", "dr", "shri", "smt", "sri", "prof"})
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_name(raw: str) -> tuple[str, ...]:
    """Lowercase, drop honorifics and punctuation, collapse whitespace, and
    return the token tuple used for all matching. A one-character token is an
    initial (``"K."`` -> ``"k"``)."""
    lowered = _NON_ALNUM.sub(" ", raw.lower())
    return tuple(t for t in lowered.split() if t and t not in _HONORIFICS)


def _slug(tokens: tuple[str, ...]) -> str:
    return "-".join(tokens)


def _is_initial(token: str) -> bool:
    return len(token) == 1


def _person_compatible(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """True when two person token tuples could denote the same person.

    Requires equal surnames (last token) and a position-wise compatible given
    sequence of the SAME length: each pair is either equal, or one is a single
    initial equal to the other's first letter. Two differing full tokens in the
    same position (Kumar vs Krishna) make the names incompatible — this is what
    stops the initial rule from over-merging distinct people who share initials
    and a surname.
    """
    if not a or not b:
        return False
    if a[-1] != b[-1]:  # surnames must match exactly
        return False
    ga, gb = a[:-1], b[:-1]
    if len(ga) != len(gb):
        return False
    for x, y in zip(ga, gb):
        if x == y:
            continue
        if _is_initial(x) and y.startswith(x):
            continue
        if _is_initial(y) and x.startswith(y):
            continue
        return False
    return True


def _more_specific(candidate: tuple[str, ...], current: tuple[str, ...]) -> bool:
    """Whether *candidate* is a more complete form than *current* (more full,
    non-initial tokens; tie-break on total token count)."""

    def fulls(toks: tuple[str, ...]) -> int:
        return sum(1 for t in toks if not _is_initial(t))

    if fulls(candidate) != fulls(current):
        return fulls(candidate) > fulls(current)
    return len(candidate) > len(current)


class EntityResolver:
    """Accumulates observed names and hands back stable :class:`Entity` objects.

    State is a list of entities plus the set of ids in use (for the uniqueness
    invariant). Deterministic given input order; no I/O.
    """

    def __init__(self) -> None:
        self._entities: list[Entity] = []
        self._tokens: dict[str, tuple[str, ...]] = {}  # entity_id -> canonical tokens
        self._ids: set[str] = set()

    def entities(self) -> list[Entity]:
        """All resolved entities, in creation order."""
        return list(self._entities)

    def resolve(self, raw: str, kind: EntityKind) -> Entity:
        """Return the entity denoted by *raw*, creating or merging as the
        conservative rule dictates."""
        tokens = normalize_name(raw)
        if not tokens:
            raise ValueError(f"Name {raw!r} normalizes to nothing")

        matches = self._matches(tokens, kind)
        if len(matches) == 1:
            return self._merge(matches[0], raw, tokens)
        # 0 matches, or >=2 (ambiguous) -> new separate entity (never guess).
        return self._create(raw, tokens, kind)

    # -- internals ---------------------------------------------------------

    def _matches(self, tokens: tuple[str, ...], kind: EntityKind) -> list[int]:
        out: list[int] = []
        for i, e in enumerate(self._entities):
            if e.kind != kind:
                continue
            cur = self._tokens[e.entity_id]
            same = (
                _person_compatible(tokens, cur) if kind == "person" else tokens == cur
            )
            if same:
                out.append(i)
        return out

    def _merge(self, index: int, raw: str, tokens: tuple[str, ...]) -> Entity:
        e = self._entities[index]
        cur = self._tokens[e.entity_id]
        aliases = set(e.aliases)
        aliases.add(e.canonical_name)
        canonical = e.canonical_name
        canonical_tokens = cur
        if _more_specific(tokens, cur):
            canonical = raw
            canonical_tokens = tokens
        aliases.discard(canonical)
        updated = Entity(
            entity_id=e.entity_id,  # STABILITY: id never changes on merge
            kind=e.kind,
            canonical_name=canonical,
            aliases=frozenset(aliases),
        )
        self._entities[index] = updated
        self._tokens[e.entity_id] = canonical_tokens
        return updated

    def _create(self, raw: str, tokens: tuple[str, ...], kind: EntityKind) -> Entity:
        entity_id = self._mint_id(kind, tokens)
        e = Entity(entity_id=entity_id, kind=kind, canonical_name=raw)
        self._entities.append(e)
        self._tokens[entity_id] = tokens
        self._ids.add(entity_id)
        return e

    def _mint_id(self, kind: EntityKind, tokens: tuple[str, ...]) -> str:
        """A stable id from the FIRST-seen form, disambiguated so that no two
        distinct entities ever collide (UNIQUENESS invariant)."""
        base = f"{kind}:{_slug(tokens)}"
        if base not in self._ids:
            return base
        n = 2
        while f"{base}-{n}" in self._ids:
            n += 1
        return f"{base}-{n}"
