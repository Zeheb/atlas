"""Multi-exchange evidence resolution — foundation for treating BSE and NSE
(and, later, a company's own investor-relations site) as complementary
sources rather than one authoritative feed.

Nothing here is BSE- or NSE-specific. It operates entirely on the existing,
already-exchange-agnostic Connector protocol types (Evidence, EvidenceSource,
DiscoveryResult) — the "one canonical evidence object regardless of source"
the acquisition layer should expose is just Evidence itself; no new type was
needed, since Evidence already carries a `source: EvidenceSource` field.
What was missing was the orchestration to run more than one connector for
the same company and reconcile their results, which is what this module adds.

No NSE connector exists yet (deliberately, per this sprint's scope — see
the Connector v2 proposal in the retrospective for what a real NSE connector
would plug into). resolve_multi_source() is fully exercised today with a
single source (a `[result]` list of size one resolves
trivially, every existing single-connector acquisition run is unaffected)
and is tested against synthetic multi-source scenarios so the merge logic
itself is proven before a second real connector ever exists to feed it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Callable

from atlas.acquisition.connectors.connector import DiscoveryResult, DiscoveryWarning
from atlas.acquisition.evidence import Evidence, EvidenceSource

# Two documents from different exchanges are presumed to be the same
# real-world filing when they share a kind and were filed on the same
# calendar day — companies file the same disclosure to every exchange
# they're listed on essentially simultaneously for regulatory compliance.
# This intentionally does *not* match on title (BSE and NSE routinely
# phrase the same filing's headline differently) or on document_url
# (exchange-specific by construction).
_MatchKey = tuple[str, str]


def _match_key(evidence: Evidence) -> _MatchKey:
    return (evidence.kind.value, evidence.source_date.date().isoformat())


def _default_quality_preference(a: Evidence, b: Evidence) -> Evidence:
    """Pick the better of two same-filing copies from different exchanges.

    Preferred over reaching for anything content-based (nothing has been
    downloaded yet at this stage — evidence discovery happens before any
    byte is fetched) — file_size_bytes is the only quality signal available
    pre-download, and a larger file is a reasonable proxy for "the complete
    document" versus a possible truncated/placeholder copy. Falls back to a
    stable, documented tiebreak (BSE) when sizes are equal or unknown,
    rather than an arbitrary dict-ordering accident.
    """
    a_size = a.file_size_bytes or 0
    b_size = b.file_size_bytes or 0
    if a_size != b_size:
        return a if a_size > b_size else b
    return a if a.source == EvidenceSource.BSE else b


def resolve_multi_source(
    results: Sequence[DiscoveryResult],
    quality_preference: Callable[
        [Evidence, Evidence], Evidence
    ] = _default_quality_preference,
) -> DiscoveryResult:
    """Merge per-connector DiscoveryResults into one deduplicated result.

    Takes a plain sequence, not a dict keyed by EvidenceSource — the merge
    logic groups by each Evidence's own `.source` field, not by anything
    the caller would have to supply externally, so there's no reason to
    make callers invent a key for each connector. One DiscoveryResult per
    connector called (today: just the one BSE connector; tomorrow: BSE +
    NSE + ...) is all a caller needs to assemble.

    Groups evidence across every source by (kind, filing date). A group
    with evidence from only one source passes through unchanged — this is
    the common case today (BSE only) and is a true no-op: with a single
    source, every group has exactly one member, so the returned evidence
    list is identical to the input, just re-assembled.

    A group with evidence from more than one source is a real duplicate:
    quality_preference picks one, and a DiscoveryWarning documents the
    decision (which source won, which was suppressed, why) — the
    "preserve provenance" requirement is met by the *evidence.source* field
    of whichever copy was kept; the warning additionally records that a
    duplicate existed and was suppressed, so a suppressed document is
    never silently invisible even though it wasn't downloaded.
    """
    groups: dict[_MatchKey, list[Evidence]] = defaultdict(list)
    for result in results:
        for evidence in result.evidence:
            groups[_match_key(evidence)].append(evidence)

    resolved: list[Evidence] = []
    warnings: list[DiscoveryWarning] = [w for r in results for w in r.warnings]

    for candidates in groups.values():
        distinct_sources = {c.source for c in candidates}
        # A clean cross-source duplicate is exactly one document per
        # source sharing this (kind, date) key. Two BSE announcements of
        # the same kind on the same day (an original + an amendment, say)
        # are *not* duplicates of each other just because a single-source
        # count would suggest otherwise — real, distinct filings from one
        # source must never collapse into one. Only collapse when every
        # candidate comes from a different source: that's the actual
        # "BSE and NSE both filed the same thing" scenario this exists for.
        if len(candidates) == 1 or len(distinct_sources) < len(candidates):
            resolved.extend(candidates)
            continue

        winner = candidates[0]
        for challenger in candidates[1:]:
            winner = quality_preference(winner, challenger)
        resolved.append(winner)

        suppressed = [c for c in candidates if c is not winner]
        warnings.append(
            DiscoveryWarning(
                source=winner.source,
                code="duplicate_across_exchanges",
                message=(
                    f"{winner.kind.value} filed {winner.source_date.date()}: kept the "
                    f"{winner.source.value} copy, suppressed {len(suppressed)} duplicate(s) "
                    f"from {sorted({c.source.value for c in suppressed})}"
                ),
                metadata={
                    "kept_evidence_id": winner.evidence_id,
                    "suppressed_evidence_ids": [c.evidence_id for c in suppressed],
                },
            )
        )

    return DiscoveryResult(evidence=resolved, warnings=warnings)
