"""Rendering: ReasoningResult (C8) -> Answer (C9) and Answer -> terminal text.

This is the M0 Conversation surface — the only place a ReasoningResult becomes
the user-facing Answer. It adds NO new claims (G1 end to end): Answer.citations
is drawn straight from the result, and the fact/judgment split is made visible
(G2). When the Conversation subsystem is built out (M5) this logic moves there.
"""
from __future__ import annotations

from atlas.reasoning.contracts import Answer, EvidenceReference, ReasoningResult


def to_answer(result: ReasoningResult) -> Answer:
    """Build the presentational Answer from a ReasoningResult."""
    if result.refused:
        return Answer(
            prose="",
            citations=(),
            overall_confidence=result.overall_confidence,
            refused=True,
            refusal_reason=result.refusal_reason,
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
    )


def format_answer(answer: Answer) -> str:
    """Render an Answer as terminal text."""
    if answer.refused:
        return f"Atlas cannot answer this question.\nReason: {answer.refusal_reason}"
    parts = [answer.prose, "", f"Overall confidence: {answer.overall_confidence}"]
    if answer.citations:
        parts += ["", "Sources:"]
        parts += [f"  - {ref.evidence_id}" for ref in answer.citations]
    return "\n".join(parts)
