"""The pinning footer (#44): one line naming the build behind an answer.

Two things have to hold at once. A pinned answer must say which build
produced it, in a form someone can paste back into `atlas fingerprint`. And
an answer that predates pinning must render byte-identically to how it
always did -- a footer that degrades to "Atlas None · 0 assertions" would
assert something false about provenance on every stored thesis in the
repository.

Segments are omitted rather than zeroed for the same reason: "0 assertions"
claims the answer consulted none, when the truth is that this build does not
yet record which rows retrieval read.
"""

from __future__ import annotations

from atlas.citation import pinning_footer
from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    Finding,
    Question,
    ReasoningResult,
    SubjectRef,
)
from atlas.reasoning.render import format_answer, to_answer

_SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")


def _result(**overrides: object) -> ReasoningResult:
    claim = Claim(
        subject_ref=_SUBJECT,
        statement="Revenue grew.",
        assertability="fact",
        confidence="high",
        evidence=(EvidenceReference(evidence_id="ev-1"),),
    )
    kwargs: dict[str, object] = {
        "question": Question(raw_text="Did revenue grow?", subject_ref=_SUBJECT),
        "findings": (
            Finding(
                statement="Revenue grew.",
                assertability="fact",
                confidence="high",
                supporting_claims=(claim,),
            ),
        ),
        "overall_confidence": "high",
        "citations": frozenset({"ev-1"}),
    }
    kwargs.update(overrides)
    return ReasoningResult(**kwargs)  # type: ignore[arg-type]


# --- the footer itself -------------------------------------------------------


def test_an_unpinned_result_has_no_footer() -> None:
    assert pinning_footer(_result()) == ""


def test_the_footer_names_the_build() -> None:
    footer = pinning_footer(_result(fingerprint="3f9a1c"))

    assert footer == "Atlas 3f9a1c"


def test_the_footer_counts_documents_and_assertions() -> None:
    footer = pinning_footer(
        _result(
            fingerprint="3f9a1c",
            consulted_assertion_ids=tuple(f"a{i}" for i in range(47)),
            consulted_evidence_ids=tuple(f"ev-{i}" for i in range(12)),
            profile_built_at="2026-07-14T10:00:00+00:00",
        )
    )

    assert (
        footer
        == "Atlas 3f9a1c · 47 assertions · 12 documents · profile built 2026-07-14"
    )


def test_empty_segments_are_omitted_not_zeroed() -> None:
    """ "0 assertions" would claim the answer consulted none. It did not."""
    footer = pinning_footer(
        _result(fingerprint="3f9a1c", consulted_evidence_ids=("ev-1", "ev-2"))
    )

    assert footer == "Atlas 3f9a1c · 2 documents"
    assert "assertions" not in footer
    assert "profile built" not in footer


def test_the_built_at_segment_is_a_date_not_a_timestamp() -> None:
    footer = pinning_footer(
        _result(fingerprint="3f9a1c", profile_built_at="2026-07-14T10:00:00+00:00")
    )

    assert footer == "Atlas 3f9a1c · profile built 2026-07-14"


# --- the answer surface ------------------------------------------------------


def test_the_answer_carries_the_footer() -> None:
    answer = to_answer(_result(fingerprint="3f9a1c", consulted_evidence_ids=("ev-1",)))

    assert answer.pinning_footer == "Atlas 3f9a1c · 1 documents"


def test_a_rendered_answer_ends_with_the_footer() -> None:
    text = format_answer(
        to_answer(_result(fingerprint="3f9a1c", consulted_evidence_ids=("ev-1",)))
    )

    assert text.endswith("Atlas 3f9a1c · 1 documents")


def test_a_rendered_refusal_carries_the_footer_too() -> None:
    refusal = _result(
        findings=(),
        citations=frozenset(),
        refused=True,
        refusal_reason="out of scope",
        fingerprint="3f9a1c",
        consulted_evidence_ids=("ev-1",),
    )

    text = format_answer(to_answer(refusal))

    assert "Atlas cannot answer this question." in text
    assert text.endswith("Atlas 3f9a1c · 1 documents")


def test_an_unpinned_answer_renders_exactly_as_before() -> None:
    """Every pre-M6 renderer expectation in this repository depends on this."""
    text = format_answer(to_answer(_result()))

    assert text == (
        "[FACT] Revenue grew. (confidence: high) [ev-1]\n"
        "\n"
        "Overall confidence: high\n"
        "\n"
        "Sources:\n"
        "  - ev-1"
    )


def test_an_unpinned_refusal_renders_exactly_as_before() -> None:
    refusal = _result(
        findings=(),
        citations=frozenset(),
        refused=True,
        refusal_reason="out of scope",
    )

    text = format_answer(to_answer(refusal))

    assert text == ("Atlas cannot answer this question.\nReason: out of scope")
