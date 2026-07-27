"""Subjective scorer: an LLM-as-judge for reasoning quality, usefulness, and
evidence use.

This evaluates Atlas; it is not part of Atlas. It reuses the generic LLMClient
transport (not any reasoning logic) so it is injectable and fake-testable.

Freeze amendments (§12.6):
- Amendment 2: the judge receives a compact listing of the AVAILABLE EVIDENCE
  (the GroundingContext's claims), so it scores against ground truth rather
  than surface plausibility — it can now detect ignored evidence, "lazy gaps"
  (claiming the evidence is silent when it isn't), and overreach.
- Amendment 3: a third axis, evidence_use (1-5), scores how well the answer
  leveraged the relevant evidence that existed. Distinct from the deterministic
  grounding scorer: grounding = nothing cited beyond the closed world
  (fabrication); evidence_use = how much of the relevant world was used
  (completeness).
- Amendment 4 (wired in runner.py): refused answers are judged too — a
  well-explained refusal scores high on reasoning_quality; refusing when the
  evidence clearly contains the answer scores 1 on evidence_use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from atlas.eval.cache import CachingLLMClient, EvalCache
from atlas.eval.cases import EvalCase
from atlas.reasoning.contracts import Answer, GroundingContext
from atlas.reasoning.llm import LLMClient

# Bound the evidence listing so a deep profile cannot blow the judge's context.
_EVIDENCE_CHAR_BUDGET = 20_000


class JudgeParseError(RuntimeError):
    """Raised when the judge model's output cannot be parsed into scores."""


@dataclass(frozen=True)
class JudgeVerdict:
    reasoning_quality: int  # 1-5
    usefulness: int  # 1-5
    evidence_use: int  # 1-5
    notes: str


JUDGE_SYSTEM_PROMPT = """\
You are a strict evaluator of an equity-research assistant. You do NOT answer \
the question yourself; you score the assistant's answer.

You are given the QUESTION, the intended good behavior, the AVAILABLE EVIDENCE \
the assistant had access to, and the assistant's ANSWER (which may be a refusal).

Score three axes, integers 1 (poor) to 5 (excellent):
- reasoning_quality: depth, use of the cited evidence, clean separation of fact \
from judgment, appropriate confidence, and no overreach beyond the evidence. A \
correct, WELL-EXPLAINED refusal of an out-of-scope question scores high; a curt \
or unexplained refusal scores low.
- usefulness: would a professional investor find this material, non-obvious, \
and actionable?
- evidence_use: how well did the answer use the AVAILABLE EVIDENCE? 5 = every \
relevant item is used or explicitly acknowledged; 1 = the answer ignores \
clearly relevant evidence, claims a gap the evidence disproves ("the filings \
don't say X" when they do), or — for a refusal — declines although the \
evidence clearly contains the answer.

Return ONLY JSON: {"reasoning_quality": <int>, "usefulness": <int>, \
"evidence_use": <int>, "notes": <string>}.\
"""


class Judge:
    """Scores an Answer's subjective quality via an injected LLM client."""

    def __init__(
        self,
        client: LLMClient,
        *,
        cache: EvalCache | None = None,
        model: str | None = None,
        fingerprint: str = "",
    ) -> None:
        # Free-tier operation: an unchanged (case, answer, context) triple
        # never re-invokes the judge model across separate `atlas eval run`
        # invocations. Wrapped once here, not per-call — CachingLLMClient
        # derives everything else (including a human-readable question
        # label) from the system/user text it receives.
        self._client = (
            CachingLLMClient(
                client, cache, model=model or "unknown", fingerprint=fingerprint
            )
            if cache is not None
            else client
        )

    def evaluate(
        self, case: EvalCase, answer: Answer, context: GroundingContext | None = None
    ) -> JudgeVerdict:
        raw = self._client.complete(
            system=JUDGE_SYSTEM_PROMPT,
            user=self._prompt(case, answer, context),
        )
        payload = _parse(raw)
        if payload is None:
            raise JudgeParseError("judge returned unparseable output")
        return JudgeVerdict(
            reasoning_quality=_clamp(payload.get("reasoning_quality")),
            usefulness=_clamp(payload.get("usefulness")),
            evidence_use=_clamp(payload.get("evidence_use")),
            notes=str(payload.get("notes") or ""),
        )

    @staticmethod
    def _prompt(
        case: EvalCase, answer: Answer, context: GroundingContext | None
    ) -> str:
        body = (
            answer.prose if not answer.refused else f"[REFUSED] {answer.refusal_reason}"
        )
        lines = [
            f"QUESTION: {case.question}",
            f"INTENDED GOOD BEHAVIOR: {case.rubric}",
            f"EXPECTED: {case.expected_behavior}",
            "",
        ]
        if context is not None:
            lines.append("AVAILABLE EVIDENCE (everything the assistant had):")
            budget = _EVIDENCE_CHAR_BUDGET
            shown = 0
            for claim in context.claims:
                line = f"- [{','.join(sorted(claim.evidence_ids))}] {claim.statement}"
                if budget - len(line) < 0:
                    lines.append(
                        f"(+{len(context.claims) - shown} more evidence items omitted for length)"
                    )
                    break
                lines.append(line)
                budget -= len(line)
                shown += 1
            lines.append("")
        lines += ["ASSISTANT ANSWER:", body]
        return "\n".join(lines)


def _clamp(value: Any) -> int:
    try:
        n = int(value)
    except TypeError, ValueError:
        return 1
    return max(1, min(5, n))


def _parse(raw: str) -> dict[str, Any] | None:
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
