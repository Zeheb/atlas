"""Rendering: ReasoningResult (C8) -> Answer (C9) and Answer -> terminal text.

This is the M0 Conversation surface — the only place a ReasoningResult becomes
the user-facing Answer. It adds NO new claims (G1 end to end): Answer.citations
is drawn straight from the result, and the fact/judgment split is made visible
(G2). When the Conversation subsystem is built out (M5) this logic moves there.

M1 commit 4: when the GroundingContext used to produce *result* is supplied,
citations carry the excerpt/section retrieved for them (drill-to-source) —
omit it for M0-equivalent behavior (bare evidence_id citations).
"""

from __future__ import annotations

from atlas.citation import pinning_footer
from atlas.reasoning.contracts import (
    Answer,
    EvidenceReference,
    GroundingContext,
    ReasoningResult,
)


def _best_reference_for(eid: str, context: GroundingContext) -> EvidenceReference:
    """The best-hydrated EvidenceReference for *eid* in *context* (excerpt
    preferred over bare); falls back to a bare reference if eid isn't found —
    it always is, in practice, since G1 already enforces citations subset."""
    bare: EvidenceReference | None = None
    for claim in context.claims:
        for ref in claim.evidence:
            if ref.evidence_id != eid:
                continue
            if ref.excerpt:
                return ref
            bare = bare or ref
    return bare or EvidenceReference(evidence_id=eid)


def to_answer(
    result: ReasoningResult, *, context: GroundingContext | None = None
) -> Answer:
    """Build the presentational Answer from a ReasoningResult.

    ``context`` — when supplied, citations carry the retrieved excerpt/section
    for drill-to-source; omit for M0-equivalent behavior (bare evidence_id).
    """
    if result.refused:
        return Answer(
            prose="",
            citations=(),
            overall_confidence=result.overall_confidence,
            refused=True,
            refusal_reason=result.refusal_reason,
            pinning_footer=pinning_footer(result),
        )

    prose_lines: list[str] = []
    fact_lines: list[str] = []
    judgment_lines: list[str] = []
    for finding in result.findings:
        is_judgment = finding.assertability == "judgment"
        tag = "JUDGMENT" if is_judgment else "FACT"
        cited = ", ".join(sorted(finding.evidence_ids))
        suffix = f" [{cited}]" if cited else ""
        prose_lines.append(
            f"[{tag}] {finding.statement} (confidence: {finding.confidence}){suffix}"
        )
        (judgment_lines if is_judgment else fact_lines).append(finding.statement)
        for unknown in finding.known_unknowns:
            prose_lines.append(f"    ? not known: {unknown}")

    if context is not None:
        citations = tuple(
            _best_reference_for(eid, context) for eid in sorted(result.citations)
        )
    else:
        citations = tuple(
            EvidenceReference(evidence_id=eid) for eid in sorted(result.citations)
        )
    return Answer(
        prose="\n".join(prose_lines),
        citations=citations,
        overall_confidence=result.overall_confidence,
        refused=False,
        fact_lines=tuple(fact_lines),
        judgment_lines=tuple(judgment_lines),
        pinning_footer=pinning_footer(result),
    )


def format_answer(answer: Answer, *, show_evidence: bool = False) -> str:
    """Render an Answer as terminal text.

    ``show_evidence`` — print each citation's retrieved excerpt (drill-to-
    source) when available, and say so plainly when it is not (never silent).
    """
    if answer.refused:
        parts = [
            "Atlas cannot answer this question.",
            f"Reason: {answer.refusal_reason}",
        ]
        return "\n".join(parts + _footer_lines(answer))
    parts = [answer.prose, "", f"Overall confidence: {answer.overall_confidence}"]
    if answer.citations:
        parts += ["", "Sources:"]
        for ref in answer.citations:
            parts.append(f"  - {ref.evidence_id}")
            if show_evidence:
                if ref.excerpt:
                    prefix = f"({ref.section}) " if ref.section else ""
                    parts.append(f'      {prefix}"{ref.excerpt}"')
                else:
                    parts.append("      (no excerpt retrieved)")
    return "\n".join(parts + _footer_lines(answer))


def _footer_lines(answer: Answer) -> list[str]:
    """The pinning line, or nothing at all for a pre-pinning answer.

    Empty rather than a placeholder: output for an answer that predates
    pinning must be byte-identical to what it was, or every stored renderer
    fixture in this repository changes for a reason unrelated to the answer.
    """
    if not answer.pinning_footer:
        return []
    return ["", answer.pinning_footer]
