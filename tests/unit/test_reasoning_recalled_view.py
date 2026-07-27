"""RecalledView / RecalledClaim (C6, M2.4 commit 1).

The load-bearing tests here are the ones proving the reserved slot survived
the retype intact: field name unchanged, default unchanged, and every
existing GroundingContext construction site (which never passed `thesis=`)
still constructs with no change at all.
"""

from __future__ import annotations

import dataclasses

import pytest

from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    GroundingContext,
    RecalledClaim,
    RecalledView,
    SubjectRef,
)

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _recalled_claim(
    statement: str = "Margins are durable.", eid: str = "ev-1"
) -> RecalledClaim:
    return RecalledClaim(
        statement=statement,
        evidence_ids=frozenset({eid}),
        confidence="medium",
    )


def _view(*claims: RecalledClaim, view_id: str = "view-1") -> RecalledView:
    return RecalledView(
        view_id=view_id,
        question="Should I invest in TCS?",
        claims=claims or (_recalled_claim(),),
        as_of="2026-07-22T00:00:00+00:00",
    )


# --- The reserved slot survives the retype ---------------------------------------
def test_grounding_context_still_defaults_thesis_to_none() -> None:
    """Every existing call site never passed thesis= -- the default must be
    unchanged, or every one of them silently changes behavior."""
    ctx = GroundingContext(subject_ref=SUBJECT, claims=(), evidence_index=frozenset())
    assert ctx.thesis is None


def test_field_name_is_still_thesis_not_recalled_view() -> None:
    """The blueprint reserved `thesis`; renaming it for cosmetic consistency
    would discard the seam's identity."""
    fields = {f.name for f in dataclasses.fields(GroundingContext)}
    assert "thesis" in fields
    assert "recalled_view" not in fields


def test_grounding_context_accepts_a_recalled_view() -> None:
    ctx = GroundingContext(
        subject_ref=SUBJECT,
        claims=(),
        evidence_index=frozenset(),
        thesis=_view(),
    )
    assert ctx.thesis is not None
    assert ctx.thesis.question == "Should I invest in TCS?"


def test_pre_m24_construction_is_completely_unaffected() -> None:
    """The exact call shape every existing GroundingContext construction site
    uses, unmodified."""
    claim = Claim(
        subject_ref=SUBJECT,
        statement="Revenue grew.",
        assertability="fact",
        confidence="high",
        evidence=[EvidenceReference(evidence_id="ev-1")],
    )
    ctx = GroundingContext(
        subject_ref=SUBJECT,
        claims=[claim],
        evidence_index=frozenset({"ev-1"}),
    )
    assert ctx.thesis is None
    assert ctx.claims == (claim,)


# --- RecalledClaim -----------------------------------------------------------------
def test_recalled_claim_requires_a_statement() -> None:
    with pytest.raises(ValueError, match="statement must be non-empty"):
        RecalledClaim(statement="  ", evidence_ids=frozenset(), confidence="high")


def test_recalled_claim_coerces_evidence_ids_to_frozenset() -> None:
    claim = RecalledClaim(
        statement="x", evidence_ids={"ev-1", "ev-2"}, confidence="high"
    )
    assert claim.evidence_ids == frozenset({"ev-1", "ev-2"})


def test_recalled_claim_permits_zero_evidence_ids() -> None:
    """Unlike Claim (G10: >=1 EvidenceReference required), a recalled claim
    may have none -- its evidence may have been withdrawn since it was formed,
    and it must still be representable."""
    RecalledClaim(
        statement="x", evidence_ids=frozenset(), confidence="low"
    )  # must not raise


def test_recalled_claim_has_no_period_value_unit_or_assertability() -> None:
    """Trimmed deliberately to what M2.4 uses -- see the module docstring's
    rejection of the speculative structured-fields draft."""
    fields = {f.name for f in dataclasses.fields(RecalledClaim)}
    assert fields == {"statement", "evidence_ids", "confidence"}


# --- RecalledView --------------------------------------------------------------------
def test_recalled_view_requires_at_least_one_claim() -> None:
    with pytest.raises(ValueError, match="claims must not be empty"):
        RecalledView(
            view_id="v",
            question="q",
            claims=(),
            as_of="2026-07-22T00:00:00+00:00",
        )


def test_recalled_view_requires_a_question() -> None:
    with pytest.raises(ValueError, match="question must be non-empty"):
        RecalledView(
            view_id="v",
            question="  ",
            claims=(_recalled_claim(),),
            as_of="2026-07-22T00:00:00+00:00",
        )


def test_recalled_view_requires_a_view_id() -> None:
    with pytest.raises(ValueError, match="view_id must be non-empty"):
        RecalledView(
            view_id="",
            question="q",
            claims=(_recalled_claim(),),
            as_of="2026-07-22T00:00:00+00:00",
        )


def test_recalled_view_requires_as_of() -> None:
    with pytest.raises(ValueError, match="as_of must be non-empty"):
        RecalledView(
            view_id="v",
            question="q",
            claims=(_recalled_claim(),),
            as_of="",
        )


def test_recalled_view_coerces_claims_to_tuple() -> None:
    view = RecalledView(
        view_id="v",
        question="q",
        claims=[_recalled_claim()],
        as_of="2026-07-22T00:00:00+00:00",
    )
    assert isinstance(view.claims, tuple)


def test_recalled_view_defaults_origin_to_atlas() -> None:
    assert _view().origin == "atlas"


def test_recalled_view_accepts_user_origin() -> None:
    view = RecalledView(
        view_id="v",
        question="q",
        claims=(_recalled_claim(),),
        as_of="2026-07-22T00:00:00+00:00",
        origin="user",
    )
    assert view.origin == "user"


def test_recalled_view_has_no_dimension_or_disposition_fields() -> None:
    """ADR-0009: C6 carries none of research.Thesis's Research-specific
    vocabulary (dimensions, dispositions, run fingerprints). No subject_ref
    either (M2.4.1): nothing read it -- the context it's shown in already
    carries one."""
    fields = {f.name for f in dataclasses.fields(RecalledView)}
    assert fields == {"view_id", "question", "claims", "as_of", "origin"}


# --- Frozen / hashable, matching every other contract type ---------------------------
def test_recalled_view_is_frozen() -> None:
    view = _view()
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.question = "different"  # type: ignore[misc]


def test_recalled_claim_is_frozen() -> None:
    claim = _recalled_claim()
    with pytest.raises(dataclasses.FrozenInstanceError):
        claim.statement = "different"  # type: ignore[misc]
