"""`atlas investigate` (M2.2.5 commit 4).

The load-bearing test is test_dry_run_builds_no_llm_client_at_all: --dry-run
must be a true zero-LLM path, not a path that builds a client and declines to
use it. Asserted with an exploding build_llm_client stub, exactly the way
test_cli_eval.py asserts it for --retrieval-only.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.analysis.base import FactKind
from atlas.cli import cli
from atlas.company.model import CompanyProfile, FinancialSnapshot, FinancialTimeSeries
from atlas.company.store import CompanyStore
from atlas.knowledge.base import KnowledgeBase

_CONTENT = (
    "Operating margin stood at 24.2% in FY26, driven by continued cost discipline "
    "across major markets, with steady improvement over prior quarters."
)


def _seed(base, ticker: str = "TCS") -> None:
    profile = CompanyProfile(
        company_id=ticker,
        financial=FinancialTimeSeries(
            snapshots=[
                FinancialSnapshot(
                    period="2026-03-31",
                    period_type="annual",
                    basis="consolidated",
                    facts={FactKind.FINANCIAL_OPERATING_MARGIN: 24.2},
                    sources=["ev-1"],
                )
            ]
        ),
    )
    repo_root = base / ticker
    repo_root.mkdir(parents=True, exist_ok=True)
    CompanyStore(repo_root / "profile.json", ticker).save(profile)

    rel = "ev-1.txt"
    (repo_root / rel).write_text(_CONTENT, encoding="utf-8")
    entry = CatalogEntry(
        evidence_id="ev-1",
        source=EvidenceSource.BSE.value,
        kind=EvidenceKind.FINANCIAL_RESULTS.value,
        title="Test filing",
        source_date="2026-03-31T00:00:00+00:00",
        document_url=None,
        local_path=rel,
        file_size_bytes=None,
        acquired_at="2026-04-01T00:00:00+00:00",
    )
    KnowledgeBase(repo_root).parse(entry)


class _GroundedFake:
    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(
            {
                "refused": False,
                "overall_confidence": "high",
                "findings": [
                    {
                        "statement": "Operating margin ~24%.",
                        "assertability": "judgment",
                        "confidence": "high",
                        "supporting_evidence_ids": ["ev-1"],
                        "known_unknowns": [],
                    }
                ],
            }
        )


# --- The zero-LLM gate --------------------------------------------------------------
def test_dry_run_builds_no_llm_client_at_all(monkeypatch, tmp_path) -> None:
    def _exploding(settings, *, role):
        raise AssertionError(
            f"build_llm_client(role={role!r}) must never be called in --dry-run mode"
        )

    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setattr("atlas.reasoning.llm.build_llm_client", _exploding)

    result = CliRunner().invoke(
        cli,
        [
            "investigate",
            "TCS",
            "Should I invest in TCS?",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Research plan: invest_decision" in result.output


def test_dry_run_needs_no_profile_and_no_knowledge_base(monkeypatch, tmp_path) -> None:
    """The plan is a pure function of the question -- nothing is read from
    disk, so an un-acquired ticker still plans fine.
    """
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    result = CliRunner().invoke(
        cli,
        [
            "investigate",
            "NEVERACQUIRED",
            "What are the key risks?",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "risk_assessment" in result.output


# --- Plan output ---------------------------------------------------------------------
def test_dry_run_prints_dimensions_rationales_and_decisions(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    result = CliRunner().invoke(
        cli,
        [
            "investigate",
            "TCS",
            "Should I invest in TCS?",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "business_quality" in result.output
    assert "why:" in result.output  # rationale is surfaced
    assert "[research_intent_keyword_match]" in result.output  # decision trace


def test_dry_run_writes_plan_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    out = tmp_path / "plan.json"
    result = CliRunner().invoke(
        cli,
        [
            "investigate",
            "TCS",
            "Should I invest in TCS?",
            "--dry-run",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["intent"] == "invest_decision"
    assert payload["investigations"]
    assert all(i["rationale"] for i in payload["investigations"])


def test_plans_for_different_questions_differ(monkeypatch, tmp_path) -> None:
    """The anti-checklist gate, at the CLI level."""
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    runner = CliRunner()

    p1 = tmp_path / "p1.json"
    p2 = tmp_path / "p2.json"
    runner.invoke(
        cli,
        [
            "investigate",
            "TCS",
            "Should I invest in TCS?",
            "--dry-run",
            "--out",
            str(p1),
        ],
    )
    runner.invoke(
        cli,
        [
            "investigate",
            "TCS",
            "What are the key risks to TCS?",
            "--dry-run",
            "--out",
            str(p2),
        ],
    )

    assert p1.read_text(encoding="utf-8") != p2.read_text(encoding="utf-8")


# --- Multi-subject -------------------------------------------------------------------
def test_also_flag_makes_the_plan_comparative(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    result = CliRunner().invoke(
        cli,
        [
            "investigate",
            "TATASTEEL",
            "What are the margins?",
            "--also",
            "JSWSTEEL",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Research plan: comparison" in result.output
    assert "TATASTEEL, JSWSTEEL" in result.output
    assert "competitive_position" in result.output  # kept only for >=2 subjects


def test_tickers_are_upper_cased(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    result = CliRunner().invoke(
        cli,
        [
            "investigate",
            "tcs",
            "Should I invest?",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "(TCS)" in result.output


# --- Full execution ------------------------------------------------------------------
def test_full_run_grounds_every_finding(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: _GroundedFake(),
    )
    _seed(tmp_path)
    out = tmp_path / "run.json"

    result = CliRunner().invoke(
        cli,
        [
            "investigate",
            "TCS",
            "Should I invest in TCS?",
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "investigations grounded" in result.output

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["resolution_rate"] == 1.0
    for row in payload["results"]:
        assert row["finding"] is not None
        assert row["finding"]["evidence_ids"]  # never an uncited claim


def test_full_run_reports_unresolved_rather_than_guessing(
    monkeypatch, tmp_path
) -> None:
    class _UncitedFake:
        def complete(self, *, system: str, user: str) -> str:
            return json.dumps(
                {
                    "refused": False,
                    "overall_confidence": "high",
                    "findings": [
                        {
                            "statement": "Margins are excellent.",
                            "assertability": "judgment",
                            "confidence": "high",
                            "supporting_evidence_ids": [],
                            "known_unknowns": [],
                        }
                    ],
                }
            )

    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: _UncitedFake(),
    )
    _seed(tmp_path)

    result = CliRunner().invoke(cli, ["investigate", "TCS", "Should I invest in TCS?"])
    assert result.exit_code == 0, result.output
    assert "UNRESOLVED" in result.output
    assert "0/" in result.output  # nothing grounded, stated plainly


# --- The report must stay untouched ---------------------------------------------------
def test_atlas_research_command_still_exists_unchanged(monkeypatch, tmp_path) -> None:
    """investigate is a NEW surface; it must not have replaced or altered the
    fixed-shape deterministic report.
    """
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    result = CliRunner().invoke(cli, ["research", "--help"])
    assert result.exit_code == 0
    assert "deterministic, evidence-first research briefing" in result.output
