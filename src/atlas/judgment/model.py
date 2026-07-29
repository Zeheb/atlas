"""The ``Judgment`` model — a human conclusion, content-addressed.

What the id is a function of
----------------------------
``judgment_id`` hashes *what was concluded*: subject identity, statement,
rationale, supporting evidence, the fingerprint of the Atlas state the user
was looking at, and the judgment it supersedes. Two users typing the same
conclusion about the same subject against the same fingerprint are making
the same judgment, and get the same id.

``asserted_at`` is deliberately **not** hashed. It records when the
conclusion was entered, not what the conclusion is, and hashing it would
make every re-entry of an identical judgment a new row — which is exactly
the duplicate the append-only store exists to reject. This is the same
reasoning as ``hashing.EXCLUDED_FROM_HASH``, applied at the call site rather
than by adding a key to that shared list: no assertion payload carries an
``asserted_at``, and widening a frozen exclusion list to serve one new
caller would change what the rebuild comparison ignores.

``fingerprint`` *is* hashed. "I still believe this, now that the numbers
have changed" is a different historical fact from the original belief, and
collapsing the two would lose the more interesting one.

``subject`` contributes ``subject_id`` and ``subject_type`` only.
``display`` and ``aliases`` are presentation; a judgment does not change
because the company's display name was reformatted.

Why append-only, with ``supersedes``
------------------------------------
A judgment made against a fingerprint that is now stale is still true as
history: the user did believe that, on that evidence. Retracting it would
destroy the only record of it. So a revision is a *new* judgment pointing
back at the old one, and the chain is the audit trail.

``supersedes`` is validated here only for the one cycle a single object can
see — a judgment superseding itself. Longer cycles need the rest of the
chain in hand and are rejected by the store.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from atlas.assertions.hashing import canonical_for_hash
from atlas.reasoning.contracts import SubjectRef

#: Length of the hex id prefix retained, matching ``assertions.model``.
_ID_CHARS = 16


def judgment_id(
    *,
    subject_id: str,
    subject_type: str,
    statement: str,
    rationale: str,
    evidence_ids: tuple[str, ...],
    fingerprint: str,
    supersedes: str | None,
) -> str:
    """Return the content address for one judgment.

    *evidence_ids* must already be canonical — sorted and deduplicated.
    ``Judgment.__post_init__`` does that normalization, so callers going
    through :meth:`Judgment.create` get it for free; callers computing an id
    directly are responsible for matching, or the two disagree.
    """
    payload = {
        "subject_id": subject_id,
        "subject_type": subject_type,
        "statement": statement,
        "rationale": rationale,
        "evidence_ids": list(evidence_ids),
        "fingerprint": fingerprint,
        "supersedes": supersedes,
    }
    digest = hashlib.sha256(canonical_for_hash(payload).encode("utf-8"))
    return digest.hexdigest()[:_ID_CHARS]


def canonical_evidence_ids(
    evidence_ids: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Return *evidence_ids* sorted and deduplicated.

    The set of documents a conclusion rests on carries no order, so two
    orderings of the same set must not produce two ids. Deduplicated for the
    same reason: citing one document twice does not make it two supports.
    """
    return tuple(sorted(set(evidence_ids)))


@dataclass(frozen=True)
class Judgment:
    """One conclusion a human recorded, at a point in time."""

    judgment_id: str
    subject: SubjectRef
    statement: str
    rationale: str
    evidence_ids: tuple[str, ...]
    asserted_at: datetime
    fingerprint: str
    supersedes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_ids", canonical_evidence_ids(self.evidence_ids)
        )
        if not self.judgment_id:
            raise ValueError("Judgment.judgment_id must be non-empty")
        if not self.statement.strip():
            raise ValueError("Judgment.statement must be non-empty")
        if self.supersedes == self.judgment_id:
            raise ValueError(
                f"Judgment {self.judgment_id!r} supersedes itself; a revision "
                f"must point at a different judgment"
            )

    @classmethod
    def create(
        cls,
        *,
        subject: SubjectRef,
        statement: str,
        rationale: str,
        evidence_ids: tuple[str, ...] | list[str] = (),
        asserted_at: datetime,
        fingerprint: str,
        supersedes: str | None = None,
    ) -> Judgment:
        """Build a Judgment, deriving its id from its content.

        *asserted_at* is required rather than defaulted to ``now``: a caller
        that forgets to pass it should say so, and tests need to pin it.
        """
        canonical_ids = canonical_evidence_ids(evidence_ids)
        return cls(
            judgment_id=judgment_id(
                subject_id=subject.subject_id,
                subject_type=subject.subject_type,
                statement=statement,
                rationale=rationale,
                evidence_ids=canonical_ids,
                fingerprint=fingerprint,
                supersedes=supersedes,
            ),
            subject=subject,
            statement=statement,
            rationale=rationale,
            evidence_ids=canonical_ids,
            asserted_at=asserted_at,
            fingerprint=fingerprint,
            supersedes=supersedes,
        )
