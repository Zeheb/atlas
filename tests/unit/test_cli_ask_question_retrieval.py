"""`atlas ask --question-retrieval` CLI wiring (M1.5 commit 3, ADR-M1.5).

test_cli_ask.py (M0) and test_cli_ask_evidence.py (M1) are untouched and still
pass, confirming the flag defaults off and prior CLI behavior is unchanged.
Here we capture the FakeLLMClient instance the CLI constructs so we can
inspect the actual prompt sent to the model — proof the flag reaches
build_context and the question-conditioned passage reaches the prompt, not
just that the CLI doesn't crash.
"""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.cli import cli
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.knowledge.base import KnowledgeBase
from atlas.reasoning.client import FakeLLMClient

# Same verified-experimentally content as test_reasoning_context_question.py:
# the two anchors ("24.2" vs "bookings"/"pricing mix") produce distinct excerpts.
_CONTENT = (
    "Operating margin stood at 24.2% in FY26, driven by continued cost discipline "
    "across major markets, with steady improvement over prior quarters and stable "
    "input costs throughout the year despite some volatility in select segments. "
    "Bookings during the quarter benefited from a favourable pricing mix and strong "
    "renewal rates across key accounts in the enterprise services business."
)
_QUESTION = "What favourable pricing mix and bookings did the company report?"

_RESPONSE = json.dumps({
    "refused": False, "overall_confidence": "high",
    "findings": [{
        "statement": "Operating margin has held near 24%.",
        "assertability": "judgment", "confidence": "high",
        "supporting_evidence_ids": ["ev-1"], "known_unknowns": [],
    }],
})


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

    rel = "ev-1.txt"
    (repo_root / rel).write_text(_CONTENT, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1", source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value, title="Test filing",
        source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(repo_root).parse(entry)


def _run_and_capture_fake(monkeypatch, tmp_path: Path, args: list[str]) -> tuple[object, FakeLLMClient]:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    fake = FakeLLMClient(response=_RESPONSE)
    monkeypatch.setattr(
        "atlas.reasoning.client.AnthropicClient.from_settings",
        classmethod(lambda cls, settings: fake),
    )
    _seed(tmp_path)
    result = CliRunner().invoke(cli, args)
    return result, fake


def test_question_retrieval_flag_merges_passage_into_prompt(monkeypatch, tmp_path: Path) -> None:
    result, fake = _run_and_capture_fake(
        monkeypatch, tmp_path, ["ask", "TCS", _QUESTION, "--question-retrieval"],
    )
    assert result.exit_code == 0, result.output
    _system, user_prompt = fake.calls[0]
    assert "Source passage:" in user_prompt
    assert "bookings" in user_prompt.lower()


def test_without_flag_no_source_passage_in_prompt(monkeypatch, tmp_path: Path) -> None:
    result, fake = _run_and_capture_fake(monkeypatch, tmp_path, ["ask", "TCS", _QUESTION])
    assert result.exit_code == 0, result.output
    _system, user_prompt = fake.calls[0]
    assert "Source passage:" not in user_prompt


def test_flag_combines_with_show_evidence(monkeypatch, tmp_path: Path) -> None:
    result, _fake = _run_and_capture_fake(
        monkeypatch, tmp_path,
        ["ask", "TCS", _QUESTION, "--question-retrieval", "--show-evidence"],
    )
    assert result.exit_code == 0, result.output
