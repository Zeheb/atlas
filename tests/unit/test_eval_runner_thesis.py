"""LiveReasoningRunner CAP_THESIS wiring (M2.4 commit 7).

The fixture on an EvalCase is inert on its own -- it only becomes a real
RecalledView in the context when CAP_THESIS is ALSO active, matching every
other capability gate in this runner (defense-in-depth: a case cannot force
its own capability on).
"""
from __future__ import annotations

from pathlib import Path

from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.config.settings import Settings
from atlas.eval.cases import CAP_THESIS, EvalCase, RecalledClaimFixture, RecalledViewFixture, load_cases
from atlas.eval.runner import LiveReasoningRunner


def _seed(base: Path) -> None:
    profile = CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
        )]),
    )
    CompanyStore(base / "TCS" / "profile.json", "TCS").save(profile)


def _fixture() -> RecalledViewFixture:
    return RecalledViewFixture(
        question="Should I invest in TCS?",
        as_of="2026-01-01T00:00:00+00:00",
        claims=(RecalledClaimFixture(statement="Margins have been stable."),),
    )


def _case(recalled_view: RecalledViewFixture | None) -> EvalCase:
    return EvalCase(
        id="t-thesis", category="A", question="Does anything contradict my thesis?",
        subject="TCS", expected_behavior="answer", rubric="check",
        requires=("thesis",), recalled_view=recalled_view,
    )


def test_fixture_is_projected_into_context_when_cap_thesis_is_active(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(settings, None, capabilities=frozenset({CAP_THESIS}), retrieval_only=True)
    outcome = runner.run(_case(_fixture()))
    assert outcome.context.thesis is not None
    assert outcome.context.thesis.question == "Should I invest in TCS?"
    assert outcome.context.thesis.claims[0].statement == "Margins have been stable."


def test_fixture_is_not_injected_when_cap_thesis_is_absent(tmp_path: Path) -> None:
    """Defense-in-depth: a fixture on the case must not leak into the context
    just because it exists -- the capability gate must actually be checked."""
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(settings, None, capabilities=frozenset(), retrieval_only=True)
    outcome = runner.run(_case(_fixture()))
    assert outcome.context.thesis is None


def test_no_fixture_means_no_thesis_even_with_cap_thesis_active(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(settings, None, capabilities=frozenset({CAP_THESIS}), retrieval_only=True)
    outcome = runner.run(_case(None))
    assert outcome.context.thesis is None


def test_bundled_thesis_cases_carry_a_fixture_and_activate() -> None:
    cases = {c.id: c for c in load_cases()}
    for case_id in ("t29", "t33", "t34", "t35"):
        case = cases[case_id]
        assert "thesis" in case.requires
        assert case.recalled_view is not None
        assert case.is_available(frozenset({"single_name", "thesis"}))


def test_bundled_thesis_case_produces_a_populated_context(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    case = next(c for c in load_cases() if c.id == "t29")
    runner = LiveReasoningRunner(settings, None, capabilities=frozenset({CAP_THESIS}), retrieval_only=True)
    outcome = runner.run(case)
    assert outcome.context.thesis is not None
    assert outcome.context.thesis.view_id == f"eval-fixture-{case.id}"
