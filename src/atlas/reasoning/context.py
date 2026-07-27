"""GroundingContext assembly (M0 commit 3; M1 commit 2 adds retrieval; M1.5
commit 2 adds question-conditioned passage merging — ADR-M1.5).

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

M1.5 (ADR-M1.5) adds a second, optional pass: when a ``question`` is ALSO
supplied, ``retrieval.retrieve_passages`` scans the SAME candidate documents
(already fetched into the shared content cache during M1's hydration — zero
extra KB reads) for passages relevant to the *question itself*, not just to an
existing claim's statement. Each accepted passage becomes an ordinary
fact-``Claim`` merged into ``claims``. ``question=None`` (the default)
reproduces M0/M1 behavior exactly.

M1.7 (retrieval planning) adds an optional ``plan`` (a ``SearchPlan``, see
``plan.py``/``planner.py``): when supplied, the question-conditioned merge
calls ``retrieval.retrieve_with_plan`` instead of ``retrieve_passages``, so
doc-type/date/period preferences bias *ranking* of the same candidate pool —
never its membership (see retrieval.py's module docstring on why that keeps
this a strict superset-or-equal of the M1.5 result). ``plan=None`` (the
default) reproduces M1.5 behavior exactly, byte-identical. A ``plan`` may be
passed without ``question`` (the plan already carries its own
``raw_question``); passing both requires them to agree.

Retrieval — both M1's hydration and M1.5's question-conditioned merge — is
deliberately scoped to evidence_ids *already* present in the profile-derived
claims. This keeps the closed-world invariant trivially true (no new ids ever
appear in ``evidence_index``, since it is recomputed from the final claim set)
and avoids an open-ended whole-corpus scan; mining previously-unextracted
documents for new claims is an extraction-layer capability for a later
milestone, not this one's job.

Passing ``known_ids`` (e.g. ``KnowledgeBase.known_ids()``) enforces C2's identity
invariant at assembly: any evidence_id not resolvable in the KB is dropped, and
a claim left with no evidence is dropped with it — nothing unbacked survives.

M1.8 (ADR-0004) adds ``build_context_with_diagnostics``, which does the actual
assembly work and additionally returns the ``RetrievalResult`` the M1.7 plan-
aware merge produced (candidate counts, score breakdowns, etc.) — needed by
the eval harness to measure retrieval, not by production reasoning. ``build_
context`` itself is unchanged in signature AND return type: it is now a thin
delegate (``build_context_with_diagnostics(...).context``), so none of its
39 existing call sites needed to change. ``ContextBuildResult`` is internal —
not a §10 contract type, the same category as ``RetrievalMatch``/
``RetrievalResult`` in ``retrieval.py``. This was chosen over a mutable
``retrieval_sink`` out-parameter: everything else in this layer is frozen
(see ``contracts.py``), and ``content_cache``'s mutability is a memo table
threaded *downward* between hydration passes, not a channel for carrying a
result back *out* to the caller — the two are not the same shape of problem.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace

from atlas.company.model import CompanyProfile
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning import retrieval as _retrieval
from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    GroundingContext,
    RecalledView,
    RetrievedEvidence,
    SubjectRef,
)
from atlas.reasoning.plan import SearchPlan
from atlas.reasoning.retrieval import RetrievalResult

# Compactness guard so a very deep profile cannot blow the context budget.
_MAX_CLAIMS = 500

# Bound on distinct evidence_ids whose content is fetched from the KB per
# build_context() call — bounds DB reads, not the (cheap, cached) per-claim
# excerpt search against already-fetched content.
_MAX_HYDRATED_DOCS = 60


@dataclass(frozen=True)
class ContextBuildResult:
    """``build_context_with_diagnostics``'s own output. Internal — not a §10
    contract type, the same category as ``RetrievalMatch``/``RetrievalResult``
    in ``retrieval.py``. ``retrieval`` is ``None`` unless a ``plan`` was given
    AND at least one candidate document existed to search (M1.8 / ADR-0004).
    """

    context: GroundingContext
    retrieval: RetrievalResult | None = None


def build_context(
    profile: CompanyProfile,
    subject_ref: SubjectRef,
    *,
    known_ids: Iterable[str] | None = None,
    kb: KnowledgeBase | None = None,
    question: str | None = None,
    plan: SearchPlan | None = None,
    thesis: RecalledView | None = None,
) -> GroundingContext:
    """Assemble the GroundingContext for one company from its profile.

    ``known_ids`` — when supplied, the set of evidence_ids that resolve in the
    KnowledgeBase; references outside it are dropped (C2 identity invariant).
    ``kb`` — when supplied, raw-text retrieval hydrates claim evidence with
    verbatim excerpts (M1). Omit for M0-equivalent behavior (structured facts
    only, no retrieval attempted).
    ``question`` — when ALSO supplied (requires ``kb``), question-conditioned
    passage retrieval merges additional relevant passages as fact-Claims
    (M1.5 / ADR-M1.5), at zero extra KB reads beyond what ``kb`` already
    fetched for hydration. Omit for M0/M1-equivalent behavior.
    ``plan`` — when ALSO supplied (requires ``kb``), a ``SearchPlan`` (M1.7)
    replaces ``retrieve_passages`` with ``retrieve_with_plan`` for the merge
    above, biasing ranking by the plan's doc-type/date/period preferences.
    May be given without ``question`` (the plan carries its own
    ``raw_question``); if both are given they must agree, or ``ValueError``.
    Omit for M1.5-equivalent behavior.
    ``thesis`` — when supplied (M2.4), a ``RecalledView`` (C6) shown to the
    model for support/contradiction checking. Never widens
    ``evidence_index``: passed straight through to ``GroundingContext``,
    which is the only place this parameter has any effect. Omit for
    M2.3-equivalent behavior.

    A thin delegate over ``build_context_with_diagnostics`` (M1.8); every
    caller that only needs the ``GroundingContext`` itself keeps calling this,
    unchanged.
    """
    return build_context_with_diagnostics(
        profile,
        subject_ref,
        known_ids=known_ids,
        kb=kb,
        question=question,
        plan=plan,
        thesis=thesis,
    ).context


def build_context_with_diagnostics(
    profile: CompanyProfile,
    subject_ref: SubjectRef,
    *,
    known_ids: Iterable[str] | None = None,
    kb: KnowledgeBase | None = None,
    question: str | None = None,
    plan: SearchPlan | None = None,
    thesis: RecalledView | None = None,
) -> ContextBuildResult:
    """Assemble the GroundingContext AND surface the retrieval diagnostics
    (M1.8 / ADR-0004) that produced it — same arguments and behavior as
    ``build_context``, which is now defined in terms of this function.
    """
    if question is not None and plan is not None and plan.raw_question != question:
        raise ValueError(
            "build_context(): question and plan.raw_question disagree "
            f"({question!r} != {plan.raw_question!r})"
        )
    allowed: frozenset[str] | None = (
        frozenset(known_ids) if known_ids is not None else None
    )

    claims: list[Claim] = list(_iter_claims(profile, subject_ref, allowed))

    notes: list[str] = []
    if len(claims) > _MAX_CLAIMS:
        # Keep the most recent evidence (claims are appended roughly oldest-first
        # per time series); record the truncation rather than hiding it (G5).
        dropped = len(claims) - _MAX_CLAIMS
        claims = claims[-_MAX_CLAIMS:]
        notes.append(
            f"Truncated to {_MAX_CLAIMS} claims; {dropped} older claims omitted."
        )

    retrieved: tuple[RetrievedEvidence, ...] = ()
    retrieval_result: RetrievalResult | None = None
    if kb is not None:
        content_cache: dict[str, str | None] = {}
        claims, hydrated_retrieved, docs_capped = _hydrate_with_excerpts(
            claims, kb, content_cache
        )
        if docs_capped:
            notes.append(
                f"Retrieval limited to {_MAX_HYDRATED_DOCS} distinct source "
                "documents; remaining citations kept without a verbatim excerpt."
            )
        passage_retrieved: tuple[RetrievedEvidence, ...] = ()
        effective_question = (
            question
            if question is not None
            else (plan.raw_question if plan is not None else None)
        )
        if effective_question is not None:
            claims, passage_retrieved, retrieval_result = _merge_question_passages(
                claims,
                subject_ref,
                kb,
                effective_question,
                content_cache,
                plan=plan,
            )
        retrieved = hydrated_retrieved + passage_retrieved

    evidence_index = frozenset(eid for c in claims for eid in c.evidence_ids)
    context = GroundingContext(
        subject_ref=subject_ref,
        claims=tuple(claims),
        evidence_index=evidence_index,
        retrieved=retrieved,
        thesis=thesis,
        budget_note="; ".join(notes) if notes else None,
    )
    return ContextBuildResult(context=context, retrieval=retrieval_result)


# ---------------------------------------------------------------------------
# Raw-text hydration (M1)
# ---------------------------------------------------------------------------
def _hydrate_with_excerpts(
    claims: list[Claim],
    kb: KnowledgeBase,
    content_cache: dict[str, str | None],
) -> tuple[list[Claim], tuple[RetrievedEvidence, ...], bool]:
    """Enrich each claim's evidence with a verbatim excerpt where a confident
    match exists. Never introduces a new evidence_id; leaves a reference bare
    when no content or no confident match is available (G5).

    ``content_cache`` is owned by the caller (``build_context``) so the M1.5
    question-conditioned pass can reuse the same fetched document content —
    zero extra KB reads for that second pass.
    """
    retrieved: list[RetrievedEvidence] = []
    seen_spans: set[tuple[str, str]] = set()
    docs_capped = False

    hydrated_claims: list[Claim] = []
    for claim in claims:
        new_evidence: list[EvidenceReference] = []
        changed = False
        for ref in claim.evidence:
            if (
                ref.evidence_id not in content_cache
                and len(content_cache) >= _MAX_HYDRATED_DOCS
            ):
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
                ref,
                excerpt=match.excerpt,
                char_offset=match.char_offset,
                section=match.section,
            )
            new_evidence.append(hydrated_ref)
            changed = True
            span_key = (ref.evidence_id, match.excerpt)
            if span_key not in seen_spans:
                seen_spans.add(span_key)
                retrieved.append(
                    RetrievedEvidence(
                        evidence_ref=hydrated_ref,
                        content_span=match.excerpt,
                        relevance=match.relevance,
                    )
                )
        hydrated_claims.append(
            replace(claim, evidence=tuple(new_evidence)) if changed else claim
        )

    return hydrated_claims, tuple(retrieved), docs_capped


# ---------------------------------------------------------------------------
# Question-conditioned passage merge (M1.5 / ADR-M1.5)
# ---------------------------------------------------------------------------
def _merge_question_passages(
    claims: list[Claim],
    subject: SubjectRef,
    kb: KnowledgeBase,
    question: str,
    content_cache: dict[str, str | None],
    *,
    plan: SearchPlan | None = None,
) -> tuple[list[Claim], tuple[RetrievedEvidence, ...], RetrievalResult | None]:
    """Merge additional passages relevant to *question* as fact-Claims.

    Candidate documents are restricted to evidence_ids ALREADY backing a claim
    AND already present in ``content_cache`` (i.e. already fetched by M1's
    hydration pass, whether or not a match was found there) — so this pass
    reads from cache only and never issues a new KB call. This is what keeps
    the closed-world invariant trivially true: every passage cites an
    evidence_id the caller already resolved and already trusts.

    ``plan`` (M1.7) — when supplied, ranking comes from
    ``retrieval.retrieve_with_plan`` instead of ``retrieve_passages``; the
    candidate pool and everything downstream (claim construction, span dedup)
    is unchanged either way. ``KnowledgeBase.get_many()`` (one extra call,
    metadata only — no additional content reads) resolves doc-type/date
    boosts inside that call, not here.

    Returns the raw ``RetrievalResult`` too (M1.8 / ADR-0004, third tuple
    element) — ``None`` when ``plan`` is ``None`` (``retrieve_passages`` has
    no such diagnostics object) or when there were no candidates to search.
    Production reasoning never looks at it; only the eval harness does, via
    ``build_context_with_diagnostics``.
    """
    candidate_ids = frozenset(
        eid for c in claims for eid in c.evidence_ids
    ) & frozenset(content_cache)
    if not candidate_ids:
        return claims, (), None

    seen_spans = {
        (ref.evidence_id, ref.excerpt)
        for c in claims
        for ref in c.evidence
        if ref.excerpt
    }
    retrieval_result: RetrievalResult | None = None
    if plan is not None:
        retrieval_result = _retrieval.retrieve_with_plan(
            kb,
            candidate_ids,
            plan,
            content_cache=content_cache,
        )
        matches = retrieval_result.matches
    else:
        matches = _retrieval.retrieve_passages(
            kb, candidate_ids, question, content_cache=content_cache
        )

    new_claims: list[Claim] = []
    retrieved: list[RetrievedEvidence] = []
    for doc_id, match in matches:
        span_key = (doc_id, match.excerpt)
        if span_key in seen_spans:
            continue  # identical to an excerpt already hydrated onto an existing claim
        seen_spans.add(span_key)
        ref = EvidenceReference(
            evidence_id=doc_id,
            excerpt=match.excerpt,
            char_offset=match.char_offset,
            section=match.section,
        )
        new_claims.append(
            Claim(
                subject_ref=subject,
                statement=f'Source passage: "{match.excerpt}"',
                assertability="fact",
                confidence=match.relevance,
                evidence=(ref,),
            )
        )
        retrieved.append(
            RetrievedEvidence(
                evidence_ref=ref,
                content_span=match.excerpt,
                relevance=match.relevance,
            )
        )

    return claims + new_claims, tuple(retrieved), retrieval_result


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

    def fact(
        statement: str, sources: Sequence[str], period: str | None
    ) -> Claim | None:
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
                fs.sources,
                fs.period,
            )
            if c:
                yield c
    for es in profile.esg.snapshots:
        for kind, value in es.facts.items():
            c = fact(
                f"{kind.value} = {value} (period {es.period})", es.sources, es.period
            )
            if c:
                yield c
    for os_ in profile.ownership.snapshots:
        for kind, value in os_.facts.items():
            c = fact(
                f"{kind.value} = {value} (period {os_.period})", os_.sources, os_.period
            )
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
    for cr in [
        *profile.credit_history.debt_ratings,
        *profile.credit_history.esg_ratings,
    ]:
        desc = " ".join(
            p for p in [cr.agency, cr.instrument, cr.rating, cr.outlook, cr.action] if p
        )
        c = fact(
            f"Credit: {desc} (as of {cr.source_date.date().isoformat()})",
            [cr.evidence_id],
            cr.source_date.date().isoformat(),
        )
        if c:
            yield c

    # Strategy statements (guidance / priorities / aspirations) — verbatim text.
    for se in profile.strategy.entries:
        c = fact(
            f"[{se.kind}] {se.text} (stated {se.source_date.date().isoformat()})",
            [se.evidence_id],
            se.source_date.date().isoformat(),
        )
        if c:
            yield c

    # Governance: risk factors and director changes.
    for risk in profile.governance.risk_factors:
        c = fact(
            f"Risk factor ({risk.period}): {risk.text}", [risk.evidence_id], risk.period
        )
        if c:
            yield c
    for change in profile.governance.director_changes:
        role = f" ({change.role})" if change.role else ""
        c = fact(
            f"Board: {change.change_type} — {change.name}{role} "
            f"({change.source_date.date().isoformat()})",
            [change.evidence_id],
            change.source_date.date().isoformat(),
        )
        if c:
            yield c

    # Capital events.
    for div in profile.capital_events.dividends:
        c = fact(
            f"Dividend: {div.per_share} per share ({div.dividend_type}, "
            f"{div.source_date.date().isoformat()})",
            [div.evidence_id],
            div.source_date.date().isoformat(),
        )
        if c:
            yield c
    for bb in profile.capital_events.buybacks:
        c = fact(
            f"Buyback ({bb.sub_type}, {bb.source_date.date().isoformat()})",
            [bb.evidence_id],
            bb.source_date.date().isoformat(),
        )
        if c:
            yield c
    for acq in profile.capital_events.acquisitions:
        c = fact(
            f"Acquisition: {acq.target_name} ({acq.source_date.date().isoformat()})",
            [acq.evidence_id],
            acq.source_date.date().isoformat(),
        )
        if c:
            yield c
    for fr in profile.capital_events.fundraises:
        c = fact(
            f"Fundraise: {fr.fundraise_type} ({fr.source_date.date().isoformat()})",
            [fr.evidence_id],
            fr.source_date.date().isoformat(),
        )
        if c:
            yield c
