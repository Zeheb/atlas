"""RetrievalStrategy protocol and registry (M1.8 commit 4, ADR-0004).

The mandatory equivalence test here is the load-bearing proof behind the
M1.8 design's baseline-as-null-plan approach: eval's "baseline" measures
retrieve_with_plan() (for symmetric diagnostics with the "planned" strategy),
while production build_context(plan=None) calls retrieve_passages(). If these
two ever diverge, the baseline measurement is invalid -- so this test pins
byte-identical output across the golden-corpus-shaped fixtures used elsewhere
in this test suite, and must be re-verified whenever either function changes.
"""

from __future__ import annotations

from pathlib import Path

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.eval.strategies import STRATEGIES, BaselineStrategy, PlannedStrategy
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.plan import SearchPlan
from atlas.reasoning.retrieval import retrieve_passages, retrieve_with_plan

_MARGIN_TEXT = "Operating margin stood at 24.2% in FY26, an improvement over last year."
_RISK_TEXT = "Currency fluctuation risk affects our overseas operations significantly."
_IRRELEVANT_TEXT = "The quarterly board meeting discussed general governance policies."
_NARRATIVE_TEXT = (
    "Management said bookings benefited from a favourable pricing mix this quarter."
)

_QUESTIONS = [
    "What was the operating margin 24.2 and the currency fluctuation risk?",
    "What did management say about margins?",
    "What was the reported revenue for FY2024?",
    "quantum entanglement spacecraft telemetry",  # irrelevant -- no candidates clear the bar
]


def _kb_with_docs(tmp_path: Path, docs: dict[str, str]) -> KnowledgeBase:
    kb = KnowledgeBase(tmp_path)
    for evidence_id, content in docs.items():
        rel = f"{evidence_id}.txt"
        (tmp_path / rel).write_text(content, encoding="utf-8")
        entry = CatalogEntry(
            evidence_id=evidence_id,
            source=EvidenceSource.BSE.value,
            kind=EvidenceKind.ANNUAL_REPORT.value,
            title="Test doc",
            source_date="2026-03-31T00:00:00+00:00",
            document_url=None,
            local_path=rel,
            file_size_bytes=None,
            acquired_at="2026-04-01T00:00:00+00:00",
        )
        kb.parse(entry)
    return kb


# --- Mandatory equivalence: baseline null plan == retrieve_passages -------------
def test_baseline_null_plan_matches_retrieve_passages_exactly(tmp_path: Path) -> None:
    kb = _kb_with_docs(
        tmp_path,
        {
            "ev-1": _MARGIN_TEXT,
            "ev-2": _RISK_TEXT,
            "ev-3": _IRRELEVANT_TEXT,
            "ev-4": _NARRATIVE_TEXT,
        },
    )
    doc_ids = ["ev-1", "ev-2", "ev-3", "ev-4"]
    strategy = BaselineStrategy()
    for question in _QUESTIONS:
        plan = strategy.plan_for(question)
        assert plan.top_k == 5  # retrieve_passages's own default k
        planned = retrieve_with_plan(kb, doc_ids, plan).matches
        baseline = retrieve_passages(kb, doc_ids, question, k=plan.top_k)
        assert list(planned) == baseline, f"mismatch for question: {question!r}"


def test_baseline_null_plan_matches_across_shuffled_doc_ids(tmp_path: Path) -> None:
    kb = _kb_with_docs(tmp_path, {"ev-1": _MARGIN_TEXT, "ev-2": _RISK_TEXT})
    strategy = BaselineStrategy()
    question = _QUESTIONS[0]
    plan = strategy.plan_for(question)
    planned = retrieve_with_plan(kb, ["ev-2", "ev-1"], plan).matches
    baseline = retrieve_passages(kb, ["ev-2", "ev-1"], question, k=plan.top_k)
    assert list(planned) == baseline


def test_baseline_null_plan_has_no_preferences(tmp_path: Path) -> None:
    plan = BaselineStrategy().plan_for("any question")
    assert plan.preferred_doc_types == ()
    assert plan.date_window is None
    assert plan.periods == ()
    assert plan.rerank.prefer_recent is False
    assert plan.rerank.prefer_numeric is False
    assert plan.rerank.max_per_document is None


def test_baseline_query_terms_match_retrieve_passages_tokenizer(tmp_path: Path) -> None:
    # The null plan's query_terms/numeric_terms must be exactly what
    # retrieve_passages derives internally -- same tokenizer, no extra filtering.
    from atlas.reasoning.text import keywords

    question = "What was the operating margin 24.2 and the currency risk?"
    plan = BaselineStrategy().plan_for(question)
    words, numbers = keywords(question)
    assert frozenset(plan.query_terms) == words
    assert frozenset(plan.numeric_terms) == numbers


# --- PlannedStrategy -------------------------------------------------------------
def test_planned_strategy_uses_heuristic_planner() -> None:
    plan = PlannedStrategy().plan_for("What did management say about margins?")
    assert isinstance(plan, SearchPlan)
    assert plan.intent == "narrative"  # HeuristicPlanner's own calibrated behavior


def test_planned_strategy_produces_doc_type_preferences() -> None:
    plan = PlannedStrategy().plan_for("What are the key risk factors disclosed?")
    assert (
        plan.preferred_doc_types
    )  # unlike the baseline, planned expresses a preference


# --- Registry ---------------------------------------------------------------------
def test_registry_contains_both_bundled_strategies() -> None:
    assert set(STRATEGIES) == {"baseline", "planned"}
    assert isinstance(STRATEGIES["baseline"], BaselineStrategy)
    assert isinstance(STRATEGIES["planned"], PlannedStrategy)


def test_strategy_name_attribute_matches_registry_key() -> None:
    for key, strategy in STRATEGIES.items():
        assert strategy.name == key
