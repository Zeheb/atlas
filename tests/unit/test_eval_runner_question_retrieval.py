"""LiveReasoningRunner + CAP_QUESTION_RETRIEVAL wiring (M1.5 commit 3, ADR-M1.5).

test_eval_runner_kb_wiring.py (M1) is untouched and still passes, confirming
LiveReasoningRunner's default capabilities=frozenset() reproduces M1 exactly
(question never passed to build_context).
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
from atlas.eval.cases import CAP_QUESTION_RETRIEVAL, EvalCase, load_cases
from atlas.eval.runner import LiveReasoningRunner
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.client import FakeLLMClient

_CONTENT = (
    "Operating margin stood at 24.2% in FY26, driven by continued cost discipline "
    "across major markets, with steady improvement over prior quarters and stable "
    "input costs throughout the year despite some volatility in select segments. "
    "Bookings during the quarter benefited from a favourable pricing mix and strong "
    "renewal rates across key accounts in the enterprise services business."
)
_QUESTION = "What favourable pricing mix and bookings did the company report?"


def _seed(tmp_path: Path) -> None:
    profile = CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
        )]),
    )
    repo_root = tmp_path / "TCS"
    CompanyStore(repo_root / "profile.json", "TCS").save(profile)
    rel = "ev-1.txt"
    (repo_root / rel).write_text(_CONTENT, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1", source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value, title="Test filing",
        source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(repo_root).parse(entry)


def _case() -> EvalCase:
    return EvalCase(
        id="qr-test", category="A", question=_QUESTION, subject="TCS",
        expected_behavior="answer", rubric="question-conditioned retrieval",
    )


def _fake_client() -> FakeLLMClient:
    return FakeLLMClient(response=json.dumps({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Bookings benefited from a favourable pricing mix.",
            "assertability": "judgment", "confidence": "high",
            "supporting_evidence_ids": ["ev-1"], "known_unknowns": [],
        }],
    }))


def test_capability_present_forwards_question(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(
        settings, _fake_client(), capabilities=frozenset({CAP_QUESTION_RETRIEVAL}),
    )
    _result, _answer, context = runner.run(_case())
    passage_claims = [c for c in context.claims if c.statement.startswith('Source passage:')]
    assert len(passage_claims) == 1
    assert "bookings" in passage_claims[0].statement.lower()


def test_capability_absent_by_default_matches_m1(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(settings, _fake_client())  # no capabilities kwarg
    _result, _answer, context = runner.run(_case())
    assert not any(c.statement.startswith('Source passage:') for c in context.claims)


def test_other_capabilities_present_without_question_retrieval_no_effect(tmp_path: Path) -> None:
    _seed(tmp_path)
    settings = Settings(_env_file=None, repository_base_path=tmp_path)
    runner = LiveReasoningRunner(
        settings, _fake_client(), capabilities=frozenset({"single_name", "drilldown"}),
    )
    _result, _answer, context = runner.run(_case())
    assert not any(c.statement.startswith('Source passage:') for c in context.claims)


def test_no_bundled_case_requires_question_retrieval_it_is_a_runner_mode_switch() -> None:
    # Protects the design intent: this capability must never gate a case's
    # availability — it only toggles LiveReasoningRunner's internal behavior.
    for case in load_cases():
        assert CAP_QUESTION_RETRIEVAL not in case.requires
