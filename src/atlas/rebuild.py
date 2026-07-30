"""Comparing two builds of the same thing.

Everything downstream of this project asks one question in different words:
did rebuilding change anything? A full rebuild against an incremental one, a
shuffled corpus against a sorted one, today's build against yesterday's. The
answer has to be a single unambiguous bit, and when the bit is "yes" it has to
be followed by *where*.

The comparison is byte-identity of a canonical form, not field sampling. A
section that comes back one entry short, or in a different order, is exactly
what a partial comparison waves through -- and it is the failure mode this
project exists to eliminate, so the check cannot be the weaker one.

One exclusion list
------------------
Wall-clock fields have to be dropped before comparing: ``built_at`` differs
between two builds by construction, so a raw comparison fails for the one
reason nobody cares about. That list already exists -- ``canonical_for_hash``
owns it, and the assertion ids and the fingerprint already use it. This module
calls it rather than restating it. Two lists would drift, and the symptom
would be a rebuild that reports a difference in a field that was never meant
to be compared, which teaches everyone to ignore the check.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from atlas.assertions.hashing import canonical_for_hash
from atlas.company.model import CompanyProfile
from atlas.company.store import (
    CompanyStore,
    ProfileSource,
    diff_profiles,
    load_results,
)


def canonical_profile(payload: Any) -> str:
    """Return the canonical string form of a serialised profile."""
    return canonical_for_hash(payload)


def profile_digest(payload: Any) -> str:
    """Return a stable digest of *payload*'s canonical form.

    For recording in a log or a store-status line, where carrying the whole
    canonical document would be absurd but "did this move" still needs an
    answer that survives a process boundary.
    """
    return hashlib.sha256(canonical_profile(payload).encode("utf-8")).hexdigest()


def profiles_match(left: Any, right: Any) -> bool:
    """Whether two serialised profiles are identical once canonicalised."""
    return canonical_profile(left) == canonical_profile(right)


def explain_difference(left: Any, right: Any) -> list[str]:
    """Return human-readable differences between two serialised profiles.

    Empty when they match. Delegates to ``diff_profiles`` so the rebuild
    check and ``atlas profile diff`` describe a difference the same way --
    someone debugging a red gate should not have to learn a second format.
    """
    if profiles_match(left, right):
        return []
    return diff_profiles(left, right)


# ---------------------------------------------------------------------------
# Orchestration (#29)
# ---------------------------------------------------------------------------

#: Where a rebuild starts from.
#:
#: ``evidence`` runs the whole pipeline -- parse, analyze, write assertions,
#: project a profile -- and is what you use after changing an analyzer.
#: ``assertions`` skips straight to projecting from what the store already
#: holds, and is what you use after changing the builder. The second is the
#: reason the store exists: re-deriving a profile without re-reading a
#: document.
RebuildSource = Literal["evidence", "assertions"]

PROFILE_FILENAME = "profile.json"


@dataclass(frozen=True)
class RebuildResult:
    """What a rebuild produced, and whether it changed anything.

    ``changed`` is None when there was nothing to compare against -- a first
    build. That is different from False, which means a rebuild ran and the
    profile came out identical, and the two must not be collapsed: "nothing
    changed" is reassuring, "there was nothing to change from" is not.

    ``reanalyzed`` names the documents a ``--stale-only`` run re-ran, and is
    empty for every other mode -- including a stale-only run that found
    nothing to do, which is the answer that makes the flag worth having.
    ``documents`` still counts the whole corpus the profile was built from,
    because that is what the profile covers.
    """

    profile: CompanyProfile
    source: RebuildSource
    documents: int
    written_to: Path | None
    changed: bool | None
    differences: tuple[str, ...] = ()
    reanalyzed: tuple[str, ...] = ()


def rebuild(
    root: Path,
    company_id: str,
    *,
    source: RebuildSource = "assertions",
    verify: bool = False,
    stale_only: bool = False,
    on_error: Callable[[str], None] | None = None,
) -> RebuildResult:
    """Rebuild *company_id*'s profile and report whether it moved.

    With ``verify=True`` nothing is written: the profile is built, compared
    against the stored one, and discarded. That is what makes it safe to run
    against a repository someone else is relying on -- the check cannot be the
    thing that breaks it.

    With ``stale_only=True`` only the documents the running build cannot serve
    are re-analysed, and the rest of the profile comes from rows already in
    the store. Requires ``source="evidence"``: staleness is fixed by re-running
    an analyzer, and reading the store again returns the same stale rows.

    Orchestration only. Every stage already exists and is tested on its own;
    this decides the order and compares the ends, and deliberately contains no
    extraction, assembly or serialisation logic of its own.
    """
    from atlas.assertions.store import AssertionStore
    from atlas.assertions.writer import write_result
    from atlas.company.builder import build_profile
    from atlas.provenance import current_fingerprint

    if stale_only:
        if source != "evidence":
            raise ValueError(
                "--stale-only re-analyses documents, so it needs "
                "--from evidence; reading the assertion store again returns "
                "the same stale rows"
            )
        return _rebuild_stale_only(root, company_id, verify=verify, on_error=on_error)

    report = load_results(root, source=_load_source(source), on_error=on_error)

    if source == "evidence":
        # The store is refreshed from what the analyzers just produced, so a
        # later --from assertions rebuild sees this run's output rather than
        # the previous one's.
        store = AssertionStore(root)
        # The object, not its digest: the writer derives both the whole digest
        # and the per-kind sub-digest from it, and two separately-passed
        # strings could come from different builds.
        fingerprint = current_fingerprint()
        for result in report.results:
            write_result(store, result, fingerprint=fingerprint)

    profile = build_profile(company_id, report.results)
    path = root / PROFILE_FILENAME
    previous = _stored_payload(path)

    if verify:
        candidate = _serialised(profile, report.results, company_id)
        changed, differences = _compare(previous, candidate)
        return RebuildResult(
            profile=profile,
            source=source,
            documents=len(report.results),
            written_to=None,
            changed=changed,
            differences=differences,
        )

    CompanyStore(path, company_id).save(profile, report.results)
    written = _stored_payload(path)
    assert written is not None  # just written by the line above
    changed, differences = _compare(previous, written)
    return RebuildResult(
        profile=profile,
        source=source,
        documents=len(report.results),
        written_to=path,
        changed=changed,
        differences=differences,
    )


def _rebuild_stale_only(
    root: Path,
    company_id: str,
    *,
    verify: bool,
    on_error: Callable[[str], None] | None,
) -> RebuildResult:
    """Re-analyse only what this build cannot serve, then project.

    The narrow set comes from ``stale_evidence_ids()``, which compares the
    per-kind sub-digest: a bump to one analyzer condemns that kind's documents
    and leaves the other ten alone. Every document it does not name is served
    from rows already in the store, unread and unrewritten -- which is the
    whole economy of the flag, and the invariant #77 checks by counting rows.

    The profile is then built from the store rather than from what was just
    analysed, so re-analysed and untouched documents reach the builder through
    one path. Merging two lists here would make the profile depend on which
    documents happened to be stale.

    A document with no run at all is NOT in scope. Nothing produced rows this
    build cannot serve, so it is new evidence rather than stale evidence, and
    ingesting it is what a full ``--from evidence`` rebuild does. Widening the
    flag to cover it would make its cost depend on how much unanalysed
    evidence the repository happens to hold, which is the unpredictability the
    flag exists to remove.
    """
    from atlas.assertions.reader import current_results, results_for
    from atlas.assertions.store import AssertionStore
    from atlas.assertions.writer import write_result
    from atlas.company.builder import build_profile
    from atlas.provenance import current_fingerprint

    fingerprint = current_fingerprint()
    store = AssertionStore(root)
    stale = store.stale_evidence_ids()
    fresh = (
        load_results(root, source="analyzers", only=stale, on_error=on_error).results
        if stale
        else []
    )

    if verify:
        # Nothing written, so the store still holds the stale rows: the
        # candidate corpus is what the store can serve plus what was just
        # analysed for the documents it cannot.
        results = current_results(store, fingerprint=fingerprint)
        results.extend(fresh)
        results.sort(key=lambda result: (result.source_date, result.evidence_id))
    else:
        for result in fresh:
            write_result(store, result, fingerprint=fingerprint)
        results = results_for(root)

    profile = build_profile(company_id, results)
    path = root / PROFILE_FILENAME
    previous = _stored_payload(path)
    reanalyzed = tuple(sorted(result.evidence_id for result in fresh))

    if verify:
        changed, differences = _compare(
            previous, _serialised(profile, results, company_id)
        )
        return RebuildResult(
            profile=profile,
            source="evidence",
            documents=len(results),
            written_to=None,
            changed=changed,
            differences=differences,
            reanalyzed=reanalyzed,
        )

    CompanyStore(path, company_id).save(profile, results)
    written = _stored_payload(path)
    assert written is not None  # just written by the line above
    changed, differences = _compare(previous, written)
    return RebuildResult(
        profile=profile,
        source="evidence",
        documents=len(results),
        written_to=path,
        changed=changed,
        differences=differences,
        reanalyzed=reanalyzed,
    )


def _load_source(source: RebuildSource) -> ProfileSource:
    """Map a rebuild source onto the profile source that supplies it.

    ``--from evidence`` means re-run the analyzers; ``--from assertions``
    means read the store. The two vocabularies stay separate because they
    answer different questions -- one is "where does this rebuild start", the
    other is "where do profiles come from by default".
    """
    return "analyzers" if source == "evidence" else "assertions"


def _stored_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    from atlas.company.store import load_profile_payload

    return load_profile_payload(path)


def _serialised(
    profile: CompanyProfile, results: Sequence[Any], company_id: str
) -> dict[str, Any]:
    """Serialise a profile the way saving it would, without saving it.

    Goes through the real writer into a discarded temporary file rather than
    reaching for the private serialiser, so --verify compares what --write
    would actually have produced.
    """
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / PROFILE_FILENAME
        CompanyStore(path, company_id).save(profile, results)
        from atlas.company.store import load_profile_payload

        return load_profile_payload(path)


def _compare(
    previous: dict[str, Any] | None, candidate: dict[str, Any]
) -> tuple[bool | None, tuple[str, ...]]:
    if previous is None:
        return None, ()
    differences = explain_difference(previous, candidate)
    return bool(differences), tuple(differences)
