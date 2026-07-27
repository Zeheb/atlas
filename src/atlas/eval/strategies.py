"""Pluggable retrieval strategies for the eval harness (M1.8 commit 4, ADR-0004).

M1.8's objective is measuring whether retrieval planning helps — which means
a BASELINE and a PLANNED strategy must be comparable on equal footing, not
"one gets a SearchPlan and full diagnostics, the other gets a bare question
string and none." ``RetrievalStrategy`` is the seam: a strategy is anything
that maps a question to a ``SearchPlan`` (or withholds one). Both bundled
strategies below always produce a plan, so both get identical observability
(candidate counts, score breakdowns, metadata coverage) through the SAME
``retrieve_with_plan`` code path in ``retrieval.py``.

Adding a third strategy (hybrid retrieval, a reranked variant, an LLM planner)
means adding one class here and one entry in ``STRATEGIES`` — nothing in
``LiveReasoningRunner`` or the comparison engine needs to change.
"""

from __future__ import annotations

from typing import Protocol

from atlas.reasoning.plan import SearchPlan
from atlas.reasoning.planner import plan_retrieval
from atlas.reasoning.text import keywords as _keywords

# The default retrieve_passages()/pre-M1.7 top_k — kept identical so the
# baseline strategy's null plan is a fair stand-in for that code path.
_BASELINE_TOP_K = 5


class RetrievalStrategy(Protocol):
    """Produces (or withholds) a SearchPlan for one question. The eval
    harness's pluggability seam for retrieval strategies.
    """

    name: str

    def plan_for(self, question: str) -> SearchPlan | None: ...


class BaselineStrategy:
    """The M1.5/pre-M1.7 behavior, expressed AS a null plan rather than a
    ``plan=None`` special case with no diagnostics.

    Query/numeric terms come from ``reasoning.text.keywords`` — the exact
    same tokenizer ``retrieve_passages`` and ``retrieve_with_plan`` both call
    internally — so this plan's terms are byte-identical to what
    ``retrieve_passages`` would derive from the same question. No doc-type
    preferences, no date window, no periods, default (inert) RerankHints:
    every boost in ``_rank_and_select`` evaluates to 0, so the total score
    reduces to ``base * 100`` — order-identical to ``retrieve_passages``'s
    own ``base`` ranking. This equivalence is pinned by a mandatory test
    (``test_eval_strategies.py``), not assumed.
    """

    name = "baseline"

    def plan_for(self, question: str) -> SearchPlan:
        words, numbers = _keywords(question)
        return SearchPlan(
            raw_question=question,
            intent="general",
            query_terms=tuple(sorted(words)),
            numeric_terms=tuple(sorted(numbers)),
            top_k=_BASELINE_TOP_K,
        )


class PlannedStrategy:
    """M1.7's HeuristicPlanner, wrapped to satisfy RetrievalStrategy."""

    name = "planned"

    def plan_for(self, question: str) -> SearchPlan:
        return plan_retrieval(question)


STRATEGIES: dict[str, RetrievalStrategy] = {
    "baseline": BaselineStrategy(),
    "planned": PlannedStrategy(),
}
