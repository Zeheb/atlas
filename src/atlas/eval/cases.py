"""Evaluation cases derived from the V2.1 acceptance tests (§8.6).

Each §8.6 task is one declarative ``EvalCase``. Cases are data, loaded from
``data/acceptance_v2_1.json``, so the acceptance tests are executable rather
than prose. A case's ``requires`` lists the capabilities it needs; a milestone
that lacks one marks the case *pending* instead of running it.

M1.8.5 (ADR-0005) adds four OPTIONAL benchmark fields -- ``scenario``,
``difficulty``, ``provenance``, ``retrieval_label`` -- all ``None`` by
default, so every case in the bundled suite that predates them still parses
unchanged. Structural validity (a real ``RetrievalScenario``/difficulty
value) is checked here at load time; whether a case's scenario/provenance
CLAIM actually holds against the real corpus is machine-checked by
``atlas.benchmark.validation``, which needs a ``KnowledgeBase`` this module
deliberately does not depend on.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from atlas.benchmark.provenance import CaseProvenance, RetrievalLabel
from atlas.benchmark.taxonomy import ALL_SCENARIO_IDS, DifficultyClass

_SUITE_PATH = Path(__file__).parent / "data" / "acceptance_v2_1.json"

_VALID_DIFFICULTIES = frozenset({"routine", "difficult"})

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

    def __post_init__(self) -> None:
        if self.scenario is not None and self.scenario not in ALL_SCENARIO_IDS:
            raise ValueError(f"EvalCase.scenario {self.scenario!r} is not a valid RetrievalScenario")
        if self.difficulty is not None and self.difficulty not in _VALID_DIFFICULTIES:
            raise ValueError(
                f"EvalCase.difficulty {self.difficulty!r} must be one of {sorted(_VALID_DIFFICULTIES)}"
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
