"""SYNTHESIS_PROMPT / build_synthesis_prompt (M2.3 commit 2).

Two things are worth pinning here. First, that the synthesis prompt exposes
per-input confidence and assertability, since one of its own rules is
unfollowable without them. Second, that it makes the closed world exactly as
explicit as the question-answering prompt does -- the prompt is where the
model learns what it may cite, and a synthesis prompt that forgot to say so
would silently degrade grounding even though ask() would still catch it.
"""

from __future__ import annotations

from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    GroundingContext,
    Question,
    SubjectRef,
)
from atlas.reasoning.prompt import (
    SYNTHESIS_PROMPT,
    SYSTEM_PROMPT,
    build_synthesis_prompt,
    build_user_prompt,
)

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")


def _claim(
    statement: str,
    eid: str,
    confidence: str = "high",
    assertability: str = "judgment",
    excerpt: str | None = None,
) -> Claim:
    return Claim(
        subject_ref=SUBJECT,
        statement=statement,
        assertability=assertability,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        evidence=[EvidenceReference(evidence_id=eid, excerpt=excerpt)],
    )


def _context(*claims: Claim) -> GroundingContext:
    used = claims or (_claim("Margins improved to 24.2%.", "ev-1"),)
    return GroundingContext(
        subject_ref=SUBJECT,
        claims=list(used),
        evidence_index=frozenset(e for c in used for e in c.evidence_ids),
    )


def _question(text: str = "Should I invest in TCS?") -> Question:
    return Question(raw_text=text, subject_ref=SUBJECT)


# --- What synthesis exposes that question-answering does not ------------------------
def test_synthesis_prompt_exposes_input_confidence() -> None:
    """Synthesis rule 4 ("cannot be more confident than its inputs") is
    unfollowable if the model cannot see each input's confidence."""
    rendered = build_synthesis_prompt(
        _question(),
        _context(_claim("Margins improved.", "ev-1", confidence="low")),
    )
    assert "confidence: low" in rendered


def test_synthesis_prompt_exposes_assertability() -> None:
    rendered = build_synthesis_prompt(
        _question(),
        _context(_claim("Margins improved.", "ev-1", assertability="fact")),
    )
    assert "(fact," in rendered


def test_question_answering_prompt_still_omits_both() -> None:
    """The M0 prompt is unchanged -- this is what makes the two pairs distinct
    rather than one prompt with a flag."""
    ctx = _context(_claim("Margins improved.", "ev-1", confidence="low"))
    rendered = build_user_prompt(_question(), ctx)

    assert "confidence: low" not in rendered
    assert "(judgment," not in rendered


# --- The closed world is stated just as explicitly ----------------------------------
def test_synthesis_prompt_names_the_valid_evidence_ids() -> None:
    rendered = build_synthesis_prompt(
        _question(),
        _context(_claim("A.", "ev-1"), _claim("B.", "ev-2")),
    )
    assert "VALID EVIDENCE IDS: ev-1, ev-2" in rendered


def test_synthesis_prompt_says_cite_only_these() -> None:
    rendered = build_synthesis_prompt(_question(), _context())
    assert "you may cite ONLY these evidence ids" in rendered


def test_synthesis_prompt_carries_evidence_ids_per_input() -> None:
    rendered = build_synthesis_prompt(
        _question(),
        _context(_claim("Margins improved.", "ev-42")),
    )
    assert "[ev-42]" in rendered


def test_synthesis_prompt_renders_excerpts_when_present() -> None:
    rendered = build_synthesis_prompt(
        _question(),
        _context(_claim("Margins improved.", "ev-1", excerpt="Margin was 24.2%.")),
    )
    assert 'source text: "Margin was 24.2%."' in rendered


def test_synthesis_prompt_carries_the_research_question() -> None:
    rendered = build_synthesis_prompt(_question("Is TCS worth owning?"), _context())
    assert "Is TCS worth owning?" in rendered


# --- The system prompt's guarantees -------------------------------------------------
def test_synthesis_system_prompt_forbids_inventing_ids() -> None:
    assert "Never invent an evidence id" in SYNTHESIS_PROMPT


def test_synthesis_system_prompt_forbids_new_facts() -> None:
    assert "Do not introduce new facts" in SYNTHESIS_PROMPT


def test_synthesis_system_prompt_forbids_averaging_away_disagreement() -> None:
    """M2.3 detects no contradictions, but it must not silently erase one
    either -- the prompt is where that is asked for."""
    assert "Do not average away disagreement" in SYNTHESIS_PROMPT


def test_synthesis_system_prompt_forbids_ratings() -> None:
    """Atlas issues no buy/sell recommendation -- stated in the report today,
    and now stated to the synthesizer too."""
    assert "NO buy/sell recommendation" in SYNTHESIS_PROMPT


def test_synthesis_system_prompt_requires_the_same_json_shape() -> None:
    """ask()'s parser is shared, so the schema must match exactly."""
    for key in (
        '"refused"',
        '"overall_confidence"',
        '"findings"',
        '"supporting_evidence_ids"',
        '"assertability"',
        '"known_unknowns"',
    ):
        assert key in SYNTHESIS_PROMPT


def test_synthesis_and_question_prompts_are_distinct() -> None:
    assert SYNTHESIS_PROMPT != SYSTEM_PROMPT
