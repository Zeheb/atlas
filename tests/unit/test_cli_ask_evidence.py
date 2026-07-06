"""`atlas ask --show-evidence` with a real, hermetic KnowledgeBase (M1 commit 4).

test_cli_ask.py (M0) is untouched and still passes with no knowledge.db
present, confirming the CLI's kb=None fallback path is unchanged.
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

    rel = "ev-1.txt"
    (repo_root / rel).write_text(_SOURCE_TEXT, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1", source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value, title="Test filing",
        source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(repo_root).parse(entry)


def _run(monkeypatch, tmp_path, response: str, args: list[str]):
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: FakeLLMClient(response=response),
    )
    _seed(tmp_path)
    return CliRunner().invoke(cli, args)


def _response() -> str:
    return json.dumps({
        "refused": False, "overall_confidence": "high",
        "findings": [{
            "statement": "Operating margin has held near 24%.",
            "assertability": "judgment", "confidence": "high",
            "supporting_evidence_ids": ["ev-1"], "known_unknowns": [],
        }],
    })


def test_show_evidence_flag_prints_retrieved_excerpt(monkeypatch, tmp_path) -> None:
    result = _run(monkeypatch, tmp_path, _response(),
                  ["ask", "TCS", "How are margins?", "--show-evidence"])
    assert result.exit_code == 0, result.output
    assert "Operating margin for FY26 stood at 24.2%" in result.output
    assert "Financial Highlights" in result.output


def test_without_show_evidence_excerpt_is_not_printed(monkeypatch, tmp_path) -> None:
    result = _run(monkeypatch, tmp_path, _response(), ["ask", "TCS", "How are margins?"])
    assert result.exit_code == 0, result.output
    assert "Operating margin for FY26 stood at 24.2%" not in result.output
    assert "ev-1" in result.output  # bare id still shown
