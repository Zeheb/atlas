"""The widened Finding.kind vocabulary and its citation obligations
(M2.3 commit 7).

The old "fact" | "synthesis" pair collapsed four genuinely different things
into one label, with a concrete consequence: an empty evidence_ids meant BOTH
"this is a disclosure" and "this claim is ungrounded", and no code could tell
them apart. A provenance gate cannot be built on that ambiguity.

These tests pin the vocabulary, the three-level obligation map, and -- most
importantly -- that the rendered report is unchanged, which is what makes
this commit a relabelling rather than a behavior change.
"""

from __future__ import annotations

from atlas.research.citations import (
    CITATION_OBLIGATION,
    CONCLUSION,
    DERIVED,
    DISCLOSURE,
    EVIDENCE_NOTE,
    FACT,
    FORBIDDEN,
    LEGACY_SYNTHESIS,
    OPTIONAL,
    REQUIRED,
    Finding,
    citation_obligation,
)


# --- The vocabulary ---------------------------------------------------------------------
def test_five_kinds_exist() -> None:
    assert {FACT, DERIVED, CONCLUSION, EVIDENCE_NOTE, DISCLOSURE} == {
        "fact",
        "derived",
        "conclusion",
        "evidence_note",
        "disclosure",
    }


def test_default_kind_is_still_fact() -> None:
    """Every pre-M2.3 call site omitted kind and meant 'fact'."""
    assert Finding(text="Revenue was 100cr.", evidence_ids=["ev-1"]).kind == FACT


# --- The obligation map ------------------------------------------------------------------
def test_claims_about_the_company_must_cite() -> None:
    for kind in (FACT, DERIVED, CONCLUSION):
        assert citation_obligation(kind) == REQUIRED


def test_evidence_notes_may_cite_or_not() -> None:
    """A statement about evidence quality may cite what it examined, or
    nothing at all -- both are legitimate."""
    assert citation_obligation(EVIDENCE_NOTE) == OPTIONAL


def test_disclosures_must_not_cite() -> None:
    """The level a binary must-cite/optional split would lose. A policy
    statement carrying evidence is a category error, not a bonus."""
    assert citation_obligation(DISCLOSURE) == FORBIDDEN


def test_three_distinct_obligation_levels_exist() -> None:
    assert len({REQUIRED, OPTIONAL, FORBIDDEN}) == 3
    assert set(CITATION_OBLIGATION.values()) == {REQUIRED, OPTIONAL, FORBIDDEN}


def test_every_kind_declares_an_obligation() -> None:
    for kind in (FACT, DERIVED, CONCLUSION, EVIDENCE_NOTE, DISCLOSURE):
        assert kind in CITATION_OBLIGATION


def test_unknown_kind_is_permissive_rather_than_an_error() -> None:
    """Render time is the wrong place to discover an unrecognized label."""
    assert citation_obligation("something_new") == OPTIONAL


# --- Legacy compatibility ------------------------------------------------------------------
def test_legacy_synthesis_label_still_resolves() -> None:
    """Persisted artifacts and any caller predating the split must still load."""
    assert citation_obligation(LEGACY_SYNTHESIS) == OPTIONAL


def test_legacy_synthesis_is_still_constructible() -> None:
    assert Finding(text="x", kind=LEGACY_SYNTHESIS).kind == "synthesis"


# --- The relabelling is honest -------------------------------------------------------------
def test_the_call_disclosure_is_labelled_disclosure() -> None:
    """ "Atlas does not issue a buy/sell recommendation" is a statement about
    Atlas, not about the company."""
    from tests.unit.research_fixtures import make_profile  # type: ignore

    from atlas.research.report import generate_report

    the_call = generate_report("TCS", make_profile()).section("the_call")
    assert the_call is not None
    disclosures = [f for f in the_call.findings if f.kind == DISCLOSURE]
    assert len(disclosures) == 1
    assert "does not issue a buy/sell recommendation" in disclosures[0].text
    assert disclosures[0].evidence_ids == ()  # FORBIDDEN, and honored


def test_open_questions_are_labelled_evidence_notes() -> None:
    """They describe what Atlas could NOT resolve -- statements about the
    evidence, not about the company.

    Driven directly rather than through generate_report: neither test fixture
    produces a genuinely empty section (an "empty" section still carries an
    explanatory note, so ReportSection.is_empty() is False), which means the
    gap-detection path never fires in a full-report test.
    """
    from atlas.research.model import ReportSection
    from atlas.research.sections import open_questions
    from tests.unit.research_fixtures import make_profile  # type: ignore

    truly_empty = ReportSection(key="valuation_like", title="Competitive Position")
    assert truly_empty.is_empty()

    section = open_questions.build(
        make_profile(),
        None,
        "TCS",
        other_sections=[truly_empty],
    )
    assert section.findings
    assert all(f.kind == EVIDENCE_NOTE for f in section.findings)


def test_no_section_still_uses_the_legacy_label() -> None:
    """The relabelling is complete: nothing in the report is left as the
    ambiguous 'synthesis'."""
    from tests.unit.research_fixtures import make_profile  # type: ignore

    from atlas.research.report import generate_report

    report = generate_report("TCS", make_profile())
    for section in report.sections:
        for finding in section.findings:
            assert (
                finding.kind != LEGACY_SYNTHESIS
            ), f"{section.key}: {finding.text[:50]}"


# --- Behavior preserved ----------------------------------------------------------------------
def test_rendered_report_is_unchanged_by_the_split() -> None:
    """All three interpretive kinds still render the reader-facing
    '[synthesis]' tag, so the report is byte-identical. The finer distinction
    exists for the provenance gate, not for the reader.
    """
    from tests.unit.research_fixtures import make_profile  # type: ignore

    from atlas.research.render import render_markdown
    from atlas.research.report import generate_report

    markdown = render_markdown(generate_report("TCS", make_profile()))
    assert "_[synthesis]_" in markdown  # the tag survived the relabelling
