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

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.cli import cli
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.eval.judge import JUDGE_SYSTEM_PROMPT
from atlas.knowledge.base import KnowledgeBase


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


_CONTENT = (
    "Operating margin stood at 24.2% in FY26, driven by continued cost discipline "
    "across major markets, with steady improvement over prior quarters."
)


def _seed_with_kb(base: Path) -> None:
    """Same profile as _seed(), plus a real KnowledgeBase entry -- retrieval
    diagnostics (M1.8) are only produced when a KnowledgeBase is present.
    """
    _seed(base)
    repo_root = base / "TCS"
    rel = "ev-1.txt"
    (repo_root / rel).write_text(_CONTENT, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1", source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value, title="Test filing",
        source_date="2026-03-31T00:00:00+00:00", document_url=None,
        local_path=rel, file_size_bytes=None, acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(repo_root).parse(entry)


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
    from atlas.eval.cases import load_cases
    assert 1 < len(report["results"]) < len(load_cases())  # a curated subset, not the full suite


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


# --- M1.8 (ADR-0004): --strategy / --retrieval-only / --with-answers -------------
def test_eval_run_retrieval_only_builds_no_llm_client_at_all(monkeypatch, tmp_path) -> None:
    def _exploding_build_llm_client(settings, *, role):
        raise AssertionError(f"build_llm_client(role={role!r}) must never be called in --retrieval-only mode")

    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setattr("atlas.reasoning.llm.build_llm_client", _exploding_build_llm_client)
    _seed_with_kb(tmp_path)
    suite = _suite(tmp_path / "suite.json")
    out = tmp_path / "report.json"

    result = CliRunner().invoke(cli, [
        "eval", "run", "--milestone", "M1.8", "--suite", str(suite), "--out", str(out),
        "--strategy", "planned", "--retrieval-only",
    ])
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    r = report["results"][0]
    assert r["correctness_pass"] is None  # no LLM call -> nothing answer-dependent
    assert r["planner_metrics"] is not None
    assert r["retrieval_metrics"] is not None


def test_eval_run_retrieval_only_and_with_answers_are_mutually_exclusive(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    result = CliRunner().invoke(cli, [
        "eval", "run", "--milestone", "M1.8", "--retrieval-only", "--with-answers",
    ])
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_eval_run_with_strategy_populates_retrieval_metrics(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: _BranchingFake(),
    )
    _seed_with_kb(tmp_path)
    suite = _suite(tmp_path / "suite.json")
    out = tmp_path / "report.json"

    result = CliRunner().invoke(cli, [
        "eval", "run", "--milestone", "M1.8", "--suite", str(suite), "--out", str(out),
        "--strategy", "baseline", "--with-answers", "--no-cache",
    ])
    assert result.exit_code == 0, result.output
    report = json.loads(out.read_text(encoding="utf-8"))
    r = report["results"][0]
    assert r["correctness_pass"] is True  # end-to-end still ran
    assert r["retrieval_metrics"] is not None
    assert r["planner_metrics"]["intent"] == "general"  # BaselineStrategy's null plan


def test_eval_compare_retrieval_prints_recommendation_and_writes_full_json(tmp_path) -> None:
    def _report(milestone: str) -> dict:
        return {
            "milestone": milestone, "created_at": "2026-07-05T00:00:00+00:00",
            "model": "fake", "capabilities": ["single_name"],
            "results": [
                {"case_id": "t01", "category": "A", "status": "active",
                 "refused": False, "correctness_pass": True, "grounding_pass": True,
                 "retrieval_metrics": {
                     "candidates_considered": 3, "docs_searched": 2,
                     "selected": [["ev-1", 0, 100]], "doc_type_counts": [["annual_report", 1]],
                     "metadata_coverage": 1.0, "boost_totals": [], "boost_share": 0.1,
                 },
                 "planner_metrics": {
                     "intent": "narrative", "preferred_kinds": [], "top_k": 5,
                     "periods_found": [], "rules_fired": ["intent_keyword_match"],
                 }},
            ],
        }
    base = tmp_path / "base.json"
    cand = tmp_path / "cand.json"
    base.write_text(json.dumps(_report("base")), encoding="utf-8")
    cand.write_text(json.dumps(_report("cand")), encoding="utf-8")
    out = tmp_path / "comparison.json"

    result = CliRunner().invoke(cli, [
        "eval", "compare-retrieval", str(base), str(cand), "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert "recommendation:" in result.output
    assert any(v in result.output for v in ("SAFE_TO_ENABLE", "NOT_READY", "INSUFFICIENT_DATA"))
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["recommendation"]["verdict"] in ("SAFE_TO_ENABLE", "NOT_READY", "INSUFFICIENT_DATA")
    assert payload["side_by_side"][0]["case_id"] == "t01"
