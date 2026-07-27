"""Provenance models for evaluation cases (M1.8.5 / ADR-0005).

Every benchmark case that claims to test a retrieval scenario carries a
``CaseProvenance`` declaring HOW that claim was verified, and (for a positive
case) a ``RetrievalLabel`` naming what retrieval SHOULD find. Neither is
self-certifying — ``validation.py`` machine-checks both against the real
KnowledgeBase and the real retriever, so a scenario tag is only as good as
the evidence backing it, not merely asserted by whoever wrote the case.

Deliberately only two origins exist: ``corpus_derived`` (the case is built
from real evidence that genuinely supports it) and
``corpus_validated_negative`` (the case asserts an absence, and that absence
is machine-verified by actually running retrieval and finding nothing). There
is no third, unverified origin — a benchmark case that skips verification is
exactly what this module exists to prevent.

Frozen and self-validating, matching ``reasoning.plan``'s own discipline
(reproduced locally rather than imported, since this package has no
dependency on ``reasoning.plan`` beyond what it needs for validation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from atlas.acquisition.evidence import EvidenceKind

_VALID_EVIDENCE_KINDS = frozenset(k.value for k in EvidenceKind)
_VALID_ORIGINS = frozenset({"corpus_derived", "corpus_validated_negative"})


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return tuple(value)


@dataclass(frozen=True)
class CaseProvenance:
    """How a benchmark case's scenario/difficulty claim was verified.

    ``corpus_derived`` requires >=1 supporting evidence id (validated,
    kind-checked, in ``validation.py``) -- a positive claim with nothing
    backing it is not corpus-derived. ``corpus_validated_negative`` requires
    none (the whole point is that nothing relevant exists); its absence
    claim is checked by actually running retrieval, not by this dataclass.
    """

    origin: str
    supporting_evidence_ids: tuple[str, ...] = ()
    verification_method: str = ""
    verified_at: str = ""
    verified_by: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "supporting_evidence_ids", _tuple(self.supporting_evidence_ids)
        )
        if self.origin not in _VALID_ORIGINS:
            raise ValueError(
                f"CaseProvenance.origin {self.origin!r} must be one of {sorted(_VALID_ORIGINS)}"
            )
        if not self.verification_method.strip():
            raise ValueError("CaseProvenance.verification_method must be non-empty")
        if not self.verified_by.strip():
            raise ValueError("CaseProvenance.verified_by must be non-empty")
        if not self.verified_at.strip():
            raise ValueError("CaseProvenance.verified_at must be non-empty")
        if self.origin == "corpus_derived" and not self.supporting_evidence_ids:
            raise ValueError(
                "CaseProvenance(origin='corpus_derived') requires >=1 supporting_evidence_ids"
            )


@dataclass(frozen=True)
class RetrievalLabel:
    """Gold retrieval target for a case: which documents retrieval SHOULD
    (and must not) surface. Used by ``eval/retrieval_quality.py`` to compute
    precision@k/recall@k/MRR against ``RetrievalCaseMetrics.selected``.
    """

    relevant_evidence_ids: tuple[str, ...] = ()
    relevant_kinds: tuple[str, ...] = ()
    must_not_retrieve: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relevant_evidence_ids", _tuple(self.relevant_evidence_ids)
        )
        object.__setattr__(self, "relevant_kinds", _tuple(self.relevant_kinds))
        object.__setattr__(self, "must_not_retrieve", _tuple(self.must_not_retrieve))
        if not self.relevant_evidence_ids and not self.relevant_kinds:
            raise ValueError(
                "RetrievalLabel needs at least one of relevant_evidence_ids/relevant_kinds"
            )
        invalid_kinds = set(self.relevant_kinds) - _VALID_EVIDENCE_KINDS
        if invalid_kinds:
            raise ValueError(
                f"RetrievalLabel.relevant_kinds has invalid EvidenceKind values: {sorted(invalid_kinds)}"
            )
        overlap = set(self.relevant_evidence_ids) & set(self.must_not_retrieve)
        if overlap:
            raise ValueError(
                f"RetrievalLabel: id(s) cannot be both relevant and forbidden: {sorted(overlap)}"
            )
