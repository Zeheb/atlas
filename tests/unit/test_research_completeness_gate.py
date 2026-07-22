"""The completeness gate: no silent omission (M2.3 commit 5).

This is the one guarantee M2.3 adds that it did not inherit from ask(), so
most of this file is adversarial: theses constructed specifically to be
dishonest in ways that would otherwise pass every other check. A gate never
shown to fail is not a gate.

The failure this exists to catch is subtle by design -- a thesis that cites
correctly, grounds every claim, and is still misleading because it quietly
omitted the finding that undercut it.
"""
from __future__ import annotations

import json
from dataclasses import replace

from atlas.reasoning.contracts import Claim, EvidenceReference, SubjectRef
from atlas.research.citations import Finding
from atlas.research.investigate import InvestigationResult, InvestigationRun
from atlas.research.plan import Investigation, ResearchPlan
from atlas.research.thesis import Disposition, check_completeness, synthesize

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _investigation(dimension: str) -> Investigation:
    return Investigation(
        dimension=dimension,
        question=f"What does {dimension} show?",
        subjects=("TCS",),
        rationale="it is one of the dimensions a view must rest on",
        priority=5,
    )


def _semantic(statement: str, eid: str):
    from atlas.reasoning.contracts import Finding as SemanticFinding

    return SemanticFinding(
        statement=statement, assertability="judgment", confidence="high",
        supporting_claims=(Claim(
            subject_ref=SUBJECT, statement=statement, assertability="fact",
            confidence="high", evidence=[EvidenceReference(evidence_id=eid)],
        ),),
    )


def _resolved(dimension: str, eid: str = "ev-1") -> InvestigationResult:
    return InvestigationResult(
        investigation=_investigation(dimension),
        finding=Finding(text=f"{dimension} looks fine.", evidence_ids=[eid]),
        semantic_findings=(_semantic(f"{dimension} looks fine.", eid),),
    )


def _unresolved(dimension: str) -> InvestigationResult:
    return InvestigationResult(
        investigation=_investigation(dimension),
        unresolved_reason="refused: no evidence",
    )


def _run(*results: InvestigationResult) -> InvestigationRun:
    used = results or (_resolved("business_quality"),)
    return InvestigationRun(
        plan=ResearchPlan(
            raw_question="Should I invest in TCS?",
            intent="invest_decision",
            subjects=("TCS",),
            investigations=tuple(_investigation(r.dimension) for r in used),
        ),
        results=used,
    )


class _Fake:
    def __init__(self, cite: list[str] | None = None) -> None:
        self._cite = cite if cite is not None else ["ev-1"]

    def complete(self, *, system: str, user: str) -> str:
        return json.dumps({
            "refused": False, "overall_confidence": "medium",
            "findings": [{
                "statement": "Durable business, fairly priced.",
                "assertability": "judgment", "confidence": "medium",
                "supporting_evidence_ids": self._cite, "known_unknowns": [],
            }],
        })


# --- An honest thesis passes ------------------------------------------------------------
def test_synthesized_thesis_passes_the_gate() -> None:
    run = _run(_resolved("business_quality", "ev-1"), _resolved("valuation", "ev-2"))
    thesis = synthesize(run, _Fake(cite=["ev-1", "ev-2"]))

    assert check_completeness(thesis, run).passed


def test_thesis_with_unresolved_investigations_passes_when_it_says_so() -> None:
    run = _run(_resolved("business_quality", "ev-1"), _unresolved("valuation"))
    thesis = synthesize(run, _Fake())

    result = check_completeness(thesis, run)
    assert result.passed
    assert thesis.unresolved_dimensions == ("valuation",)


def test_setting_a_finding_aside_with_a_reason_passes() -> None:
    """Judging a finding immaterial is legitimate -- it just has to be said."""
    run = _run(_resolved("business_quality", "ev-1"), _resolved("esg_governance", "ev-2"))
    thesis = synthesize(run, _Fake(cite=["ev-1", "ev-2"]))
    edited = replace(thesis, dispositions=(
        Disposition(dimension="business_quality", materiality="incorporated"),
        Disposition(
            dimension="esg_governance", materiality="not_material",
            rationale="disclosure is boilerplate and does not bear on the question",
        ),
    ))

    assert check_completeness(edited, run).passed


# --- ADVERSARIAL: the gate must reject these -------------------------------------------
def test_silently_dropped_finding_is_rejected() -> None:
    """THE failure this gate exists for: an inconvenient finding simply
    omitted. Every citation is valid; the thesis is still dishonest.
    """
    run = _run(_resolved("business_quality", "ev-1"), _resolved("risks", "ev-2"))
    thesis = synthesize(run, _Fake(cite=["ev-1"]))
    dishonest = replace(thesis, dispositions=(
        Disposition(dimension="business_quality", materiality="incorporated"),
    ))  # 'risks' investigated, grounded, and never mentioned

    result = check_completeness(dishonest, run)
    assert not result.passed
    assert any(v.kind == "undisposed_finding" for v in result.violations)
    assert any("risks" in v.detail for v in result.violations)


def test_dropped_unresolved_investigation_is_rejected() -> None:
    """An unanswered question presented as no question at all."""
    run = _run(_resolved("business_quality", "ev-1"), _unresolved("valuation"))
    thesis = synthesize(run, _Fake())
    dishonest = replace(thesis, unresolved_dimensions=())

    result = check_completeness(dishonest, run)
    assert not result.passed
    assert any(v.kind == "dropped_unresolved" for v in result.violations)


def test_phantom_disposition_is_rejected() -> None:
    """Claiming to have considered something the run never produced."""
    run = _run(_resolved("business_quality", "ev-1"))
    thesis = synthesize(run, _Fake())
    inflated = replace(thesis, dispositions=(
        Disposition(dimension="business_quality", materiality="incorporated"),
        Disposition(dimension="competitive_position", materiality="incorporated"),
    ))

    result = check_completeness(inflated, run)
    assert not result.passed
    assert any(v.kind == "phantom_disposition" for v in result.violations)


def test_phantom_unresolved_is_rejected() -> None:
    """Claiming something was unanswerable when it was in fact answered."""
    run = _run(_resolved("business_quality", "ev-1"), _resolved("valuation", "ev-2"))
    thesis = synthesize(run, _Fake(cite=["ev-1", "ev-2"]))
    excused = replace(
        thesis,
        dispositions=(Disposition(dimension="business_quality", materiality="incorporated"),),
        unresolved_dimensions=("valuation",),
    )

    result = check_completeness(excused, run)
    assert not result.passed
    assert any(v.kind == "phantom_unresolved" for v in result.violations)


def test_citation_outside_the_run_is_rejected() -> None:
    """Unreachable while synthesis goes through ask() -- asserted so a future
    synthesizer that bypassed it could not silently lose the guarantee.
    """
    run = _run(_resolved("business_quality", "ev-1"))
    thesis = synthesize(run, _Fake())

    from atlas.reasoning.contracts import ReasoningResult

    smuggled = replace(
        thesis,
        result=ReasoningResult(
            question=thesis.result.question,
            findings=thesis.result.findings,
            overall_confidence="medium",
            citations=frozenset({"ev-1", "ev-SMUGGLED"}),
        ),
    )

    result = check_completeness(smuggled, run)
    assert not result.passed
    assert any(v.kind == "citation_outside_run" for v in result.violations)


def test_multiple_violations_are_all_reported() -> None:
    """A reviewer should see every problem at once, not the first one."""
    run = _run(
        _resolved("business_quality", "ev-1"),
        _resolved("risks", "ev-2"),
        _unresolved("valuation"),
    )
    thesis = synthesize(run, _Fake(cite=["ev-1"]))
    dishonest = replace(
        thesis,
        dispositions=(Disposition(dimension="business_quality", materiality="incorporated"),),
        unresolved_dimensions=(),
    )

    result = check_completeness(dishonest, run)
    kinds = {v.kind for v in result.violations}
    assert {"undisposed_finding", "dropped_unresolved"} <= kinds


# --- Violation reporting quality ---------------------------------------------------------
def test_violations_name_the_dimension_and_explain_the_problem() -> None:
    run = _run(_resolved("business_quality", "ev-1"), _resolved("risks", "ev-2"))
    thesis = synthesize(run, _Fake(cite=["ev-1"]))
    dishonest = replace(thesis, dispositions=(
        Disposition(dimension="business_quality", materiality="incorporated"),
    ))

    violation = check_completeness(dishonest, run).violations[0]
    assert "risks" in violation.detail
    assert len(violation.detail.split()) > 6  # a sentence, not a code


def test_passing_gate_reports_no_violations() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    assert check_completeness(synthesize(run, _Fake()), run).violations == ()
