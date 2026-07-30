"""The round-trip invariant, written once for both variants.

``write(analyze(x))`` then ``read(x)`` must return the same facts. "Same" is
defined here, deliberately narrowly:

``(kind, value, value type, unit, period, confidence, provenance)``

Value *type* is part of it. The store column is text, so a lost ``value_type``
turns ``5`` into ``"5"`` and every comparison downstream still passes -- the
one failure this check exists to catch would be invisible to an equality test
that let Python coerce.

Order is not part of it. Facts come back ordered by content address, not by
emission order, so the comparison is a multiset. What must not change is
which facts exist and what they say.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    EntityMention,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.assertions.reader import read_result
from atlas.assertions.store import AssertionStore
from atlas.assertions.writer import write_result
from atlas.knowledge.entities.model import Entity
from atlas.provenance import BuildFingerprint, current_fingerprint

#: The writer takes a ``BuildFingerprint``, not a digest string, so that a
#: run's whole digest and its per-kind sub-digest cannot come from different
#: builds. Tests therefore need a real one.
#:
#: The running build's, rather than a synthetic fingerprint with two invented
#: analyzers: ``affects(kind)`` raises for a kind with no registered analyzer,
#: and these helpers are used across all eleven.
FINGERPRINT = current_fingerprint()


def foreign_fingerprint() -> BuildFingerprint:
    """A fingerprint from a build that is not this one.

    Every digest it produces -- whole and per-kind -- differs from
    ``FINGERPRINT``'s, because ``parser_version`` feeds both. That is what
    "written by another build" actually means, and it is stronger than the
    invented digest strings these tests used before: an arbitrary string could
    never have been produced by any build, so it could not exercise the
    comparison the way a real competing fingerprint does.
    """
    return dataclasses.replace(FINGERPRINT, parser_version="parser-from-elsewhere")


def fact_key(fact: AnalysisFact) -> tuple[str, ...]:
    """Return the comparison key for one fact, everything stringified.

    Strings rather than the raw values so the key is hashable (``Provenance``
    is a mutable dataclass) and sortable regardless of ``None``. The type name
    is carried separately, so ``5`` and ``"5"`` produce different keys.
    """
    provenance = fact.provenance
    return (
        fact.kind.value,
        type(fact.value).__name__,
        repr(fact.value),
        fact.unit.value if fact.unit else "",
        fact.period or "",
        fact.confidence,
        provenance.section,
        "" if provenance.char_offset is None else str(provenance.char_offset),
        provenance.excerpt or "",
    )


def fact_multiset(facts: Sequence[AnalysisFact]) -> Counter[tuple[str, ...]]:
    return Counter(fact_key(fact) for fact in facts)


def mention_key(mention: EntityMention) -> tuple[str, ...]:
    """Return the comparison key for one entity mention.

    Includes every context field, because those are the whole reason
    ``EntityMention`` wraps ``Entity`` rather than being one: a round trip that
    kept the name and dropped the role would look correct in any test that
    compared names.
    """
    entity = mention.entity
    provenance = mention.provenance
    return (
        entity.entity_id,
        entity.kind,
        entity.canonical_name,
        "|".join(sorted(entity.aliases)),
        mention.role or "",
        mention.affiliation or "",
        mention.identifier or "",
        mention.question_text or "",
        "none" if provenance is None else provenance.section,
        (
            ""
            if provenance is None or provenance.char_offset is None
            else str(provenance.char_offset)
        ),
        "" if provenance is None else (provenance.excerpt or ""),
    )


def mention_multiset(
    mentions: Sequence[EntityMention],
) -> Counter[tuple[str, ...]]:
    return Counter(mention_key(mention) for mention in mentions)


def assert_round_trip(
    root: Path,
    result: AnalysisResult,
    *,
    fingerprint: BuildFingerprint = FINGERPRINT,
) -> AnalysisResult:
    """Write *result*, read it back, and assert nothing changed.

    Returns the restored result so a caller can make further assertions on it.

    The writer takes the fingerprint object; the reader takes its digest,
    because selecting which stored run to serve is a whole-build question.
    """
    store = AssertionStore(root)
    write_result(store, result, fingerprint=fingerprint)
    restored = read_result(store, result.evidence_id, fingerprint=fingerprint.digest())

    assert fact_multiset(restored.facts) == fact_multiset(result.facts)
    assert mention_multiset(restored.entities) == mention_multiset(result.entities)
    assert restored.evidence_id == result.evidence_id
    assert restored.kind == result.kind
    assert restored.analyzer_version == result.analyzer_version
    assert restored.confidence == result.confidence
    assert restored.source_date == result.source_date
    assert restored.analyzed_at == result.analyzed_at
    assert restored.warnings == list(result.warnings)
    return restored


# ---------------------------------------------------------------------------
# Synthetic inputs — the CI variant
# ---------------------------------------------------------------------------


def make_fact(
    kind: FactKind,
    value: str | int | float | None,
    *,
    unit: FactUnit | None = None,
    period: str | None = "2026-03-31",
    section: str = "body",
    char_offset: int | None = 42,
    excerpt: str | None = "a short verbatim excerpt",
    confidence: str = "high",
) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence=confidence,  # type: ignore[arg-type]
        provenance=Provenance(
            section=section, char_offset=char_offset, excerpt=excerpt
        ),
    )


def make_result(
    evidence_kind: str,
    *,
    facts: list[AnalysisFact] | None = None,
    entities: list[EntityMention] | None = None,
    analyzer_version: str = "1.0",
    warnings: list[str] | None = None,
) -> AnalysisResult:
    """Return a result shaped like *evidence_kind*'s analyzer would produce."""
    return AnalysisResult(
        evidence_id=f"ev-{evidence_kind}",
        kind=evidence_kind,
        analyzer_version=analyzer_version,
        confidence="high",
        source_date=datetime(2026, 4, 9, tzinfo=timezone.utc),
        analyzed_at=datetime(2026, 7, 29, 10, 30, tzinfo=timezone.utc),
        warnings=warnings if warnings is not None else ["one non-fatal warning"],
        facts=facts if facts is not None else default_facts(),
        entities=entities if entities is not None else default_entities(),
    )


def default_entities() -> list[EntityMention]:
    """Mentions covering the states the store has to reproduce.

    An analyst asked twice from one section (the ordinal case), a director
    carrying a DIN (the ``identifier`` field, which nothing else exercises),
    and a mention with no provenance at all -- a state ``EntityMention``
    permits and a reader must restore as None rather than as an empty one.
    """
    analyst = Entity(
        entity_id="person-analyst",
        kind="person",
        canonical_name="K S Rao",
        aliases=frozenset({"KS Rao", "Rao"}),
    )
    return [
        EntityMention(
            entity=analyst,
            role="analyst",
            affiliation="Kotak Institutional Equities",
            question_text="What drove the margin expansion?",
            provenance=Provenance(section="qa", char_offset=1200, excerpt="Rao asked"),
        ),
        EntityMention(
            entity=analyst,
            role="analyst",
            affiliation="Kotak Institutional Equities",
            question_text="And on attrition?",
            provenance=Provenance(section="qa", char_offset=1200, excerpt="Rao asked"),
        ),
        EntityMention(
            entity=Entity(
                entity_id="person-director",
                kind="person",
                canonical_name="N Chandrasekaran",
            ),
            role="chairman",
            identifier="DIN-00121863",
            provenance=Provenance(section="board", char_offset=None),
        ),
        EntityMention(
            entity=Entity(
                entity_id="org-auditor",
                kind="organization",
                canonical_name="B S R & Co. LLP",
            ),
            role="auditor",
        ),
    ]


def default_facts() -> list[AnalysisFact]:
    """Facts covering every hazard the round trip has to survive.

    Each entry earns its place: the two identical risk strings are the
    ``annual_report`` loop that made ``ordinal`` necessary; the offsetless
    fact is the six emission sites that pass ``char_offset=None``; the
    numeric spread is the value-type fidelity case.
    """
    return [
        make_fact(FactKind.RISK_FACTOR, "Cyber security risk", section="mda_risk"),
        make_fact(FactKind.RISK_FACTOR, "Cyber security risk", section="mda_risk"),
        make_fact(
            FactKind.FINANCIAL_REVENUE,
            64988,
            unit=FactUnit.CRORE_INR,
            section="p_and_l",
        ),
        make_fact(
            FactKind.FINANCIAL_OPERATING_MARGIN,
            24.5,
            unit=FactUnit.PERCENT,
            section="p_and_l",
        ),
        make_fact(
            FactKind.OWNERSHIP_PROMOTER_PCT,
            None,
            unit=None,
            period=None,
            char_offset=None,
            excerpt=None,
            confidence="low",
            section="shareholding",
        ),
    ]
