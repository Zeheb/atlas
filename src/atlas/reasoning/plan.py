"""SearchPlan data model (M1.7 commit 3).

``SearchPlan`` is the frozen, structured output of a ``RetrievalPlanner``
(``planner.py``, M1.7 commit 4) and the sole input the retriever needs beyond
the candidate document ids it already had (``retrieval.py``'s
``retrieve_with_plan``, M1.7 commit 5).

Deliberately NOT added to ``contracts.py``: that file holds the §10 contracts
C1-C9, which are contract-version-locked (see its module docstring). This is
an internal interface between two components inside the reasoning package —
the same category ``RetrievalMatch`` occupies in ``retrieval.py`` ("internal
implementation detail, not a §10 contract type").

Every type here is frozen; sequence fields are coerced to tuples so a plan is
immutable and hashable-friendly while callers may pass plain lists — the same
discipline ``contracts.py`` uses (its ``_tuple`` helper), reproduced locally
rather than imported, since ``plan.py`` intentionally has NO dependency on
``contracts.py`` (see the import-boundary rule below).

Import boundary (enforced by test, not just convention — see
``tests/unit/test_reasoning_planner.py``'s import-boundary assertions): this
module imports no ``KnowledgeBase``, no LLM client, no network/filesystem
module. It imports ``EvidenceKind`` only to validate ``DocTypePreference.kind``
against the one real vocabulary Atlas already has (``acquisition/evidence.py``)
rather than inventing a second one.

No ``strategy`` field: which retrieval *mechanism* runs (lexical today; hybrid
or vector later) is deployment/execution configuration owned by the retriever,
not a property of the question. A future hybrid retriever adds its own
execution-profile input; if the question itself should influence that choice,
that arrives as a differently-named hint field then, not by resurrecting
"strategy" here.

``from_dict`` is deliberately NOT written yet: it has no consumer until an
LLM-based planner exists, and an unused parser is maintenance debt without a
caller to keep it honest. When that milestone arrives, it will construct
``SearchPlan`` through these same dataclass constructors, so ``__post_init__``
validation remains the safety boundary for a model-generated plan exactly as
it is for the heuristic planner's own output.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Literal

from atlas.acquisition.evidence import EvidenceKind

_VALID_EVIDENCE_KINDS = frozenset(k.value for k in EvidenceKind)

RetrievalIntent = Literal[
    "financial_metric",  # revenue, margin, EPS, debt
    "guidance",  # outlook, target, expects, aspiration
    "risk",  # risk factor, exposure, litigation
    "governance",  # board, director, auditor, remuneration
    "capital_action",  # dividend, buyback, acquisition, fundraise
    "esg",  # emissions, diversity, BRSR
    "ownership",  # shareholding, promoter, pledge, FII
    "narrative",  # strategy, commentary, management view
    "general",  # fallback -- no preference expressed
]

_VALID_INTENTS = frozenset(RetrievalIntent.__args__)  # type: ignore[attr-defined]


def _tuple(value: Any) -> tuple[Any, ...]:
    """Coerce a caller-supplied sequence into an immutable tuple."""
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return tuple(value)


@dataclass(frozen=True)
class DocTypePreference:
    """One document kind the planner wants boosted, and by how much.

    ``weight`` is an additive score boost (1..100), never a filter — the
    retriever's fallback guarantee (a plan can never return FEWER results
    than an unplanned query) depends on doc-type preference being purely
    additive. See retrieval.py's candidate/ranking split.
    """

    kind: str  # must be a value of EvidenceKind
    weight: int

    def __post_init__(self) -> None:
        if self.kind not in _VALID_EVIDENCE_KINDS:
            raise ValueError(
                f"DocTypePreference.kind {self.kind!r} is not a valid EvidenceKind value"
            )
        if not (1 <= self.weight <= 100):
            raise ValueError(
                f"DocTypePreference.weight must be in 1..100, got {self.weight}"
            )


@dataclass(frozen=True)
class DateWindow:
    """An inclusive ISO-date range the planner prefers, never a hard filter."""

    start: str | None = None
    end: str | None = None

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError(
                f"DateWindow.start ({self.start!r}) must not be after end ({self.end!r})"
            )


@dataclass(frozen=True)
class RerankHints:
    """Deterministic ranking preferences the retriever's scorer consults."""

    prefer_recent: bool = False
    prefer_numeric: bool = False
    max_per_document: int | None = None

    def __post_init__(self) -> None:
        if self.max_per_document is not None and self.max_per_document < 1:
            raise ValueError(
                f"RerankHints.max_per_document must be >=1, got {self.max_per_document}"
            )


@dataclass(frozen=True)
class PlanningDecision:
    """One planner rule firing -- the plan's own audit trail.

    Deliberately has no ``confidence`` field: a deterministic rule engine has
    no meaningful confidence to report (every firing of the same rule would
    carry an identical constant), and a future LLM planner's confidence
    semantics would not mean the same thing as this one's. Add it in the
    milestone where it is a real, varying signal.
    """

    rule: str  # stable identifier, e.g. "intent_keyword_match", "top_k_default"
    input: str  # what the rule matched on, e.g. "risk factor"
    output: str  # what it decided, e.g. "risk"

    def __post_init__(self) -> None:
        if not self.rule:
            raise ValueError("PlanningDecision.rule must be non-empty")


@dataclass(frozen=True)
class SearchPlan:
    """The structured output of a RetrievalPlanner -- the sole input the
    retriever needs beyond the candidate document ids it already had.

    Immutable and self-validating: every field is checked in __post_init__,
    so a malformed plan (from a future LLM planner, or from hand-constructed
    test data) raises ValueError at construction rather than propagating a
    silently-wrong retrieval into the grounding context.
    """

    raw_question: str
    intent: RetrievalIntent
    query_terms: tuple[str, ...]
    numeric_terms: tuple[str, ...] = ()
    preferred_doc_types: tuple[DocTypePreference, ...] = ()
    date_window: DateWindow | None = None
    periods: tuple[str, ...] = ()
    top_k: int = 5
    rerank: RerankHints = field(default_factory=RerankHints)
    planner_version: str = "heuristic-1"
    decisions: tuple[PlanningDecision, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_terms", _tuple(self.query_terms))
        object.__setattr__(self, "numeric_terms", _tuple(self.numeric_terms))
        object.__setattr__(
            self, "preferred_doc_types", _tuple(self.preferred_doc_types)
        )
        object.__setattr__(self, "periods", _tuple(self.periods))
        object.__setattr__(self, "decisions", _tuple(self.decisions))

        if not self.raw_question.strip():
            raise ValueError("SearchPlan.raw_question must be non-empty")
        if self.intent not in _VALID_INTENTS:
            raise ValueError(
                f"SearchPlan.intent {self.intent!r} is not a valid RetrievalIntent"
            )
        if not (1 <= self.top_k <= 50):
            raise ValueError(f"SearchPlan.top_k must be in 1..50, got {self.top_k}")

        seen_kinds: set[str] = set()
        for pref in self.preferred_doc_types:
            if pref.kind in seen_kinds:
                raise ValueError(
                    f"SearchPlan.preferred_doc_types has a duplicate kind: {pref.kind!r}"
                )
            seen_kinds.add(pref.kind)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready snapshot -- for eval reports, caching, and replay.

        A thin ``dataclasses.asdict()`` wrapper: it recurses through the
        nested frozen dataclasses (DocTypePreference, DateWindow, RerankHints,
        PlanningDecision) automatically, so it can never drift from the
        actual field set. No custom encoding is needed because every field
        is already a JSON-primitive, a string tuple, or a nested dataclass.
        """
        return dataclasses.asdict(self)
