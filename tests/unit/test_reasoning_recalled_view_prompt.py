"""The recalled-view prompt block (M2.4 commit 5).

The load-bearing test is byte-identity: build_user_prompt's output for a
context with thesis=None must be EXACTLY what it was before this milestone.
A prompt that every atlas ask call renders is the highest-blast-radius
surface in the reasoning package; this is asserted, not assumed.
"""

from __future__ import annotations

from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    GroundingContext,
    Question,
    RecalledClaim,
    RecalledView,
    SubjectRef,
)
from atlas.reasoning.prompt import build_user_prompt

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")


def _claim(
    statement: str = "Margins ~24%.", eid: str = "ev-1", excerpt: str | None = None
) -> Claim:
    return Claim(
        subject_ref=SUBJECT,
        statement=statement,
        assertability="fact",
        confidence="high",
        evidence=[EvidenceReference(evidence_id=eid, excerpt=excerpt)],
    )


def _context(*claims: Claim, thesis: RecalledView | None = None) -> GroundingContext:
    used = claims or (_claim(),)
    return GroundingContext(
        subject_ref=SUBJECT,
        claims=list(used),
        evidence_index=frozenset(e for c in used for e in c.evidence_ids),
        thesis=thesis,
    )


def _question(text: str = "How have margins been?") -> Question:
    return Question(raw_text=text, subject_ref=SUBJECT)


def _view(view_id: str = "view-1") -> RecalledView:
    return RecalledView(
        view_id=view_id,
        question="Should I invest in TCS?",
        claims=(
            RecalledClaim(
                statement="Margins were improving.",
                evidence_ids=frozenset({"ev-OLD"}),
                confidence="medium",
            ),
        ),
        as_of="2026-01-01T00:00:00+00:00",
    )


# --- THE load-bearing test: byte-identity when absent --------------------------------
def test_prompt_is_byte_identical_to_pre_m24_when_thesis_is_none() -> None:
    """Captured expected output IS the pre-M2.4 build_user_prompt behavior --
    the exact string that function produced before this commit existed."""
    context = _context(_claim("Margins ~24%.", "ev-1"))
    expected = (
        "COMPANY: Tata Consultancy Services (TCS)\n"
        "\n"
        "EVIDENCE (you may cite ONLY these evidence ids):\n"
        "- [ev-1] Margins ~24%.\n"
        "\n"
        "VALID EVIDENCE IDS: ev-1\n"
        "\n"
        "QUESTION: How have margins been?"
    )
    assert build_user_prompt(_question(), context) == expected


def test_prompt_with_excerpt_is_byte_identical_when_thesis_is_none() -> None:
    context = _context(_claim("Margins ~24%.", "ev-1", excerpt="Margin was 24.2%."))
    rendered = build_user_prompt(_question(), context)
    assert 'source text: "Margin was 24.2%."' in rendered
    assert "RECALLED VIEW" not in rendered


def test_no_recalled_view_block_when_thesis_absent() -> None:
    rendered = build_user_prompt(_question(), _context())
    assert "RECALLED VIEW" not in rendered


# --- The block, when present ------------------------------------------------------------
def test_recalled_view_block_appears_when_thesis_present() -> None:
    rendered = build_user_prompt(_question(), _context(thesis=_view()))
    assert "RECALLED VIEW" in rendered
    assert "Margins were improving." in rendered


def test_recalled_view_shows_its_own_question() -> None:
    rendered = build_user_prompt(_question(), _context(thesis=_view()))
    assert "Should I invest in TCS?" in rendered


def test_recalled_view_shows_as_of() -> None:
    rendered = build_user_prompt(_question(), _context(thesis=_view()))
    assert "2026-01-01T00:00:00+00:00" in rendered


def test_recalled_view_shows_confidence() -> None:
    rendered = build_user_prompt(_question(), _context(thesis=_view()))
    assert "confidence was medium" in rendered


def test_recalled_view_evidence_labelled_not_citable() -> None:
    """The reference-only guarantee, visible in the actual prompt text."""
    rendered = build_user_prompt(_question(), _context(thesis=_view()))
    assert "ev-OLD" in rendered
    assert "NOT citable now" in rendered


def test_recalled_view_evidence_not_in_valid_evidence_ids() -> None:
    """The closed world itself: ev-OLD must not appear in VALID EVIDENCE IDS
    just because it's mentioned in the recalled-view block."""
    rendered = build_user_prompt(_question(), _context(thesis=_view()))
    valid_line = next(
        l for l in rendered.splitlines() if l.startswith("VALID EVIDENCE IDS")
    )
    assert "ev-OLD" not in valid_line


def test_recalled_view_with_no_evidence_says_so() -> None:
    view = RecalledView(
        view_id="v",
        question="q",
        claims=(
            RecalledClaim(statement="x", evidence_ids=frozenset(), confidence="low"),
        ),
        as_of="2026-01-01T00:00:00+00:00",
    )
    rendered = build_user_prompt(_question(), _context(thesis=view))
    assert "no evidence recorded" in rendered


def test_recalled_view_block_comes_before_valid_evidence_ids() -> None:
    """Placement matters: the model should see the recalled view before the
    final closed-world declaration, not interleaved with current evidence."""
    rendered = build_user_prompt(_question(), _context(thesis=_view()))
    assert rendered.index("RECALLED VIEW") < rendered.index("VALID EVIDENCE IDS")


def test_recalled_view_has_no_output_instruction_yet() -> None:
    """Deliberately no ask-the-model-to-flag-contradiction instruction in
    this commit -- there is no schema field yet to receive the answer. That
    arrives in the next commit as one coherent unit with the schema."""
    rendered = build_user_prompt(_question(), _context(thesis=_view()))
    assert "contradict" not in rendered.lower()
