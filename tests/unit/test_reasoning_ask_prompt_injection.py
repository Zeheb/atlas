"""ask()'s injectable prompt seam (M2.3 commit 1).

The point of these tests is NOT that a custom prompt reaches the model -- that
is trivially true. It is that every grounding guarantee below the model call
holds identically with a custom prompt, because those guarantees are enforced
against the GroundingContext and never against the prompt text.

If a future refactor ever moved a citation check into prompt construction,
these tests fail. That is what they are for.
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
from atlas.reasoning.prompt import SYSTEM_PROMPT, build_user_prompt

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


class _CapturingClient:
    """Records what it was asked, returns one grounded finding."""

    def __init__(self) -> None:
        self.system: str | None = None
        self.user: str | None = None

    def complete(self, *, system: str, user: str) -> str:
        self.system, self.user = system, user
        return json.dumps({
            "refused": False, "overall_confidence": "high",
            "findings": [{
                "statement": "Margins ~24%.", "assertability": "judgment",
                "confidence": "high", "supporting_evidence_ids": ["ev-1"],
                "known_unknowns": [],
            }],
        })


# --- The defaults are unchanged (every existing call site is unaffected) -----------
def test_defaults_are_the_m0_question_answering_pair() -> None:
    client = _CapturingClient()
    ask(_question(), _context(), client)

    assert client.system == SYSTEM_PROMPT
    assert client.user == build_user_prompt(_question(), _context())


# --- Injection reaches the model ----------------------------------------------------
def test_custom_prompts_are_used() -> None:
    client = _CapturingClient()
    ask(
        _question(), _context(), client,
        system_prompt="CUSTOM SYSTEM",
        build_prompt=lambda q, c: f"CUSTOM USER for {q.raw_text}",
    )

    assert client.system == "CUSTOM SYSTEM"
    assert client.user == "CUSTOM USER for How have margins been?"


# --- Every guarantee still holds with a custom prompt (the actual point) ------------
def test_invented_citation_still_dropped_with_custom_prompt() -> None:
    """G10: an id outside the closed world is dropped no matter what was asked."""
    client = _fake({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Margins ~24%.", "assertability": "fact",
            "confidence": "high",
            "supporting_evidence_ids": ["ev-1", "ev-DOES-NOT-EXIST"],
            "known_unknowns": [],
        }],
    })
    result = ask(
        _question(), _context(), client,
        system_prompt="anything", build_prompt=lambda q, c: "anything",
    )

    assert result.citations == frozenset({"ev-1"})
    assert "ev-DOES-NOT-EXIST" not in result.citations


def test_ungrounded_judgment_still_dropped_with_custom_prompt() -> None:
    """G3/G4: a judgment with no valid support cannot survive, prompt aside."""
    client = _fake({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Margins are excellent.", "assertability": "judgment",
            "confidence": "high", "supporting_evidence_ids": ["ev-NOPE"],
            "known_unknowns": [],
        }],
    })
    result = ask(
        _question(), _context(), client,
        system_prompt="anything", build_prompt=lambda q, c: "anything",
    )

    # Nothing grounded survived -> refusal, not an empty answer (G8).
    assert result.refused
    assert result.findings == ()


def test_refusal_still_honored_with_custom_prompt() -> None:
    client = _fake({
        "refused": True, "refusal_reason": "out of scope", "findings": [],
    })
    result = ask(
        _question(), _context(), client,
        system_prompt="anything", build_prompt=lambda q, c: "anything",
    )

    assert result.refused
    assert result.refusal_reason == "out of scope"


def test_unparseable_output_still_refuses_with_custom_prompt() -> None:
    result = ask(
        _question(), _context(), FakeLLMClient(response="not json at all"),
        system_prompt="anything", build_prompt=lambda q, c: "anything",
    )

    assert result.refused


def test_citations_subset_invariant_holds_with_custom_prompt() -> None:
    """ReasoningResult.__post_init__ enforces citations >= findings' evidence;
    it constructs successfully here, which is the assertion."""
    client = _CapturingClient()
    result = ask(
        _question(), _context(), client,
        system_prompt="S", build_prompt=lambda q, c: "U",
    )

    finding_ids = {eid for f in result.findings for eid in f.evidence_ids}
    assert finding_ids <= result.citations
    assert result.citations <= _context().evidence_index
