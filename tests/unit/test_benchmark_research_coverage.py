"""The M2.2.5 anti-checklist gate (commit 5).

The gate's whole purpose is to fail a planner that looks fine case-by-case,
so the important tests here are the ones that construct deliberately
degenerate planners and assert they are REJECTED. A gate never shown to fail
is not a gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas.benchmark.coverage import analyze_research_plans
from atlas.research.plan import Investigation, ResearchDecision, ResearchPlan
from atlas.research.planner import ALL_RESEARCH_RULE_IDS, plan_research

_ALL_NINE = (
    "what_changed",
    "business_quality",
    "management_credibility",
    "balance_sheet",
    "valuation",
    "risks",
    "catalysts",
    "competitive_position",
    "esg_governance",
)


@dataclass(frozen=True)
class _FakePlan:
    """A stand-in satisfying ResearchPlanLike structurally -- proof the
    analyzer needs no concrete research type (and that plans wider than
    ResearchPlan's own MAX_INVESTIGATIONS cap can still be measured).
    """

    intent: str
    dimensions: tuple[str, ...]
    decisions: tuple[ResearchDecision, ...] = ()


def _real_plans() -> list[ResearchPlan]:
    return [
        plan_research(q, s)
        for q, s in (
            ("Should I invest in TCS?", ("TCS",)),
            ("What are the key risks to SBI?", ("SBIN",)),
            ("Compare Tata Steel with JSW Steel.", ("TATASTEEL", "JSWSTEEL")),
            ("How exposed is TCS to input costs?", ("TCS",)),
            ("What was the FY24 dividend?", ("TCS",)),
            ("What are the margins?", ("TATASTEEL", "JSWSTEEL")),
            ("Compare TCS against its peers.", ("TCS",)),
        )
    ]


# --- THE GATE: the real planner must pass -------------------------------------------
def test_real_planner_is_not_a_checklist() -> None:
    coverage = analyze_research_plans(_real_plans())
    assert not coverage.is_checklist, coverage.checklist_reasons


def test_real_planner_produces_several_distinct_dimension_sets() -> None:
    coverage = analyze_research_plans(_real_plans())
    assert coverage.distinct_dimension_sets >= 4


def test_real_planner_stays_well_under_full_vocabulary_width() -> None:
    coverage = analyze_research_plans(_real_plans())
    assert coverage.mean_plan_width < coverage.vocabulary_size * 0.9


def test_real_planner_fires_every_declared_rule_over_a_wide_question_set() -> None:
    coverage = analyze_research_plans(_real_plans())
    assert coverage.dead_rules == (), f"dead research rules: {coverage.dead_rules}"


# --- THE GATE: degenerate planners must FAIL ------------------------------------------
def test_constant_planner_is_rejected() -> None:
    """A planner emitting the same dimensions for every question passes every
    single-plan test and is still worthless.
    """
    identical = [
        _FakePlan(intent="invest_decision", dimensions=("risks", "valuation"))
        for _ in range(6)
    ]
    coverage = analyze_research_plans(identical)

    assert coverage.is_checklist
    assert coverage.distinct_dimension_sets == 1
    assert any("constant function" in r for r in coverage.checklist_reasons)


def test_everything_planner_is_rejected_even_when_ordering_varies() -> None:
    """The subtle failure: emit all nine dimensions every time but shuffle the
    order. Dimension-level entropy would call this maximally diverse; the
    width check catches it.
    """
    rotated = [
        _FakePlan(intent="invest_decision", dimensions=_ALL_NINE[i:] + _ALL_NINE[:i])
        for i in range(6)
    ]
    coverage = analyze_research_plans(rotated)

    assert coverage.distinct_dimension_sets == 6  # "diverse" by set identity
    assert coverage.set_entropy == 1.0  # and by evenness
    assert coverage.is_checklist  # but still a checklist
    assert any("nearly" in r and "everything" in r for r in coverage.checklist_reasons)


def test_no_plans_is_unmeasured_not_passing() -> None:
    """An empty analysis must not silently report a healthy planner."""
    coverage = analyze_research_plans([])

    assert coverage.is_checklist
    assert coverage.plans_analyzed == 0
    assert any("unmeasured, not proven" in r for r in coverage.checklist_reasons)
    assert set(coverage.dead_rules) == ALL_RESEARCH_RULE_IDS


# --- Descriptive statistics --------------------------------------------------------
def test_dimension_and_intent_counts_are_reported() -> None:
    coverage = analyze_research_plans(_real_plans())

    dims = dict(coverage.dimension_counts)
    intents = dict(coverage.intent_counts)
    assert dims["risks"] > 0
    assert intents["invest_decision"] == 1
    assert intents["comparison"] == 3  # two explicit + one forced by 2 subjects


def test_dead_rules_are_detected_on_a_narrow_question_set() -> None:
    """One question exercises few rules; the analyzer must say so rather than
    reporting a clean bill of health.
    """
    coverage = analyze_research_plans(
        [plan_research("Should I invest in TCS?", ("TCS",))]
    )
    assert coverage.dead_rules  # most rules never fired on a single question


def test_analyzer_accepts_structural_plans_without_importing_them() -> None:
    coverage = analyze_research_plans(
        [
            _FakePlan(
                intent="a",
                dimensions=("risks",),
                decisions=(ResearchDecision(rule="r", input="i", output="o"),),
            ),
            _FakePlan(intent="b", dimensions=("valuation", "risks")),
        ]
    )
    assert coverage.plans_analyzed == 2
    assert coverage.distinct_dimension_sets == 2


def test_max_plan_width_is_reported() -> None:
    coverage = analyze_research_plans(
        [
            _FakePlan(intent="a", dimensions=("risks",)),
            _FakePlan(intent="b", dimensions=("risks", "valuation", "catalysts")),
        ]
    )
    assert coverage.max_plan_width == 3
    assert coverage.mean_plan_width == 2.0


def test_real_plan_satisfies_the_structural_protocol() -> None:
    """ResearchPlan must actually satisfy ResearchPlanLike -- otherwise the
    decoupling is theoretical.
    """
    plan = ResearchPlan(
        raw_question="Should I invest in TCS?",
        intent="invest_decision",
        subjects=("TCS",),
        investigations=(
            Investigation(
                dimension="risks",
                question="What risks are disclosed?",
                subjects=("TCS",),
                rationale="the downside bounds the thesis",
                priority=5,
            ),
        ),
    )
    coverage = analyze_research_plans([plan])
    assert coverage.plans_analyzed == 1
    assert coverage.dimension_counts == (("risks", 1),)
