"""Evaluation runner: run the suite, score every dimension, build a Report.

The runner is orthogonal to reasoning: it drives reasoning's public API
(build_context -> ask -> to_answer) via an injected ReasoningRunner and scores
the output. Both the runner and the judge are injected, so the whole harness is
unit-testable offline with fakes. One failing case never aborts the batch.

M1: LiveReasoningRunner passes a KnowledgeBase through when the subject's
knowledge.db exists (else kb=None, identical to M0), and forwards the context
into to_answer() so citations carry retrieved excerpts — this is the wiring
that lets `atlas eval run --capabilities ...,drilldown` actually exercise the
existing t43 (drill-to-source) case. No new eval case was needed: t43 already
declares requires=["drilldown"] and simply activates.

M1.5 (ADR-M1.5): LiveReasoningRunner also accepts a `capabilities` set. When it
contains "question_retrieval", the case's question is forwarded into
build_context(), activating question-conditioned passage merging so
`atlas eval compare` can measure its effect against the M1 baseline. This is a
runner-mode switch, not a case gate — no case requires it, so no case's
availability changes; capabilities defaults to frozenset() (question never
passed), reproducing M1's LiveReasoningRunner behavior exactly.

M1.7 (ADR-M1.7): a second runner-mode switch, CAP_RETRIEVAL_PLAN, layered on
top of CAP_QUESTION_RETRIEVAL. When both are active, the case's question is
also run through plan_retrieval() (HeuristicPlanner) and the resulting
SearchPlan is forwarded into build_context() alongside the question, so
`atlas eval compare` can measure the plan's effect against the M1.5 baseline.
CAP_RETRIEVAL_PLAN alone (without CAP_QUESTION_RETRIEVAL) is a no-op, matching
the CLI's --retrieval-plan-without---question-retrieval behavior.

M1.8 (ADR-0004): ``ReasoningRunner.run()`` returns a frozen ``RunOutcome``
instead of a bare ``(result, answer, context)`` 3-tuple. This is a mechanical
change (commit 1 of M1.8) — every field ``RunOutcome`` adds beyond the three
existing values (``plan``, ``retrieval``) is ``None`` until later M1.8 commits
wire them in; this commit only gives them a place to live. The 3-tuple was
already at capacity — a 4th positional value (the plan) would have been
ambiguous to unpack correctly — and a named, frozen object is the same pattern
``ContextBuildResult``/``RetrievalResult`` already use elsewhere in this
codebase rather than a new idiom introduced just for the runner.
"""
from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from atlas.company.store import CompanyStore
from atlas.config.settings import Settings
from atlas.eval.cache import CachingLLMClient, EvalCache
from atlas.eval.cases import CAP_QUESTION_RETRIEVAL, CAP_RETRIEVAL_PLAN, EvalCase
from atlas.eval.correctness import score_correctness
from atlas.eval.grounding import score_grounding
from atlas.eval.judge import Judge
from atlas.eval.report import CaseResult, Report
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.ask import ask
from atlas.reasoning.context import build_context
from atlas.reasoning.contracts import (
    Answer,
    GroundingContext,
    Question,
    ReasoningResult,
    SubjectRef,
)
from atlas.reasoning.llm import LLMClient
from atlas.reasoning.planner import plan_retrieval
from atlas.reasoning.render import to_answer


class RunnerError(RuntimeError):
    """A case could not be executed (e.g. missing profile)."""


@dataclass(frozen=True)
class RunOutcome:
    """One case's full execution outcome (M1.8). Internal to the eval
    harness — not a §10 contract type, the same category as
    ``ContextBuildResult``/``RetrievalResult`` in the reasoning package.

    ``plan``/``retrieval`` are ``None`` until a later M1.8 commit wires the
    planner/retrieval diagnostics through; this commit only gives every field
    a place to live.
    """

    context: GroundingContext
    result: ReasoningResult
    answer: Answer
    plan: object | None = None
    retrieval: object | None = None


class ReasoningRunner(Protocol):
    """Runs one case through the system under test."""

    def run(self, case: EvalCase) -> RunOutcome:
        ...


class LiveReasoningRunner:
    """Production runner: loads the profile and drives the M0 reasoning pipeline.

    ``capabilities`` — when it contains CAP_QUESTION_RETRIEVAL, the case's
    question is forwarded into build_context(), activating M1.5's
    question-conditioned passage merge (ADR-M1.5). Defaults to frozenset()
    (question never passed), reproducing M1 behavior exactly.
    """

    def __init__(
        self, settings: Settings, client: LLMClient, *, capabilities: frozenset[str] = frozenset(),
        cache: EvalCache | None = None, fingerprint: str = "",
    ) -> None:
        self._settings = settings
        # Free-tier operation: an unchanged (model, fingerprint, prompt,
        # context) tuple never re-invokes the reasoning model across separate
        # `atlas eval run` invocations. Wrapped once here, not per-case.
        self._client: LLMClient = (
            CachingLLMClient(client, cache, model=settings.reasoning_model, fingerprint=fingerprint)
            if cache is not None
            else client
        )
        self._capabilities = capabilities

    def run(self, case: EvalCase) -> RunOutcome:
        repo_root = self._settings.repository_base_path / case.subject
        profile_path = repo_root / "profile.json"
        if not profile_path.exists():
            raise RunnerError(f"no profile for {case.subject!r}")
        profile = CompanyStore(profile_path, case.subject).load()
        subject = SubjectRef(subject_id=case.subject, display=case.subject)
        kb = KnowledgeBase(repo_root) if (repo_root / "knowledge.db").exists() else None
        question = case.question if CAP_QUESTION_RETRIEVAL in self._capabilities else None
        # M1.7: planning is a no-op unless question-conditioned retrieval is
        # ALSO active -- a plan with nothing to merge it into would never be
        # consumed by build_context().
        plan = (
            plan_retrieval(case.question)
            if question is not None and CAP_RETRIEVAL_PLAN in self._capabilities
            else None
        )
        context = build_context(profile, subject, kb=kb, question=question, plan=plan)
        result = ask(
            Question(raw_text=case.question, subject_ref=subject), context, self._client
        )
        answer = to_answer(result, context=context)
        return RunOutcome(context=context, result=result, answer=answer, plan=plan)


def resolve_judge_sample(
    value: str | None, active_ids: Sequence[str]
) -> frozenset[str] | None:
    """Resolve a ``--judge-sample`` value to the exact set of case ids to judge.

    ``None`` (the default, when the option is omitted) means "judge every
    active case" — fully backward compatible with pre-existing behavior. A
    comma-separated list of case ids judges exactly those cases.

    A plain integer ``N`` judges ``N`` cases chosen by hash rank, not by
    suite/file position: each active case id is ranked by sha256(case_id),
    and the N lowest-ranked ids are selected. This is deterministic and
    reproducible (same case ids always yield the same sample), but — unlike
    "first N in file order" — it is not biased by the suite's category-block
    layout (e.g. the acceptance suite's first N ids are all one category),
    and it is largely stable as the suite grows (a case's rank depends only
    on its own id, not on what else exists, so adding cases elsewhere
    doesn't reshuffle the whole sample).
    """
    if value is None or not value.strip():
        return None
    value = value.strip()
    if value.isdigit():
        n = int(value)
        ranked = sorted(active_ids, key=lambda cid: hashlib.sha256(cid.encode("utf-8")).hexdigest())
        return frozenset(ranked[:n])
    return frozenset(tok.strip() for tok in value.split(",") if tok.strip())


def run_suite(
    cases: Sequence[EvalCase],
    runner: ReasoningRunner,
    judge: Judge | None,
    capabilities: Iterable[str],
    *,
    milestone: str,
    model: str,
    judge_model: str | None = None,
    judge_sample: str | None = None,
) -> Report:
    """Run every available case, mark the rest pending, and build a Report.

    ``judge_sample`` (see resolve_judge_sample) selectively skips the judge
    for cases outside the sample — deterministic scoring (correctness/
    grounding) always runs for every active case regardless; only the LLM
    judge call is gated, minimizing LLM calls for free-tier operation.
    """
    caps = frozenset(capabilities)
    active_ids = [c.id for c in cases if c.is_available(caps)]
    sample = resolve_judge_sample(judge_sample, active_ids)
    results = [
        CaseResult(case_id=c.id, category=c.category, status="pending")
        if not c.is_available(caps)
        else _run_case(c, runner, judge if (sample is None or c.id in sample) else None)
        for c in cases
    ]
    return Report(
        milestone=milestone,
        created_at=datetime.now(timezone.utc).isoformat(),
        model=model,
        capabilities=tuple(sorted(caps)),
        results=tuple(results),
        git_commit=_git_commit(),
        judge_model=judge_model,
    )


def _run_case(case: EvalCase, runner: ReasoningRunner, judge: Judge | None) -> CaseResult:
    try:
        outcome = runner.run(case)
    except Exception as exc:  # noqa: BLE001 - batch robustness: one case must not abort the suite
        return CaseResult(case_id=case.id, category=case.category, status="active", error=str(exc))

    result, answer, context = outcome.result, outcome.answer, outcome.context

    corr = score_correctness(case, result, answer)
    grnd = score_grounding(result, context)
    quality: int | None = None
    usefulness: int | None = None
    evidence_use: int | None = None
    notes = ""
    # §12.6 amendment 4: refused answers are judged too — refusal quality is a
    # product feature (G8/§8.8), and evidence_use catches the "lazy refusal"
    # (declining although the evidence contains the answer).
    if judge is not None:
        try:
            verdict = judge.evaluate(case, answer, context)  # amendment 2: context
            quality, usefulness, evidence_use, notes = (
                verdict.reasoning_quality, verdict.usefulness,
                verdict.evidence_use, verdict.notes,
            )
        except Exception as exc:  # noqa: BLE001 - a judge failure must not abort the case
            notes = f"judge error: {exc}"

    return CaseResult(
        case_id=case.id, category=case.category, status="active",
        refused=result.refused,
        correctness_pass=corr.passed, correctness_reasons=corr.reasons,
        grounding_pass=grnd.passed, grounding_reasons=grnd.reasons,
        reasoning_quality=quality, usefulness=usefulness,
        evidence_use=evidence_use,
        distinct_docs_cited=len(result.citations),
        judge_notes=notes,
    )


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None
