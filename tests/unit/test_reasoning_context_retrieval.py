"""GroundingContext raw-text hydration via a KnowledgeBase (M1 commit 2).

build_context(kb=None) must remain byte-identical to M0 (covered by the
existing test_reasoning_context.py, untouched). These tests cover the new
kb-aware path only, against a real, hermetic KnowledgeBase.
"""
from __future__ import annotations

from pathlib import Path

import atlas.reasoning.context as context_mod
from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.context import build_context
from atlas.reasoning.contracts import SubjectRef

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")

_MATCHING_TEXT = """
Financial Highlights

Operating margin for FY26 stood at 24.2%, driven by continued cost
discipline across major markets.
"""

_IRRELEVANT_TEXT = "This document discusses an unrelated corporate matter entirely."


def _profile(evidence_id: str = "ev-1") -> CompanyProfile:
    return CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2},
            sources=[evidence_id],
        )]),
    )


def _kb_with(tmp_path: Path, evidence_id: str, content: str) -> KnowledgeBase:
    rel = f"{evidence_id}.txt"
    (tmp_path / rel).write_text(content, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id=evidence_id, source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value, title="Test filing",
        source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
    )
    kb = KnowledgeBase(tmp_path)
    kb.parse(entry)
    return kb


def test_hydrates_excerpt_when_kb_has_matching_content(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _MATCHING_TEXT)
    ctx = build_context(_profile(), SUBJECT, kb=kb)
    claim = ctx.claims[0]
    assert claim.evidence[0].excerpt is not None
    assert "24.2" in claim.evidence[0].excerpt


def test_populates_retrieved_ledger(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _MATCHING_TEXT)
    ctx = build_context(_profile(), SUBJECT, kb=kb)
    assert len(ctx.retrieved) == 1
    assert ctx.retrieved[0].evidence_ref.evidence_id == "ev-1"
    assert "24.2" in ctx.retrieved[0].content_span


def test_evidence_index_unchanged_by_hydration(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _MATCHING_TEXT)
    ctx = build_context(_profile(), SUBJECT, kb=kb)
    assert ctx.evidence_index == frozenset({"ev-1"})  # no new ids introduced


def test_no_confident_match_leaves_reference_bare(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _IRRELEVANT_TEXT)
    ctx = build_context(_profile(), SUBJECT, kb=kb)
    claim = ctx.claims[0]
    assert claim.evidence[0].excerpt is None
    assert ctx.retrieved == ()


def test_kb_none_matches_m0_behavior_exactly(tmp_path: Path) -> None:
    ctx = build_context(_profile(), SUBJECT)  # kb omitted, as in M0
    assert ctx.claims[0].evidence[0].excerpt is None
    assert ctx.retrieved == ()
    assert ctx.budget_note is None


def test_missing_document_content_is_graceful(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path)  # empty KB, ev-1 never parsed
    ctx = build_context(_profile(), SUBJECT, kb=kb)
    assert ctx.claims[0].evidence[0].excerpt is None


def test_doc_cap_records_budget_note(tmp_path: Path, monkeypatch) -> None:
    kb = _kb_with(tmp_path, "ev-1", _MATCHING_TEXT)
    monkeypatch.setattr(context_mod, "_MAX_HYDRATED_DOCS", 0)
    ctx = build_context(_profile(), SUBJECT, kb=kb)
    assert ctx.claims[0].evidence[0].excerpt is None  # capped before any fetch
    assert ctx.budget_note is not None
    assert "Retrieval limited" in ctx.budget_note
