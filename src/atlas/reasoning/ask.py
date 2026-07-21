"""Reasoning orchestration for M0 (commit 5).

``ask()`` runs one grounded reasoning pass: render prompts -> call the LLM ->
parse its structured JSON -> validate every citation against the closed-world
GroundingContext -> build a ReasoningResult (C8).

Citation validation is a HARD code path, not a hope: any evidence id the model
emits that is not in ``context.evidence_index`` is dropped (G10). A judgment
finding left with no valid support is dropped (G3/G4). If nothing grounded
survives, the result is a refusal rather than an empty answer (G8).

M2.3: the two prompts are injectable (``system_prompt``/``build_prompt``),
defaulting to the M0 question-answering pair. Everything AFTER the model call
-- the closed-world citation filter, the ungrounded-judgment drop, the refusal
fallback, the ReasoningResult assembly -- is prompt-independent and is the
reason this seam exists. Thesis synthesis (``research/thesis.py``) is a
different question posed to the same validated machinery, not a second
implementation of it: a synthesizer that bypassed ``ask()`` would have to
re-derive G1/G3/G4/G8/G10, which is precisely the duplication ADR-0009 warns
against.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from atlas.reasoning.contracts import (
    Claim,
    ConfidenceLevel,
    Finding,
    GroundingContext,
    Question,
    ReasoningResult,
)
from atlas.reasoning.llm import LLMClient
from atlas.reasoning.prompt import SYSTEM_PROMPT, build_user_prompt

_CONFIDENCE: frozenset[str] = frozenset({"high", "medium", "low"})

PromptBuilder = Callable[[Question, GroundingContext], str]


def ask(
    question: Question,
    context: GroundingContext,
    client: LLMClient,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    build_prompt: PromptBuilder = build_user_prompt,
) -> ReasoningResult:
    """Answer *question* over the closed-world *context* using *client*.

    ``system_prompt``/``build_prompt`` default to the M0 question-answering
    pair, so every existing call site is unchanged. A caller supplying its own
    pair (M2.3's synthesis) changes only what the model is ASKED; every
    grounding guarantee below the model call applies identically, because
    those guarantees are enforced against ``context``, never against the
    prompt text.
    """
    raw = client.complete(
        system=system_prompt,
        user=build_prompt(question, context),
    )
    payload = _parse_json(raw)
    if payload is None:
        return _refuse(question, "The model returned output that could not be parsed.")

    if payload.get("refused") is True:
        reason = str(payload.get("refusal_reason") or "The model declined to answer.")
        return _refuse(question, reason)

    by_evidence = _index_claims_by_evidence(context)
    findings: list[Finding] = []
    for rank, raw_finding in enumerate(_as_list(payload.get("findings"))):
        finding = _build_finding(raw_finding, context, by_evidence, rank)
        if finding is not None:
            findings.append(finding)

    if not findings:
        # The model answered but nothing survived grounding validation.
        return _refuse(
            question,
            "No finding could be grounded in the available evidence.",
        )

    citations = frozenset(eid for f in findings for eid in f.evidence_ids)
    return ReasoningResult(
        question=question,
        findings=tuple(findings),
        overall_confidence=_confidence(payload.get("overall_confidence")),
        citations=citations,
        refused=False,
        trace=(f"single-pass grounded reasoning over {len(context.claims)} claims",),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _refuse(question: Question, reason: str) -> ReasoningResult:
    return ReasoningResult(
        question=question,
        findings=(),
        overall_confidence="low",
        citations=frozenset(),
        refused=True,
        refusal_reason=reason,
    )


def _build_finding(
    raw: Any,
    context: GroundingContext,
    by_evidence: dict[str, list[Claim]],
    rank: int,
) -> Finding | None:
    if not isinstance(raw, dict):
        return None
    statement = str(raw.get("statement") or "").strip()
    if not statement:
        return None

    assertability = "judgment" if raw.get("assertability") == "judgment" else "fact"

    # Keep only cited ids that exist in the closed world (G10).
    valid_ids = [
        eid for eid in _as_list(raw.get("supporting_evidence_ids"))
        if isinstance(eid, str) and eid in context.evidence_index
    ]
    supporting: list[Claim] = []
    seen: set[int] = set()
    for eid in valid_ids:
        for claim in by_evidence.get(eid, ()):
            if id(claim) not in seen:
                seen.add(id(claim))
                supporting.append(claim)

    # A judgment with no valid support is ungrounded — drop it (G3/G4).
    if assertability == "judgment" and not supporting:
        return None

    return Finding(
        statement=statement,
        assertability=assertability,  # type: ignore[arg-type]
        confidence=_confidence(raw.get("confidence")),
        supporting_claims=tuple(supporting),
        salience_rank=rank,
        known_unknowns=tuple(
            str(u) for u in _as_list(raw.get("known_unknowns")) if str(u).strip()
        ),
    )


def _index_claims_by_evidence(context: GroundingContext) -> dict[str, list[Claim]]:
    index: dict[str, list[Claim]] = {}
    for claim in context.claims:
        for eid in claim.evidence_ids:
            index.setdefault(eid, []).append(claim)
    return index


def _confidence(value: Any) -> ConfidenceLevel:
    return value if value in _CONFIDENCE else "low"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _parse_json(raw: str) -> dict[str, Any] | None:
    """Parse the model's JSON, tolerating markdown fences and surrounding prose."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None
