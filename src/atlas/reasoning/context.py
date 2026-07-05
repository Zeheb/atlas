"""GroundingContext assembly (M0 commit 3; M1 commit 2 adds retrieval).

Turns a persisted ``CompanyProfile`` into the closed-world ``GroundingContext``
(C5) the reasoner is allowed to cite. Each profile record becomes one grounded
``Claim`` (C3) carrying the evidence_ids Atlas already recorded as its source —
so the grounding chain starts here, fully backed (G1/G10).

M0 grounded on the *structured* profile only (terse "kind = value" strings).
M1 adds an *optional* raw-text hydration pass: when a ``KnowledgeBase`` is
supplied, each claim's evidence is enriched with a verbatim excerpt from its
source document (via ``retrieval.fetch_and_match``) wherever a confident match
exists — strengthening semantic grounding by exposing the actual prose behind
a conclusion, not just its structured summary. ``kb=None`` (the default)
reproduces M0's behavior exactly: no retrieval is attempted, no cost is paid.

Retrieval is deliberately scoped to evidence_ids *already* present in the
profile-derived claims — it enriches existing evidence, it never introduces a
new citable id. This keeps the closed-world invariant trivially true (no new
ids appear in ``evidence_index``) and avoids an open-ended whole-corpus scan;
mining additional, previously-unextracted documents for new claims is an
extraction-layer capability for a later milestone, not M1's job.

Passing ``known_ids`` (e.g. ``KnowledgeBase.known_ids()``) enforces C2's identity
invariant at assembly: any evidence_id not resolvable in the KB is dropped, and
a claim left with no evidence is dropped with it — nothing unbacked survives.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import replace

from atlas.company.model import CompanyProfile
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning import retrieval as _retrieval
from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    GroundingContext,
    RetrievedEvidence,
    SubjectRef,
)

# Compactness guard so a very deep profile cannot blow the context budget.
_MAX_CLAIMS = 500

# Bound on distinct evidence_ids whose content is fetched from the KB per
# build_context() call — bounds DB reads, not the (cheap, cached) per-claim
# excerpt search against already-fetched content.
_MAX_HYDRATED_DOCS = 60


def build_context(
    profile: CompanyProfile,
    subject_ref: SubjectRef,
    *,
    known_ids: Iterable[str] | None = None,
    kb: KnowledgeBase | None = None,
) -> GroundingContext:
    """Assemble the GroundingContext for one company from its profile.

    ``known_ids`` — when supplied, the set of evidence_ids that resolve in the
    KnowledgeBase; references outside it are dropped (C2 identity invariant).
    ``kb`` — when supplied, raw-text retrieval hydrates claim evidence with
    verbatim excerpts (M1). Omit for M0-equivalent behavior (structured facts
    only, no retrieval attempted).
    """
    allowed: frozenset[str] | None = frozenset(known_ids) if known_ids is not None else None

    claims: list[Claim] = list(_iter_claims(profile, subject_ref, allowed))

    notes: list[str] = []
    if len(claims) > _MAX_CLAIMS:
        # Keep the most recent evidence (claims are appended roughly oldest-first
        # per time series); record the truncation rather than hiding it (G5).
        dropped = len(claims) - _MAX_CLAIMS
        claims = claims[-_MAX_CLAIMS:]
        notes.append(f"Truncated to {_MAX_CLAIMS} claims; {dropped} older claims omitted.")

    retrieved: tuple[RetrievedEvidence, ...] = ()
    if kb is not None:
        claims, retrieved, docs_capped = _hydrate_with_excerpts(claims, kb)
        if docs_capped:
            notes.append(
                f"Retrieval limited to {_MAX_HYDRATED_DOCS} distinct source "
                "documents; remaining citations kept without a verbatim excerpt."
            )

    evidence_index = frozenset(eid for c in claims for eid in c.evidence_ids)
    return GroundingContext(
        subject_ref=subject_ref,
        claims=tuple(claims),
        evidence_index=evidence_index,
        retrieved=retrieved,
        budget_note="; ".join(notes) if notes else None,
    )


# ---------------------------------------------------------------------------
# Raw-text hydration (M1)
# ---------------------------------------------------------------------------
def _hydrate_with_excerpts(
    claims: list[Claim], kb: KnowledgeBase
) -> tuple[list[Claim], tuple[RetrievedEvidence, ...], bool]:
    """Enrich each claim's evidence with a verbatim excerpt where a confident
    match exists. Never introduces a new evidence_id; leaves a reference bare
    when no content or no confident match is available (G5).
    """
    content_cache: dict[str, str | None] = {}
    retrieved: list[RetrievedEvidence] = []
    seen_spans: set[tuple[str, str]] = set()
    docs_capped = False

    hydrated_claims: list[Claim] = []
    for claim in claims:
        new_evidence: list[EvidenceReference] = []
        changed = False
        for ref in claim.evidence:
            if ref.evidence_id not in content_cache and len(content_cache) >= _MAX_HYDRATED_DOCS:
                docs_capped = True
                new_evidence.append(ref)
                continue
            match = _retrieval.fetch_and_match(
                kb, ref.evidence_id, claim.statement, content_cache=content_cache
            )
            if match is None:
                new_evidence.append(ref)
                continue
            hydrated_ref = replace(
                ref, excerpt=match.excerpt, char_offset=match.char_offset, section=match.section,
            )
            new_evidence.append(hydrated_ref)
            changed = True
            span_key = (ref.evidence_id, match.excerpt)
            if span_key not in seen_spans:
                seen_spans.add(span_key)
                retrieved.append(RetrievedEvidence(
                    evidence_ref=hydrated_ref, content_span=match.excerpt,
                    relevance=match.relevance,
                ))
        hydrated_claims.append(replace(claim, evidence=tuple(new_evidence)) if changed else claim)

    return hydrated_claims, tuple(retrieved), docs_capped


# ---------------------------------------------------------------------------
# Per-domain claim generation
# ---------------------------------------------------------------------------
def _iter_claims(
    profile: CompanyProfile,
    subject: SubjectRef,
    allowed: frozenset[str] | None,
) -> Iterator[Claim]:
    def refs(*ids: str | None) -> tuple[EvidenceReference, ...]:
        out: list[EvidenceReference] = []
        for eid in ids:
            if not eid:
                continue
            if allowed is not None and eid not in allowed:
                continue
            out.append(EvidenceReference(evidence_id=eid))
        return tuple(out)

    def fact(statement: str, sources: Sequence[str], period: str | None) -> Claim | None:
        evidence = refs(*sources)
        if not evidence:
            return None
        return Claim(
            subject_ref=subject,
            statement=statement,
            assertability="fact",
            confidence="high",
            evidence=evidence,
            period=period,
        )

    # Financial / ESG / Ownership snapshots — one claim per (period, fact).
    for fs in profile.financial.snapshots:
        for kind, value in fs.facts.items():
            c = fact(
                f"{kind.value} = {value} ({fs.period_type}, {fs.basis}, period {fs.period})",
                fs.sources, fs.period,
            )
            if c:
                yield c
    for es in profile.esg.snapshots:
        for kind, value in es.facts.items():
            c = fact(f"{kind.value} = {value} (period {es.period})", es.sources, es.period)
            if c:
                yield c
    for os_ in profile.ownership.snapshots:
        for kind, value in os_.facts.items():
            c = fact(f"{kind.value} = {value} (period {os_.period})", os_.sources, os_.period)
            if c:
                yield c

    # Segments.
    for seg in profile.segments.entries:
        parts = [f"Segment '{seg.name}' ({seg.period})"]
        if seg.revenue is not None:
            parts.append(f"revenue={seg.revenue}")
        if seg.ebit is not None:
            parts.append(f"EBIT={seg.ebit}")
        if seg.growth_pct is not None:
            parts.append(f"growth={seg.growth_pct}%")
        c = fact(", ".join(parts), [seg.evidence_id], seg.period)
        if c:
            yield c

    # Credit ratings (debt + ESG).
    for cr in [*profile.credit_history.debt_ratings, *profile.credit_history.esg_ratings]:
        desc = " ".join(
            p for p in [cr.agency, cr.instrument, cr.rating, cr.outlook, cr.action] if p
        )
        c = fact(
            f"Credit: {desc} (as of {cr.source_date.date().isoformat()})",
            [cr.evidence_id], cr.source_date.date().isoformat(),
        )
        if c:
            yield c

    # Strategy statements (guidance / priorities / aspirations) — verbatim text.
    for se in profile.strategy.entries:
        c = fact(
            f"[{se.kind}] {se.text} (stated {se.source_date.date().isoformat()})",
            [se.evidence_id], se.source_date.date().isoformat(),
        )
        if c:
            yield c

    # Governance: risk factors and director changes.
    for risk in profile.governance.risk_factors:
        c = fact(f"Risk factor ({risk.period}): {risk.text}", [risk.evidence_id], risk.period)
        if c:
            yield c
    for change in profile.governance.director_changes:
        role = f" ({change.role})" if change.role else ""
        c = fact(
            f"Board: {change.change_type} — {change.name}{role} "
            f"({change.source_date.date().isoformat()})",
            [change.evidence_id], change.source_date.date().isoformat(),
        )
        if c:
            yield c

    # Capital events.
    for div in profile.capital_events.dividends:
        c = fact(
            f"Dividend: {div.per_share} per share ({div.dividend_type}, "
            f"{div.source_date.date().isoformat()})",
            [div.evidence_id], div.source_date.date().isoformat(),
        )
        if c:
            yield c
    for bb in profile.capital_events.buybacks:
        c = fact(
            f"Buyback ({bb.sub_type}, {bb.source_date.date().isoformat()})",
            [bb.evidence_id], bb.source_date.date().isoformat(),
        )
        if c:
            yield c
    for acq in profile.capital_events.acquisitions:
        c = fact(
            f"Acquisition: {acq.target_name} ({acq.source_date.date().isoformat()})",
            [acq.evidence_id], acq.source_date.date().isoformat(),
        )
        if c:
            yield c
    for fr in profile.capital_events.fundraises:
        c = fact(
            f"Fundraise: {fr.fundraise_type} ({fr.source_date.date().isoformat()})",
            [fr.evidence_id], fr.source_date.date().isoformat(),
        )
        if c:
            yield c
