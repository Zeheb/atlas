"""Investigation executor (M2.2.5 commit 3).

The load-bearing tests here are the provenance ones: InvestigationResult must
be structurally incapable of holding an ungrounded claim, and every failure
mode (refusal, no citation, exception) must land as an explicit unresolved
result rather than as a confident sentence with nothing behind it.
"""

from __future__ import annotations

import json

import pytest

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.knowledge.base import KnowledgeBase
from atlas.research.citations import Finding
from atlas.research.investigate import (
    InvestigationResult,
    InvestigationRun,
    run_investigation,
    run_plan,
)
from atlas.research.plan import Investigation
from atlas.research.planner import plan_research

_CONTENT = (
    "Operating margin stood at 24.2% in FY26, driven by continued cost discipline "
    "across major markets, with steady improvement over prior quarters."
)


def _inv(
    dimension: str = "business_quality", subjects: tuple[str, ...] = ("TCS",)
) -> Investigation:
    return Investigation(
        dimension=dimension,
        question="What do margins show about business quality?",
        subjects=subjects,
        rationale="margins are the cheapest available test of business durability",
        priority=5,
    )


def _seed(base) -> None:
    """A profile plus a real KnowledgeBase entry, so retrieval has something
    to ground against. Same shapes test_cli_eval.py's _seed uses.
    """
    profile = CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(
            snapshots=[
                FinancialSnapshot(
                    period="2026-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2},
                    sources=["ev-1"],
                )
            ]
        ),
    )
    repo_root = base / "TCS"
    repo_root.mkdir(parents=True, exist_ok=True)
    CompanyStore(repo_root / "profile.json", "TCS").save(profile)

    rel = "ev-1.txt"
    (repo_root / rel).write_text(_CONTENT, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1",
        source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value,
        title="Test filing",
        source_date="2026-03-31T00:00:00+00:00",
        document_url=None,
        local_path=rel,
        file_size_bytes=None,
        acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(repo_root).parse(entry)


class _GroundedFake:
    """An LLM that answers with a citation to evidence that is in context."""

    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(
            {
                "refused": False,
                "overall_confidence": "high",
                "findings": [
                    {
                        "statement": "Operating margin ~24%.",
                        "assertability": "judgment",
                        "confidence": "high",
                        "supporting_evidence_ids": ["ev-1"],
                        "known_unknowns": [],
                    }
                ],
            }
        )


class _RefusingFake:
    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(
            {
                "refused": True,
                "overall_confidence": "low",
                "refusal_reason": "no evidence in context supports this",
                "findings": [],
            }
        )


class _UncitedFake:
    """Answers confidently but cites nothing -- the exact failure the
    provenance rule exists to catch."""

    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(
            {
                "refused": False,
                "overall_confidence": "high",
                "findings": [
                    {
                        "statement": "Margins are excellent.",
                        "assertability": "judgment",
                        "confidence": "high",
                        "supporting_evidence_ids": [],
                        "known_unknowns": [],
                    }
                ],
            }
        )


class _ExplodingFake:
    def complete(self, *, system: str, user: str) -> str:
        raise RuntimeError("transport exploded")


# --- Structural provenance guarantee ------------------------------------------------
def test_result_cannot_hold_both_finding_and_unresolved() -> None:
    with pytest.raises(ValueError, match="exactly one of finding"):
        InvestigationResult(
            investigation=_inv(),
            finding=Finding(text="x", evidence_ids=["ev-1"]),
            unresolved_reason="also unresolved",
        )


def test_result_cannot_hold_neither() -> None:
    with pytest.raises(ValueError, match="exactly one of finding"):
        InvestigationResult(investigation=_inv())


def test_result_rejects_a_finding_with_no_evidence() -> None:
    """An ungrounded claim must be recorded as unresolved, never as a Finding."""
    with pytest.raises(ValueError, match="at least one evidence_id"):
        InvestigationResult(
            investigation=_inv(),
            finding=Finding(text="Margins are great.", evidence_ids=[]),
        )


# --- Execution paths ------------------------------------------------------------------
def test_grounded_answer_becomes_a_cited_finding(tmp_path) -> None:
    _seed(tmp_path)
    result = run_investigation(_inv(), tmp_path, _GroundedFake())

    assert result.resolved
    assert result.finding is not None
    assert result.finding.evidence_ids == ("ev-1",)  # tuple since M2.3 froze Finding
    assert result.finding.kind == "fact"
    assert result.plan is not None  # the retrieval plan used, for diagnostics
    assert result.unresolved_reason is None


def test_refusal_becomes_unresolved_not_a_finding(tmp_path) -> None:
    _seed(tmp_path)
    result = run_investigation(_inv(), tmp_path, _RefusingFake())

    assert not result.resolved
    assert result.finding is None
    assert result.unresolved_reason is not None
    assert "refused" in result.unresolved_reason


def test_uncited_answer_never_becomes_a_finding(tmp_path) -> None:
    """The guarantee, whichever layer enforces it.

    In practice the reasoning layer catches this first -- ask()/to_answer()
    already refuse a finding with no supporting evidence ("No finding could be
    grounded in the available evidence"), so the executor sees a refusal
    rather than an uncited answer. The executor's own no-citation branch is
    therefore defense-in-depth for any future path that yields prose without
    citations; test_result_rejects_a_finding_with_no_evidence covers that
    branch directly at the type level.
    """
    _seed(tmp_path)
    result = run_investigation(_inv(), tmp_path, _UncitedFake())

    assert not result.resolved
    assert result.finding is None
    assert result.unresolved_reason is not None


def test_executor_error_becomes_unresolved_and_never_raises(tmp_path) -> None:
    _seed(tmp_path)
    result = run_investigation(_inv(), tmp_path, _ExplodingFake())

    assert not result.resolved
    assert "execution error" in (result.unresolved_reason or "")


def test_missing_profile_becomes_unresolved_and_never_raises(tmp_path) -> None:
    # Nothing seeded at all.
    result = run_investigation(_inv(), tmp_path, _GroundedFake())

    assert not result.resolved
    assert "no profile" in (result.unresolved_reason or "")


# --- Whole-plan execution ---------------------------------------------------------------
def test_run_plan_executes_every_investigation_in_priority_order(tmp_path) -> None:
    _seed(tmp_path)
    plan = plan_research("Should I invest in TCS?", ("TCS",))
    run = run_plan(plan, tmp_path, _GroundedFake())

    assert len(run.results) == len(plan.investigations)
    executed = [r.investigation.dimension for r in run.results]
    assert executed == [i.dimension for i in plan.ordered_investigations()]


def test_one_failing_investigation_never_aborts_the_run(tmp_path) -> None:
    """Batch robustness, matching eval/runner.py's _run_case rule."""
    _seed(tmp_path)
    calls = {"n": 0}

    class _FlakyFake:
        def complete(self, *, system: str, user: str) -> str:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("second one explodes")
            return _GroundedFake().complete(system=system, user=user)

    plan = plan_research("Should I invest in TCS?", ("TCS",))
    run = run_plan(plan, tmp_path, _FlakyFake())

    assert len(run.results) == len(plan.investigations)  # nothing aborted
    assert len(run.unresolved) == 1
    assert len(run.findings) == len(plan.investigations) - 1


def test_run_exposes_findings_and_resolution_rate(tmp_path) -> None:
    _seed(tmp_path)
    plan = plan_research("Should I invest in TCS?", ("TCS",))
    run = run_plan(plan, tmp_path, _GroundedFake())

    assert run.resolution_rate == 1.0
    assert all(f.evidence_ids for f in run.findings)


def test_all_findings_are_grounded_even_when_some_investigations_fail(tmp_path) -> None:
    """Acceptance criterion 5, at the run level: every Finding that survives
    carries evidence; everything else is explicitly unresolved.
    """
    _seed(tmp_path)
    plan = plan_research("What are the key risks to TCS?", ("TCS",))
    run = run_plan(plan, tmp_path, _UncitedFake())

    assert run.findings == ()  # nothing uncited leaked through
    assert len(run.unresolved) == len(plan.investigations)
    assert run.resolution_rate == 0.0


def test_empty_run_has_zero_resolution_rate() -> None:
    plan = plan_research("Should I invest in TCS?", ("TCS",))
    run = InvestigationRun(plan=plan, results=())
    assert run.resolution_rate == 0.0
