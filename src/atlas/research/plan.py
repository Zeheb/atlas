"""ResearchPlan data model (M2.2.5 commit 1).

``ResearchPlan`` is the frozen, structured output of a ``ResearchPlanner``
(``planner.py``, M2.2.5 commit 2) and the sole input the investigation
executor needs (``investigate.py``, M2.2.5 commit 3).

Two planners, strictly layered
------------------------------
M1.7's ``SearchPlan``/``RetrievalPlanner`` decides *how to retrieve* for one
question. This decides *what should be investigated* for one open-ended
research question, and each ``Investigation`` it emits carries a concrete
sub-question that is handed to ``plan_retrieval()`` unchanged. One
``ResearchPlan`` therefore fans out into N ``SearchPlan``s:

    Question -> ResearchPlan (N Investigations)
                  each Investigation.question -> SearchPlan -> retrieval

The research planner sits strictly ABOVE the retrieval planner and duplicates
none of its logic. It never retrieves evidence, never calls an LLM, and never
synthesizes a conclusion -- synthesis is M2.3's job alone.

One vocabulary, not two
-----------------------
``ResearchDimension`` values are EXACTLY the section keys emitted by
``research/report.py``'s body builders. This is deliberate and test-enforced
(``test_research_plan.py``): the deterministic report and the research planner
must name the same nine things the same way, or a reader comparing
`atlas research` output against an `atlas investigate` plan would be reading
two different taxonomies for one domain.

Note this vocabulary's one inherited blind spot, called out rather than
silently accepted: there is no standalone ``capital_allocation`` dimension --
that judgment is currently split across ``balance_sheet`` (leverage, cash) and
``what_changed`` (buybacks, dividends, acquisitions). Anchoring to the existing
keys keeps the two surfaces consistent today; introducing a tenth dimension is
a report-layer change, not a planner-layer one, so it belongs in whichever
milestone adds the matching section builder.

Import boundary (enforced by test, not just convention -- see
``tests/unit/test_research_planner.py``): this module imports no
``KnowledgeBase``, no LLM client, no network/filesystem module, and nothing
from ``atlas.reasoning``. Frozen-dataclass discipline (tuple coercion,
``__post_init__`` validation, ``to_dict`` via ``dataclasses.asdict``) is
reproduced from ``reasoning/plan.py`` locally rather than imported, for the
same reason that module reproduced it from ``contracts.py``: the boundary is
the point.

``from_dict`` is deliberately NOT written yet, matching ``reasoning/plan.py``'s
own reasoning: it has no consumer until an ``LLMResearchPlanner`` exists, and
an unused parser is maintenance debt without a caller to keep it honest. When
that milestone arrives it will construct these same dataclasses, so
``__post_init__`` remains the safety boundary for a model-generated plan
exactly as it is for the heuristic planner's output -- a hallucinated
dimension raises ``ValueError`` rather than reaching the executor.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Literal

# EXACTLY research/report.py's _BODY_BUILDERS section keys, in that file's own
# rendered order. Test-enforced against the real builders so the two cannot
# drift (see test_research_plan.py::test_dimensions_match_report_section_keys).
ResearchDimension = Literal[
    "what_changed",  # the one question every memo genre answers first
    "business_quality",  # margins, returns, durability
    "management_credibility",  # said-vs-did, tenure, governance signals
    "balance_sheet",  # leverage, liquidity, cash generation
    "valuation",  # multiples where available; honest gap where not
    "risks",  # disclosed risk factors and exposures
    "catalysts",  # forward events that could change the view
    "competitive_position",  # peer-relative standing
    "esg_governance",  # BRSR/ESG disclosure and governance structure
]

_VALID_DIMENSIONS = frozenset(ResearchDimension.__args__)  # type: ignore[attr-defined]

ResearchIntent = Literal[
    "invest_decision",  # "should I invest in TCS?" -- the widest plan
    "risk_assessment",  # "what are the key risks to SBI?"
    "comparison",  # "compare Tata Steel with JSW Steel" -- multi-subject
    "thematic",  # "how exposed is X to input costs?" -- narrow but multi-dimension
    "targeted",  # a single-dimension lookup; degenerates to a plain `ask`
]

_VALID_RESEARCH_INTENTS = frozenset(ResearchIntent.__args__)  # type: ignore[attr-defined]

# A plan wider than this is a checklist, not a judgment -- see the
# anti-checklist gate in the M2.2.5 design. Nine dimensions exist; a plan
# naming all of them for every question is exactly the degenerate behavior
# M1.8.5 measured in the retrieval planner (55% of cases fell through to a
# no-op `general` intent). The cap is a structural guard, not a style rule.
MAX_INVESTIGATIONS = 8


def _tuple(value: Any) -> tuple[Any, ...]:
    """Coerce a caller-supplied sequence into an immutable tuple."""
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return tuple(value)


@dataclass(frozen=True)
class ResearchDecision:
    """One research-planner rule firing -- the plan's own audit trail.

    Deliberately identical in shape to ``reasoning.plan.PlanningDecision``
    (rule/input/output, no ``confidence``) so the eval harness's dead-rule
    detection works on both planners with the same code path. A deterministic
    rule engine has no meaningful confidence to report; see PlanningDecision's
    own docstring for the full argument, which applies here unchanged.
    """

    rule: str  # stable identifier, e.g. "intent_keyword_match"
    input: str  # what the rule matched on, e.g. "should i invest"
    output: str  # what it decided, e.g. "invest_decision"

    def __post_init__(self) -> None:
        if not self.rule:
            raise ValueError("ResearchDecision.rule must be non-empty")


@dataclass(frozen=True)
class Investigation:
    """One dimension the planner says must be investigated, and the concrete
    sub-question that investigates it.

    ``question`` is a real, self-contained question handed verbatim to
    ``plan_retrieval()`` -- not a topic label. This is what makes the two
    planners compose: the research planner's output is the retrieval planner's
    input, with no adapter in between.

    ``rationale`` is required and must be non-empty. A dimension that cannot
    explain in words why it belongs in this plan is a checklist entry, and the
    design's read-through check ("why is Atlas investigating this?") is
    unanswerable without it.

    ``subjects`` holds more than one ticker only for comparison intents, which
    depend on M2.2's multi-subject support.
    """

    dimension: ResearchDimension
    question: str
    subjects: tuple[str, ...]
    rationale: str
    priority: int = 5

    def __post_init__(self) -> None:
        object.__setattr__(self, "subjects", _tuple(self.subjects))

        if self.dimension not in _VALID_DIMENSIONS:
            raise ValueError(
                f"Investigation.dimension {self.dimension!r} is not a valid ResearchDimension"
            )
        if not self.question.strip():
            raise ValueError("Investigation.question must be non-empty")
        if not self.rationale.strip():
            raise ValueError(
                f"Investigation.rationale must be non-empty (dimension {self.dimension!r})"
            )
        if not self.subjects:
            raise ValueError(
                f"Investigation.subjects must name at least one subject "
                f"(dimension {self.dimension!r})"
            )
        if not (1 <= self.priority <= 10):
            raise ValueError(
                f"Investigation.priority must be in 1..10, got {self.priority}"
            )


@dataclass(frozen=True)
class ResearchPlan:
    """The structured output of a ResearchPlanner: what must be investigated
    before a view can be formed, and why.

    Immutable and self-validating: a malformed plan (from a future
    LLMResearchPlanner, or from hand-constructed test data) raises ValueError
    at construction rather than propagating an unanswerable investigation into
    the executor.
    """

    raw_question: str
    intent: ResearchIntent
    subjects: tuple[str, ...]
    investigations: tuple[Investigation, ...]
    planner_version: str = "heuristic-1"
    decisions: tuple[ResearchDecision, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "subjects", _tuple(self.subjects))
        object.__setattr__(self, "investigations", _tuple(self.investigations))
        object.__setattr__(self, "decisions", _tuple(self.decisions))

        if not self.raw_question.strip():
            raise ValueError("ResearchPlan.raw_question must be non-empty")
        if self.intent not in _VALID_RESEARCH_INTENTS:
            raise ValueError(
                f"ResearchPlan.intent {self.intent!r} is not a valid ResearchIntent"
            )
        if not self.subjects:
            raise ValueError("ResearchPlan.subjects must name at least one subject")
        if not self.investigations:
            raise ValueError(
                "ResearchPlan.investigations must not be empty -- a plan that "
                "investigates nothing cannot ground a view"
            )
        if len(self.investigations) > MAX_INVESTIGATIONS:
            raise ValueError(
                f"ResearchPlan has {len(self.investigations)} investigations, "
                f"exceeding MAX_INVESTIGATIONS={MAX_INVESTIGATIONS} -- a plan this "
                f"wide is a checklist, not a research judgment"
            )

        seen: set[str] = set()
        for inv in self.investigations:
            if inv.dimension in seen:
                raise ValueError(
                    f"ResearchPlan has a duplicate dimension: {inv.dimension!r}"
                )
            seen.add(inv.dimension)

    @property
    def dimensions(self) -> tuple[str, ...]:
        """The dimension set this plan covers, in plan order.

        The unit the anti-checklist entropy gate measures across a suite of
        questions -- a planner emitting the same dimension set for every
        question is dead in exactly the way a never-firing rule is.
        """
        return tuple(inv.dimension for inv in self.investigations)

    def ordered_investigations(self) -> tuple[Investigation, ...]:
        """Investigations in execution order: highest priority first, ties
        broken by the planner's own emission order (Python's sort is stable),
        never by dimension name -- the planner's ordering is a judgment and
        must not be silently re-sorted alphabetically.
        """
        return tuple(sorted(self.investigations, key=lambda i: -i.priority))

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready snapshot -- for `--out`, eval reports, and replay.

        A thin ``dataclasses.asdict()`` wrapper, matching
        ``SearchPlan.to_dict()``: it recurses through the nested frozen
        dataclasses automatically, so it can never drift from the actual
        field set.
        """
        return dataclasses.asdict(self)
