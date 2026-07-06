"""Evaluation cases derived from the V2.1 acceptance tests (§8.6).

Each §8.6 task is one declarative ``EvalCase``. Cases are data, loaded from
``data/acceptance_v2_1.json``, so the acceptance tests are executable rather
than prose. A case's ``requires`` lists the capabilities it needs; a milestone
that lacks one marks the case *pending* instead of running it.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

_SUITE_PATH = Path(__file__).parent / "data" / "acceptance_v2_1.json"

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

    def is_available(self, capabilities: frozenset[str]) -> bool:
        """True when every required capability is present in *capabilities*."""
        return set(self.requires) <= capabilities


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
