"""CaseProvenance / RetrievalLabel invariants (M1.8.5 commit 1, ADR-0005).

Mirrors the discipline test_reasoning_plan.py applies to SearchPlan: every
invariant is pinned by a test.
"""
from __future__ import annotations

import pytest

from atlas.benchmark.provenance import CaseProvenance, RetrievalLabel


def _provenance(**overrides: object) -> CaseProvenance:
    defaults: dict[str, object] = dict(
        origin="corpus_derived", supporting_evidence_ids=("ev-1",),
        verification_method="inspected the annual report by hand",
        verified_at="2026-07-21", verified_by="zeheb",
    )
    defaults.update(overrides)
    return CaseProvenance(**defaults)  # type: ignore[arg-type]


# --- CaseProvenance.origin -------------------------------------------------------
def test_origin_must_be_a_valid_value() -> None:
    with pytest.raises(ValueError):
        _provenance(origin="synthetic_unverified")


@pytest.mark.parametrize("origin", ["corpus_derived", "corpus_validated_negative"])
def test_every_declared_origin_is_accepted(origin: str) -> None:
    kwargs: dict[str, object] = {"origin": origin}
    if origin == "corpus_validated_negative":
        kwargs["supporting_evidence_ids"] = ()  # negatives need none
    _provenance(**kwargs)  # must not raise


# --- corpus_derived requires evidence --------------------------------------------
def test_corpus_derived_requires_at_least_one_supporting_evidence_id() -> None:
    with pytest.raises(ValueError):
        _provenance(origin="corpus_derived", supporting_evidence_ids=())


def test_corpus_validated_negative_requires_no_evidence() -> None:
    _provenance(origin="corpus_validated_negative", supporting_evidence_ids=())  # must not raise


# --- required text fields ---------------------------------------------------------
def test_verification_method_must_be_non_empty() -> None:
    with pytest.raises(ValueError):
        _provenance(verification_method="")


def test_verification_method_whitespace_only_rejected() -> None:
    with pytest.raises(ValueError):
        _provenance(verification_method="   ")


def test_verified_by_must_be_non_empty() -> None:
    with pytest.raises(ValueError):
        _provenance(verified_by="")


def test_verified_at_must_be_non_empty() -> None:
    with pytest.raises(ValueError):
        _provenance(verified_at="")


# --- Immutability & tuple coercion ------------------------------------------------
def test_provenance_is_frozen() -> None:
    p = _provenance()
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        p.origin = "corpus_validated_negative"  # type: ignore[misc]


def test_supporting_evidence_ids_coerced_to_tuple_from_list() -> None:
    p = _provenance(supporting_evidence_ids=["ev-1", "ev-2"])
    assert p.supporting_evidence_ids == ("ev-1", "ev-2")
    assert isinstance(p.supporting_evidence_ids, tuple)


# --- RetrievalLabel ----------------------------------------------------------------
def test_label_requires_at_least_one_of_ids_or_kinds() -> None:
    with pytest.raises(ValueError):
        RetrievalLabel()


def test_label_accepts_ids_only() -> None:
    RetrievalLabel(relevant_evidence_ids=("ev-1",))  # must not raise


def test_label_accepts_kinds_only() -> None:
    RetrievalLabel(relevant_kinds=("annual_report",))  # must not raise


def test_label_rejects_invalid_evidence_kind() -> None:
    with pytest.raises(ValueError):
        RetrievalLabel(relevant_kinds=("not_a_real_kind",))


def test_label_rejects_overlap_between_relevant_and_forbidden() -> None:
    with pytest.raises(ValueError):
        RetrievalLabel(relevant_evidence_ids=("ev-1",), must_not_retrieve=("ev-1",))


def test_label_is_frozen() -> None:
    label = RetrievalLabel(relevant_evidence_ids=("ev-1",))
    with pytest.raises(Exception):
        label.relevant_evidence_ids = ()  # type: ignore[misc]


def test_label_tuple_coercion_from_list() -> None:
    label = RetrievalLabel(relevant_evidence_ids=["ev-1", "ev-2"])
    assert isinstance(label.relevant_evidence_ids, tuple)


def test_label_must_not_retrieve_alone_is_insufficient() -> None:
    # must_not_retrieve without any positive signal is not a retrieval label
    # (that's what CaseProvenance(origin="corpus_validated_negative") is for).
    with pytest.raises(ValueError):
        RetrievalLabel(must_not_retrieve=("ev-1",))
