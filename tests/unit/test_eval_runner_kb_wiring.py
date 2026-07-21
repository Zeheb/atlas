"""LiveReasoningRunner passes a KnowledgeBase through when present (M1 commit 5).

Activates the existing t43 (drilldown) case end-to-end: with a seeded profile
+ KB, the Answer returned by the runner carries a retrieved excerpt, exactly
as `atlas eval run --capabilities single_name,drilldown` would exercise it.
Existing eval tests (test_eval_runner_report.py, test_cli_eval.py) are
untouched and still pass with no KB present, confirming the kb=None fallback.
"""
from __future__ import annotations

import json
from pathlib import Path

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.config.settings import Settings
from atlas.eval.cases import CAP_DRILLDOWN, CAP_SINGLE_NAME, EvalCase
from atlas.eval.runner import LiveReasoningRunner
from atlas.reasoning.llm import FakeLLMClient

_SOURCE_TEXT = """
Financial Highlights

Operating margin for FY26 stood at 24.2%, driven by continued cost discipline.
"""


def _seed(base: Path, ticker: str = "TCS") -> None:
    profile = CompanyProfile(
        company_id=ticker,
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
        )]),
    )
    repo_root = base / ticker
    CompanyStore(repo_root / "profile.json", ticker).save(profile)

    from atlas.knowledge.base import KnowledgeBase

    rel = "ev-1.txt"
    (repo_root / rel).write_text(_SOURCE_TEXT, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1", source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value, title="Test filing",
        source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(repo_root).parse(entry)


def _case() -> EvalCase:
    return EvalCase(
        id="t43", category="I", question="Show me the evidence behind your conclusion.",
        subject="TCS", expected_behavior="answer", rubric="drilldown",
        requires=(CAP_DRILLDOWN,),
    )


def _fake_client() -> FakeLLMClient:
    return FakeLLMClient(response=json.dumps({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Operating margin has held near 24%.",
            "assertability": "judgment", "confidence": "high",
            "supporting_evidence_ids": ["ev-1"], "known_unknowns": [],
        }],
    }))


def test_live_runner_hydrates_excerpt_when_kb_present(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(settings, _fake_client())
    outcome = runner.run(_case())
    result, answer, context = outcome.result, outcome.answer, outcome.context

    assert not result.refused
    assert context.claims[0].evidence[0].excerpt is not None  # M1 hydration ran
    assert answer.citations[0].excerpt is not None            # carried into Answer
    assert "24.2" in answer.citations[0].excerpt


def test_drilldown_case_is_available_once_capability_is_present() -> None:
    case = _case()
    assert not case.is_available(frozenset({CAP_SINGLE_NAME}))       # pending pre-M1
    assert case.is_available(frozenset({CAP_SINGLE_NAME, CAP_DRILLDOWN}))  # active post-M1


def test_live_runner_falls_back_to_none_without_kb(tmp_path: Path) -> None:
    # Same seeding but WITHOUT the KB: mirrors pre-M1 behavior exactly.
    profile = CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
        )]),
    )
    CompanyStore(tmp_path / "TCS" / "profile.json", "TCS").save(profile)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(settings, _fake_client())
    outcome = runner.run(_case())
    answer, context = outcome.answer, outcome.context
    assert context.claims[0].evidence[0].excerpt is None
    assert answer.citations[0].excerpt is None
