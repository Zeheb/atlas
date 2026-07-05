"""`atlas eval run` / `atlas eval compare` CLI (eval commit 5).

Offline: a branching fake stands in for the Anthropic client, returning
reasoning JSON to the reasoning pass and score JSON to the judge (it branches on
the system prompt). A synthetic TCS profile and a 1-case suite keep it fast.
"""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from atlas.analysis.base import FactKind
from atlas.cli import cli
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.eval.judge import JUDGE_SYSTEM_PROMPT


class _BranchingFake:
    """Reasoning JSON for the reasoning pass; score JSON for the judge."""

    def complete(self, *, system: str, user: str) -> str:
        if system == JUDGE_SYSTEM_PROMPT:
            return json.dumps(
                {"reasoning_quality": 4, "usefulness": 4, "evidence_use": 4, "notes": "ok"}
            )
        return json.dumps({
            "refused": False, "overall_confidence": "high",
            "findings": [{
                "statement": "Operating margin ~24%.", "assertability": "judgment",
                "confidence": "high", "supporting_evidence_ids": ["ev-1"],
                "known_unknowns": [],
            }],
        })


def _seed(base: Path) -> None:
    profile = CompanyProfile(
        company_id="TCS",
        financial=FinancialTimeSeries(snapshots=[FinancialSnapshot(
            period="2026-03-31", period_type="annual", basis="consolidated",
            facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2}, sources=["ev-1"],
        )]),
    )
    CompanyStore(base / "TCS" / "profile.json", "TCS").save(profile)


def _suite(path: Path) -> Path:
    path.write_text(json.dumps([
        {"id": "t01", "category": "A", "question": "How stable are margins?",
         "subject": "TCS", "expected_behavior": "answer", "rubric": "synthesize"},
    ]), encoding="utf-8")
    return path


def test_eval_run_writes_report_and_prints_summary(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    # from_settings is called twice: reasoning client (no kwargs) and judge
    # client (model=judge_model) — the fake accepts both (§12.6 amendment 1).
    monkeypatch.setattr(
        "atlas.reasoning.client.AnthropicClient.from_settings",
        classmethod(lambda cls, settings, **kwargs: _BranchingFake()),
    )
    _seed(tmp_path)
    suite = _suite(tmp_path / "suite.json")
    out = tmp_path / "report.json"

    result = CliRunner().invoke(cli, [
        "eval", "run", "--milestone", "M0", "--suite", str(suite), "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["milestone"] == "M0"
    assert report["aggregates"]["correctness_pass_rate"] == 1.0
    assert report["aggregates"]["grounding_pass_rate"] == 1.0
    assert report["results"][0]["reasoning_quality"] == 4
    assert report["judge_model"]  # instrument provenance recorded (§12.6 am. 1)
    assert "coverage" in result.output


def test_eval_run_requires_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.delenv("ATLAS_ANTHROPIC_API_KEY", raising=False)
    result = CliRunner().invoke(cli, ["eval", "run", "--milestone", "M0"])
    assert result.exit_code == 1


def test_eval_compare_reports_delta(monkeypatch, tmp_path) -> None:
    # Two hand-written reports differing only in coverage.
    def _report(milestone: str, second_status: str) -> dict:
        return {
            "milestone": milestone, "created_at": "2026-07-05T00:00:00+00:00",
            "model": "fake", "git_commit": None, "capabilities": ["single_name"],
            "results": [
                {"case_id": "t01", "category": "A", "status": "active",
                 "refused": False, "correctness_pass": True, "correctness_reasons": [],
                 "grounding_pass": True, "grounding_reasons": [],
                 "reasoning_quality": 4, "usefulness": 4, "judge_notes": "", "error": None},
                {"case_id": "t29", "category": "F", "status": second_status,
                 "refused": None, "correctness_pass": True if second_status == "active" else None,
                 "correctness_reasons": [], "grounding_pass": True if second_status == "active" else None,
                 "grounding_reasons": [], "reasoning_quality": None, "usefulness": None,
                 "judge_notes": "", "error": None},
            ],
        }
    base = tmp_path / "M0.json"
    cand = tmp_path / "M2.json"
    base.write_text(json.dumps(_report("M0", "pending")), encoding="utf-8")
    cand.write_text(json.dumps(_report("M2", "active")), encoding="utf-8")

    result = CliRunner().invoke(cli, ["eval", "compare", str(base), str(cand)])
    assert result.exit_code == 0, result.output
    assert "M0 -> M2" in result.output
    assert "t29" in result.output  # newly active
