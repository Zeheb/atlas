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
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.analysis.base import AnalysisResult
from atlas.analysis.registry import analyze, analyzer_versions
from atlas.assertions.model import Assertion, AssertionRun, assign_ordinals
from atlas.assertions.store import AssertionStore
from atlas.knowledge.base import KnowledgeBase, ParsedDocument


def result_to_rows(
    result: AnalysisResult, *, fingerprint: str
) -> tuple[AssertionRun, tuple[Assertion, ...]]:
    """Return the run row and assertion rows for *result*.

    Pure: no database, no clock. Everything time-dependent is carried on the
    result already, so the same result and fingerprint always produce the same
    rows -- which is what makes the ids comparable between a full rebuild and
    an incremental one.
    """
    ordinals = assign_ordinals(result.facts)
    assertions = tuple(
        Assertion.from_fact(
            fact,
            evidence_id=result.evidence_id,
            analyzer_version=result.analyzer_version,
            fingerprint=fingerprint,
            ordinal=ordinal,
        )
        for fact, ordinal in zip(result.facts, ordinals, strict=True)
    )
    run = AssertionRun(
        evidence_id=result.evidence_id,
        kind=result.kind,
        analyzer_version=result.analyzer_version,
        fingerprint=fingerprint,
        result_confidence=result.confidence,
        source_date=result.source_date,
        analyzed_at=result.analyzed_at,
        warnings=tuple(result.warnings),
        status="ok",
        error=None,
    )
    return run, assertions


def write_result(
    store: AssertionStore, result: AnalysisResult, *, fingerprint: str
) -> AssertionRun:
    """Persist *result* and return the run row that was written."""
    run, assertions = result_to_rows(result, fingerprint=fingerprint)
    store.write_run(run, assertions)
    return run


def failure_run(
    document: ParsedDocument,
    *,
    analyzer_version: str,
    fingerprint: str,
    error: str,
) -> AssertionRun:
    """Return the run row recording that analysis of *document* failed.

    ``result_confidence`` is ``"low"``: a run that produced nothing cannot
    claim otherwise, and the column is not nullable because every other run
    has a real value for it.
    """
    return AssertionRun(
        evidence_id=document.evidence_id,
        kind=document.kind,
        analyzer_version=analyzer_version,
        fingerprint=fingerprint,
        result_confidence="low",
        source_date=datetime.fromisoformat(document.source_date),
        analyzed_at=datetime.now(timezone.utc),
        warnings=(),
        status="failed",
        error=error,
    )


def analyze_and_write(
    evidence_id: str,
    kb: KnowledgeBase,
    store: AssertionStore,
    *,
    fingerprint: str,
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
