"""Evaluation cases derived from the V2.1 acceptance tests (§8.6).

Each §8.6 task is one declarative ``EvalCase``. Cases are data, loaded from
``data/acceptance_v2_1.json``, so the acceptance tests are executable rather
than prose. A case's ``requires`` lists the *milestone-availability* gates it
needs (``CAP_*`` below); a milestone that lacks one marks the case *pending*
instead of running it.

``requires`` is NOT the same axis as ``capabilities`` (M-E.3, below). The
former asks "does this build provide the feature?"; the latter asks "what must
the system be able to do to answer this question at all?" -- the
``AtlasCapability`` axis from the Atlas Evaluation Matrix §6 / ADR-0011. The
two are kept deliberately distinct; a case can carry both.

M1.8.5 (ADR-0005) adds four OPTIONAL benchmark fields -- ``scenario``,
``difficulty``, ``provenance``, ``retrieval_label`` -- all ``None`` by
default, so every case in the bundled suite that predates them still parses
unchanged. Structural validity (a real ``RetrievalScenario``/difficulty
value) is checked here at load time; whether a case's scenario/provenance
CLAIM actually holds against the real corpus is machine-checked by
``atlas.benchmark.validation``, which needs a ``KnowledgeBase`` this module
deliberately does not depend on.

M2.4 adds ``recalled_view``: a FIXTURE recalled view for cases requiring
``thesis`` (t29/t33/t34/t35), never read from any on-disk ``ThesisStore``.
This is deliberate, not an oversight -- if evaluation read the user's actual
memory store, a run's outcome would depend on what happens to be persisted
on the machine running it, and the same case could pass or fail depending on
unrelated state. ``RecalledViewFixture``/``RecalledClaimFixture`` are plain
data here (not ``reasoning.contracts.RecalledView``/``RecalledClaim``), for
the same reason ``CaseProvenance``/``RetrievalLabel`` are benchmark-layer
types rather than reasoning ones: this module has never imported
``atlas.reasoning`` and should not start for one optional field.
``eval/runner.py`` (which already imports the reasoning contracts) projects
the fixture into a real ``RecalledView`` at run time.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from atlas.benchmark.provenance import CaseProvenance, RetrievalLabel
from atlas.benchmark.taxonomy import (
    ALL_CAPABILITY_IDS,
    ALL_SCENARIO_IDS,
    DifficultyClass,
)

_SUITE_PATH = Path(__file__).parent / "data" / "acceptance_v2_1.json"

_VALID_DIFFICULTIES = frozenset({"routine", "difficult"})
_VALID_CONFIDENCE = frozenset({"high", "medium", "low"})

# Capability tags a milestone may provide. M0/M1 provide only single-name pull.
CAP_SINGLE_NAME = "single_name"
CAP_THESIS = "thesis"  # M2
CAP_PROMISE_LEDGER = "promise_ledger"  # M3
CAP_MULTI_NAME = "multi_name"  # M5
CAP_CONVERSATION = "conversation"  # M5
CAP_DRILLDOWN = "drilldown"  # M1
CAP_DETERMINISM = "determinism"  # M4
# M1.5 (ADR-M1.5): a runner-MODE switch, not a case gate — no case declares
# this in `requires`, so including it in --capabilities never changes which
# cases are attempted. It only tells LiveReasoningRunner to pass the case's
# question into build_context(), activating question-conditioned retrieval so
# `atlas eval compare` can measure its effect against the M1 baseline.
CAP_QUESTION_RETRIEVAL = "question_retrieval"
# M1.7 (ADR-M1.7): another runner-mode switch, layered on top of
# CAP_QUESTION_RETRIEVAL rather than replacing it. No case declares this in
# `requires` either -- it tells LiveReasoningRunner to additionally plan that
# retrieval (HeuristicPlanner) before running it, so `atlas eval compare` can
# measure the plan's effect against the M1.5 baseline. Has no effect unless
# CAP_QUESTION_RETRIEVAL is ALSO active (planning without question-retrieval
# is a no-op -- nothing would consume the plan).
CAP_RETRIEVAL_PLAN = "retrieval_plan"

# "honest_negative" (§12.6 amendment 5): the ideal response is EITHER a clean
# refusal OR an answer that honestly denies/declares-absent (e.g. "no such
# promise exists in the evidence", "customers are not disclosed"). Behavioral
# refused-vs-answered never fails for this class; the fabrication guards
# (must_not_contain) are the teeth.
Behavior = Literal["answer", "refuse", "honest_negative"]


@dataclass(frozen=True)
class RecalledClaimFixture:
    """One statement of a fixture recalled view (M2.4). Plain data -- projected
    into ``reasoning.contracts.RecalledClaim`` by ``eval/runner.py``, never
    constructed as one here.
    """

    statement: str
    evidence_ids: tuple[str, ...] = ()
    confidence: str = "medium"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        if not self.statement.strip():
            raise ValueError("RecalledClaimFixture.statement must be non-empty")
        if self.confidence not in _VALID_CONFIDENCE:
            raise ValueError(
                f"RecalledClaimFixture.confidence {self.confidence!r} must be one of "
                f"{sorted(_VALID_CONFIDENCE)}"
            )


@dataclass(frozen=True)
class RecalledViewFixture:
    """A fixture recalled view: what a case pretends Atlas (or a user)
    concluded, for cases requiring the ``thesis`` capability. Never sourced
    from a real ``ThesisStore`` -- see the module docstring.
    """

    question: str
    as_of: str
    claims: tuple[RecalledClaimFixture, ...]
    origin: str = "atlas"

    def __post_init__(self) -> None:
        object.__setattr__(self, "claims", tuple(self.claims))
        if not self.question.strip():
            raise ValueError("RecalledViewFixture.question must be non-empty")
        if not self.as_of.strip():
            raise ValueError("RecalledViewFixture.as_of must be non-empty")
        if not self.claims:
            raise ValueError("RecalledViewFixture.claims must not be empty")
        if self.origin not in ("atlas", "user"):
            raise ValueError(
                f"RecalledViewFixture.origin {self.origin!r} must be 'atlas' or 'user'"
            )


@dataclass(frozen=True)
class EvalCase:
    """One executable acceptance test."""

    id: str
    category: str
    question: str
    subject: str
    expected_behavior: Behavior
    rubric: str
    requires: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()
    must_contain_any: tuple[str, ...] = ()
    # M1.8.5 (ADR-0005): the benchmark taxonomy this case exercises. All
    # optional/None -- absent for every pre-M1.8.5 case, and for any case
    # that isn't claiming to test a specific retrieval scenario.
    scenario: str | None = None
    difficulty: DifficultyClass | None = None
    provenance: CaseProvenance | None = None
    retrieval_label: RetrievalLabel | None = None
    # M2.4: a fixture recalled view for cases requiring "thesis". None for
    # every case that doesn't need one -- see the module docstring for why
    # this is never read from an on-disk ThesisStore.
    recalled_view: RecalledViewFixture | None = None
    # M-E.3 (ADR-0011): the AtlasCapability ids this question DEMANDS -- the
    # second benchmark axis. Deliberately NOT the same thing as `requires`
    # above: `requires` holds CAP_* milestone *availability* gates ("does this
    # build provide the feature?"), while `capabilities` holds question-grading
    # capabilities ("what must the system be able to do to answer this at
    # all?"). A case legitimately carries both. Empty for every case today --
    # authoring the 45 benchmark questions as cases is deferred (matrix §9),
    # so this is the field only, with no bundled-suite population yet.
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.scenario is not None and self.scenario not in ALL_SCENARIO_IDS:
            raise ValueError(
                f"EvalCase.scenario {self.scenario!r} is not a valid RetrievalScenario"
            )
        if self.difficulty is not None and self.difficulty not in _VALID_DIFFICULTIES:
            raise ValueError(
                f"EvalCase.difficulty {self.difficulty!r} must be one of {sorted(_VALID_DIFFICULTIES)}"
            )
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        unknown = set(self.capabilities) - ALL_CAPABILITY_IDS
        if unknown:
            raise ValueError(
                f"EvalCase.capabilities {sorted(unknown)} are not valid AtlasCapability ids"
            )

    def is_available(self, capabilities: frozenset[str]) -> bool:
        """True when every required capability is present in *capabilities*."""
        return set(self.requires) <= capabilities


def _provenance_from_dict(d: dict[str, Any] | None) -> CaseProvenance | None:
    if d is None:
        return None
    return CaseProvenance(
        origin=d["origin"],
        supporting_evidence_ids=tuple(d.get("supporting_evidence_ids", ())),
        verification_method=d.get("verification_method", ""),
        verified_at=d.get("verified_at", ""),
        verified_by=d.get("verified_by", ""),
    )


def _retrieval_label_from_dict(d: dict[str, Any] | None) -> RetrievalLabel | None:
    if d is None:
        return None
    return RetrievalLabel(
        relevant_evidence_ids=tuple(d.get("relevant_evidence_ids", ())),
        relevant_kinds=tuple(d.get("relevant_kinds", ())),
        must_not_retrieve=tuple(d.get("must_not_retrieve", ())),
    )


def _recalled_view_from_dict(d: dict[str, Any] | None) -> RecalledViewFixture | None:
    if d is None:
        return None
    return RecalledViewFixture(
        question=d["question"],
        as_of=d["as_of"],
        claims=tuple(
            RecalledClaimFixture(
                statement=c["statement"],
                evidence_ids=tuple(c.get("evidence_ids", ())),
                confidence=c.get("confidence", "medium"),
            )
            for c in d.get("claims", ())
        ),
        origin=d.get("origin", "atlas"),
    )


def _case(d: dict[str, Any]) -> EvalCase:
    return EvalCase(
        id=d["id"],
        category=d["category"],
        question=d["question"],
        subject=d.get("subject", "TCS"),
        expected_behavior=d["expected_behavior"],
        rubric=d.get("rubric", ""),
        requires=tuple(d.get("requires", ())),
        must_not_contain=tuple(d.get("must_not_contain", ())),
        must_contain_any=tuple(d.get("must_contain_any", ())),
        scenario=d.get("scenario"),
        difficulty=d.get("difficulty"),
        provenance=_provenance_from_dict(d.get("provenance")),
        retrieval_label=_retrieval_label_from_dict(d.get("retrieval_label")),
        recalled_view=_recalled_view_from_dict(d.get("recalled_view")),
        capabilities=tuple(d.get("capabilities", ())),
    )


def load_cases(path: Path | None = None) -> list[EvalCase]:
    """Load the evaluation suite (defaults to the bundled §8.6 acceptance set)."""
    raw = json.loads((path or _SUITE_PATH).read_text(encoding="utf-8"))
    cases = [_case(d) for d in raw]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case ids in evaluation suite")
    return cases


# Free-tier "core" preset: a small, always-available sample (requires=())
# spanning the functional breadth of the suite (retrieval-synthesis, temporal,
# comparative, evaluative, dialectical), so a quick smoke run exercises
# several distinct code paths without needing every milestone's capabilities.
_CORE_IDS = ("t01", "t06", "t11", "t16", "t28")

# "grounding" preset: category H is the evidence-integrity/refusal cluster —
# the cases built specifically to catch fabrication, lazy refusal, and false
# premises.
_GROUNDING_CATEGORY = "H"

SuiteName = Literal["core", "grounding", "refusals", "full"]
SUITE_NAMES: tuple[str, ...] = ("core", "grounding", "refusals", "full")


def _select_core(cases: list[EvalCase]) -> list[EvalCase]:
    by_id = {c.id: c for c in cases}
    return [by_id[i] for i in _CORE_IDS if i in by_id]


_PRESETS: dict[str, Callable[[list[EvalCase]], list[EvalCase]]] = {
    "full": lambda cases: list(cases),
    "core": _select_core,
    "grounding": lambda cases: [c for c in cases if c.category == _GROUNDING_CATEGORY],
    "refusals": lambda cases: [c for c in cases if c.expected_behavior != "answer"],
}


def resolve_suite(value: str) -> list[EvalCase]:
    """Resolve a ``--suite`` value to a list of cases.

    Either a named preset (``core``/``grounding``/``refusals``/``full``),
    applied over the bundled §8.6 set, or a path to a custom suite JSON file —
    preserving the pre-existing "--suite <path>" behavior for anything that
    isn't a preset name.
    """
    preset = _PRESETS.get(value.strip().lower())
    if preset is not None:
        return preset(load_cases())
    return load_cases(Path(value))
