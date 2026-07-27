"""build_user_prompt (M1 commit 3: renders retrieved excerpts alongside facts)."""

from __future__ import annotations

from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    GroundingContext,
    Question,
    SubjectRef,
)
from atlas.reasoning.prompt import build_user_prompt

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")


def _question() -> Question:
    return Question(raw_text="How stable are margins?", subject_ref=SUBJECT)


def test_no_excerpt_renders_terse_fact_only_m0_equivalent() -> None:
    claim = Claim(
        subject_ref=SUBJECT,
        statement="operating margin = 24.2",
        assertability="fact",
        confidence="high",
        evidence=[EvidenceReference(evidence_id="ev-1")],
    )
    context = GroundingContext(
        subject_ref=SUBJECT, claims=[claim], evidence_index=frozenset({"ev-1"})
    )
    prompt = build_user_prompt(_question(), context)
    assert "operating margin = 24.2" in prompt
    assert "source text:" not in prompt


def test_hydrated_excerpt_is_rendered_alongside_fact() -> None:
    ref = EvidenceReference(
        evidence_id="ev-1",
        excerpt="Operating margin stood at 24.2% in FY26.",
    )
    claim = Claim(
        subject_ref=SUBJECT,
        statement="operating margin = 24.2",
        assertability="fact",
        confidence="high",
        evidence=[ref],
    )
    context = GroundingContext(
        subject_ref=SUBJECT, claims=[claim], evidence_index=frozenset({"ev-1"})
    )
    prompt = build_user_prompt(_question(), context)
    assert 'source text: "Operating margin stood at 24.2% in FY26."' in prompt


def test_duplicate_excerpts_across_refs_render_once() -> None:
    same_excerpt = "Operating margin stood at 24.2% in FY26."
    refs = (
        EvidenceReference(evidence_id="ev-1", excerpt=same_excerpt),
        EvidenceReference(evidence_id="ev-2", excerpt=same_excerpt),
    )
    claim = Claim(
        subject_ref=SUBJECT,
        statement="operating margin = 24.2",
        assertability="fact",
        confidence="high",
        evidence=refs,
    )
    context = GroundingContext(
        subject_ref=SUBJECT,
        claims=[claim],
        evidence_index=frozenset({"ev-1", "ev-2"}),
    )
    prompt = build_user_prompt(_question(), context)
    assert prompt.count("source text:") == 1
