"""LiveReasoningRunner retrieval_only mode (M1.8 commit 5, ADR-0004).

The whole point of this mode is measuring retrieval/planner metrics with
ZERO LLM calls -- so the central proof here is a client whose complete()
raises, confirming it is genuinely never touched, not just "happens not to
be called by coincidence in this fixture."
"""
from __future__ import annotations

from pathlib import Path

from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.config.settings import Settings
from atlas.eval.cases import EvalCase
from atlas.eval.runner import LiveReasoningRunner, run_suite
from atlas.eval.strategies import STRATEGIES


class _ExplodingLLMClient:
    """A client that fails loudly if the runner ever calls it -- retrieval_only
    mode's central guarantee is that this never happens."""

    def complete(self, *, system: str, user: str) -> str:
        raise AssertionError("LLM client.complete() must never be called in retrieval_only mode")


def _seed(base: Path) -> None:
    profile = CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
        )]),
    )
    CompanyStore(base / "TCS" / "profile.json", "TCS").save(profile)


def _case() -> EvalCase:
    return EvalCase(id="t01", category="A", question="How stable are margins?",
                    subject="TCS", expected_behavior="answer", rubric="synthesize")


def test_retrieval_only_never_calls_the_llm_client(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(
        settings, _ExplodingLLMClient(), strategy=STRATEGIES["baseline"], retrieval_only=True,
    )
    outcome = runner.run(_case())  # must not raise
    assert outcome.result is None
    assert outcome.answer is None
    assert outcome.context is not None


def test_retrieval_only_works_with_no_client_at_all(tmp_path: Path) -> None:
    # The CLI builds no LLM client at all in retrieval-only mode -- proves
    # None is a genuinely valid value, not merely tolerated.
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(
        settings, None, strategy=STRATEGIES["planned"], retrieval_only=True,
    )
    outcome = runner.run(_case())
    assert outcome.result is None
    assert outcome.plan is not None


def test_retrieval_only_still_populates_plan_and_context(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(
        settings, None, strategy=STRATEGIES["planned"], retrieval_only=True,
    )
    outcome = runner.run(_case())
    assert outcome.plan is not None
    assert outcome.plan.raw_question == _case().question
    assert outcome.context.claims  # profile-derived claims still assembled


def test_run_suite_handles_retrieval_only_outcomes_without_crashing(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(
        settings, None, strategy=STRATEGIES["baseline"], retrieval_only=True,
    )
    report = run_suite([_case()], runner, None, {"single_name"}, milestone="M1.8", model="none")
    result = report.results[0]
    assert result.status == "active"
    assert result.correctness_pass is None  # nothing answer-dependent was scored
    assert result.grounding_pass is None
    assert result.refused is None
