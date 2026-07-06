"""`atlas eval run` / `atlas eval compare` CLI (eval commit 5).

Offline: a branching fake stands in for the LLM client, returning reasoning
JSON to the reasoning pass and score JSON to the judge (it branches on the
system prompt). A synthetic TCS profile and a 1-case suite keep it fast.
"""
from __future__ import annotations

import hashlib
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
    # build_llm_client is called twice: reasoning role and judge role (§12.6
    # amendment 1, goal 7) — the fake serves both, branching on system prompt.
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: _BranchingFake(),
    )
    _seed(tmp_path)
    suite = _suite(tmp_path / "suite.json")
    out = tmp_path / "report.json"

    result = CliRunner().invoke(cli, [
        "eval", "run", "--milestone", "M0", "--suite", str(suite), "--out", str(out),
        # Caching is on by default; keep the cache dir inside tmp_path so the
        # test never touches the real project's .eval_cache/ directory.
        "--cache-path", str(tmp_path / "cache"),
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
    assert report["cache_hits"] == 0 and report["cache_misses"] == 2  # reasoning + judge
    # Reasoning and judge each get their own file, not one shared blob.
    assert (tmp_path / "cache" / "reasoning.json").exists()
    assert (tmp_path / "cache" / "judge.json").exists()


def test_eval_run_no_cache_skips_the_cache_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: _BranchingFake(),
    )
    _seed(tmp_path)
    suite = _suite(tmp_path / "suite.json")
    out = tmp_path / "report.json"
    cache_dir = tmp_path / "cache"

    result = CliRunner().invoke(cli, [
        "eval", "run", "--milestone", "M0", "--suite", str(suite), "--out", str(out),
        "--no-cache", "--cache-path", str(cache_dir),
    ])
    assert result.exit_code == 0, result.output
    assert not cache_dir.exists()  # --no-cache: never constructed, never written
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["cache_hits"] is None and report["cache_misses"] is None


def test_eval_run_judge_sample_limits_judge_calls(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: _BranchingFake(),
    )
    _seed(tmp_path)
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps([
        {"id": "t01", "category": "A", "question": "How stable are margins?",
         "subject": "TCS", "expected_behavior": "answer", "rubric": "synthesize"},
        {"id": "t02", "category": "A", "question": "How stable is revenue?",
         "subject": "TCS", "expected_behavior": "answer", "rubric": "synthesize"},
    ]), encoding="utf-8")
    out = tmp_path / "report.json"

    result = CliRunner().invoke(cli, [
        "eval", "run", "--milestone", "M0", "--suite", str(suite_path), "--out", str(out),
        "--judge-sample", "1", "--no-cache",
    ])
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    by_id = {r["case_id"]: r for r in report["results"]}
    # judge_sample="1" picks exactly one case by hash rank, not file position —
    # assert on "exactly one sampled, matching hash rank" rather than assuming
    # which specific id wins.
    expected_sampled = min(by_id, key=lambda cid: hashlib.sha256(cid.encode()).hexdigest())
    judged = [cid for cid, r in by_id.items() if r["reasoning_quality"] == 4]
    unjudged = [cid for cid, r in by_id.items() if r["reasoning_quality"] is None]
    assert judged == [expected_sampled]
    assert len(unjudged) == 1
    assert by_id[unjudged[0]]["correctness_pass"] is True  # deterministic scoring unaffected


def test_eval_run_suite_preset_core_runs_a_small_bundled_subset(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: _BranchingFake(),
    )
    _seed(tmp_path)
    out = tmp_path / "report.json"

    result = CliRunner().invoke(cli, [
        "eval", "run", "--milestone", "M0", "--suite", "core", "--out", str(out),
        "--no-judge", "--no-cache",
    ])
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    assert 1 < len(report["results"]) < 44  # a curated subset, not the full 44


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
