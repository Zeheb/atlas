"""`atlas thesis` (M2.3 commit 8).

The behavior worth pinning is that the completeness gate BLOCKS rendering
rather than warning: a thesis that fails it is not printed at all, and the
command exits non-zero. A gate that prints the thesis anyway with a warning
above it is not a gate.
"""

from __future__ import annotations

import json

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
                "overall_confidence": "medium",
                "findings": [
                    {
                        "statement": "Margins are durable at ~24%.",
                        "assertability": "judgment",
                        "confidence": "medium",
                        "supporting_evidence_ids": ["ev-1"],
                        "known_unknowns": ["no segment-level detail disclosed"],
                    }
                ],
            }
        )


class _RefusingFake:
    def complete(self, *, system: str, user: str) -> str:
        return json.dumps(
            {
                "refused": True,
                "overall_confidence": "low",
                "refusal_reason": "the evidence does not support a view",
                "findings": [],
            }
        )


def _env(monkeypatch, tmp_path, client) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(
        "atlas.reasoning.llm.build_llm_client",
        lambda settings, *, role: client,
    )


# --- The happy path ---------------------------------------------------------------------
def test_thesis_prints_a_grounded_view(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)

    result = CliRunner().invoke(cli, ["thesis", "TCS", "Should I invest in TCS?"])
    assert result.exit_code == 0, result.output
    assert "Margins are durable" in result.output
    assert "evidence: ev-1" in result.output


def test_every_printed_statement_shows_its_evidence(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)

    result = CliRunner().invoke(cli, ["thesis", "TCS", "Should I invest in TCS?"])
    for line in result.output.splitlines():
        if line.strip().startswith(("[JUDGMENT]", "[FACT]")):
            assert "evidence:" in result.output


def test_known_unknowns_are_surfaced(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)

    result = CliRunner().invoke(cli, ["thesis", "TCS", "Should I invest in TCS?"])
    assert "not known: no segment-level detail disclosed" in result.output


def test_no_rating_is_issued(monkeypatch, tmp_path) -> None:
    """Atlas states its own limit in the output, as the report does."""
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)

    result = CliRunner().invoke(cli, ["thesis", "TCS", "Should I invest in TCS?"])
    assert "does not issue a buy/sell recommendation" in result.output


def test_writes_json_when_asked(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)
    out = tmp_path / "thesis.json"

    result = CliRunner().invoke(
        cli,
        ["thesis", "TCS", "Should I invest in TCS?", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["findings"][0]["evidence_ids"] == ["ev-1"]
    assert payload["citations"] == ["ev-1"]
    assert payload["dispositions"]
    assert "rating" not in payload and "stance" not in payload


# --- Refusal / failure paths -------------------------------------------------------------
def test_refused_synthesis_exits_nonzero_without_printing_a_view(
    monkeypatch, tmp_path
) -> None:
    _env(monkeypatch, tmp_path, _RefusingFake())
    _seed(tmp_path)

    result = CliRunner().invoke(cli, ["thesis", "TCS", "Should I invest in TCS?"])
    assert result.exit_code == 1
    assert "No thesis could be formed" in result.output
    assert "Overall confidence" not in result.output  # nothing was rendered


def test_missing_profile_produces_no_thesis(monkeypatch, tmp_path) -> None:
    """Nothing seeded: every investigation errors, so nothing is grounded."""
    _env(monkeypatch, tmp_path, _GroundedFake())

    result = CliRunner().invoke(cli, ["thesis", "NOPROFILE", "Should I invest?"])
    assert result.exit_code == 1
    assert "No thesis could be formed" in result.output


def test_missing_api_key_fails_cleanly(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.delenv("ATLAS_ANTHROPIC_API_KEY", raising=False)

    def _boom(settings, *, role):
        from atlas.reasoning.llm import LLMConfigurationError

        raise LLMConfigurationError("no credential configured")

    monkeypatch.setattr("atlas.reasoning.llm.build_llm_client", _boom)

    result = CliRunner().invoke(cli, ["thesis", "TCS", "Should I invest?"])
    assert result.exit_code == 1
    assert "no credential configured" in result.output


# --- The gate BLOCKS rendering ---------------------------------------------------------------
def test_failing_gate_blocks_the_thesis_entirely(monkeypatch, tmp_path) -> None:
    """The command's central claim: a thesis that does not account for every
    investigation is not printed with a warning above it -- it is not printed.

    synthesize() always produces complete dispositions, so the gate is forced
    to fail here to exercise the branch that matters.
    """
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)

    from atlas.research.thesis import GateResult, GateViolation

    monkeypatch.setattr(
        "atlas.research.thesis.check_completeness",
        lambda thesis, run: GateResult(
            violations=(
                GateViolation(
                    kind="undisposed_finding",
                    detail="'risks' produced a grounded finding but the thesis ignored it",
                ),
            )
        ),
    )

    result = CliRunner().invoke(cli, ["thesis", "TCS", "Should I invest in TCS?"])

    assert result.exit_code == 1
    assert "REJECTED" in result.output
    assert "undisposed_finding" in result.output
    assert "'risks'" in result.output
    # Nothing from the thesis body was rendered.
    assert "Margins are durable" not in result.output
    assert "Overall confidence" not in result.output


def test_gate_violations_are_all_listed(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)

    from atlas.research.thesis import GateResult, GateViolation

    monkeypatch.setattr(
        "atlas.research.thesis.check_completeness",
        lambda thesis, run: GateResult(
            violations=(
                GateViolation(kind="undisposed_finding", detail="first problem here"),
                GateViolation(kind="dropped_unresolved", detail="second problem here"),
            )
        ),
    )

    result = CliRunner().invoke(cli, ["thesis", "TCS", "Should I invest in TCS?"])
    assert "first problem here" in result.output
    assert "second problem here" in result.output


# --- Multi-subject -------------------------------------------------------------------------
def test_also_flag_investigates_both_subjects(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path, "TATASTEEL")
    _seed(tmp_path, "JSWSTEEL")

    result = CliRunner().invoke(
        cli,
        [
            "thesis",
            "TATASTEEL",
            "Compare Tata Steel with JSW Steel.",
            "--also",
            "JSWSTEEL",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "TATASTEEL, JSWSTEEL" in result.output
    assert "comparison" in result.output


def test_tickers_are_upper_cased(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)

    result = CliRunner().invoke(cli, ["thesis", "tcs", "Should I invest?"])
    assert result.exit_code == 0, result.output
    assert "TCS" in result.output


# --- --remember (M2.4) -----------------------------------------------------------------------
def test_remember_persists_the_thesis_to_the_store(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["thesis", "TCS", "Should I invest in TCS?", "--remember"],
    )
    assert result.exit_code == 0, result.output
    assert "Remembered as view_id=" in result.output

    from atlas.research.memory import ThesisStore

    store = ThesisStore(tmp_path / "TCS" / "theses.json", "TCS")
    stored = store.list()
    assert len(stored) == 1
    assert stored[0].question == "Should I invest in TCS?"


def test_without_remember_nothing_is_persisted(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)

    result = CliRunner().invoke(cli, ["thesis", "TCS", "Should I invest in TCS?"])
    assert result.exit_code == 0, result.output
    assert "Remembered as view_id=" not in result.output
    assert not (tmp_path / "TCS" / "theses.json").exists()


def test_remember_is_not_reached_when_the_gate_rejects(monkeypatch, tmp_path) -> None:
    """The gate blocks BEFORE --remember runs -- a rejected thesis is never
    persisted, matching the fact that it is never rendered either."""
    _env(monkeypatch, tmp_path, _GroundedFake())
    _seed(tmp_path)

    from atlas.research.thesis import GateResult, GateViolation

    monkeypatch.setattr(
        "atlas.research.thesis.check_completeness",
        lambda thesis, run: GateResult(
            violations=(
                GateViolation(kind="undisposed_finding", detail="ignored a finding"),
            )
        ),
    )

    result = CliRunner().invoke(
        cli,
        ["thesis", "TCS", "Should I invest in TCS?", "--remember"],
    )
    assert result.exit_code == 1
    assert not (tmp_path / "TCS" / "theses.json").exists()


# --- The other commands are untouched --------------------------------------------------------
def test_investigate_and_research_still_exist(monkeypatch, tmp_path) -> None:
    """thesis is a NEW surface; it replaced nothing."""
    runner = CliRunner()
    for command in ("investigate", "research"):
        assert runner.invoke(cli, [command, "--help"]).exit_code == 0
