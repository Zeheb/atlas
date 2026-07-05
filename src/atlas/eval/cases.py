"""Evaluation cases derived from the V2.1 acceptance tests (§8.6).

Each §8.6 task is one declarative ``EvalCase``. Cases are data, loaded from
``data/acceptance_v2_1.json``, so the acceptance tests are executable rather
than prose. A case's ``requires`` lists the capabilities it needs; a milestone
that lacks one marks the case *pending* instead of running it.
"""
from __future__ import annotations

import json
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

Behavior = Literal["answer", "refuse"]


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
