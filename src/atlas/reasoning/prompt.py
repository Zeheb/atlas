"""Prompt construction for M0 reasoning (commit 5); M1 commit 3 adds excerpts.

The system prompt encodes the §8.4 guarantees the model must honor; the user
prompt presents the closed-world GroundingContext (C5) and the question. The
model must return STRUCTURED JSON so ``ask.py`` can map it onto Findings (C7)
and validate every citation — prose is never parsed for claims.

M1: when a claim's evidence carries a retrieved excerpt, it is rendered
alongside the terse structured fact — the reasoner sees the actual source
prose behind a conclusion, not only its "kind = value" summary.

M2.3: a second pair (``SYNTHESIS_PROMPT`` / ``build_synthesis_prompt``) poses
a different question to the same machinery — synthesizing already-established
findings rather than answering from raw evidence. Both pairs are consumed
through ``ask()``'s injectable prompt seam, so the closed-world citation
filter, the ungrounded-judgment drop, and the refusal fallback apply
identically to both. Only what the model is ASKED differs; what it is ALLOWED
to cite never does.

M2.4: ``build_user_prompt`` renders ``GroundingContext.thesis`` (the C6
RecalledView) as an additional block, present only when a view was supplied
to the context. When absent, the rendered prompt is BYTE-IDENTICAL to before
this milestone -- asserted by test, not assumed. The block is reference
only: recalled evidence ids are shown but explicitly labelled not citable,
since the closed world is never widened by memory (a stale view cannot
resurrect withdrawn evidence).

Rule 7 (M2.4) and the ``contradicts_thesis``/``counter_case`` output fields
finally populate two C7 ``Finding`` fields that have been declared, unused,
since M0 -- revived here rather than in an earlier milestone because there
was previously nothing to check a finding against. Both are optional in the
JSON schema and default to false/null in ``ask.py``'s parser, so every
existing fake-LLM response in this codebase's test suite (none of which
emit these keys) is unaffected.
"""

from __future__ import annotations

from atlas.reasoning.contracts import GroundingContext, Question, RecalledView

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
7. If a RECALLED VIEW is provided below the evidence, check each finding you \
produce against every recalled statement. Set "contradicts_thesis": true ONLY \
if the finding genuinely conflicts with a recalled statement, and use \
"counter_case" to name which recalled statement and why. If there is no \
recalled view, or a finding does not conflict with it, leave \
"contradicts_thesis" false and "counter_case" null. Do not force a \
contradiction where none exists -- most findings will not contradict \
anything.

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
      "known_unknowns": [<string>, ...],
      "contradicts_thesis": <bool>,
      "counter_case": <string or null>
    }
  ]
}
Order findings most-material-first. If refused is true, findings must be []. \
Rule 7's fields are only meaningful when a RECALLED VIEW is present -- omit \
or leave them at their defaults (false / null) otherwise.\
"""


SYNTHESIS_PROMPT = """\
You are Atlas, an equity research analyst. You are given the FINDINGS of \
several completed investigations into one research question, each already \
grounded in specific evidence. Your job is to synthesize them into a single \
coherent view.

This is a synthesis task, not a retrieval task. The findings below are your \
whole world: you are reasoning ACROSS already-established findings, not \
discovering new ones.

Hard rules (these are product guarantees):
1. Ground everything. Every statement you make must cite the evidence ids of \
the findings it rests on. A synthesis that cites nothing is worthless.
2. Never invent an evidence id. Cite ONLY ids that appear in the provided \
list. Citing an id not in the list is a critical failure.
3. Do not introduce new facts. You may connect, weigh, and generalize across \
the given findings; you may not add information they do not contain.
4. Respect the input confidence. A synthesis resting on low-confidence \
findings cannot itself be high-confidence. Say so rather than overstating.
5. Do not average away disagreement. If two findings point in different \
directions, say that both hold and let the reader see the tension. Never \
resolve it by silently dropping one side.
6. State what you do not know. Use "known_unknowns" where the investigations \
were silent, thin, or unresolved.
7. Issue NO buy/sell recommendation, price target, or position sizing. Atlas \
has no market price data and does not rate securities. Describe what the \
evidence shows; the investment decision is the reader's.

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


def build_synthesis_prompt(question: Question, context: GroundingContext) -> str:
    """Render already-established findings for cross-finding synthesis (M2.3).

    Differs from ``build_user_prompt`` in what it exposes, not in what it
    permits: each input carries its own ``confidence`` and ``assertability``,
    because synthesis rule 4 ("a synthesis resting on low-confidence findings
    cannot itself be high-confidence") is unfollowable if the model cannot see
    how certain each input was. ``build_user_prompt`` deliberately omits both
    — for question answering they describe the evidence's own certainty, which
    is not the reader's concern; here they are the primary signal.

    The closed world is identical and enforced identically: whatever this
    renders, ``ask()`` still drops any cited id outside
    ``context.evidence_index``.
    """
    lines: list[str] = [
        f"COMPANY: {context.subject_ref.display} ({context.subject_ref.subject_id})",
        "",
        "COMPLETED INVESTIGATIONS (you may cite ONLY these evidence ids):",
    ]
    for claim in context.claims:
        ids = ",".join(sorted(claim.evidence_ids))
        lines.append(
            f"- [{ids}] ({claim.assertability}, confidence: {claim.confidence}) "
            f"{claim.statement}"
        )
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
        f"RESEARCH QUESTION: {question.raw_text}",
        "",
        "Synthesize the investigations above into a view on that question.",
    ]
    return "\n".join(lines)


def _render_recalled_view(view: RecalledView) -> list[str]:
    """The recalled-view block (M2.4 commit 5), rendered only when
    ``context.thesis`` is present.

    Reference only: recalled evidence ids are shown, labelled explicitly as
    not currently citable, so the model understands what a prior conclusion
    rested on without being able to smuggle a withdrawn id into a new
    finding. Whatever this renders, ``GroundingContext.evidence_index`` is
    unaffected -- the closed world is built once, upstream of the prompt, and
    a recalled view never widens it (enforced at context assembly, not here).

    Deliberately informational only in this commit: no instruction here asks
    the model to flag support/contradiction, because there is no schema field
    yet for it to answer into. That instruction and the corresponding output
    field arrive together in the next commit, as one coherent unit rather
    than a prompt asking a question the parser cannot yet hear the answer to.
    """
    lines = [
        "",
        f"RECALLED VIEW (from {view.as_of}, {view.origin}) -- for reference only, "
        "NOT current evidence:",
        f'  question asked: "{view.question}"',
    ]
    for claim in view.claims:
        ids = ", ".join(sorted(claim.evidence_ids)) or "no evidence recorded"
        lines.append(
            f"  - (confidence was {claim.confidence}) {claim.statement} "
            f"[originally rested on: {ids} -- NOT citable now unless it also "
            f"appears in VALID EVIDENCE IDS below]"
        )
    return lines


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
    if context.thesis is not None:
        lines += _render_recalled_view(context.thesis)
    lines += [
        "",
        f"VALID EVIDENCE IDS: {', '.join(sorted(context.evidence_index))}",
        "",
        f"QUESTION: {question.raw_text}",
    ]
    return "\n".join(lines)
