"""build_context_with_diagnostics / ContextBuildResult (M1.8 commit 2, ADR-0004).

build_context() is now a thin delegate over build_context_with_diagnostics();
this file proves the delegation is exact (same GroundingContext, for every
argument combination already covered by test_reasoning_context.py (M0),
test_reasoning_context_retrieval.py (M1), test_reasoning_context_question.py
(M1.5), and test_reasoning_context_plan.py (M1.7) — none of which needed to
change), and that the diagnostics variant surfaces a RetrievalResult exactly
when a plan produced one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.context import (
    ContextBuildResult,
    build_context,
    build_context_with_diagnostics,
)
from atlas.reasoning.contracts import SubjectRef
from atlas.reasoning.plan import SearchPlan
from atlas.reasoning.retrieval import RetrievalResult

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")

_CONTENT = (
    "Operating margin stood at 24.2% in FY26, driven by continued cost discipline "
    "across major markets, with steady improvement over prior quarters and stable "
    "input costs throughout the year despite some volatility in select segments. "
    "Bookings during the quarter benefited from a favourable pricing mix and strong "
    "renewal rates across key accounts in the enterprise services business."
)
_QUESTION = "What favourable pricing mix and bookings did the company report?"


def _profile() -> CompanyProfile:
    return CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(
            snapshots=[
                FinancialSnapshot(
                    period="2026-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2},
                    sources=["ev-1"],
                )
            ]
        ),
    )


def _kb_with(tmp_path: Path, evidence_id: str, content: str) -> KnowledgeBase:
    rel = f"{evidence_id}.txt"
    (tmp_path / rel).write_text(content, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id=evidence_id,
        source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value,
        title="Test filing",
        source_date="2026-03-31T00:00:00+00:00",
        document_url=None,
        local_path=rel,
        file_size_bytes=None,
        acquired_at="2026-04-01T00:00:00+00:00",
    )
    kb = KnowledgeBase(tmp_path)
    kb.parse(entry)
    return kb


def _plan(**overrides: object) -> SearchPlan:
    defaults: dict[str, object] = dict(
        raw_question=_QUESTION,
        intent="general",
        query_terms=("favourable", "pricing", "mix", "bookings", "company", "report"),
        top_k=5,
    )
    defaults.update(overrides)
    return SearchPlan(**defaults)  # type: ignore[arg-type]


# --- Delegation is exact, across every argument combination -------------------
def test_no_kb_no_question_delegation_matches() -> None:
    direct = build_context(_profile(), SUBJECT)
    via_diagnostics = build_context_with_diagnostics(_profile(), SUBJECT)
    assert direct == via_diagnostics.context


def test_kb_hydration_only_delegation_matches(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    direct = build_context(_profile(), SUBJECT, kb=kb)
    via_diagnostics = build_context_with_diagnostics(_profile(), SUBJECT, kb=kb)
    assert direct == via_diagnostics.context


def test_question_conditioned_delegation_matches(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    direct = build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION)
    via_diagnostics = build_context_with_diagnostics(
        _profile(), SUBJECT, kb=kb, question=_QUESTION
    )
    assert direct == via_diagnostics.context


def test_plan_conditioned_delegation_matches(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    plan = _plan()
    direct = build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION, plan=plan)
    via_diagnostics = build_context_with_diagnostics(
        _profile(),
        SUBJECT,
        kb=kb,
        question=_QUESTION,
        plan=plan,
    )
    assert direct == via_diagnostics.context


def test_known_ids_filter_delegation_matches() -> None:
    direct = build_context(_profile(), SUBJECT, known_ids={"ev-1"})
    via_diagnostics = build_context_with_diagnostics(
        _profile(), SUBJECT, known_ids={"ev-1"}
    )
    assert direct == via_diagnostics.context


# --- Diagnostics surface exactly when a plan produced them ---------------------
def test_retrieval_is_none_without_kb() -> None:
    result = build_context_with_diagnostics(_profile(), SUBJECT)
    assert isinstance(result, ContextBuildResult)
    assert result.retrieval is None


def test_retrieval_is_none_without_question_or_plan(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    result = build_context_with_diagnostics(_profile(), SUBJECT, kb=kb)
    assert result.retrieval is None


def test_retrieval_is_none_with_question_but_no_plan(tmp_path: Path) -> None:
    # retrieve_passages (the M1.5 path) has no RetrievalResult to surface.
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    result = build_context_with_diagnostics(
        _profile(), SUBJECT, kb=kb, question=_QUESTION
    )
    assert result.retrieval is None


def test_retrieval_result_present_when_plan_given(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    plan = _plan()
    result = build_context_with_diagnostics(
        _profile(), SUBJECT, kb=kb, question=_QUESTION, plan=plan
    )
    assert isinstance(result.retrieval, RetrievalResult)
    assert result.retrieval.plan is plan


def test_retrieval_result_matches_reflected_in_context_claims(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    plan = _plan()
    result = build_context_with_diagnostics(
        _profile(), SUBJECT, kb=kb, question=_QUESTION, plan=plan
    )
    assert result.retrieval is not None
    passage_claims = [
        c for c in result.context.claims if c.statement.startswith("Source passage:")
    ]
    assert len(result.retrieval.matches) == len(passage_claims)


def test_context_build_result_is_frozen() -> None:
    result = build_context_with_diagnostics(_profile(), SUBJECT)
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        result.retrieval = None  # type: ignore[misc]
