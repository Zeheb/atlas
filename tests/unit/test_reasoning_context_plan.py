"""SearchPlan threading through build_context (M1.7 commit 6).

test_reasoning_context.py (M0), test_reasoning_context_retrieval.py (M1), and
test_reasoning_context_question.py (M1.5) are untouched and still pass,
confirming plan=None is byte-identical to M1.5. This file covers what changes
when a plan IS supplied: ranking (never membership), the question/plan
agreement check, and the read-cost guarantees (one get_many call, zero extra
content reads).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.context import build_context
from atlas.reasoning.contracts import SubjectRef
from atlas.reasoning.plan import DocTypePreference, SearchPlan

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")

_CONTENT = (
    "Operating margin stood at 24.2% in FY26, driven by continued cost discipline "
    "across major markets, with steady improvement over prior quarters and stable "
    "input costs throughout the year despite some volatility in select segments. "
    "Bookings during the quarter benefited from a favourable pricing mix and strong "
    "renewal rates across key accounts in the enterprise services business."
)
_QUESTION = "What favourable pricing mix and bookings did the company report?"


def _profile(sources: list[str] | None = None) -> CompanyProfile:
    return CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=sources or ["ev-1"],
        )]),
    )


def _kb_with(
    tmp_path: Path, evidence_id: str, content: str,
    kind: EvidenceKind = EvidenceKind.FINANCIAL_RESULTS,
) -> KnowledgeBase:
    rel = f"{evidence_id}.txt"
    (tmp_path / rel).write_text(content, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id=evidence_id, source=EvidenceSource.BSE.value,
        kind=kind.value, title="Test filing",
        source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
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


# --- plan=None byte-identical to M1.5 -------------------------------------------
def test_plan_none_is_byte_identical_to_m15(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    ctx_question_only = build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION)
    ctx_explicit_none_plan = build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION, plan=None)
    assert ctx_question_only.claims == ctx_explicit_none_plan.claims
    assert ctx_question_only.retrieved == ctx_explicit_none_plan.retrieved
    assert ctx_question_only.budget_note == ctx_explicit_none_plan.budget_note


# --- plan may be given without question -----------------------------------------
def test_plan_alone_without_question_works(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    ctx = build_context(_profile(), SUBJECT, kb=kb, plan=_plan())
    passage_claims = [c for c in ctx.claims if c.statement.startswith("Source passage:")]
    assert len(passage_claims) == 1


# --- question/plan agreement -----------------------------------------------------
def test_mismatched_question_and_plan_raises(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    plan = _plan(raw_question="a completely different question")
    with pytest.raises(ValueError):
        build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION, plan=plan)


def test_matching_question_and_plan_is_accepted(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION, plan=_plan())  # must not raise


# --- Plan changes ranking, never membership --------------------------------------
def test_plan_doc_type_boost_changes_which_passage_is_kept(tmp_path: Path) -> None:
    # Two evidence docs with IDENTICAL content -- a doc-type-preferring plan
    # must select the preferred one; an unplanned merge falls back to the
    # deterministic doc_id tie-break.
    kb = KnowledgeBase(tmp_path)
    for evidence_id, kind in [
        ("ev-transcript", EvidenceKind.EARNINGS_TRANSCRIPT),
        ("ev-annual", EvidenceKind.ANNUAL_REPORT),
    ]:
        rel = f"{evidence_id}.txt"
        (tmp_path / rel).write_text(_CONTENT, encoding="utf-8")
        kb.parse(CatalogEntry(
            evidence_id=evidence_id, source=EvidenceSource.BSE.value, kind=kind.value,
            title="Test filing", source_date="2026-03-31T00:00:00+00:00", document_url=None,
            local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
        ))

    profile = _profile(sources=["ev-transcript", "ev-annual"])

    ctx_unplanned = build_context(profile, SUBJECT, kb=kb, question=_QUESTION)
    unplanned_ids = {
        ref.evidence_id for c in ctx_unplanned.claims
        if c.statement.startswith("Source passage:") for ref in c.evidence
    }

    plan = _plan(
        top_k=1,
        preferred_doc_types=(DocTypePreference(kind="earnings_transcript", weight=60),),
    )
    ctx_planned = build_context(profile, SUBJECT, kb=kb, question=_QUESTION, plan=plan)
    planned_ids = {
        ref.evidence_id for c in ctx_planned.claims
        if c.statement.startswith("Source passage:") for ref in c.evidence
    }
    assert "ev-transcript" in planned_ids
    assert planned_ids != unplanned_ids or unplanned_ids == {"ev-transcript"}


def test_plan_never_introduces_an_evidence_id_outside_profile_claims(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    plan = _plan(top_k=5)
    ctx = build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION, plan=plan)
    assert ctx.evidence_index == frozenset({"ev-1"})  # closed-world invariant holds


# --- budget_note is unaffected (it reaches the LLM prompt) -----------------------
def test_budget_note_unaffected_by_plan(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    ctx_no_plan = build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION)
    ctx_with_plan = build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION, plan=_plan())
    assert ctx_no_plan.budget_note == ctx_with_plan.budget_note


# --- Read-cost guarantees --------------------------------------------------------
def test_plan_adds_exactly_one_get_many_call(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    call_count = {"n": 0}
    original_get_many = kb.get_many

    def _counting_get_many(ids: object) -> dict:
        call_count["n"] += 1
        return original_get_many(ids)  # type: ignore[arg-type]

    kb.get_many = _counting_get_many  # type: ignore[method-assign]
    build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION, plan=_plan())
    assert call_count["n"] == 1


def test_plan_issues_zero_extra_content_reads_beyond_m15(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    call_count = {"n": 0}
    original_get_content = kb.get_content

    def _counting_get_content(evidence_id: str) -> str | None:
        call_count["n"] += 1
        return original_get_content(evidence_id)

    kb.get_content = _counting_get_content  # type: ignore[method-assign]

    build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION)  # M1.5 baseline
    reads_without_plan = call_count["n"]

    call_count["n"] = 0
    build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION, plan=_plan())
    reads_with_plan = call_count["n"]

    assert reads_with_plan == reads_without_plan
