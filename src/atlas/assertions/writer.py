"""Turning one ``AnalysisResult`` into rows, including the runs that failed.

The mapping itself is mechanical -- facts become assertions, the envelope
becomes a run row -- and lives in one place so that the CLI, the backfill and
the tests cannot each grow their own slightly different version of it.

Two parts are not mechanical.

Ordinals
--------
``assign_ordinals`` is called here, over ``result.facts`` in the order the
analyzer emitted them, and nowhere else. That order is the only thing
distinguishing facts that agree on every hashed component -- ``annual_report``
emits every ``RISK_FACTOR`` in one loop with the same section and the same
section-level ``char_offset`` -- so recomputing ordinals anywhere downstream,
against rows that no longer carry emission order, would mint different ids for
the same facts.

Failed runs
-----------
A failed run is written, not skipped. "This document was analyzed and the
analyzer raised" and "this document has never been analyzed" are different
states that call for different actions: the first is a bug to fix, the second
is work to do. Dropping the failure collapses them, and the store then reports
the document as pending forever.

This is the one place that catches an analyzer's exceptions broadly. An
analyzer is a large body of parsing code over documents that arrive from the
outside world; the failure modes are not enumerable, and the point of catching
them is precisely that any of them must be recorded rather than propagated
into an aborted batch. C3's named-exceptions rule constrains the migration and
store code, where every failure mode *is* known.

The fingerprint arrives as an object, not a digest
--------------------------------------------------
Every function here takes a ``BuildFingerprint``, and the two values that
reach the database -- ``fingerprint`` (the whole build) and ``affects_digest``
(just what can change this kind) -- are derived from that one instance at the
row-building step. Taking two strings instead would let a caller pass a whole
digest from one build and a sub-digest from another, and the result would be a
row that reads as current under one test and stale under the other. Nothing
downstream could detect it: both columns would look like perfectly good
hashes. Deriving both from one object makes the inconsistent pair
unrepresentable rather than merely discouraged.

The split happens here, at the persistence boundary, because this is where
rows are built. ``Assertion`` and ``Mention`` take the whole digest only --
their tables have no sub-digest column, since invalidation is decided per run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from atlas.analysis.base import AnalysisResult
from atlas.analysis.registry import analyze, analyzer_versions
from atlas.assertions.model import (
    Assertion,
    AssertionRun,
    Mention,
    assign_mention_ordinals,
    assign_ordinals,
)
from atlas.assertions.store import AssertionStore
from atlas.knowledge.base import KnowledgeBase, ParsedDocument

if TYPE_CHECKING:
    # Type-only: this module calls methods on a BuildFingerprint and never
    # constructs one, so there is no runtime import and no import cycle to
    # route around.
    from atlas.provenance import BuildFingerprint


def result_to_rows(
    result: AnalysisResult, *, fingerprint: BuildFingerprint
) -> tuple[AssertionRun, tuple[Assertion, ...]]:
    """Return the run row and assertion rows for *result*.

    Pure: no database, no clock. Everything time-dependent is carried on the
    result already, so the same result and fingerprint always produce the same
    rows -- which is what makes the ids comparable between a full rebuild and
    an incremental one.

    Both stamped values come from *fingerprint* itself, so the whole digest
    and the per-kind sub-digest always describe the same build.

    Raises ``ValueError`` (from ``affects``) if ``result.kind`` has no
    registered analyzer. That state is unreachable through the normal path --
    a result exists because an analyzer produced it -- and raising beats
    storing a NULL sub-digest, which would silently mark the row
    permanently stale.
    """
    digest = fingerprint.digest()
    ordinals = assign_ordinals(result.facts)
    assertions = tuple(
        Assertion.from_fact(
            fact,
            evidence_id=result.evidence_id,
            analyzer_version=result.analyzer_version,
            fingerprint=digest,
            ordinal=ordinal,
        )
        for fact, ordinal in zip(result.facts, ordinals, strict=True)
    )
    run = AssertionRun(
        evidence_id=result.evidence_id,
        kind=result.kind,
        analyzer_version=result.analyzer_version,
        fingerprint=digest,
        result_confidence=result.confidence,
        source_date=result.source_date,
        analyzed_at=result.analyzed_at,
        warnings=tuple(result.warnings),
        status="ok",
        error=None,
        affects_digest=fingerprint.affects(result.kind),
    )
    return run, assertions


def result_to_mentions(
    result: AnalysisResult, *, fingerprint: BuildFingerprint
) -> tuple[Mention, ...]:
    """Return the entity-mention rows for *result*.

    Separate from ``result_to_rows`` because entities are the envelope's third
    output category and most analyzers emit none; keeping them apart means the
    fact mapping does not have to mention them at all.

    Ordinals come from ``assign_mention_ordinals`` over emission order, for the
    reason facts have them: a transcript names one analyst repeatedly in one
    section, and the mentions would otherwise hash identically.
    """
    digest = fingerprint.digest()
    ordinals = assign_mention_ordinals(result.entities)
    return tuple(
        Mention.from_mention(
            mention,
            evidence_id=result.evidence_id,
            analyzer_version=result.analyzer_version,
            fingerprint=digest,
            ordinal=ordinal,
        )
        for mention, ordinal in zip(result.entities, ordinals, strict=True)
    )


def write_result(
    store: AssertionStore, result: AnalysisResult, *, fingerprint: BuildFingerprint
) -> AssertionRun:
    """Persist *result* -- facts and entity mentions together -- and return
    the run row that was written.

    One ``BuildFingerprint`` reaches both row builders, so the run's whole
    digest, its sub-digest, and every assertion and mention written alongside
    it describe the same build.
    """
    run, assertions = result_to_rows(result, fingerprint=fingerprint)
    mentions = result_to_mentions(result, fingerprint=fingerprint)
    store.write_run(run, assertions, mentions)
    return run


def failure_run(
    document: ParsedDocument,
    *,
    analyzer_version: str,
    fingerprint: BuildFingerprint,
    error: str,
) -> AssertionRun:
    """Return the run row recording that analysis of *document* failed.

    ``result_confidence`` is ``"low"``: a run that produced nothing cannot
    claim otherwise, and the column is not nullable because every other run
    has a real value for it.

    The sub-digest is stamped on a failure too. "This build tried and failed"
    has to be distinguishable from "an older build tried and failed", or a
    re-analysis after fixing the analyzer would look like work already done.
    """
    return AssertionRun(
        evidence_id=document.evidence_id,
        kind=document.kind,
        analyzer_version=analyzer_version,
        fingerprint=fingerprint.digest(),
        result_confidence="low",
        source_date=datetime.fromisoformat(document.source_date),
        analyzed_at=datetime.now(timezone.utc),
        warnings=(),
        status="failed",
        error=error,
        affects_digest=fingerprint.affects(document.kind),
    )


def analyze_and_write(
    evidence_id: str,
    kb: KnowledgeBase,
    store: AssertionStore,
    *,
    fingerprint: BuildFingerprint,
) -> AssertionRun:
    """Analyze one document and persist the outcome, success or failure.

    Returns the run row that was written, so a caller can report what happened
    without a second read.

    Two conditions raise instead of being recorded, because neither produces a
    row that could be keyed: a document the knowledge base has never seen, and
    a document whose kind has no registered analyzer. There is no analyzer
    version to record the attempt against, and inventing one would put a run
    in the store that no later version comparison could interpret.
    """
    document = kb.get(evidence_id)
    if document is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    versions = analyzer_versions()
    if document.kind not in versions:
        raise ValueError(
            f"no analyzer registered for kind={document.kind!r}; "
            f"supported kinds: {sorted(versions)}"
        )

    try:
        result = analyze(evidence_id, kb)
    except Exception as exc:  # noqa: BLE001 - see module docstring
        run = failure_run(
            document,
            analyzer_version=versions[document.kind],
            fingerprint=fingerprint,
            error=f"{type(exc).__name__}: {exc}",
        )
        store.write_run(run, ())
        return run

    return write_result(store, result, fingerprint=fingerprint)
