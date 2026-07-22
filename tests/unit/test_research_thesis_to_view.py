"""Thesis.to_view() and deterministic view_id (M2.4 commit 2).

The load-bearing property here is determinism: two syntheses over identical
evidence must produce the same view_id, and any evidence change must produce
a different one. That is what lets ThesisStore.list() show genuinely
distinct views later, rather than silently overwriting history with random
ids.
"""
from __future__ import annotations

import json

from atlas.reasoning.contracts import Claim, EvidenceReference, SubjectRef
from atlas.research.citations import Finding
from atlas.research.investigate import InvestigationResult, InvestigationRun
from atlas.research.plan import Investigation, ResearchPlan
from atlas.research.thesis import compute_view_id, run_fingerprint, synthesize

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


def _run(*results: InvestigationResult, question: str = "Should I invest in TCS?") -> InvestigationRun:
    used = results or (_resolved("business_quality"),)
    return InvestigationRun(
        plan=ResearchPlan(
            raw_question=question, intent="invest_decision", subjects=("TCS",),
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


# --- Determinism: the property that actually matters -----------------------------------
def test_view_id_is_stable_across_identical_syntheses() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    t1 = synthesize(run, _Fake())
    t2 = synthesize(run, _Fake())

    assert t1.view_id == t2.view_id


def test_view_id_changes_when_evidence_changes() -> None:
    run_a = _run(_resolved("business_quality", "ev-1"))
    run_b = _run(_resolved("business_quality", "ev-2"))

    assert synthesize(run_a, _Fake(cite=["ev-1"])).view_id != \
        synthesize(run_b, _Fake(cite=["ev-2"])).view_id


def test_view_id_changes_when_the_question_changes() -> None:
    run_a = _run(_resolved("business_quality", "ev-1"), question="Should I invest in TCS?")
    run_b = _run(_resolved("business_quality", "ev-1"), question="What are the risks to TCS?")

    assert synthesize(run_a, _Fake()).view_id != synthesize(run_b, _Fake()).view_id


def test_view_id_is_computed_from_run_fingerprint_and_question_directly() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    thesis = synthesize(run, _Fake())

    assert thesis.view_id == compute_view_id(run_fingerprint(run), run.plan.raw_question)


def test_view_id_is_not_a_uuid() -> None:
    """Deterministic identity, not a random one -- the whole point."""
    run = _run(_resolved("business_quality", "ev-1"))
    thesis = synthesize(run, _Fake())

    assert len(thesis.view_id) == 64  # sha256 hex digest
    assert all(c in "0123456789abcdef" for c in thesis.view_id)


def test_as_of_is_populated() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    thesis = synthesize(run, _Fake())

    assert thesis.as_of  # non-empty ISO timestamp
    from datetime import datetime

    datetime.fromisoformat(thesis.as_of)  # must not raise


# --- to_view(): the projection ------------------------------------------------------------
def test_to_view_carries_the_same_view_id() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    thesis = synthesize(run, _Fake())

    assert thesis.to_view().view_id == thesis.view_id


def test_to_view_carries_the_same_question_and_as_of() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    thesis = synthesize(run, _Fake())
    view = thesis.to_view()

    assert view.question == thesis.question
    assert view.as_of == thesis.as_of


def test_to_view_defaults_origin_to_atlas() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    assert synthesize(run, _Fake()).to_view().origin == "atlas"


def test_to_view_produces_one_claim_per_finding() -> None:
    run = _run(_resolved("business_quality", "ev-1"), _resolved("risks", "ev-2"))
    thesis = synthesize(run, _Fake(cite=["ev-1", "ev-2"]))
    view = thesis.to_view()

    assert len(view.claims) == len(thesis.result.findings)


def test_to_view_reuses_evidence_and_confidence_without_recomputing() -> None:
    """The projection must not recompute anything the gate already checked --
    two copies that could drift is the exact hazard this design avoids."""
    run = _run(_resolved("business_quality", "ev-1"))
    thesis = synthesize(run, _Fake())
    view = thesis.to_view()

    finding = thesis.result.findings[0]
    claim = view.claims[0]
    assert claim.statement == finding.statement
    assert claim.evidence_ids == finding.evidence_ids
    assert claim.confidence == finding.confidence


def test_to_view_subject_ref_matches_the_thesis_subject() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    thesis = synthesize(run, _Fake())
    view = thesis.to_view()

    assert view.subject_ref.subject_id == "TCS"


def test_to_view_is_a_valid_recalled_view() -> None:
    """Round-trips through RecalledView's own __post_init__ without raising --
    proves the projection always satisfies the contract's invariants."""
    run = _run(_resolved("business_quality", "ev-1"), _resolved("risks", "ev-2"))
    thesis = synthesize(run, _Fake(cite=["ev-1", "ev-2"]))
    view = thesis.to_view()  # must not raise

    assert view.claims  # RecalledView.__post_init__ requires non-empty


# --- to_dict() carries the new fields ----------------------------------------------------
def test_to_dict_includes_view_id_and_as_of() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    thesis = synthesize(run, _Fake())
    payload = thesis.to_dict()

    assert payload["view_id"] == thesis.view_id
    assert payload["as_of"] == thesis.as_of


def test_to_dict_is_still_json_serializable() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    json.dumps(synthesize(run, _Fake()).to_dict())
