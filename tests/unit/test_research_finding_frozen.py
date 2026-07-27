"""research.citations.Finding is frozen with tuple evidence_ids (M2.3 commit 6).

This was the last mutable dataclass in the research dependency chain, and the
mutability was load-bearing in a bad way: the_call.py builds derived findings
by passing another finding's evidence_ids straight through, which aliased one
list object across two Findings. Nothing mutated it, so nothing broke -- but
the safety was accidental, not structural.
"""

from __future__ import annotations

import dataclasses

import pytest

from atlas.research.citations import Finding


def test_finding_is_frozen() -> None:
    finding = Finding(text="Margins improved.", evidence_ids=["ev-1"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.text = "something else"  # type: ignore[misc]


def test_evidence_ids_is_a_tuple() -> None:
    assert Finding(text="x", evidence_ids=["ev-1", "ev-2"]).evidence_ids == (
        "ev-1",
        "ev-2",
    )


def test_a_list_is_still_accepted_and_coerced() -> None:
    """Every existing call site passes a list; none had to change."""
    assert isinstance(Finding(text="x", evidence_ids=["ev-1"]).evidence_ids, tuple)


def test_a_tuple_passes_through_unchanged() -> None:
    assert Finding(text="x", evidence_ids=("ev-1",)).evidence_ids == ("ev-1",)


def test_default_is_an_empty_tuple() -> None:
    assert Finding(text="x").evidence_ids == ()


def test_evidence_ids_cannot_be_mutated_after_construction() -> None:
    finding = Finding(text="x", evidence_ids=["ev-1"])
    with pytest.raises(AttributeError):
        finding.evidence_ids.append("ev-2")  # type: ignore[attr-defined]


def test_order_is_preserved() -> None:
    """The docstring promises it and the citation renderer depends on it."""
    assert Finding(text="x", evidence_ids=["ev-3", "ev-1", "ev-2"]).evidence_ids == (
        "ev-3",
        "ev-1",
        "ev-2",
    )


def test_sharing_evidence_ids_between_findings_is_now_structurally_safe() -> None:
    """the_call.py's pattern: a derived finding reuses the underlying
    finding's evidence ids. With a tuple, the two cannot diverge or corrupt
    each other."""
    source = Finding(text="Revenue grew.", evidence_ids=["ev-1", "ev-2"])
    derived = Finding(
        text=f"Most recent development: {source.text}",
        evidence_ids=source.evidence_ids,
        kind="synthesis",
    )

    assert derived.evidence_ids == source.evidence_ids
    with pytest.raises(AttributeError):
        derived.evidence_ids.append("ev-3")  # type: ignore[attr-defined]


def test_findings_are_hashable_now_that_they_are_frozen() -> None:
    a = Finding(text="x", evidence_ids=["ev-1"])
    b = Finding(text="x", evidence_ids=["ev-1"])
    assert len({a, b}) == 1  # value equality, deduplicable


def test_the_call_still_builds_derived_findings(tmp_path) -> None:
    """The real aliasing site, exercised end to end rather than in the
    abstract: the deterministic report must still assemble."""
    from atlas.research.report import generate_report
    from tests.unit.research_fixtures import make_profile  # type: ignore

    report = generate_report("TCS", make_profile())
    the_call = report.section("the_call")
    assert the_call is not None
    for finding in the_call.findings:
        assert isinstance(finding.evidence_ids, tuple)
