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
from typing import Any, Literal

from atlas.reasoning.ask import ask
from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    GroundingContext,
    Question,
    ReasoningResult,
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
    result: ReasoningResult
    dispositions: tuple[Disposition, ...] = ()
    unresolved_dimensions: tuple[str, ...] = ()
    synthesizer_version: str = SYNTHESIZER_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "subjects", tuple(self.subjects))
        object.__setattr__(self, "dispositions", tuple(self.dispositions))
        object.__setattr__(self, "unresolved_dimensions", tuple(self.unresolved_dimensions))

        if not self.question.strip():
            raise ValueError("Thesis.question must be non-empty")
        if not self.subjects:
            raise ValueError("Thesis.subjects must name at least one subject")
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
        return tuple(d.dimension for d in self.dispositions if d.materiality == "incorporated")

    @property
    def set_aside_dimensions(self) -> tuple[str, ...]:
        return tuple(d.dimension for d in self.dispositions if d.materiality == "not_material")

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready snapshot. ``result`` is projected field-by-field rather
        than via ``dataclasses.asdict`` because ReasoningResult holds a
        frozenset (``citations``) and nested Claims, neither JSON-native.
        """
        return {
            "question": self.question,
            "subjects": list(self.subjects),
            "run_fingerprint": self.run_fingerprint,
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
        statement, assertability, confidence = sf.statement, sf.assertability, sf.confidence
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


def build_synthesis_context(run: InvestigationRun, subject_ref: SubjectRef) -> GroundingContext:
    """The closed world for synthesis: exactly what the run actually grounded.

    Nothing outside this context can be cited by the resulting thesis, because
    ``ask()`` drops any id absent from ``evidence_index``. That is the whole
    provenance mechanism -- assembling this context correctly IS the gate, and
    there is no second check to keep in sync with it.
    """
    claims = [c for c in (_claim_for(r, subject_ref) for r in run.results) if c is not None]
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
    return Thesis(
        question=run.plan.raw_question,
        subjects=run.plan.subjects,
        run_fingerprint=run_fingerprint(run),
        result=result,
        dispositions=tuple(
            Disposition(dimension=r.dimension, materiality="incorporated")
            for r in resolved
        ),
        unresolved_dimensions=tuple(r.dimension for r in run.results if not r.resolved),
    )
