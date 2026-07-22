"""contradicts_thesis / counter_case, populated for the first time (M2.4
commit 6).

Both fields have existed on Finding (C7) since M0, declared but never set by
anything. This commit is the one that gives them a value. The load-bearing
tests are backward compatibility (a model response that never mentions these
keys must produce the exact Finding it always did) and the "no view, no
claim" property -- the model should not fabricate a contradiction when there
was nothing to check against.
"""
from __future__ import annotations

import json

from atlas.reasoning.ask import ask
from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    GroundingContext,
    Question,
    RecalledClaim,
    RecalledView,
    SubjectRef,
)
from atlas.reasoning.llm import FakeLLMClient
from atlas.reasoning.prompt import SYSTEM_PROMPT

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _context(thesis: RecalledView | None = None) -> GroundingContext:
    claim = Claim(
        subject_ref=SUBJECT, statement="Margin was 24.2% in FY26.",
        assertability="fact", confidence="high",
        evidence=[EvidenceReference(evidence_id="ev-1")],
    )
    return GroundingContext(
        subject_ref=SUBJECT, claims=[claim], evidence_index=frozenset({"ev-1"}),
        thesis=thesis,
    )


def _question(text: str = "How have margins been?") -> Question:
    return Question(raw_text=text, subject_ref=SUBJECT)


def _view() -> RecalledView:
    return RecalledView(
        view_id="view-1", subject_ref=SUBJECT, question="Should I invest in TCS?",
        claims=(RecalledClaim(
            statement="Margins were declining.", evidence_ids=frozenset({"ev-OLD"}),
            confidence="medium",
        ),),
        as_of="2026-01-01T00:00:00+00:00",
    )


def _fake(payload: dict) -> FakeLLMClient:
    return FakeLLMClient(response=json.dumps(payload))


# --- Backward compatibility: the property that must never break ------------------------
def test_response_omitting_the_new_keys_defaults_exactly_as_before() -> None:
    """Every fake-LLM response in this codebase's existing tests omits
    contradicts_thesis/counter_case -- this is what must keep working."""
    client = _fake({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Margins improved.", "assertability": "judgment",
            "confidence": "high", "supporting_evidence_ids": ["ev-1"],
            "known_unknowns": [],
        }],
    })
    result = ask(_question(), _context(), client)

    finding = result.findings[0]
    assert finding.contradicts_thesis is False
    assert finding.counter_case is None


def test_response_with_thesis_present_but_keys_omitted_still_defaults() -> None:
    """A view was supplied, but the model's response is old-shaped anyway --
    must not crash, must default the same way."""
    client = _fake({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Margins improved.", "assertability": "judgment",
            "confidence": "high", "supporting_evidence_ids": ["ev-1"],
            "known_unknowns": [],
        }],
    })
    result = ask(_question(), _context(thesis=_view()), client)

    assert result.findings[0].contradicts_thesis is False
    assert result.findings[0].counter_case is None


# --- Populated when present -----------------------------------------------------------
def test_contradicts_thesis_is_populated_when_the_model_reports_it() -> None:
    client = _fake({
        "refused": False, "overall_confidence": "medium",
        "findings": [{
            "statement": "Margins improved to 24.2%.", "assertability": "judgment",
            "confidence": "medium", "supporting_evidence_ids": ["ev-1"],
            "known_unknowns": [], "contradicts_thesis": True,
            "counter_case": "Recalled view said margins were declining; new evidence shows improvement.",
        }],
    })
    result = ask(_question(), _context(thesis=_view()), client)

    finding = result.findings[0]
    assert finding.contradicts_thesis is True
    assert "declining" in finding.counter_case


def test_contradicts_thesis_false_with_no_counter_case() -> None:
    client = _fake({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Margins improved.", "assertability": "judgment",
            "confidence": "high", "supporting_evidence_ids": ["ev-1"],
            "known_unknowns": [], "contradicts_thesis": False, "counter_case": None,
        }],
    })
    result = ask(_question(), _context(thesis=_view()), client)

    assert result.findings[0].contradicts_thesis is False
    assert result.findings[0].counter_case is None


def test_counter_case_string_is_coerced_and_empty_string_becomes_none() -> None:
    client = _fake({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "x.", "assertability": "fact", "confidence": "high",
            "supporting_evidence_ids": ["ev-1"], "known_unknowns": [],
            "contradicts_thesis": False, "counter_case": "",
        }],
    })
    result = ask(_question(), _context(thesis=_view()), client)
    assert result.findings[0].counter_case is None


def test_multiple_findings_can_disagree_independently() -> None:
    """One finding may contradict the recalled view while a sibling does
    not -- per-finding, not per-result."""
    client = _fake({
        "refused": False, "overall_confidence": "medium",
        "findings": [
            {
                "statement": "Margins improved.", "assertability": "judgment",
                "confidence": "medium", "supporting_evidence_ids": ["ev-1"],
                "known_unknowns": [], "contradicts_thesis": True,
                "counter_case": "Contradicts the recalled decline.",
            },
            {
                "statement": "Revenue in line with expectations.", "assertability": "fact",
                "confidence": "high", "supporting_evidence_ids": ["ev-1"],
                "known_unknowns": [],
            },
        ],
    })
    result = ask(_question(), _context(thesis=_view()), client)

    assert result.findings[0].contradicts_thesis is True
    assert result.findings[1].contradicts_thesis is False


# --- Rule 7 exists in the system prompt, only meaningfully with a view --------------------
def test_system_prompt_documents_rule_7() -> None:
    assert "contradicts_thesis" in SYSTEM_PROMPT
    assert "RECALLED VIEW" in SYSTEM_PROMPT


def test_system_prompt_says_do_not_force_a_contradiction() -> None:
    """The 'no view, no claim' property, stated to the model directly."""
    assert "Do not force a" in SYSTEM_PROMPT


def test_synthesis_prompt_is_unmodified_by_this_commit() -> None:
    """Synthesis forms a NEW view; it does not compare against a recalled
    one -- rule 7 and its schema fields belong only to question-answering."""
    from atlas.reasoning.prompt import SYNTHESIS_PROMPT

    assert "contradicts_thesis" not in SYNTHESIS_PROMPT
