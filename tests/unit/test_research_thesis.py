"""Thesis synthesis (M2.3 commit 4).

The load-bearing test here is test_citation_outside_the_run_cannot_reach_the_thesis:
it proves the closed world is genuinely INHERITED from ask() rather than
re-implemented. If a future refactor ever bypassed ask(), that test fails --
which is the point of building synthesis as a reasoning pass in the first
place.
"""
from __future__ import annotations

import json

import pytest

from atlas.reasoning.contracts import Claim, EvidenceReference, SubjectRef
from atlas.research.citations import Finding
from atlas.research.investigate import InvestigationResult, InvestigationRun
from atlas.research.plan import Investigation, ResearchPlan
from atlas.research.thesis import (
    Disposition,
    SynthesisError,
    Thesis,
    build_synthesis_context,
    run_fingerprint,
    synthesize,
)

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


# --- Builders --------------------------------------------------------------------------
def _investigation(dimension: str = "business_quality") -> Investigation:
    return Investigation(
        dimension=dimension,
        question=f"What does {dimension} show?",
        subjects=("TCS",),
        rationale="it is one of the dimensions a view must rest on",
        priority=5,
    )


def _semantic(statement: str, eid: str, confidence: str = "high",
              assertability: str = "judgment"):
    from atlas.reasoning.contracts import Finding as SemanticFinding

    return SemanticFinding(
        statement=statement,
        assertability=assertability,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        supporting_claims=(Claim(
            subject_ref=SUBJECT, statement=statement,
            assertability="fact", confidence=confidence,  # type: ignore[arg-type]
            evidence=[EvidenceReference(evidence_id=eid)],
        ),),
    )


def _resolved(dimension: str, eid: str = "ev-1", confidence: str = "high") -> InvestigationResult:
    return InvestigationResult(
        investigation=_investigation(dimension),
        finding=Finding(text=f"{dimension} looks fine.", evidence_ids=[eid]),
        semantic_findings=(_semantic(f"{dimension} looks fine.", eid, confidence),),
    )


def _unresolved(dimension: str) -> InvestigationResult:
    return InvestigationResult(
        investigation=_investigation(dimension),
        unresolved_reason="refused: no evidence",
    )


def _plan(*dimensions: str) -> ResearchPlan:
    return ResearchPlan(
        raw_question="Should I invest in TCS?",
        intent="invest_decision",
        subjects=("TCS",),
        investigations=tuple(_investigation(d) for d in (dimensions or ("business_quality",))),
    )


def _run(*results: InvestigationResult) -> InvestigationRun:
    used = results or (_resolved("business_quality"),)
    return InvestigationRun(
        plan=_plan(*[r.dimension for r in used]),
        results=used,
    )


class _Fake:
    """Synthesizes, citing whatever ids it is told to."""

    def __init__(self, cite: list[str] | None = None, refused: bool = False) -> None:
        self._cite = cite if cite is not None else ["ev-1"]
        self._refused = refused
        self.user_prompt: str | None = None

    def complete(self, *, system: str, user: str) -> str:
        self.user_prompt = user
        if self._refused:
            return json.dumps({
                "refused": True, "overall_confidence": "low",
                "refusal_reason": "the findings do not support a view", "findings": [],
            })
        return json.dumps({
            "refused": False, "overall_confidence": "medium",
            "findings": [{
                "statement": "The business looks durable but fairly priced.",
                "assertability": "judgment", "confidence": "medium",
                "supporting_evidence_ids": self._cite,
                "known_unknowns": ["no segment detail"],
            }],
        })


# --- THE load-bearing test: closed world is inherited, not rebuilt ---------------------
def test_citation_outside_the_run_cannot_reach_the_thesis() -> None:
    """A synthesizer citing a real-but-unretrieved id must not be able to
    smuggle it into a Thesis. ask() drops it before Thesis is constructed --
    there is no second gate to keep in sync.
    """
    run = _run(_resolved("business_quality", eid="ev-1"))
    thesis = synthesize(run, _Fake(cite=["ev-1", "ev-NOT-IN-RUN"]))

    assert thesis.citations == frozenset({"ev-1"})
    assert "ev-NOT-IN-RUN" not in thesis.citations


def test_thesis_citations_are_a_subset_of_the_runs_evidence() -> None:
    run = _run(_resolved("business_quality", "ev-1"), _resolved("valuation", "ev-2"))
    thesis = synthesize(run, _Fake(cite=["ev-1", "ev-2"]))

    run_evidence = build_synthesis_context(run, SUBJECT).evidence_index
    assert thesis.citations <= run_evidence


def test_synthesis_citing_only_invalid_ids_raises_rather_than_producing_a_thesis() -> None:
    """Nothing grounded survives -> ask() refuses -> not a degraded thesis,
    no thesis at all."""
    run = _run(_resolved("business_quality", "ev-1"))
    with pytest.raises(SynthesisError, match="refused"):
        synthesize(run, _Fake(cite=["ev-BOGUS"]))


# --- Synthesis context ------------------------------------------------------------------
def test_context_claims_come_from_the_runs_findings() -> None:
    run = _run(_resolved("business_quality", "ev-1"), _resolved("risks", "ev-2"))
    ctx = build_synthesis_context(run, SUBJECT)

    assert len(ctx.claims) == 2
    assert ctx.evidence_index == frozenset({"ev-1", "ev-2"})


def test_unresolved_investigations_contribute_no_claims() -> None:
    run = _run(_resolved("business_quality", "ev-1"), _unresolved("valuation"))
    ctx = build_synthesis_context(run, SUBJECT)

    assert len(ctx.claims) == 1


def test_context_preserves_per_finding_confidence() -> None:
    """Synthesis rule 4 depends on it reaching the prompt."""
    run = _run(_resolved("business_quality", "ev-1", confidence="low"))
    ctx = build_synthesis_context(run, SUBJECT)

    assert ctx.claims[0].confidence == "low"


def test_confidence_reaches_the_model(monkeypatch) -> None:
    run = _run(_resolved("business_quality", "ev-1", confidence="low"))
    fake = _Fake()
    synthesize(run, fake)

    assert fake.user_prompt is not None
    assert "confidence: low" in fake.user_prompt


def test_falls_back_to_the_flattened_view_for_pre_m23_runs() -> None:
    """A run recorded before semantic_findings existed still synthesizes."""
    legacy = InvestigationResult(
        investigation=_investigation("business_quality"),
        finding=Finding(text="Margins improved.", evidence_ids=["ev-1"]),
    )
    ctx = build_synthesis_context(_run(legacy), SUBJECT)

    assert len(ctx.claims) == 1
    assert ctx.claims[0].confidence == "medium"  # honest unknown, not invented "high"


# --- Refusal / empty handling ------------------------------------------------------------
def test_run_with_no_grounded_findings_raises() -> None:
    run = _run(_unresolved("business_quality"), _unresolved("valuation"))
    with pytest.raises(SynthesisError, match="nothing to synthesize"):
        synthesize(run, _Fake())


def test_refused_synthesis_raises_rather_than_returning_an_empty_thesis() -> None:
    with pytest.raises(SynthesisError, match="synthesis refused"):
        synthesize(_run(), _Fake(refused=True))


# --- Thesis invariants --------------------------------------------------------------------
def _thesis(**overrides) -> Thesis:
    run = _run(_resolved("business_quality", "ev-1"))
    base = synthesize(run, _Fake())
    if not overrides:
        return base
    from dataclasses import replace

    return replace(base, **overrides)


def test_thesis_rejects_a_refused_result() -> None:
    run = _run(_resolved("business_quality", "ev-1"))
    good = synthesize(run, _Fake())
    from atlas.reasoning.contracts import ReasoningResult

    refused = ReasoningResult(
        question=good.result.question, findings=(), overall_confidence="low",
        citations=frozenset(), refused=True, refusal_reason="nope",
    )
    with pytest.raises(ValueError, match="refused ReasoningResult"):
        _thesis(result=refused)


def test_thesis_rejects_duplicate_dispositions() -> None:
    with pytest.raises(ValueError, match="duplicate disposition"):
        _thesis(dispositions=(
            Disposition(dimension="risks", materiality="incorporated"),
            Disposition(dimension="risks", materiality="incorporated"),
        ))


def test_thesis_rejects_a_dimension_both_disposed_and_unresolved() -> None:
    with pytest.raises(ValueError, match="both disposed and unresolved"):
        _thesis(
            dispositions=(Disposition(dimension="risks", materiality="incorporated"),),
            unresolved_dimensions=("risks",),
        )


def test_thesis_rejects_empty_question() -> None:
    with pytest.raises(ValueError, match="question must be non-empty"):
        _thesis(question="  ")


def test_thesis_rejects_no_subjects() -> None:
    with pytest.raises(ValueError, match="at least one subject"):
        _thesis(subjects=())


# --- Disposition invariants ----------------------------------------------------------------
def test_not_material_disposition_requires_a_reason() -> None:
    """Setting a finding aside without saying why is silent omission wearing
    a label."""
    with pytest.raises(ValueError, match="must say why it was set aside"):
        Disposition(dimension="risks", materiality="not_material")


def test_incorporated_disposition_needs_no_rationale() -> None:
    Disposition(dimension="risks", materiality="incorporated")  # must not raise


def test_invalid_materiality_rejected() -> None:
    with pytest.raises(ValueError, match="not a valid Materiality"):
        Disposition(dimension="risks", materiality="contradicting")  # type: ignore[arg-type]


def test_no_contradiction_vocabulary_exists() -> None:
    """M2.3 makes no semantic claim about contradiction. If a future commit
    adds one, it should be a deliberate design decision (M2.4), not a drift.
    """
    from atlas.research import thesis as thesis_mod

    assert not hasattr(thesis_mod, "Contradiction")
    assert "contradicting" not in thesis_mod._VALID_MATERIALITY


# --- No rating surface -----------------------------------------------------------------------
def test_thesis_exposes_no_rating_or_price_target() -> None:
    """Atlas issues no buy/sell recommendation; the type makes that
    structurally true, so a future edit cannot add one silently."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(Thesis)}
    for banned in ("stance", "rating", "recommendation", "target_price", "position_size"):
        assert banned not in fields


# --- Bookkeeping ------------------------------------------------------------------------------
def test_every_resolved_investigation_gets_a_disposition() -> None:
    run = _run(_resolved("business_quality", "ev-1"), _resolved("valuation", "ev-2"))
    thesis = synthesize(run, _Fake(cite=["ev-1", "ev-2"]))

    assert set(thesis.incorporated_dimensions) == {"business_quality", "valuation"}


def test_unresolved_investigations_are_carried_through() -> None:
    run = _run(_resolved("business_quality", "ev-1"), _unresolved("valuation"))
    thesis = synthesize(run, _Fake())

    assert thesis.unresolved_dimensions == ("valuation",)
    assert "valuation" not in thesis.incorporated_dimensions


def test_fingerprint_is_stable_and_evidence_sensitive() -> None:
    a = _run(_resolved("business_quality", "ev-1"))
    b = _run(_resolved("business_quality", "ev-1"))
    c = _run(_resolved("business_quality", "ev-2"))

    assert run_fingerprint(a) == run_fingerprint(b)
    assert run_fingerprint(a) != run_fingerprint(c)  # same plan, different evidence


def test_to_dict_is_json_serializable() -> None:
    json.dumps(synthesize(_run(), _Fake()).to_dict())


def test_to_dict_carries_findings_and_dispositions() -> None:
    payload = synthesize(_run(), _Fake()).to_dict()

    assert payload["findings"][0]["statement"]
    assert payload["citations"] == ["ev-1"]
    assert payload["dispositions"][0]["materiality"] == "incorporated"
