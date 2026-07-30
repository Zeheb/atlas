"""Assertion and AssertionRun — the persisted form of analyzer output.

One ``Assertion`` is one ``AnalysisFact`` made durable. One ``AssertionRun``
carries everything on the ``AnalysisResult`` envelope that is not a fact:
result-level confidence, warnings, source date, status. Together they hold
enough to reconstruct a faithful ``AnalysisResult`` without re-reading the
document.

Content-addressed ids
---------------------
``assertion_id`` is a hash of what the assertion says, not a counter. Two
runs of the same analyzer over the same document therefore produce the same
ids, which is what lets a full rebuild and an incremental rebuild be
compared by set equality rather than by fuzzy diffing.

``ordinal`` is part of that hash and is not optional. Analyzers legitimately
emit several facts that share every other component: ``annual_report``
constructs every ``RISK_FACTOR`` in one loop with the same
``section="mda_risk"`` and the same ``char_offset`` — the offset of the
section, not of the individual risk — and ``_extract_risks`` deduplicates on
neither of its two paths. Two equal risk strings would collapse to one row.
The ordinal distinguishes them while staying deterministic, because analyzer
emission order is fixed for a given document and version.

A spike over the 54 shareholding-pattern documents in this repository found
no collisions in 299 facts, so this is insurance rather than an observed
failure. It is cheap insurance: the alternative is a fact silently vanishing
from a profile with no error at any layer.

Value fidelity
--------------
``value`` is ``str | int | float | None``, and the distinction matters:
``5``, ``5.0`` and ``"5"`` are three different assertions. Storage is
therefore a text column plus an explicit ``value_type``, never a text column
alone with the type inferred back. Python's ``repr`` is shortest-round-trip
for floats, so ``float -> str -> float`` is exact, including ``-0.0`` and
values like ``0.1 + 0.2``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from atlas.analysis.base import (
    AnalysisFact,
    EntityMention,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.assertions.hashing import canonical_for_hash
from atlas.knowledge.entities.model import Entity, EntityKind

ValueType = Literal["str", "int", "float", "null"]

Confidence = Literal["high", "medium", "low"]

RunStatus = Literal["ok", "failed"]

#: Length of the hex id prefix retained. 16 hex chars = 64 bits; at the
#: scale of one company repository the birthday bound is far away, and a
#: shorter id keeps the store readable during debugging.
_ID_CHARS = 16


def encode_value(value: str | int | float | None) -> tuple[str | None, ValueType]:
    """Return the storable text for *value* and the type tag to restore it.

    Strings are stored as themselves rather than as ``repr``, so the column
    stays readable and a quoted form never has to be unwrapped. Numbers use
    ``repr``, which round-trips exactly.
    """
    if value is None:
        return None, "null"
    if isinstance(value, bool):
        # bool is a subclass of int; AnalysisFact.value is never a bool, and
        # silently storing one as an int would be a lie about the source.
        raise TypeError("AnalysisFact.value must not be a bool")
    if isinstance(value, str):
        return value, "str"
    if isinstance(value, int):
        return repr(value), "int"
    if isinstance(value, float):
        return repr(value), "float"
    raise TypeError(f"unsupported value type {type(value).__name__}")


def decode_value(raw: str | None, value_type: ValueType) -> str | int | float | None:
    """Inverse of :func:`encode_value`."""
    if value_type == "null":
        return None
    if raw is None:
        raise ValueError(f"value_type {value_type!r} requires a non-null value")
    if value_type == "str":
        return raw
    if value_type == "int":
        return int(raw)
    if value_type == "float":
        return float(raw)
    raise ValueError(f"unknown value_type {value_type!r}")


def assertion_id(
    *,
    evidence_id: str,
    kind: str,
    value: str | None,
    value_type: ValueType,
    unit: str | None,
    period: str | None,
    section: str,
    char_offset: int | None,
    analyzer_version: str,
    ordinal: int,
) -> str:
    """Return the content address for one assertion.

    Deterministic: the same inputs always produce the same id, in any
    process, on any machine. Built through ``canonical_for_hash`` so the
    canonicalisation rules live in exactly one place.
    """
    payload = {
        "evidence_id": evidence_id,
        "kind": kind,
        "value": value,
        "value_type": value_type,
        "unit": unit,
        "period": period,
        "section": section,
        "char_offset": char_offset,
        "analyzer_version": analyzer_version,
        "ordinal": ordinal,
    }
    digest = hashlib.sha256(canonical_for_hash(payload).encode("utf-8"))
    return digest.hexdigest()[:_ID_CHARS]


@dataclass(frozen=True)
class Assertion:
    """One extracted fact, made durable."""

    assertion_id: str
    evidence_id: str
    kind: str
    value: str | None
    value_type: ValueType
    unit: str | None
    period: str | None
    confidence: Confidence
    section: str
    char_offset: int | None
    excerpt: str | None
    analyzer_version: str
    fingerprint: str
    ordinal: int

    @classmethod
    def from_fact(
        cls,
        fact: AnalysisFact,
        *,
        evidence_id: str,
        analyzer_version: str,
        fingerprint: str,
        ordinal: int,
    ) -> Assertion:
        """Build an Assertion from an AnalysisFact.

        *ordinal* is the fact's 0-based index within its
        ``(evidence_id, kind, section)`` group, in analyzer emission order.
        """
        value, value_type = encode_value(fact.value)
        provenance = fact.provenance
        section = provenance.section
        char_offset = provenance.char_offset
        return cls(
            assertion_id=assertion_id(
                evidence_id=evidence_id,
                kind=fact.kind.value,
                value=value,
                value_type=value_type,
                unit=fact.unit.value if fact.unit else None,
                period=fact.period,
                section=section,
                char_offset=char_offset,
                analyzer_version=analyzer_version,
                ordinal=ordinal,
            ),
            evidence_id=evidence_id,
            kind=fact.kind.value,
            value=value,
            value_type=value_type,
            unit=fact.unit.value if fact.unit else None,
            period=fact.period,
            confidence=fact.confidence,
            section=section,
            char_offset=char_offset,
            excerpt=provenance.excerpt,
            analyzer_version=analyzer_version,
            fingerprint=fingerprint,
            ordinal=ordinal,
        )

    def to_fact(self) -> AnalysisFact:
        """Rebuild the AnalysisFact this assertion was made from."""
        return AnalysisFact(
            kind=FactKind(self.kind),
            value=decode_value(self.value, self.value_type),
            unit=FactUnit(self.unit) if self.unit else None,
            period=self.period,
            confidence=self.confidence,
            provenance=Provenance(
                section=self.section,
                char_offset=self.char_offset,
                excerpt=self.excerpt,
            ),
        )


@dataclass(frozen=True)
class AssertionRun:
    """One analyzer pass over one document — the envelope, minus the facts.

    A failed run is recorded rather than dropped. "This document was tried
    and the analyzer raised" and "this document was never tried" are
    different states, and only the second should cause a retry.

    ``fingerprint`` is the whole build's digest; ``affects_digest`` is the
    sub-digest of just the components that can change THIS kind's output
    (``BuildFingerprint.affects(kind)``). Both are stored because they answer
    different questions: the first is "was this row written by the running
    build", the second is "could anything that matters to this kind have
    moved". A whole digest cannot be narrowed after the fact -- sha256 does
    not invert -- so the narrow answer has to be recorded when it is known.

    ``affects_digest`` is ``None`` for a run written before the sub-digest
    existed. None means unknown, and unknown must be read as stale: there is
    no way to recompute it, because the versions it was derived from survive
    only inside the whole digest.
    """

    evidence_id: str
    kind: str
    analyzer_version: str
    fingerprint: str
    result_confidence: Confidence
    source_date: datetime
    analyzed_at: datetime
    warnings: tuple[str, ...]
    status: RunStatus
    error: str | None = None
    affects_digest: str | None = None


def assign_ordinals(facts: list[AnalysisFact]) -> list[int]:
    """Return the ordinal for each fact, in emission order.

    Grouped by ``(kind, section)``: the ordinal only has to disambiguate
    facts that would otherwise hash identically, and a global counter would
    make every id depend on how many unrelated facts preceded it — so
    extracting one extra fact anywhere would change every later id.
    """
    counters: dict[tuple[str, str], int] = {}
    ordinals: list[int] = []
    for fact in facts:
        key = (fact.kind.value, fact.provenance.section)
        ordinal = counters.get(key, 0)
        counters[key] = ordinal + 1
        ordinals.append(ordinal)
    return ordinals


def mention_id(
    *,
    evidence_id: str,
    section: str | None,
    char_offset: int | None,
    analyzer_version: str,
    ordinal: int,
) -> str:
    """Return the content address for one entity mention.

    Every input is a position in an immutable document. Nothing the resolver
    produces enters the hash, and that is the whole design: both of its
    outputs move with corpus traversal order.

    * ``Entity.entity_id`` derives from the first observed name and takes a
      disambiguation suffix on collision (``knowledge/entities/model.py``).
    * ``Entity.canonical_name`` is upgraded to the most complete form seen so
      far, so the *same* mention of "K S Rao" resolves to canonical "K S Rao"
      or to "K Srinivasa Rao" depending on which document was read first.

    Either one in the hash would make a backfill mint new ids for mentions
    that had not changed, and the set equality that full-vs-incremental
    comparison rests on would stop meaning anything.

    What this costs: two different people named in the same section at the
    same offset are separated only by ``ordinal``, their emission order. That
    is the same trade already accepted for facts, whose ordinals exist for
    exactly this reason.
    """
    payload = {
        "evidence_id": evidence_id,
        "section": section,
        "char_offset": char_offset,
        "analyzer_version": analyzer_version,
        "ordinal": ordinal,
    }
    digest = hashlib.sha256(canonical_for_hash(payload).encode("utf-8"))
    return digest.hexdigest()[:_ID_CHARS]


@dataclass(frozen=True)
class Mention:
    """One entity mention, made durable.

    Flat, like ``Assertion``: the nested ``Entity`` and ``Provenance`` are
    spread into columns so a query can filter on a name or a section without
    decoding anything. ``entity_id`` rides along as data -- it is what the
    resolver decided in the session that produced this row, worth keeping and
    not worth hashing.
    """

    mention_id: str
    evidence_id: str
    entity_id: str
    entity_kind: EntityKind
    canonical_name: str
    aliases: tuple[str, ...]
    role: str | None
    affiliation: str | None
    identifier: str | None
    question_text: str | None
    section: str | None
    char_offset: int | None
    excerpt: str | None
    ordinal: int
    analyzer_version: str
    fingerprint: str

    @classmethod
    def from_mention(
        cls,
        mention: EntityMention,
        *,
        evidence_id: str,
        analyzer_version: str,
        fingerprint: str,
        ordinal: int,
    ) -> Mention:
        """Build a Mention from an EntityMention.

        Aliases are sorted on the way in. ``Entity.aliases`` is a frozenset,
        whose iteration order is not stable across processes, and an unsorted
        JSON list would make two identical stores differ byte for byte.
        """
        provenance = mention.provenance
        entity = mention.entity
        section = provenance.section if provenance else None
        char_offset = provenance.char_offset if provenance else None
        return cls(
            mention_id=mention_id(
                evidence_id=evidence_id,
                section=section,
                char_offset=char_offset,
                analyzer_version=analyzer_version,
                ordinal=ordinal,
            ),
            evidence_id=evidence_id,
            entity_id=entity.entity_id,
            entity_kind=entity.kind,
            canonical_name=entity.canonical_name,
            aliases=tuple(sorted(entity.aliases)),
            role=mention.role,
            affiliation=mention.affiliation,
            identifier=mention.identifier,
            question_text=mention.question_text,
            section=section,
            char_offset=char_offset,
            excerpt=provenance.excerpt if provenance else None,
            ordinal=ordinal,
            analyzer_version=analyzer_version,
            fingerprint=fingerprint,
        )

    def to_mention(self) -> EntityMention:
        """Rebuild the EntityMention this row was made from.

        A NULL section means there was no ``Provenance`` at all, which is a
        state ``EntityMention`` permits; it is restored as None rather than as
        an empty one, because "not recorded" and "recorded as blank" are
        different claims about the document.
        """
        return EntityMention(
            entity=Entity(
                entity_id=self.entity_id,
                kind=self.entity_kind,
                canonical_name=self.canonical_name,
                aliases=frozenset(self.aliases),
            ),
            role=self.role,
            affiliation=self.affiliation,
            identifier=self.identifier,
            question_text=self.question_text,
            provenance=(
                None
                if self.section is None
                else Provenance(
                    section=self.section,
                    char_offset=self.char_offset,
                    excerpt=self.excerpt,
                )
            ),
        )


def assign_mention_ordinals(mentions: list[EntityMention]) -> list[int]:
    """Return the ordinal for each mention, in emission order.

    Grouped by ``section`` alone, not by name. ``assign_ordinals`` can group
    facts by kind because a fact's kind is fixed by the analyzer; a mention's
    resolved name is not fixed by anything the document controls, and grouping
    on it would put the resolver's traversal order back into ``mention_id``
    through the ordinal after :func:`mention_id` was built to keep it out.

    Section is coarser, so an extra mention early in a section shifts the
    ordinals of the later mentions in that section. That is the cost of an id
    that survives re-resolution, and it is bounded to one section rather than
    the whole document.
    """
    counters: dict[str | None, int] = {}
    ordinals: list[int] = []
    for mention in mentions:
        section = mention.provenance.section if mention.provenance else None
        ordinal = counters.get(section, 0)
        counters[section] = ordinal + 1
        ordinals.append(ordinal)
    return ordinals
