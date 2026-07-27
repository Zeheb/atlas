"""Contract-type invariants for the reasoning subsystem (§10, M0 commit 2).

These tests pin the §10 invariants that make the §8 product guarantees
type-level facts. If a future change relaxes one of these, a test breaks —
which is the point: the contracts are frozen, the implementations behind them
are not.
"""

from __future__ import annotations

import pytest

from atlas.reasoning.contracts import (
    Answer,
    Claim,
    EvidenceReference,
    Finding,
    GroundingContext,
    Question,
    ReasoningResult,
    Resolution,
    SubjectRef,
)

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")


def _ref(eid: str = "bse-ev-1") -> EvidenceReference:
    return EvidenceReference(evidence_id=eid)


def _claim(eid: str = "bse-ev-1", assertability: str = "fact") -> Claim:
    return Claim(
        subject_ref=SUBJECT,
        statement="operating margin was 24.2% (FY2026)",
        assertability=assertability,  # type: ignore[arg-type]
        confidence="high",
        evidence=[_ref(eid)],
    )


# --- C1 SubjectRef -----------------------------------------------------------
def test_subjectref_requires_id() -> None:
    with pytest.raises(ValueError):
        SubjectRef(subject_id="", display="x")


# --- C2 EvidenceReference (amendment M0-01: excerpt optional) -----------------
def test_evidenceref_excerpt_is_optional() -> None:
    ref = EvidenceReference(evidence_id="bse-ev-1")
    assert ref.excerpt is None


def test_evidenceref_requires_id() -> None:
    with pytest.raises(ValueError):
        EvidenceReference(evidence_id="")


# --- C3 Claim (G10: no unbacked claim) ---------------------------------------
def test_claim_requires_at_least_one_evidence() -> None:
    with pytest.raises(ValueError):
        Claim(
            subject_ref=SUBJECT,
            statement="x",
            assertability="fact",
            confidence="high",
            evidence=[],
        )


def test_claim_exposes_evidence_ids() -> None:
    assert _claim("bse-ev-9").evidence_ids == frozenset({"bse-ev-9"})


def test_resolution_delivered_requires_backing() -> None:
    with pytest.raises(ValueError):
        Resolution(status="missed", resolved_by=[])


# --- C4 Question -------------------------------------------------------------
def test_question_rejects_blank_text() -> None:
    with pytest.raises(ValueError):
        Question(raw_text="   ", subject_ref=SUBJECT)


def test_question_defaults_to_unclassified() -> None:
    assert Question(raw_text="q", subject_ref=SUBJECT).question_class == "unclassified"


# --- C5 GroundingContext (closed-world index) --------------------------------
def test_grounding_index_must_cover_claim_evidence() -> None:
    with pytest.raises(ValueError):
        GroundingContext(
            subject_ref=SUBJECT,
            claims=[_claim("bse-ev-1")],
            evidence_index=frozenset({"some-other-id"}),
        )


def test_grounding_context_ok_when_index_covers_claims() -> None:
    ctx = GroundingContext(
        subject_ref=SUBJECT,
        claims=[_claim("bse-ev-1")],
        evidence_index=frozenset({"bse-ev-1"}),
    )
    assert "bse-ev-1" in ctx.evidence_index


# --- C7 Finding (G3/G4: no ungrounded judgment) ------------------------------
def test_judgment_finding_requires_supporting_claim() -> None:
    with pytest.raises(ValueError):
        Finding(
            statement="management is credible",
            assertability="judgment",
            confidence="high",
            supporting_claims=[],
        )


def test_fact_finding_may_have_no_supporting_claim() -> None:
    f = Finding(
        statement="revenue rose",
        assertability="fact",
        confidence="high",
        supporting_claims=[],
    )
    assert f.assertability == "fact"


# --- C8 ReasoningResult (G8 refusal; G1 citation coverage) -------------------
def test_refused_result_must_have_reason_and_no_findings() -> None:
    with pytest.raises(ValueError):
        ReasoningResult(
            question=Question(raw_text="q", subject_ref=SUBJECT),
            findings=[],
            overall_confidence="low",
            citations=frozenset(),
            refused=True,
            refusal_reason=None,
        )


def test_result_citations_must_cover_finding_evidence() -> None:
    finding = Finding(
        statement="margin durable",
        assertability="judgment",
        confidence="high",
        supporting_claims=[_claim("bse-ev-1")],
    )
    with pytest.raises(ValueError):
        ReasoningResult(
            question=Question(raw_text="q", subject_ref=SUBJECT),
            findings=[finding],
            overall_confidence="high",
            citations=frozenset(),  # missing bse-ev-1
        )


def test_valid_result_roundtrips() -> None:
    finding = Finding(
        statement="margin durable",
        assertability="judgment",
        confidence="high",
        supporting_claims=[_claim("bse-ev-1")],
    )
    result = ReasoningResult(
        question=Question(raw_text="q", subject_ref=SUBJECT),
        findings=[finding],
        overall_confidence="high",
        citations=frozenset({"bse-ev-1"}),
    )
    assert not result.refused
    assert result.citations == frozenset({"bse-ev-1"})


# --- C9 Answer ---------------------------------------------------------------
def test_refused_answer_requires_reason() -> None:
    with pytest.raises(ValueError):
        Answer(
            prose="",
            citations=[],
            overall_confidence="low",
            refused=True,
            refusal_reason=None,
        )
