"""Deterministic ResearchPlanner (M2.2.5 commit 2).

Turns an open-ended research question into a ``ResearchPlan`` (``plan.py``) --
an intent, the subjects involved, and the ordered set of investigations that
must be answered before a view can be formed -- using ONLY keyword rules
against the question text. No LLM, no KB, no network, no filesystem.

This is the same "deterministic floor" philosophy as ``reasoning/planner.py``
(M1.7) one layer up: every decision here is a literal, independently testable
rule, not an inference. ``HeuristicResearchPlanner`` is the only implementation
today; a future ``LLMResearchPlanner`` implements the same ``ResearchPlanner``
protocol and produces the same frozen, self-validating ``ResearchPlan`` -- so a
hallucinated dimension or an absurd 30-investigation plan raises ``ValueError``
in ``ResearchPlan.__post_init__`` rather than reaching the executor.

What this module does NOT do (the layering, stated as a boundary):

- It does not retrieve. Each ``Investigation.question`` is handed to
  ``plan_retrieval()`` by ``investigate.py``; this module never imports it.
- It does not answer or synthesize. Forming the view from the investigations'
  results is M2.3's job, behind its own provenance gate.
- It does not touch ``atlas research``'s fixed-shape report. That report's
  constant section list is an audit guarantee (see report.py's docstring);
  this planner shares its vocabulary but never edits or reorders it.

Import boundary (enforced by test, not just convention -- see
``test_research_planner.py``'s import-boundary assertions): this module imports
NOTHING from ``atlas.knowledge``, ``atlas.reasoning``, ``atlas.acquisition``,
or any network/filesystem library. Its only Atlas import is ``plan.py``.

Why these dimension sets
------------------------
The per-intent dimension tables below are the milestone's actual domain
content -- the encoded judgment about what must be checked before answering a
given class of question. They are deliberately NOT uniform: an
``invest_decision`` is wide (six dimensions), a ``risk_assessment`` is
narrow-but-deep (four, weighted toward downside), a ``comparison`` is
peer-relative (five), and a ``targeted`` question expands to one. That
non-uniformity is what the anti-checklist entropy gate measures; a planner
whose tables were all identical would pass every other test and still be
worthless.
"""
from __future__ import annotations

from typing import Protocol

from atlas.research.plan import (
    Investigation,
    ResearchDecision,
    ResearchDimension,
    ResearchIntent,
    ResearchPlan,
)

# Every ResearchDecision.rule identifier HeuristicResearchPlanner can emit.
# The eval harness diffs this against which rules actually fired across a
# suite to surface dead rules -- exactly as reasoning/planner.py's
# ALL_RULE_IDS does for the retrieval planner, and consumed by the same
# aggregate code path. Kept here, next to the rules themselves, so it cannot
# silently drift out of sync with what the planner actually does.
ALL_RESEARCH_RULE_IDS: frozenset[str] = frozenset({
    "research_intent_keyword_match",
    "research_intent_fallback",
    "dimensions_from_intent",
    "comparison_subjects_detected",
    "dimension_dropped_single_subject",
})

# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------
# Order matters: checked top-to-bottom, first match wins. Narrower readings
# are checked before broader ones. "Should I invest in X, and what are the
# risks?" is an invest_decision whose risk clause is one of its dimensions --
# not a risk_assessment that happens to mention investing -- so the
# invest markers are checked first.
_RESEARCH_INTENT_RULES: tuple[tuple[ResearchIntent, tuple[str, ...]], ...] = (
    ("comparison", (
        "compare", "versus", " vs ", " vs. ", "against its peer", "relative to",
        "better than", "which is stronger", "peer comparison",
    )),
    ("invest_decision", (
        "should i invest", "should i buy", "worth investing", "worth buying",
        "is it a good investment", "investment case", "should we invest",
        "would you invest", "is this a buy", "attractive investment",
    )),
    ("risk_assessment", (
        "key risks", "what are the risks", "risk to", "risks to", "downside",
        "what could go wrong", "bear case", "biggest risk", "red flags",
    )),
    ("thematic", (
        "exposed", "exposure", "how does it handle", "impact of",
        "affected by", "sensitivity to", "dependent on", "reliance on",
    )),
)

# The domain content of this milestone: what must be investigated, per class
# of question. Each entry is (dimension, priority) -- priority drives
# execution order and the top-N cap, and encodes which dimension a human
# analyst would look at first for that question type.
#
# These sets are deliberately different sizes and compositions; see the
# module docstring. An invest_decision omits esg_governance not because ESG
# does not matter but because it is rarely the deciding factor at first pass
# and the plan must stay under MAX_INVESTIGATIONS to remain a judgment.
_INTENT_DIMENSIONS: dict[ResearchIntent, tuple[tuple[ResearchDimension, int], ...]] = {
    "invest_decision": (
        ("business_quality", 9),
        ("valuation", 8),
        ("balance_sheet", 7),
        ("what_changed", 6),
        ("risks", 5),
        ("management_credibility", 4),
    ),
    "risk_assessment": (
        ("risks", 10),
        ("balance_sheet", 8),
        ("what_changed", 6),
        ("management_credibility", 4),
    ),
    "comparison": (
        ("business_quality", 9),
        ("competitive_position", 8),
        ("valuation", 7),
        ("balance_sheet", 6),
        ("what_changed", 4),
    ),
    "thematic": (
        ("risks", 8),
        ("business_quality", 7),
        ("what_changed", 5),
    ),
    "targeted": (
        ("what_changed", 5),
    ),
}

# The sub-question each dimension asks. "{subject}" is substituted per
# subject; comparison intents render a single question naming every subject
# so the retrieval layer sees one comparative question, not N isolated ones.
# These are real, self-contained questions -- not topic labels -- because
# plan_retrieval() consumes them verbatim.
_DIMENSION_QUESTIONS: dict[ResearchDimension, str] = {
    "what_changed": "What material developments has {subject} disclosed most recently?",
    "business_quality": "What do {subject}'s revenue growth and operating margins show about business quality?",
    "management_credibility": "What has {subject}'s management said about performance, and what was delivered?",
    "balance_sheet": "What do {subject}'s debt, leverage and cash position show about balance sheet strength?",
    "valuation": "What valuation multiples or earnings figures has {subject} disclosed?",
    "risks": "What risk factors and exposures has {subject} disclosed?",
    "catalysts": "What forward-looking guidance or outlook has {subject} provided?",
    "competitive_position": "How does {subject} describe its competitive position and market share?",
    "esg_governance": "What ESG and governance disclosures has {subject} made?",
}

# Why each dimension belongs in a plan, in words. Required by
# Investigation.__post_init__ -- a dimension that cannot explain itself is a
# checklist entry, and the design's read-through check depends on these.
_DIMENSION_RATIONALES: dict[ResearchDimension, str] = {
    "what_changed": "The most recent disclosures set the starting point; a view built on stale facts is wrong before it is argued.",
    "business_quality": "Growth and margin durability determine whether the business itself is worth owning, independent of price.",
    "management_credibility": "Whether prior guidance was met is the cheapest available test of whether current guidance can be believed.",
    "balance_sheet": "Leverage and liquidity determine whether the company survives a bad outcome, which bounds the downside.",
    "valuation": "A good business at the wrong price is a bad investment; the price paid must be part of the judgment.",
    "risks": "The disclosed downside is what the thesis must survive; unexamined risk is not the same as absent risk.",
    "catalysts": "Forward guidance identifies what could change the view, and when.",
    "competitive_position": "Relative standing determines whether current economics are defensible against competitors.",
    "esg_governance": "Governance and ESG disclosures surface structural issues that financial statements alone do not show.",
}


class ResearchPlanner(Protocol):
    """A pure function (question, subjects) -> ResearchPlan.

    See the module docstring for the boundary every implementation
    (heuristic today, LLM later) must honor: plan only, never retrieve,
    never synthesize.
    """

    def plan(self, question: str, subjects: tuple[str, ...]) -> ResearchPlan: ...


class HeuristicResearchPlanner:
    """M2.2.5's only research planner: keyword rules, no LLM, no KB, no I/O."""

    def plan(self, question: str, subjects: tuple[str, ...]) -> ResearchPlan:
        if not subjects:
            raise ValueError("HeuristicResearchPlanner.plan requires at least one subject")

        decisions: list[ResearchDecision] = []

        intent = self._classify_intent(question, decisions)
        intent = self._reconcile_subjects(intent, subjects, decisions)
        investigations = self._investigations(intent, subjects, decisions)

        return ResearchPlan(
            raw_question=question,
            intent=intent,
            subjects=subjects,
            investigations=investigations,
            decisions=tuple(decisions),
        )

    # -- rules, one method each, so each is independently testable ---------

    def _classify_intent(
        self, question: str, decisions: list[ResearchDecision],
    ) -> ResearchIntent:
        haystack = question.lower()
        for intent, markers in _RESEARCH_INTENT_RULES:
            for marker in markers:
                if marker in haystack:
                    decisions.append(ResearchDecision(
                        rule="research_intent_keyword_match", input=marker, output=intent,
                    ))
                    return intent
        # No marker matched: a narrow, specific question. It degenerates to a
        # single investigation, which `atlas ask` would already have answered
        # directly -- the plan says so honestly rather than inventing breadth.
        decisions.append(ResearchDecision(
            rule="research_intent_fallback", input=question, output="targeted",
        ))
        return "targeted"

    def _reconcile_subjects(
        self, intent: ResearchIntent, subjects: tuple[str, ...],
        decisions: list[ResearchDecision],
    ) -> ResearchIntent:
        """Multiple subjects mean a comparison regardless of phrasing.

        "Tata Steel and JSW Steel margins" names no comparison marker but is
        unambiguously comparative once two subjects are supplied, so subject
        count overrides keyword classification here rather than the reverse.
        """
        if len(subjects) > 1 and intent != "comparison":
            decisions.append(ResearchDecision(
                rule="comparison_subjects_detected",
                input=", ".join(subjects),
                output="comparison",
            ))
            return "comparison"
        return intent

    def _investigations(
        self, intent: ResearchIntent, subjects: tuple[str, ...],
        decisions: list[ResearchDecision],
    ) -> tuple[Investigation, ...]:
        entries = _INTENT_DIMENSIONS[intent]
        decisions.append(ResearchDecision(
            rule="dimensions_from_intent",
            input=intent,
            output=", ".join(dim for dim, _priority in entries),
        ))

        subject_label = " and ".join(subjects)
        investigations: list[Investigation] = []
        for dimension, priority in entries:
            # competitive_position compares a company against peers; with one
            # subject and no peer set supplied it has nothing to compare
            # against, so it is dropped with an explicit, audited decision
            # rather than emitted as an investigation that cannot be answered.
            if dimension == "competitive_position" and len(subjects) < 2:
                decisions.append(ResearchDecision(
                    rule="dimension_dropped_single_subject",
                    input=dimension,
                    output="dropped: needs >=2 subjects to be answerable",
                ))
                continue
            investigations.append(Investigation(
                dimension=dimension,
                question=_DIMENSION_QUESTIONS[dimension].format(subject=subject_label),
                subjects=subjects,
                rationale=_DIMENSION_RATIONALES[dimension],
                priority=priority,
            ))
        return tuple(investigations)


def plan_research(question: str, subjects: tuple[str, ...]) -> ResearchPlan:
    """Convenience wrapper: the default research planner, one call.

    Mirrors ``reasoning.planner.plan_retrieval`` so call sites read the same
    at both layers.
    """
    return HeuristicResearchPlanner().plan(question, subjects)
