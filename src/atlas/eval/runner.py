"""Evaluation runner: run the suite, score every dimension, build a Report.

The runner is orthogonal to reasoning: it drives reasoning's public API
(build_context -> ask -> to_answer) via an injected ReasoningRunner and scores
the output. Both the runner and the judge are injected, so the whole harness is
unit-testable offline with fakes. One failing case never aborts the batch.
"""
from __future__ import annotations

import subprocess
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Protocol

from atlas.company.store import CompanyStore
from atlas.config.settings import Settings
from atlas.eval.cases import EvalCase
from atlas.eval.correctness import score_correctness
from atlas.eval.grounding import score_grounding
from atlas.eval.judge import Judge
from atlas.eval.report import CaseResult, Report
from atlas.reasoning.ask import ask
from atlas.reasoning.client import LLMClient
from atlas.reasoning.context import build_context
from atlas.reasoning.contracts import (
    Answer,
    GroundingContext,
    Question,
    ReasoningResult,
    SubjectRef,
)
from atlas.reasoning.render import to_answer


class RunnerError(RuntimeError):
    """A case could not be executed (e.g. missing profile)."""


class ReasoningRunner(Protocol):
    """Runs one case through the system under test."""

    def run(self, case: EvalCase) -> tuple[ReasoningResult, Answer, GroundingContext]:
        ...


class LiveReasoningRunner:
    """Production runner: loads the profile and drives the M0 reasoning pipeline."""

    def __init__(self, settings: Settings, client: LLMClient) -> None:
        self._settings = settings
        self._client = client

    def run(self, case: EvalCase) -> tuple[ReasoningResult, Answer, GroundingContext]:
        profile_path = self._settings.repository_base_path / case.subject / "profile.json"
        if not profile_path.exists():
            raise RunnerError(f"no profile for {case.subject!r}")
        profile = CompanyStore(profile_path, case.subject).load()
        subject = SubjectRef(subject_id=case.subject, display=case.subject)
        context = build_context(profile, subject)
        result = ask(
            Question(raw_text=case.question, subject_ref=subject), context, self._client
        )
        return result, to_answer(result), context


def run_suite(
    cases: Sequence[EvalCase],
    runner: ReasoningRunner,
    judge: Judge | None,
    capabilities: Iterable[str],
    *,
    milestone: str,
    model: str,
) -> Report:
    """Run every available case, mark the rest pending, and build a Report."""
    caps = frozenset(capabilities)
    results = [
        CaseResult(case_id=c.id, category=c.category, status="pending")
        if not c.is_available(caps)
        else _run_case(c, runner, judge)
        for c in cases
    ]
    return Report(
        milestone=milestone,
        created_at=datetime.now(timezone.utc).isoformat(),
        model=model,
        capabilities=tuple(sorted(caps)),
        results=tuple(results),
        git_commit=_git_commit(),
    )


def _run_case(case: EvalCase, runner: ReasoningRunner, judge: Judge | None) -> CaseResult:
    try:
        result, answer, context = runner.run(case)
    except Exception as exc:  # noqa: BLE001 - batch robustness: one case must not abort the suite
        return CaseResult(case_id=case.id, category=case.category, status="active", error=str(exc))

    corr = score_correctness(case, result, answer)
    grnd = score_grounding(result, context)
    quality: int | None = None
    usefulness: int | None = None
    notes = ""
    if judge is not None and not result.refused:
        try:
            verdict = judge.evaluate(case, answer)
            quality, usefulness, notes = (
                verdict.reasoning_quality, verdict.usefulness, verdict.notes,
            )
        except Exception as exc:  # noqa: BLE001 - a judge failure must not abort the case
            notes = f"judge error: {exc}"

    return CaseResult(
        case_id=case.id, category=case.category, status="active",
        refused=result.refused,
        correctness_pass=corr.passed, correctness_reasons=corr.reasons,
        grounding_pass=grnd.passed, grounding_reasons=grnd.reasons,
        reasoning_quality=quality, usefulness=usefulness, judge_notes=notes,
    )


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None
