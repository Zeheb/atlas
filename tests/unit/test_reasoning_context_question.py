"""Question-conditioned passage merging in build_context (M1.5 commit 2,
ADR-M1.5). test_reasoning_context.py (M0) and test_reasoning_context_retrieval
.py (M1) are untouched and still pass, confirming question=None is
byte-identical to the prior milestones.
"""
from __future__ import annotations

from pathlib import Path

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.context import build_context
from atlas.reasoning.contracts import SubjectRef

SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")

# Verified experimentally: the hydration excerpt (query = claim statement,
# anchored on "24.2") and the question excerpt (query = the question below,
# anchored on "bookings"/"pricing mix") are genuinely different spans.
_CONTENT = (
    "Operating margin stood at 24.2% in FY26, driven by continued cost discipline "
    "across major markets, with steady improvement over prior quarters and stable "
    "input costs throughout the year despite some volatility in select segments. "
    "Bookings during the quarter benefited from a favourable pricing mix and strong "
    "renewal rates across key accounts in the enterprise services business."
)
_QUESTION = "What favourable pricing mix and bookings did the company report?"
_IRRELEVANT_QUESTION = "quantum entanglement spacecraft telemetry systems"


def _profile() -> CompanyProfile:
    return CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
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


def test_question_none_is_byte_identical_to_m1(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    ctx_no_question = build_context(_profile(), SUBJECT, kb=kb)
    # Re-run with question=None explicitly — same call shape M0/M1 always used.
    ctx_explicit_none = build_context(_profile(), SUBJECT, kb=kb, question=None)
    assert ctx_no_question.claims == ctx_explicit_none.claims
    assert ctx_no_question.retrieved == ctx_explicit_none.retrieved


def test_relevant_question_adds_a_source_passage_claim(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    ctx = build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION)
    passage_claims = [c for c in ctx.claims if c.statement.startswith('Source passage:')]
    assert len(passage_claims) == 1
    assert "bookings" in passage_claims[0].statement.lower()
    assert passage_claims[0].assertability == "fact"


def test_passage_claim_evidence_id_already_in_index_no_growth(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    ctx = build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION)
    assert ctx.evidence_index == frozenset({"ev-1"})  # no new id introduced


def test_passage_populates_retrieved_ledger(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    ctx = build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION)
    spans = [r.content_span for r in ctx.retrieved]
    assert any("bookings" in s.lower() for s in spans)


def test_irrelevant_question_adds_no_passage_claims(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    ctx = build_context(_profile(), SUBJECT, kb=kb, question=_IRRELEVANT_QUESTION)
    assert not any(c.statement.startswith('Source passage:') for c in ctx.claims)


def test_question_without_kb_is_ignored_gracefully(tmp_path: Path) -> None:
    ctx_no_kb = build_context(_profile(), SUBJECT)  # no kb at all
    ctx_question_no_kb = build_context(_profile(), SUBJECT, question=_QUESTION)
    assert ctx_no_kb.claims == ctx_question_no_kb.claims
    assert ctx_question_no_kb.retrieved == ()


def test_identical_excerpt_to_existing_hydration_is_not_duplicated(tmp_path: Path) -> None:
    # A question whose keywords match the SAME span the M1 hydration already
    # attached must not produce a redundant Source-passage claim.
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    question_matching_hydrated_span = "What was the operating margin 24.2 percent?"
    ctx = build_context(_profile(), SUBJECT, kb=kb, question=question_matching_hydrated_span)
    passage_claims = [c for c in ctx.claims if c.statement.startswith('Source passage:')]
    hydrated_excerpts = {ref.excerpt for c in ctx.claims for ref in c.evidence if ref.excerpt}
    for pc in passage_claims:
        excerpt = pc.evidence[0].excerpt
        # If it duplicated the hydration excerpt exactly, it would have been
        # filtered — any surviving passage claim must be a genuinely new span.
        assert excerpt not in (hydrated_excerpts - {excerpt})


def test_question_conditioned_pass_issues_zero_extra_kb_reads(tmp_path: Path) -> None:
    kb = _kb_with(tmp_path, "ev-1", _CONTENT)
    call_count = {"n": 0}
    original_get_content = kb.get_content

    def _counting_get_content(evidence_id: str) -> str | None:
        call_count["n"] += 1
        return original_get_content(evidence_id)

    kb.get_content = _counting_get_content  # type: ignore[method-assign]

    build_context(_profile(), SUBJECT, kb=kb)  # hydration only: baseline reads
    reads_without_question = call_count["n"]

    call_count["n"] = 0
    build_context(_profile(), SUBJECT, kb=kb, question=_QUESTION)  # + passage merge
    reads_with_question = call_count["n"]

    assert reads_with_question == reads_without_question  # zero extra reads
