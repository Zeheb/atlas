"""build_context(..., thesis=...) threading (M2.4 commit 5).

thesis is passed straight through to GroundingContext with no other effect --
it must never widen evidence_index, and omitting it must reproduce
M2.3-equivalent behavior exactly (checked against the pre-M2.4 call shape,
which every existing test in this file's siblings already exercises without
this parameter).
"""

from __future__ import annotations

from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.reasoning.context import build_context, build_context_with_diagnostics
from atlas.reasoning.contracts import RecalledClaim, RecalledView, SubjectRef

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")


def _profile() -> CompanyProfile:
    return CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(
            snapshots=[
                FinancialSnapshot(
                    period="2026-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={},
                    sources=["ev-1"],
                )
            ]
        ),
    )


def _view() -> RecalledView:
    return RecalledView(
        view_id="view-1",
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


# --- Omitted: reproduces pre-M2.4 behavior exactly -----------------------------------
def test_omitting_thesis_leaves_context_thesis_none() -> None:
    context = build_context(_profile(), SUBJECT)
    assert context.thesis is None


def test_omitting_thesis_via_diagnostics_leaves_context_thesis_none() -> None:
    result = build_context_with_diagnostics(_profile(), SUBJECT)
    assert result.context.thesis is None


# --- Supplied: threaded through, nothing else --------------------------------------
def test_thesis_is_threaded_into_the_context() -> None:
    context = build_context(_profile(), SUBJECT, thesis=_view())
    assert context.thesis is not None
    assert context.thesis.view_id == "view-1"


def test_thesis_is_threaded_through_diagnostics_too() -> None:
    result = build_context_with_diagnostics(_profile(), SUBJECT, thesis=_view())
    assert result.context.thesis is not None


def test_build_context_delegates_thesis_identically_to_diagnostics() -> None:
    """build_context is a thin delegate (M1.8) -- this parameter must not
    break that equivalence."""
    via_build_context = build_context(_profile(), SUBJECT, thesis=_view())
    via_diagnostics = build_context_with_diagnostics(
        _profile(), SUBJECT, thesis=_view()
    ).context
    assert via_build_context.thesis == via_diagnostics.thesis


# --- The one invariant that must never break -----------------------------------------
def test_thesis_never_widens_evidence_index() -> None:
    """The closed-world guarantee (ADR-0008/0009): a recalled view's evidence
    ids are reference only. ev-OLD must not become citable just because a
    view mentioning it was supplied."""
    context = build_context(_profile(), SUBJECT, thesis=_view())
    assert "ev-OLD" not in context.evidence_index


def test_thesis_does_not_change_which_claims_are_assembled() -> None:
    without = build_context(_profile(), SUBJECT)
    with_view = build_context(_profile(), SUBJECT, thesis=_view())
    assert without.claims == with_view.claims
    assert without.evidence_index == with_view.evidence_index
