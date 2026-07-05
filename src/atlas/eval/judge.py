"""Subjective scorer: an LLM-as-judge for reasoning quality and usefulness.

This evaluates Atlas; it is not part of Atlas. It reuses the generic LLMClient
transport (not any reasoning logic) so it is injectable and fake-testable. Two
axes, 1-5: reasoning_quality (depth, evidence use, fact/judgment discipline,
no overreach) and investor_usefulness (material, non-obvious, actionable).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from atlas.eval.cases import EvalCase
from atlas.reasoning.client import LLMClient
from atlas.reasoning.contracts import Answer


class JudgeParseError(RuntimeError):
    """Raised when the judge model's output cannot be parsed into scores."""


@dataclass(frozen=True)
class JudgeVerdict:
    reasoning_quality: int  # 1-5
    usefulness: int  # 1-5
    notes: str


JUDGE_SYSTEM_PROMPT = """\
You are a strict evaluator of an equity-research assistant. You do NOT answer \
the question yourself; you score the assistant's answer.

Score two axes, integers 1 (poor) to 5 (excellent):
- reasoning_quality: depth, use of the cited evidence, clean separation of fact \
from judgment, appropriate confidence, and no overreach beyond the evidence. A \
correct, well-explained refusal of an out-of-scope question scores high.
- usefulness: would a professional investor find this material, non-obvious, \
and actionable?

Return ONLY JSON: {"reasoning_quality": <int>, "usefulness": <int>, "notes": <string>}.\
"""


class Judge:
    """Scores an Answer's subjective quality via an injected LLM client."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def evaluate(self, case: EvalCase, answer: Answer) -> JudgeVerdict:
        raw = self._client.complete(
            system=JUDGE_SYSTEM_PROMPT,
            user=self._prompt(case, answer),
        )
        payload = _parse(raw)
        if payload is None:
            raise JudgeParseError("judge returned unparseable output")
        return JudgeVerdict(
            reasoning_quality=_clamp(payload.get("reasoning_quality")),
            usefulness=_clamp(payload.get("usefulness")),
            notes=str(payload.get("notes") or ""),
        )

    @staticmethod
    def _prompt(case: EvalCase, answer: Answer) -> str:
        body = answer.prose if not answer.refused else f"[REFUSED] {answer.refusal_reason}"
        return "\n".join([
            f"QUESTION: {case.question}",
            f"INTENDED GOOD BEHAVIOR: {case.rubric}",
            f"EXPECTED: {case.expected_behavior}",
            "",
            "ASSISTANT ANSWER:",
            body,
        ])


def _clamp(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
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
