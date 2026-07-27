"""Deterministic GROUNDING scorer.

Independently verifies — from outside the engine — that the reasoning output
obeys the grounding guarantees (G1/G10/G8): every citation resolves in the
closed world, answers are cited, and refusals are clean. Pure function; no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas.reasoning.contracts import GroundingContext, ReasoningResult


@dataclass(frozen=True)
class GroundingScore:
    passed: bool
    reasons: tuple[str, ...]  # failure descriptions; empty when passed


def score_grounding(
    result: ReasoningResult, context: GroundingContext
) -> GroundingScore:
    reasons: list[str] = []

    # G1/G10: nothing may be cited outside the closed world.
    hallucinated = result.citations - context.evidence_index
    if hallucinated:
        reasons.append(f"cited evidence ids not in context: {sorted(hallucinated)}")

    if result.refused:
        # G8: a refusal is clean — no findings, a reason given.
        if result.findings:
            reasons.append("refused result carries findings")
        if not result.refusal_reason:
            reasons.append("refused result has no reason")
    else:
        # Every finding must rest on cited evidence, and an answer must cite.
        for finding in result.findings:
            uncited = finding.evidence_ids - result.citations
            if uncited:
                reasons.append(f"finding rests on uncited evidence: {sorted(uncited)}")
        if not result.citations:
            reasons.append("answered without any citation")

    return GroundingScore(passed=not reasons, reasons=tuple(reasons))
