"""Rows back into facts, in an order that does not depend on SQLite.

Two rules live here, and both exist to stop a wrong answer from looking like
a right one.

Which version wins
------------------
The run key ``(evidence_id, analyzer_version)`` admits several versions of the
same document, and something has to choose. The rule is: **the highest
analyzer version whose stored fingerprint matches the current build; if none
matches, raise.**

Raising is the point. The alternative -- falling back to the newest row that
exists -- answers every query with facts extracted by code that is no longer
running, and nothing downstream can tell. A profile built that way is wrong in
a way no test of the profile itself can catch. An empty store and a stale
store are different problems, and only one of them is fixed by re-analyzing.

Failed runs are candidates like any other. A run that was attempted under the
current build and raised is the current state of that document; skipping it to
reach an older successful run would report facts that the current code does
not produce. The reconstructed result carries ``status`` so the caller can see
which it got.

What order they come back in
----------------------------
``(source_date, evidence_id, assertion_id)``. SQLite's natural order is an
implementation detail of the file, not a promise, and ``build_profile`` sorts
by ``(priority, source_date)`` with a *stable* sort -- so results that tie on
that key keep the order they arrived in. Feed the builder rows in file order
and two runs of the same data can produce two different profiles. The
tie-breakers are content, not arrival: ``source_date`` first because it is
what the builder itself orders on, then ``evidence_id``, then the content
address.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from atlas.analysis.base import AnalysisFact, AnalysisResult
from atlas.assertions.model import AssertionRun
from atlas.assertions.store import AssertionStore


class StaleAssertionsError(RuntimeError):
    """No stored run for a document matches the current build fingerprint.

    Named, so a caller can act on it -- re-analyze the document -- instead of
    treating it as an unspecified read failure or, worse, as an empty store.
    """


def version_key(analyzer_version: str) -> tuple[int, ...]:
    """Return a sortable key for a dotted version string.

    Compared segment by segment as integers, so ``"10.0"`` sorts above
    ``"9.0"``; string comparison would put it below and quietly prefer the
    older analyzer once versions reach double digits. Non-numeric segments
    sort as 0 rather than raising: an unparseable version is a labelling
    mistake, and refusing to read the store over it would be a larger failure
    than ordering it conservatively.
    """
    key: list[int] = []
    for segment in analyzer_version.split("."):
        key.append(int(segment) if segment.isdigit() else 0)
    return tuple(key)


def select_run(runs: Sequence[AssertionRun], *, fingerprint: str) -> AssertionRun:
    """Return the run to read, or raise if none was produced by this build.

    A pure function of the runs given: the same set in any order returns the
    same run, because the choice is made on version and fingerprint, never on
    position.
    """
    matching = [run for run in runs if run.fingerprint == fingerprint]
    if not matching:
        stored = sorted({run.fingerprint for run in runs})
        raise StaleAssertionsError(
            f"no stored run matches the current fingerprint {fingerprint!r}; "
            f"stored fingerprints: {stored or ['none']}"
        )
    return max(matching, key=lambda run: version_key(run.analyzer_version))


def read_result(
    store: AssertionStore, evidence_id: str, *, fingerprint: str
) -> AnalysisResult:
    """Rebuild the AnalysisResult for *evidence_id* under the current build.

    ``entities`` is reattached from the stored mentions, ordered by mention id
    on the same principle as the facts: content, not row position.

    ``excerpts`` comes back empty. The store never held it: section bodies are
    hundreds to thousands of characters each and nothing downstream reads them
    (``builder.py`` contains no reference to ``.excerpts``). This is the one
    documented loss in the round trip.
    """
    run = select_run(store.runs_for(evidence_id), fingerprint=fingerprint)
    stored = store.read_run(evidence_id, run.analyzer_version)
    if stored is None:  # pragma: no cover - runs_for just returned this key
        raise StaleAssertionsError(
            f"run ({evidence_id}, {run.analyzer_version}) vanished mid-read"
        )
    # read_run already returns assertions ordered by id, which is the
    # within-document tie-breaker: content, not row position.
    facts = [item.to_fact() for item in stored.assertions]
    entities = [item.to_mention() for item in stored.mentions]
    return AnalysisResult(
        evidence_id=run.evidence_id,
        kind=run.kind,
        analyzer_version=run.analyzer_version,
        confidence=run.result_confidence,
        source_date=run.source_date,
        analyzed_at=run.analyzed_at,
        warnings=list(run.warnings),
        facts=facts,
        excerpts={},
        entities=entities,
    )


def read_results(store: AssertionStore, *, fingerprint: str) -> list[AnalysisResult]:
    """Rebuild every document's result, ordered by ``(source_date, evidence_id)``.

    Raises ``StaleAssertionsError`` on the first document with no run from this
    build. Skipping it instead would hand the builder a partial corpus that
    looks complete -- the exact shape of failure the fingerprint exists to
    prevent.
    """
    results = [
        read_result(store, evidence_id, fingerprint=fingerprint)
        for evidence_id in store.evidence_ids()
    ]
    results.sort(key=lambda result: (result.source_date, result.evidence_id))
    return results


def results_for(root: Path, *, fingerprint: str | None = None) -> list[AnalysisResult]:
    """Rebuild every result in one company repository, ready for the builder.

    The entry point M3 routes profile builds through. It takes the repository
    root rather than a company id because the store is per-repository and
    holds no company id anywhere; resolving one would mean reaching into
    settings from inside Tier 1, which is a dependency this layer does not
    otherwise have.

    *fingerprint* defaults to the current build's, which is the only value a
    caller should normally pass. It stays an argument so a test can ask what
    the store holds for some other build without monkeypatching provenance.
    """
    # Local import: provenance pulls in the registry and the builder, and this
    # module is imported by company.store, which the builder must not depend
    # on in either direction.
    from atlas.provenance import current_fingerprint

    digest = current_fingerprint().digest() if fingerprint is None else fingerprint
    return read_results(AssertionStore(root), fingerprint=digest)


def read_facts(store: AssertionStore, *, fingerprint: str) -> list[AnalysisFact]:
    """Return every fact in the store, in ``(source_date, evidence_id, id)`` order."""
    return [
        fact
        for result in read_results(store, fingerprint=fingerprint)
        for fact in result.facts
    ]
