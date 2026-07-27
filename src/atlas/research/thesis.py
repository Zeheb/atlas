"""Thesis synthesis (M2.3 commit 4, ADR-0008 as revised).

Turns a completed ``InvestigationRun`` into an argued view. This is the last
step of the research pipeline and the one that actually concludes:

    ResearchPlanner  -> WHAT to investigate          (planner.py)
    RetrievalPlanner -> HOW to retrieve each one     (reasoning/planner.py)
    investigate.py   -> executes them                (grounded findings)
    THIS MODULE      -> forms a view from the results

Synthesis is a reasoning pass, not a new engine
-----------------------------------------------
``synthesize()`` builds a ``GroundingContext`` whose claims are the run's own
already-grounded findings, then hands it to ``ask()`` with the synthesis
prompt pair. Every grounding guarantee therefore applies unchanged and
unduplicated:

  * G10 -- a cited id outside the run's evidence is DROPPED by ``ask()``
    before a Thesis can be constructed. The closed world is inherited, not
    re-implemented here.
  * G3/G4 -- an ungrounded judgment cannot survive.
  * G8 -- if nothing grounded survives, the result is a refusal, and a
    refusal is not a thesis (invariant 1).

A pre-implementation review found that an earlier design proposed its own
closed-world citation gate; ``ask()`` already had one, correct and tested
since M0. Building a second would have duplicated the most safety-critical
path in the codebase. What remains genuinely new is the COMPLETENESS
guarantee (commit 5): that nothing the run investigated was silently dropped
from the thesis.

What this module deliberately does not do
-----------------------------------------
**No contradiction semantics.** ``Disposition`` records whether a finding was
incorporated or judged not material -- never whether two findings disagree.
Cross-investigation contradiction is a different capability from C7's
``contradicts_thesis`` (which models conflict against a previously STORED
thesis, via the deferred C6 slot), and implementing either requires extending
the shared reasoning prompt and parser -- a reasoning-layer change affecting
every ``atlas ask`` call, not a synthesis-layer one. Deferred to M2.4, which
inherits a clean extension point: ``Disposition`` gains states and ``Thesis``
gains a relation record, neither retrofitted.

**No rating.** ``Thesis`` has no stance, target price, or position size, and
the synthesis prompt forbids issuing one. Atlas's own report already tells
readers it is "an evidence briefing, not a rating"; the type makes that
structurally true rather than merely stated.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from atlas.reasoning.ask import ask
from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    GroundingContext,
    Question,
    ReasoningResult,
    RecalledClaim,
    RecalledView,
    SubjectRef,
)
from atlas.reasoning.llm import LLMClient
from atlas.reasoning.prompt import SYNTHESIS_PROMPT, build_synthesis_prompt
from atlas.research.investigate import InvestigationResult, InvestigationRun

SYNTHESIZER_VERSION = "reasoning-synthesis-1"


class SynthesisError(RuntimeError):
    """No thesis could honestly be produced from this run."""


# Whether a resolved investigation made it into the view, or was considered
# and set aside. Deliberately TWO states: a third ("contradicting") would be a
# semantic claim about the relationship between investigations, which M2.3
# does not detect and therefore must not assert. See the module docstring.
Materiality = Literal["incorporated", "not_material"]

_VALID_MATERIALITY: frozenset[str] = frozenset({"incorporated", "not_material"})


@dataclass(frozen=True)
class Disposition:
    """What became of one resolved investigation.

    The no-silent-omission ledger's unit. Every investigation the run
    RESOLVED gets exactly one of these; unresolved investigations are carried
    on ``Thesis.unresolved_dimensions`` instead, derived from the run rather
    than restated here (one source of truth per fact).
    """

    dimension: str
    materiality: Materiality
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.materiality not in _VALID_MATERIALITY:
            raise ValueError(
                f"Disposition.materiality {self.materiality!r} is not a valid Materiality"
            )
        if self.materiality == "not_material" and not self.rationale.strip():
            raise ValueError(
                "A 'not_material' Disposition must say why it was set aside "
                f"(dimension {self.dimension!r}) -- silently dropping a finding is "
                "exactly what the completeness guarantee exists to prevent"
            )


@dataclass(frozen=True)
class Thesis:
    """An argued view over one InvestigationRun.

    ``result`` is COMPOSED, not copied: the statements, per-finding
    confidence, citations, overall confidence and known-unknowns all live on
    the ``ReasoningResult`` and are read through it. Restating any of them as
    Thesis fields would create a second source of truth that could drift from
    the first (ADR-0009).
    """

    question: str
    subjects: tuple[str, ...]
    run_fingerprint: str
    view_id: str
    as_of: str
    result: ReasoningResult
    dispositions: tuple[Disposition, ...] = ()
    unresolved_dimensions: tuple[str, ...] = ()
    synthesizer_version: str = SYNTHESIZER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "subjects", tuple(self.subjects))
        object.__setattr__(self, "dispositions", tuple(self.dispositions))
        object.__setattr__(
            self, "unresolved_dimensions", tuple(self.unresolved_dimensions)
        )

        if not self.question.strip():
            raise ValueError("Thesis.question must be non-empty")
        if not self.subjects:
            raise ValueError("Thesis.subjects must name at least one subject")
        if not self.view_id.strip():
            raise ValueError("Thesis.view_id must be non-empty")
        if not self.as_of.strip():
            raise ValueError("Thesis.as_of must be non-empty")
        # Invariant 1: a refusal is not a thesis. ask() refuses when nothing
        # grounded survives, and that outcome must not be dressed up as a view.
        if self.result.refused:
            raise ValueError(
                "Thesis cannot be built from a refused ReasoningResult -- "
                f"reason: {self.result.refusal_reason!r}"
            )
        if not self.result.findings:
            raise ValueError("Thesis.result must carry at least one finding")

        seen: set[str] = set()
        for d in self.dispositions:
            if d.dimension in seen:
                raise ValueError(f"Thesis has a duplicate disposition: {d.dimension!r}")
            seen.add(d.dimension)

        overlap = seen & set(self.unresolved_dimensions)
        if overlap:
            raise ValueError(
                f"Dimensions cannot be both disposed and unresolved: {sorted(overlap)}"
            )

    @property
    def citations(self) -> frozenset[str]:
        """Every evidence id this thesis rests on -- read from the result."""
        return self.result.citations

    @property
    def incorporated_dimensions(self) -> tuple[str, ...]:
        return tuple(
            d.dimension for d in self.dispositions if d.materiality == "incorporated"
        )

    @property
    def set_aside_dimensions(self) -> tuple[str, ...]:
        return tuple(
            d.dimension for d in self.dispositions if d.materiality == "not_material"
        )

    def to_view(self) -> RecalledView:
        """Project this Thesis down to the C6 contract type (M2.4).

        The projection direction matters: research.Thesis carries dimensions,
        dispositions and run fingerprints, which are Research vocabulary that
        must not appear on a type consumed identically by Conversation,
        Research and Attention (ADR-0009). RecalledView keeps only what a
        later reasoning pass needs to check new evidence against -- the
        statements, their evidence, and their confidence.

        One RecalledClaim per C7 finding, using the SAME evidence_ids/
        confidence already computed and gate-checked -- never recomputed,
        since recomputing invites the two copies to drift.
        """
        return RecalledView(
            view_id=self.view_id,
            question=self.question,
            claims=tuple(
                RecalledClaim(
                    statement=f.statement,
                    evidence_ids=f.evidence_ids,
                    confidence=f.confidence,
                )
                for f in self.result.findings
            ),
            as_of=self.as_of,
            origin="atlas",
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready snapshot. ``result`` is projected field-by-field rather
        than via ``dataclasses.asdict`` because ReasoningResult holds a
        frozenset (``citations``) and nested Claims, neither JSON-native.

        Per-finding keys are a deliberate SUBSET of ``memory.py``'s
        persistence shape, not an independent list: this is a user-facing
        export (``atlas thesis --out``), while the store additionally keeps
        ``salience_rank`` to reconstruct claim ordering on load, which has no
        reader here. ``contradicts_thesis``/``counter_case`` (M2.4.1) are
        included in both, though -- a contradiction the model flagged is
        exactly the kind of fact this export exists to report, and omitting
        it here while the store kept it was a bug (M2.4.1), not a scope
        difference.
        """
        return {
            "question": self.question,
            "subjects": list(self.subjects),
            "run_fingerprint": self.run_fingerprint,
            "view_id": self.view_id,
            "as_of": self.as_of,
            "synthesizer_version": self.synthesizer_version,
            "overall_confidence": self.result.overall_confidence,
            "citations": sorted(self.result.citations),
            "findings": [
                {
                    "statement": f.statement,
                    "assertability": f.assertability,
                    "confidence": f.confidence,
                    "evidence_ids": sorted(f.evidence_ids),
                    "known_unknowns": list(f.known_unknowns),
                    "contradicts_thesis": f.contradicts_thesis,
                    "counter_case": f.counter_case,
                }
                for f in self.result.findings
            ],
            "dispositions": [
                {
                    "dimension": d.dimension,
                    "materiality": d.materiality,
                    "rationale": d.rationale,
                }
                for d in self.dispositions
            ],
            "unresolved_dimensions": list(self.unresolved_dimensions),
        }


@dataclass(frozen=True)
class GateViolation:
    """One reason a thesis may not be shown."""

    kind: str
    detail: str


@dataclass(frozen=True)
class GateResult:
    """The completeness gate's verdict. ``passed`` is the only thing a caller
    should branch on; ``violations`` says why for a human.
    """

    violations: tuple[GateViolation, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.violations


def check_completeness(thesis: Thesis, run: InvestigationRun) -> GateResult:
    """The one guarantee M2.3 adds that it did not inherit: **no silent
    omission**.

    The deterministic report earns its trust by running the same fixed section
    list for every company, so a reader always sees the full extent of what
    Atlas checked (``report.py``). A thesis is variable by nature -- it argues
    a view -- so it needs the equivalent property enforced rather than
    structural: every investigation the run performed must be *accounted for*.

    Concretely, each resolved investigation carries exactly one Disposition
    (incorporated, or set aside with a stated reason), and each unresolved one
    is carried on ``unresolved_dimensions``. A synthesis that quietly drops an
    inconvenient finding fails here. That is the difference between a thesis
    that is technically well-cited and one that is honest.

    Closed-world is re-asserted (not re-implemented): ``ask()`` already
    guarantees it, and this check exists so a future synthesizer that bypassed
    ``ask()`` could not silently lose the guarantee. It should never fire in
    normal operation -- if it does, the pipeline changed underneath.

    Pure: no I/O, no LLM. Needs the run because the thesis alone cannot know
    what was investigated -- which is precisely why this is a separate
    function rather than a ``__post_init__`` check.
    """
    violations: list[GateViolation] = []

    disposed = {d.dimension for d in thesis.dispositions}
    unresolved_declared = set(thesis.unresolved_dimensions)

    resolved_actual = {r.dimension for r in run.results if r.resolved}
    unresolved_actual = {r.dimension for r in run.results if not r.resolved}

    for dimension in sorted(resolved_actual - disposed):
        violations.append(
            GateViolation(
                kind="undisposed_finding",
                detail=(
                    f"{dimension!r} produced a grounded finding but the thesis neither "
                    "incorporated it nor recorded why it was set aside"
                ),
            )
        )

    for dimension in sorted(disposed - resolved_actual):
        violations.append(
            GateViolation(
                kind="phantom_disposition",
                detail=(
                    f"{dimension!r} has a disposition but no resolved investigation in "
                    "this run produced it"
                ),
            )
        )

    for dimension in sorted(unresolved_actual - unresolved_declared):
        violations.append(
            GateViolation(
                kind="dropped_unresolved",
                detail=(
                    f"{dimension!r} could not be resolved, and the thesis does not say so -- "
                    "an unanswered question presented as no question at all"
                ),
            )
        )

    for dimension in sorted(unresolved_declared - unresolved_actual):
        violations.append(
            GateViolation(
                kind="phantom_unresolved",
                detail=f"{dimension!r} is declared unresolved but the run resolved it",
            )
        )

    # Should be unreachable while synthesis goes through ask(); see docstring.
    run_evidence = frozenset(
        eid
        for r in run.results
        if r.finding is not None
        for eid in r.finding.evidence_ids
    )
    outside = thesis.citations - run_evidence
    if outside:
        violations.append(
            GateViolation(
                kind="citation_outside_run",
                detail=(
                    f"thesis cites evidence the run never retrieved: {sorted(outside)} -- "
                    "the closed world was bypassed"
                ),
            )
        )

    return GateResult(violations=tuple(violations))


def run_fingerprint(run: InvestigationRun) -> str:
    """Identify which run a thesis was synthesized from.

    sha256 over the run's (dimension, sorted evidence ids) pairs -- the same
    fingerprint pattern ``eval/report.py``'s ``build_coverage_snapshot`` uses.
    Evidence is included, not just dimensions, so re-running the same plan
    against a grown corpus produces a different fingerprint: a thesis and the
    evidence behind it are pinned together.
    """
    parts: list[str] = []
    for r in sorted(run.results, key=lambda r: r.dimension):
        ids = ",".join(sorted(r.finding.evidence_ids)) if r.finding is not None else ""
        parts.append(f"{r.dimension}:{ids}")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def compute_view_id(run_fingerprint_: str, question: str) -> str:
    """A Thesis's identity for recall (M2.4): deterministic, not a uuid.

    Re-running the same plan against unchanged evidence yields the same
    view_id -- idempotent, matching every other identity scheme in this
    codebase (SearchPlan has none because it is never persisted; ResearchPlan/
    coverage fingerprints all hash their own inputs rather than mint a random
    id). Any change to the underlying evidence (run_fingerprint_ changes)
    produces a different id, which is what lets ThesisStore.list() show
    genuinely distinct views rather than silently overwriting history.
    """
    return hashlib.sha256(f"{run_fingerprint_}:{question}".encode("utf-8")).hexdigest()


def _claim_for(result: InvestigationResult, subject_ref: SubjectRef) -> Claim | None:
    """One resolved investigation, expressed as a Claim for the synthesis
    context.

    Prefers the preserved C7 finding (M2.3 commit 3) because it carries real
    assertability and confidence, which the synthesis prompt renders and the
    synthesis rules depend on. Falls back to the flattened rendering view for
    a run produced before that field existed, where the only honest reading is
    "some claim, unknown certainty" -- hence ``confidence="medium"``, not an
    invented "high".
    """
    if result.finding is None:
        return None

    if result.semantic_findings:
        sf = result.semantic_findings[0]
        statement, assertability, confidence = (
            sf.statement,
            sf.assertability,
            sf.confidence,
        )
        evidence_ids = sorted(sf.evidence_ids)
    else:
        statement, assertability, confidence = result.finding.text, "judgment", "medium"
        evidence_ids = sorted(result.finding.evidence_ids)

    if not evidence_ids:
        return None
    return Claim(
        subject_ref=subject_ref,
        statement=statement,
        assertability=assertability,
        confidence=confidence,
        evidence=tuple(EvidenceReference(evidence_id=eid) for eid in evidence_ids),
    )


def build_synthesis_context(
    run: InvestigationRun, subject_ref: SubjectRef
) -> GroundingContext:
    """The closed world for synthesis: exactly what the run actually grounded.

    Nothing outside this context can be cited by the resulting thesis, because
    ``ask()`` drops any id absent from ``evidence_index``. That is the whole
    provenance mechanism -- assembling this context correctly IS the gate, and
    there is no second check to keep in sync with it.
    """
    claims = [
        c for c in (_claim_for(r, subject_ref) for r in run.results) if c is not None
    ]
    evidence_index = frozenset(eid for c in claims for eid in c.evidence_ids)
    return GroundingContext(
        subject_ref=subject_ref,
        claims=tuple(claims),
        evidence_index=evidence_index,
    )


def synthesize(run: InvestigationRun, client: LLMClient) -> Thesis:
    """Form a view from a completed run.

    Raises ``SynthesisError`` when no thesis can honestly be produced: an
    empty/unresolved run, or a synthesis the reasoning layer refused. Both are
    real outcomes, not degraded theses, and neither should be representable as
    a Thesis object.

    Dispositions default to "incorporated" for every resolved investigation.
    Judging one "not material" is a substantive editorial act that needs a
    reason; a synthesizer that cannot supply one has not judged it immaterial,
    it has merely not used it -- and the completeness gate (commit 5) is what
    surfaces that difference.
    """
    subject_id = run.plan.subjects[0]
    subject_ref = SubjectRef(subject_id=subject_id, display=subject_id)

    context = build_synthesis_context(run, subject_ref)
    if not context.claims:
        raise SynthesisError(
            "nothing to synthesize: no investigation in this run produced a "
            "grounded finding"
        )

    result = ask(
        Question(raw_text=run.plan.raw_question, subject_ref=subject_ref),
        context,
        client,
        system_prompt=SYNTHESIS_PROMPT,
        build_prompt=build_synthesis_prompt,
    )
    if result.refused:
        raise SynthesisError(f"synthesis refused: {result.refusal_reason}")

    resolved = [r for r in run.results if r.resolved]
    rf = run_fingerprint(run)
    return Thesis(
        question=run.plan.raw_question,
        subjects=run.plan.subjects,
        run_fingerprint=rf,
        view_id=compute_view_id(rf, run.plan.raw_question),
        as_of=datetime.now(timezone.utc).isoformat(),
        result=result,
        dispositions=tuple(
            Disposition(dimension=r.dimension, materiality="incorporated")
            for r in resolved
        ),
        unresolved_dimensions=tuple(r.dimension for r in run.results if not r.resolved),
    )
