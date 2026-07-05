"""Prompt construction for M0 reasoning (commit 5); M1 commit 3 adds excerpts.

The system prompt encodes the §8.4 guarantees the model must honor; the user
prompt presents the closed-world GroundingContext (C5) and the question. The
model must return STRUCTURED JSON so ``ask.py`` can map it onto Findings (C7)
and validate every citation — prose is never parsed for claims.

M1: when a claim's evidence carries a retrieved excerpt, it is rendered
alongside the terse structured fact — the reasoner sees the actual source
prose behind a conclusion, not only its "kind = value" summary.
"""
from __future__ import annotations

from atlas.reasoning.contracts import GroundingContext, Question

SYSTEM_PROMPT = """\
You are Atlas, an equity research analyst. You answer questions about a company \
ONLY from the evidence provided in the user message. You never use outside \
knowledge and never invent facts or citations.

Hard rules (these are product guarantees):
1. Ground everything. Every claim must be supported by one or more of the \
provided evidence ids. If the evidence does not support an answer, say so.
2. Never invent an evidence id. You may cite ONLY ids that appear in the \
provided evidence list. Citing an id not in the list is a critical failure.
3. Distinguish fact from judgment. Mark each finding's "assertability" as \
"fact" (directly stated by the evidence) or "judgment" (your interpretation). \
Every "judgment" finding MUST cite supporting evidence ids.
4. State confidence ("high" | "medium" | "low") for each finding and overall.
5. State what you do not know. Use "known_unknowns" when the evidence is \
silent or partial. Absence of evidence is not evidence of absence — do not \
infer undisclosed facts.
6. Refuse out-of-scope questions rather than guessing. Set "refused": true \
with a "refusal_reason" when the question requires data Atlas does not have: \
market price or valuation, causal/mechanistic explanation not in the evidence, \
emulating a specific person's opinion, or news/sentiment/industry data. \
Refusing correctly is success, not failure.

Return ONLY a JSON object, no prose, of exactly this shape:
{
  "refused": <bool>,
  "refusal_reason": <string or null>,
  "overall_confidence": "high" | "medium" | "low",
  "findings": [
    {
      "statement": <string>,
      "assertability": "fact" | "judgment",
      "confidence": "high" | "medium" | "low",
      "supporting_evidence_ids": [<evidence id>, ...],
      "known_unknowns": [<string>, ...]
    }
  ]
}
Order findings most-material-first. If refused is true, findings must be [].\
"""


def build_user_prompt(question: Question, context: GroundingContext) -> str:
    """Render the closed-world evidence and the question for the model."""
    lines: list[str] = [
        f"COMPANY: {context.subject_ref.display} ({context.subject_ref.subject_id})",
        "",
        "EVIDENCE (you may cite ONLY these evidence ids):",
    ]
    for claim in context.claims:
        ids = ",".join(sorted(claim.evidence_ids))
        lines.append(f"- [{ids}] {claim.statement}")
        seen_excerpts: set[str] = set()
        for ref in claim.evidence:
            if ref.excerpt and ref.excerpt not in seen_excerpts:
                seen_excerpts.add(ref.excerpt)
                lines.append(f'    source text: "{ref.excerpt}"')
    if context.budget_note:
        lines.append(f"(note: {context.budget_note})")
    lines += [
        "",
        f"VALID EVIDENCE IDS: {', '.join(sorted(context.evidence_index))}",
        "",
        f"QUESTION: {question.raw_text}",
    ]
    return "\n".join(lines)
