"""Deterministic RetrievalPlanner (M1.7 commit 4).

Turns a raw question string into a ``SearchPlan`` (``plan.py``) -- a coarse
intent, preferred document types, period/date hints, a ``top_k``, and rerank
hints -- using ONLY keyword/regex rules against the question text. No LLM, no
KB, no network, no filesystem: the planner never retrieves evidence and never
answers the question. It only plans HOW retrieval should be biased.

This is the M1.7 "deterministic floor," the same philosophy already applied
to retrieval.py's lexical matching and acquisition/classifier.py's Sub-line
rules: every decision here is a literal, independently testable rule, not an
inference. ``HeuristicPlanner`` is the only implementation today; a future
``LLMPlanner`` implements the same ``RetrievalPlanner`` protocol and produces
the same frozen, self-validating ``SearchPlan`` -- so a hallucinated doc kind
or an absurd ``top_k`` raises ``ValueError`` in ``SearchPlan.__post_init__``
rather than propagating into retrieval.

Import boundary (load-bearing, not decorative -- see
``test_reasoning_planner.py``'s import-boundary assertions): this module
imports NOTHING from ``atlas.knowledge``, ``atlas.reasoning.llm``, or any
network/filesystem library. Its only Atlas import is ``plan.py`` itself
(which in turn only knows about ``EvidenceKind``, a plain enum).
"""
from __future__ import annotations

import re
from typing import Protocol

from atlas.reasoning.plan import (
    DocTypePreference,
    PlanningDecision,
    RerankHints,
    RetrievalIntent,
    SearchPlan,
)
from atlas.reasoning.text import keywords as _keywords

# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------
# Order matters: checked top-to-bottom, first match wins. Narrower / more
# specific intents are checked before broad ones so a question mentioning
# both a narrative trigger ("what did management say") and a metric word
# ("margins") resolves to the narrative reading -- "what management SAID"
# is the actual ask; the metric word is its object, not a separate signal.
# Calibrated against the M1.7 design's own example: "What did management say
# about margins?" must resolve to a transcript-favoring intent, not a bare
# financial-metric lookup.
_INTENT_RULES: tuple[tuple[RetrievalIntent, tuple[str, ...]], ...] = (
    ("governance", (
        "board", "director", "auditor", "remuneration", "appointment",
        "resignation", "independent director", "committee",
    )),
    ("capital_action", (
        "dividend", "buyback", "acquisition", "acquire", "merger",
        "fundraise", "rights issue", "qip", "preferential allotment",
    )),
    ("esg", (
        "esg", "brsr", "emission", "sustainability", "carbon",
        "diversity", "csr",
    )),
    ("ownership", (
        "shareholding", "promoter", "pledge", "fii", "dii",
        "institutional holding", "stake",
    )),
    ("risk", (
        "risk factor", "risk", "exposure", "litigation",
        "contingent liability", "regulatory action",
    )),
    ("guidance", (
        "guidance", "outlook", "target", "forecast", "aspiration",
    )),
    ("narrative", (
        "management said", "management's view", "management view",
        "what did management", "commentary", "management commentary",
        "strategy", "said about", "view on", "management believes",
    )),
    ("financial_metric", (
        "revenue", "margin", "profit", "eps", "ebitda", "turnover",
        "net income", "growth rate", "debt", "earnings per share",
    )),
)

# One vocabulary (EvidenceKind), one mapping table -- the only place
# intent-to-doc-type knowledge lives. Weights are additive score boosts
# (retrieval.py's _rank_and_select), never filters: an intent with no
# entry here (or "general") simply applies no boost, and every candidate
# document stays fully eligible either way.
_INTENT_DOC_TYPES: dict[RetrievalIntent, tuple[tuple[str, int], ...]] = {
    "financial_metric": (
        ("financial_results", 60), ("annual_report", 40),
        ("investor_presentation", 20),
    ),
    "guidance": (
        ("earnings_transcript", 60), ("investor_presentation", 45),
        ("annual_report", 20),
    ),
    "risk": (
        ("annual_report", 60), ("brsr", 25), ("regulatory_filing", 20),
    ),
    "governance": (
        ("agm_notice", 55), ("board_outcome", 50),
        ("corporate_governance_report", 50), ("annual_report", 25),
    ),
    "capital_action": (
        ("board_outcome", 55), ("dividend", 50), ("buyback", 50),
        ("acquisition", 50),
    ),
    "esg": (
        ("brsr", 70), ("annual_report", 30),
    ),
    "ownership": (
        ("shareholding_pattern", 70), ("annual_report", 20),
    ),
    "narrative": (
        ("earnings_transcript", 55), ("annual_report", 35),
        ("investor_presentation", 25),
    ),
    "general": (),
}

# ---------------------------------------------------------------------------
# Period extraction -- fiscal-year / quarter phrases, the same vocabulary
# CompanyProfile snapshots already use for their `period` field (e.g.
# "FY2024", "Q3FY24"), so a plan's `periods` can be matched literally against
# window text without any further normalization at the retrieval side.
# ---------------------------------------------------------------------------
_RE_QUARTER_FY = re.compile(r"\bQ([1-4])\s?-?\s?FY\s?(\d{2,4})\b", re.IGNORECASE)
_RE_FY = re.compile(r"\bFY\s?(\d{2,4})\b", re.IGNORECASE)

# top_k broadening: an "enumerate everything" question needs more passages
# than a pointed lookup.
_BROADEN_WORDS = frozenset({"all", "every", "list", "various", "multiple"})

_DEFAULT_TOP_K = 5
_BROAD_TOP_K = 10
_NARROW_TOP_K = 3


def _normalize_year(raw: str) -> str:
    """"24" -> "2024"; "2024" stays "2024". Two-digit years assumed 20xx."""
    return f"20{raw}" if len(raw) == 2 else raw


def _extract_periods(question: str) -> tuple[str, ...]:
    periods: list[str] = []
    seen: set[str] = set()
    for match in _RE_QUARTER_FY.finditer(question):
        quarter, year = match.group(1), _normalize_year(match.group(2))
        canonical = f"Q{quarter}FY{year}"
        if canonical not in seen:
            seen.add(canonical)
            periods.append(canonical)
    # Plain "FY24" mentions not already captured as part of a quarter match.
    quarter_spans = {m.span() for m in _RE_QUARTER_FY.finditer(question)}
    for match in _RE_FY.finditer(question):
        if any(match.start() >= s and match.end() <= e for s, e in quarter_spans):
            continue
        canonical = f"FY{_normalize_year(match.group(1))}"
        if canonical not in seen:
            seen.add(canonical)
            periods.append(canonical)
    return tuple(periods)


class RetrievalPlanner(Protocol):
    """A pure function str -> SearchPlan. See module docstring for the
    boundary every implementation (heuristic today, LLM later) must honor.
    """

    def plan(self, question: str) -> SearchPlan: ...


class HeuristicPlanner:
    """M1.7's only planner: keyword/regex rules, no LLM, no KB, no I/O."""

    def plan(self, question: str) -> SearchPlan:
        decisions: list[PlanningDecision] = []

        query_words, query_numbers = _keywords(question)
        query_terms = tuple(sorted(query_words))
        numeric_terms = tuple(sorted(query_numbers))

        intent = self._classify_intent(question, decisions)
        preferred_doc_types = self._doc_type_preferences(intent, decisions)
        periods = _extract_periods(question)
        if periods:
            decisions.append(PlanningDecision(
                rule="period_extraction", input=question, output=", ".join(periods),
            ))
        top_k = self._top_k(question, intent, numeric_terms, query_terms, decisions)

        return SearchPlan(
            raw_question=question,
            intent=intent,
            query_terms=query_terms,
            numeric_terms=numeric_terms,
            preferred_doc_types=preferred_doc_types,
            periods=periods,
            top_k=top_k,
            rerank=RerankHints(),
            decisions=tuple(decisions),
        )

    # -- rules, one method each, so each is independently testable ---------

    def _classify_intent(
        self, question: str, decisions: list[PlanningDecision],
    ) -> RetrievalIntent:
        haystack = question.lower()
        for intent, markers in _INTENT_RULES:
            for marker in markers:
                if marker in haystack:
                    decisions.append(PlanningDecision(
                        rule="intent_keyword_match", input=marker, output=intent,
                    ))
                    return intent
        decisions.append(PlanningDecision(
            rule="intent_fallback", input=question, output="general",
        ))
        return "general"

    def _doc_type_preferences(
        self, intent: RetrievalIntent, decisions: list[PlanningDecision],
    ) -> tuple[DocTypePreference, ...]:
        entries = _INTENT_DOC_TYPES.get(intent, ())
        if entries:
            decisions.append(PlanningDecision(
                rule="doc_type_boost_from_intent", input=intent,
                output=", ".join(f"{kind}:{weight}" for kind, weight in entries),
            ))
        return tuple(DocTypePreference(kind=kind, weight=weight) for kind, weight in entries)

    def _top_k(
        self, question: str, intent: RetrievalIntent,
        numeric_terms: tuple[str, ...], query_terms: tuple[str, ...],
        decisions: list[PlanningDecision],
    ) -> int:
        words = set(question.lower().split())
        if words & _BROADEN_WORDS:
            decisions.append(PlanningDecision(
                rule="top_k_broaden_list_query",
                input=", ".join(sorted(words & _BROADEN_WORDS)),
                output=str(_BROAD_TOP_K),
            ))
            return _BROAD_TOP_K
        if intent == "financial_metric" and numeric_terms and len(query_terms) <= 3:
            decisions.append(PlanningDecision(
                rule="top_k_narrow_specific_metric",
                input=f"numeric_terms={len(numeric_terms)}, query_terms={len(query_terms)}",
                output=str(_NARROW_TOP_K),
            ))
            return _NARROW_TOP_K
        decisions.append(PlanningDecision(
            rule="top_k_default", input="", output=str(_DEFAULT_TOP_K),
        ))
        return _DEFAULT_TOP_K


def plan_retrieval(question: str) -> SearchPlan:
    """Convenience entry point: plan *question* with the default planner.

    CLI and eval call sites use this rather than constructing
    ``HeuristicPlanner`` themselves -- the one place that would need to
    change if the default planner implementation ever changes.
    """
    return HeuristicPlanner().plan(question)
