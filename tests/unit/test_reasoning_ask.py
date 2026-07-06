"""ask() orchestration + citation validation (§10 C7/C8, M0 commit 5).

Uses FakeLLMClient — no network. These tests pin the integrity guarantees that
gate release (§8.6 tests 25, 36-41): no invented citations (G10), grounded
judgment (G3/G4), and graceful refusal (G8).
"""
from __future__ import annotations

import json

from atlas.reasoning.ask import ask
from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    GroundingContext,
    Question,
    SubjectRef,
)
from atlas.reasoning.llm import FakeLLMClient

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")


def _context() -> GroundingContext:
    claim = Claim(
        subject_ref=SUBJECT,
        statement="operating margin = 24.2 (annual, period 2026-03-31)",
        assertability="fact",
        confidence="high",
        evidence=[EvidenceReference(evidence_id="ev-1")],
    )
    return GroundingContext(
        subject_ref=SUBJECT, claims=[claim], evidence_index=frozenset({"ev-1"})
    )


def _question(text: str = "How have margins been?") -> Question:
    return Question(raw_text=text, subject_ref=SUBJECT)


def _fake(payload: dict) -> FakeLLMClient:
    return FakeLLMClient(response=json.dumps(payload))


def test_valid_grounded_answer_produces_result() -> None:
    client = _fake({
        "refused": False, "refusal_reason": None, "overall_confidence": "high",
        "findings": [{
            "statement": "Operating margin has been ~24%.",
            "assertability": "judgment", "confidence": "high",
            "supporting_evidence_ids": ["ev-1"], "known_unknowns": [],
        }],
    })
    result = ask(_question(), _context(), client)
    assert not result.refused
    assert result.citations == frozenset({"ev-1"})
    assert result.findings[0].assertability == "judgment"


def test_hallucinated_citation_is_dropped() -> None:
    # Model cites an id that is NOT in the closed world; it must not survive (G10).
    client = _fake({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Margins are great.",
            "assertability": "judgment", "confidence": "high",
            "supporting_evidence_ids": ["ev-DOES-NOT-EXIST"], "known_unknowns": [],
        }],
    })
    result = ask(_question(), _context(), client)
    # The only finding was ungrounded after filtering -> refusal, no bad citation.
    assert result.refused
    assert result.citations == frozenset()


def test_mixed_valid_and_invalid_ids_keeps_only_valid() -> None:
    client = _fake({
        "refused": False, "overall_confidence": "medium",
        "findings": [{
            "statement": "Margin ~24%.", "assertability": "judgment", "confidence": "medium",
            "supporting_evidence_ids": ["ev-1", "ev-bogus"], "known_unknowns": [],
        }],
    })
    result = ask(_question(), _context(), client)
    assert result.citations == frozenset({"ev-1"})  # ev-bogus dropped


def test_graceful_refusal_is_passed_through() -> None:
    client = _fake({
        "refused": True, "refusal_reason": "No market price data in Atlas.",
        "overall_confidence": "low", "findings": [],
    })
    result = ask(_question("What is the stock worth?"), _context(), client)
    assert result.refused
    assert "market price" in (result.refusal_reason or "")
    assert result.findings == ()


def test_unparseable_output_refuses_rather_than_crashes() -> None:
    result = ask(_question(), _context(), FakeLLMClient(response="not json at all"))
    assert result.refused
    assert result.citations == frozenset()


def test_json_wrapped_in_code_fence_is_parsed() -> None:
    body = json.dumps({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Margin ~24%.", "assertability": "fact", "confidence": "high",
            "supporting_evidence_ids": ["ev-1"], "known_unknowns": [],
        }],
    })
    result = ask(_question(), _context(), FakeLLMClient(response=f"```json\n{body}\n```"))
    assert not result.refused
    assert result.citations == frozenset({"ev-1"})
