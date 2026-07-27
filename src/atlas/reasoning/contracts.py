"""Internal contract types for the reasoning subsystem (blueprint §10).

These are the *stable interfaces* between subsystems. Implementation behind each
may change freely; these shapes may not, without a contract-version bump.
C10 ConversationState (M5) remains intentionally deferred (blueprint: "do not
optimize for future milestones beyond stable extension points").

CONTRACT VERSION 2 (M2.4): C6 ``RecalledView``/``RecalledClaim`` defined, and
``GroundingContext.thesis`` retyped from ``None`` to ``RecalledView | None``.
The field name is unchanged -- only the reserved slot's type widened. This is
the first contract-version bump since M0; every existing construction site
(reasoning, research, eval, tests) is source-compatible because the field
already defaulted to ``None``.

Every class carries its contract id (C1..C9). Invariants from §10 are enforced
in ``__post_init__`` and raise ``ValueError`` — the guarantees (§8.4) are thereby
type-level facts, not conventions:

  * G1/G10 (evidence-backed, no invented citations) -> ``Claim`` needs >=1
    ``EvidenceReference``; ``GroundingContext`` closed-world index; the
    grounding chain narrows at every hop (validated where the pieces meet).
  * G2 -> the ``Assertability`` marker on every stated proposition.
  * G3/G4 -> a judgment ``Finding`` must rest on >=1 supporting claim.
  * G8 -> a refused ``ReasoningResult`` carries a reason and no findings.
  * G9 -> ``Claim.resolution`` conservatism (the M3 extension seam; unused in M0).

All types are frozen; sequence fields are coerced to tuples / frozensets so the
objects are immutable and hashable-friendly while callers may pass plain lists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# --- Shared vocabularies (fixed once, referenced everywhere; §10.0) ----------
# ConfidenceLevel deliberately REUSES AnalysisFact.confidence's vocabulary — no
# float confidence anywhere (stability + reuse).
ConfidenceLevel = Literal["high", "medium", "low"]
Assertability = Literal["fact", "judgment"]
ResolutionStatus = Literal["pending", "delivered", "missed", "unresolved"]


def _tuple(value: Any) -> tuple[Any, ...]:
    """Coerce a caller-supplied sequence into an immutable tuple."""
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return tuple(value)


# --- C1 SubjectRef -----------------------------------------------------------
@dataclass(frozen=True)
class SubjectRef:
    """C1 — subject-general identity backbone.

    Only ``company`` subjects exist in V2.1, but the type is general so a future
    person/sector generalization does not break every other contract.
    """

    subject_id: str
    display: str
    subject_type: str = "company"
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "aliases", _tuple(self.aliases))
        if not self.subject_id:
            raise ValueError("SubjectRef.subject_id must be non-empty")


# --- C2 EvidenceReference ----------------------------------------------------
@dataclass(frozen=True)
class EvidenceReference:
    """C2 — the citation pointer; the atom of grounding.

    ``excerpt`` is OPTIONAL as of amendment M0-01: the persisted CompanyProfile
    carries fact-level evidence_ids but not fact-level excerpts, and raw-text
    retrieval is deferred to M1. Grounding integrity is enforced by the identity
    link (``evidence_id`` must resolve in the KnowledgeBase — checked at context
    assembly, where the KB is in scope), not by the excerpt. The excerpt becomes
    required again at M1 (drill-to-source).
    """

    evidence_id: str
    excerpt: str | None = None
    section: str | None = None
    char_offset: int | None = None
    display_name: str | None = None
    source_date: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("EvidenceReference.evidence_id must be non-empty")


# --- C3 Claim (subsumes Signal + Assertion) ----------------------------------
@dataclass(frozen=True)
class Resolution:
    """Sub-structure of C3 marking a promise/Assertion. M3 extension seam.

    Present ⇒ the owning Claim is a resolvable promise. Unused in M0, defined so
    the ``Claim.resolution`` field is a stable extension point for the ledger.
    G9: status is ``delivered``/``missed`` only on an unambiguous, evidence-
    backed match — enforced by the M3 resolver, not here.
    """

    status: ResolutionStatus = "pending"
    resolved_by: tuple[EvidenceReference, ...] = ()
    owner: str | None = None
    made_on: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolved_by", _tuple(self.resolved_by))
        if self.status in ("delivered", "missed") and not self.resolved_by:
            raise ValueError(
                "Resolution status 'delivered'/'missed' requires resolved_by "
                "evidence (G9: no unbacked promise resolution)"
            )


@dataclass(frozen=True)
class Claim:
    """C3 — one grounded proposition Atlas takes to be true about a Subject.

    Always carries >=1 EvidenceReference (G10). A populated ``resolution`` marks
    it as a promise (Assertion); absent ⇒ a plain observation (Signal).
    """

    subject_ref: SubjectRef
    statement: str
    assertability: Assertability
    confidence: ConfidenceLevel
    evidence: tuple[EvidenceReference, ...]
    period: str | None = None
    value: str | int | float | None = None
    unit: str | None = None
    resolution: Resolution | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", _tuple(self.evidence))
        if not self.statement:
            raise ValueError("Claim.statement must be non-empty")
        if len(self.evidence) < 1:
            raise ValueError(
                "Claim requires >=1 EvidenceReference (G10: no unbacked claim)"
            )

    @property
    def evidence_ids(self) -> frozenset[str]:
        return frozenset(ref.evidence_id for ref in self.evidence)


# --- C4 Question -------------------------------------------------------------
# M0 has no classifier (thin Meta); question_class is the transitional
# "unclassified" and the in/out-of-scope decision is made inside the single
# reasoning call. Full QC1..QC7 classification arrives with M4.
QUESTION_CLASS_UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class Question:
    """C4 — a user request resolved into something reasoning can plan over."""

    raw_text: str
    subject_ref: SubjectRef
    question_class: str = QUESTION_CLASS_UNCLASSIFIED
    thesis_ref: str | None = None
    time_frame: str | None = None
    conversation_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.raw_text.strip():
            raise ValueError("Question.raw_text must be non-empty")


# --- C5 GroundingContext (+ RetrievedEvidence) -------------------------------
@dataclass(frozen=True)
class RetrievedEvidence:
    """Element of C5 for raw-text retrieval (populated from M1; empty in M0)."""

    evidence_ref: EvidenceReference
    content_span: str
    relevance: ConfidenceLevel = "medium"


# --- C6 RecalledView (M2.4) ---------------------------------------------------
@dataclass(frozen=True)
class RecalledClaim:
    """One proposition of a RecalledView -- what Atlas (or a user) concluded at
    a past time, not what is true now.

    Deliberately NOT a ``Claim`` (C3): a Claim asserts something CURRENTLY true
    and requires >=1 EvidenceReference (G10), enforced in its own
    __post_init__. A recalled claim records a past conclusion and must survive
    its evidence being withdrawn or superseded -- it cannot satisfy G10 by
    construction, and it must not be placed in ``GroundingContext.claims``,
    where the model would read it as current evidence rather than as a prior
    judgment to check against.

    Trimmed to exactly what M2.4 consumes: the contradiction/support check is
    LLM-level and reads prose, so ``statement`` is sufficient. No ``period``/
    ``value``/``unit``/``assertability`` -- an earlier draft carried them
    speculatively to pre-empt a future contract change, which is the reasoning
    this design's own falsification pass rejects elsewhere. Add them in the
    milestone that actually needs claim-level comparison, mirroring Claim's
    shape at that point rather than guessing it now.
    """

    statement: str
    evidence_ids: frozenset[str]
    confidence: ConfidenceLevel

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ids", frozenset(self.evidence_ids))
        if not self.statement.strip():
            raise ValueError("RecalledClaim.statement must be non-empty")


@dataclass(frozen=True)
class RecalledView:
    """C6 -- what Atlas (or a user) recalls having concluded about a question,
    at a past time. Fulfils the ``GroundingContext.thesis`` seam reserved since
    M0.

    Named generally rather than after theses: the same shape holds an
    Atlas-synthesized thesis (``research.Thesis.to_view()``), a user-registered
    view, or a recalled prior answer -- ``origin`` records which. Consumed
    identically by Conversation, Research and Attention, so it carries none of
    ``research.Thesis``'s dimensions, dispositions or run fingerprints; those
    stay in ``research/thesis.py``, which projects INTO this type rather than
    this type absorbing them (the orthogonal-concerns rule this codebase
    applies elsewhere -- see ADR-0009).

    Reference only, never evidence: nothing in ``claims`` widens
    ``evidence_index`` (enforced at ``GroundingContext`` construction, not
    here -- a RecalledView has no evidence_index of its own to violate). A
    stale view can be shown to the model; it can never be cited.

    No ``subject_ref`` (removed in M2.4.1, before this contract version was
    ever published): the field this milestone shipped with had no reader.
    ``_render_recalled_view`` renders ``context.subject_ref`` instead
    (``prompt.py``); ``check_staleness`` takes ``repo_root`` explicitly
    (``staleness.py``). Carrying it would have been exactly the kind of dead
    structure on a live contract that ``RecalledClaim``'s own
    ``period``/``value``/``unit`` trim (above) was rejected for -- the trim
    just wasn't applied to the field the same review added.
    """

    view_id: str
    question: str
    claims: tuple[RecalledClaim, ...]
    as_of: str
    origin: Literal["atlas", "user"] = "atlas"

    def __post_init__(self) -> None:
        object.__setattr__(self, "claims", _tuple(self.claims))
        if not self.view_id.strip():
            raise ValueError("RecalledView.view_id must be non-empty")
        if not self.question.strip():
            raise ValueError("RecalledView.question must be non-empty")
        if not self.claims:
            raise ValueError("RecalledView.claims must not be empty")
        if not self.as_of.strip():
            raise ValueError("RecalledView.as_of must be non-empty")


@dataclass(frozen=True)
class GroundingContext:
    """C5 — the CLOSED WORLD a ReasoningResult may cite.

    ``evidence_index`` is the set of every citable evidence_id. Invariant: every
    evidence_id referenced by a contained Claim is in the index — the base of the
    grounding chain (index ⊇ result.citations ⊇ answer.citations). Nothing
    outside the index may be cited downstream (G1/G10).

    ``thesis`` (C6, M2.4) is a recalled view under examination, shown to the
    model for support/contradiction checking -- never added to
    ``evidence_index``. Field name preserved from the M0 reservation
    (``thesis: None = None  # C6, deferred to M2``); only the type widened.
    """

    subject_ref: SubjectRef
    claims: tuple[Claim, ...]
    evidence_index: frozenset[str]
    retrieved: tuple[RetrievedEvidence, ...] = ()
    thesis: RecalledView | None = None  # C6
    budget_note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "claims", _tuple(self.claims))
        object.__setattr__(self, "retrieved", _tuple(self.retrieved))
        object.__setattr__(self, "evidence_index", frozenset(self.evidence_index))
        referenced = {eid for c in self.claims for eid in c.evidence_ids}
        missing = referenced - self.evidence_index
        if missing:
            raise ValueError(
                f"GroundingContext.evidence_index missing ids cited by claims: "
                f"{sorted(missing)}"
            )


# --- C7 Finding --------------------------------------------------------------
@dataclass(frozen=True)
class Finding:
    """C7 — one reasoned conclusion; the unit of an answer.

    A judgment-grade finding must rest on >=1 supporting claim (G3/G4: no
    ungrounded judgment).
    """

    statement: str
    assertability: Assertability
    confidence: ConfidenceLevel
    supporting_claims: tuple[Claim, ...]
    salience_rank: int | None = None
    contradicts_thesis: bool = False
    counter_case: str | None = None
    known_unknowns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "supporting_claims", _tuple(self.supporting_claims))
        object.__setattr__(self, "known_unknowns", _tuple(self.known_unknowns))
        if not self.statement:
            raise ValueError("Finding.statement must be non-empty")
        if self.assertability == "judgment" and len(self.supporting_claims) < 1:
            raise ValueError("A judgment Finding requires >=1 supporting claim (G3/G4)")

    @property
    def evidence_ids(self) -> frozenset[str]:
        return frozenset(eid for c in self.supporting_claims for eid in c.evidence_ids)


# --- C8 ReasoningResult ------------------------------------------------------
@dataclass(frozen=True)
class ReasoningResult:
    """C8 — the language-independent reasoning output.

    Consumed identically by Conversation (-> Answer), Research, and Attention.
    ``citations`` must cover every evidence_id its findings rest on, and (checked
    where the context is in scope) be a subset of the GroundingContext index. A
    refused result carries a reason and no findings (G8).
    """

    question: Question
    findings: tuple[Finding, ...]
    overall_confidence: ConfidenceLevel
    citations: frozenset[str]
    refused: bool = False
    trace: tuple[str, ...] = ()
    known_unknowns: tuple[str, ...] = ()
    refusal_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", _tuple(self.findings))
        object.__setattr__(self, "trace", _tuple(self.trace))
        object.__setattr__(self, "known_unknowns", _tuple(self.known_unknowns))
        object.__setattr__(self, "citations", frozenset(self.citations))
        if self.refused:
            if self.findings:
                raise ValueError("A refused ReasoningResult must have no findings (G8)")
            if not self.refusal_reason:
                raise ValueError(
                    "A refused ReasoningResult must set refusal_reason (G8)"
                )
        finding_ids = {eid for f in self.findings for eid in f.evidence_ids}
        uncited = finding_ids - self.citations
        if uncited:
            raise ValueError(
                f"ReasoningResult.citations missing ids its findings rest on: "
                f"{sorted(uncited)} (G1)"
            )


# --- C9 Answer ---------------------------------------------------------------
@dataclass(frozen=True)
class Answer:
    """C9 — the presentational response (Conversation -> user).

    Prose plus citations, with fact/judgment made visible (G2). ``citations``
    must be a subset of the ReasoningResult's citations (G1, end to end). A
    refused answer carries a reason.
    """

    prose: str
    citations: tuple[EvidenceReference, ...]
    overall_confidence: ConfidenceLevel
    refused: bool = False
    fact_lines: tuple[str, ...] = ()
    judgment_lines: tuple[str, ...] = ()
    refusal_reason: str | None = None
    follow_up_suggestions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "citations", _tuple(self.citations))
        object.__setattr__(self, "fact_lines", _tuple(self.fact_lines))
        object.__setattr__(self, "judgment_lines", _tuple(self.judgment_lines))
        object.__setattr__(
            self, "follow_up_suggestions", _tuple(self.follow_up_suggestions)
        )
        if self.refused and not self.refusal_reason:
            raise ValueError("A refused Answer must set refusal_reason (G8)")
