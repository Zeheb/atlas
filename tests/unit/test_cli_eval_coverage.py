"""`atlas eval coverage` / `atlas eval validate-cases` CLI (M1.8.5 commit 5,
ADR-0005). Both read-only, no LLM client ever built.
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


def _seed(base: Path, subject: str = "TCS") -> None:
    profile = CompanyProfile(
        company_id=subject,
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
        )]),
    )
    root = base / subject
    CompanyStore(root / "profile.json", subject).save(profile)
    rel = "ev-1.txt"
    (root / rel).write_text("Operating margin stood at 24.2%.", encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1", source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value, title="Test filing",
        source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(root).parse(entry)


def _suite(path: Path, extra: list[dict] | None = None) -> Path:
    cases = [
        {"id": "t01", "category": "A", "question": "How stable are margins?",
         "subject": "TCS", "expected_behavior": "answer", "rubric": "synthesize"},
    ] + (extra or [])
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


# --- eval coverage ------------------------------------------------------------------
def test_coverage_summary_prints_no_llm_client_needed(monkeypatch, tmp_path) -> None:
    def _exploding(*a, **k):
        raise AssertionError("build_llm_client must never be called by `eval coverage`")
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setattr("atlas.reasoning.llm.build_llm_client", _exploding)
    _seed(tmp_path)
    suite = _suite(tmp_path / "suite.json")

    result = CliRunner().invoke(cli, ["eval", "coverage", "--suite", str(suite)])
    assert result.exit_code == 0, result.output
    assert "Benchmark coverage: 1 cases" in result.output
    assert "structurally dead doc types" in result.output


def test_coverage_json_format_is_valid_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    _seed(tmp_path)
    suite = _suite(tmp_path / "suite.json")

    result = CliRunner().invoke(cli, ["eval", "coverage", "--suite", str(suite), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "suite" in payload and "corpus" in payload
    assert payload["suite"]["total_cases"] == 1


def test_coverage_out_writes_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    _seed(tmp_path)
    suite = _suite(tmp_path / "suite.json")
    out = tmp_path / "coverage.json"

    result = CliRunner().invoke(cli, ["eval", "coverage", "--suite", str(suite), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["suite"]["total_cases"] == 1


def test_coverage_unknown_suite_errors_cleanly(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    result = CliRunner().invoke(cli, ["eval", "coverage", "--suite", "not-a-real-file.json"])
    assert result.exit_code == 1
    assert "Unknown suite" in result.output


# --- eval validate-cases -------------------------------------------------------------
def test_validate_cases_passes_when_no_case_has_provenance(monkeypatch, tmp_path) -> None:
    def _exploding(*a, **k):
        raise AssertionError("build_llm_client must never be called by `eval validate-cases`")
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setattr("atlas.reasoning.llm.build_llm_client", _exploding)
    _seed(tmp_path)
    suite = _suite(tmp_path / "suite.json")

    result = CliRunner().invoke(cli, ["eval", "validate-cases", "--suite", str(suite)])
    assert result.exit_code == 0, result.output
    assert "PASSED" in result.output


def test_validate_cases_fails_on_broken_provenance(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    _seed(tmp_path)
    suite = _suite(tmp_path / "suite.json", extra=[{
        "id": "t02", "category": "A", "question": "q", "subject": "TCS",
        "expected_behavior": "answer", "rubric": "r",
        "provenance": {
            "origin": "corpus_derived", "supporting_evidence_ids": ["ev-ghost"],
            "verification_method": "m", "verified_at": "2026-07-21", "verified_by": "z",
        },
    }])

    result = CliRunner().invoke(cli, ["eval", "validate-cases", "--suite", str(suite)])
    assert result.exit_code == 1
    assert "FAILED" in result.output
    assert "t02" in result.output
    assert "missing_evidence" in result.output


def test_validate_cases_passes_on_valid_provenance(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    _seed(tmp_path)
    suite = _suite(tmp_path / "suite.json", extra=[{
        "id": "t02", "category": "A", "question": "q", "subject": "TCS",
        "expected_behavior": "answer", "rubric": "r",
        "provenance": {
            "origin": "corpus_derived", "supporting_evidence_ids": ["ev-1"],
            "verification_method": "m", "verified_at": "2026-07-21", "verified_by": "z",
        },
    }])

    result = CliRunner().invoke(cli, ["eval", "validate-cases", "--suite", str(suite)])
    assert result.exit_code == 0, result.output
    assert "PASSED" in result.output
