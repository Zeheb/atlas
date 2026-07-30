"""`atlas migrate assertions --company X [--dry-run]` (#54).

The command's job is to make the safety properties visible. An operator
deciding whether to run this against a real repository reads the dry run's
output and nothing else, so the counts have to be the real ones and "nothing
was written" has to be unmistakable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.assertions.store import DB_FILENAME
from atlas.cli import cli
from atlas.company.store import LoadReport
from tests.support.roundtrip import make_fact, make_result

_TICKER = "TCS"


def _result(evidence_id: str = "ev-1") -> AnalysisResult:
    result = make_result(
        "financial_results",
        facts=[
            make_fact(
                FactKind.FINANCIAL_REVENUE,
                64988,
                unit=FactUnit.CRORE_INR,
                period="2026-03-31",
                section="consolidated_p_and_l",
            )
        ],
        entities=[],
    )
    result.evidence_id = evidence_id
    result.source_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
    return result


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    root = tmp_path / _TICKER
    root.mkdir()
    results = [_result()]

    def _load(
        root: Path,
        *,
        source: object = None,
        on_error: object = None,
        only: object = None,
    ) -> LoadReport:
        return LoadReport(
            results=list(results), source="analyzers", parsed=len(results)
        )

    monkeypatch.setattr("atlas.migrate.load_results", _load)
    return root


def _run(*args: str):
    return CliRunner().invoke(
        cli, ["migrate", "assertions", "--company", _TICKER, *args]
    )


def test_a_migration_reports_what_it_wrote(repo: Path) -> None:
    result = _run()

    assert result.exit_code == 0, result.output
    assert "Documents:  1" in result.output
    assert "Store replaced." in result.output
    assert (repo / DB_FILENAME).exists()


def test_a_dry_run_says_nothing_was_written(repo: Path) -> None:
    """And says how to keep it, so the next command is obvious."""
    result = _run("--dry-run")

    assert result.exit_code == 0, result.output
    assert "Nothing written" in result.output
    assert "--dry-run" in result.output
    assert not (repo / DB_FILENAME).exists()


def test_a_dry_run_still_reports_real_counts(repo: Path) -> None:
    dry = _run("--dry-run")
    wet = _run()

    assert "Documents:  1" in dry.output
    assert "Documents:  1" in wet.output


def test_a_re_run_is_labelled_as_one(repo: Path) -> None:
    """A first migration and a repeat should not read identically."""
    _run()

    result = _run()

    assert "this is a re-run" in result.output


def test_a_missing_repository_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")

    result = CliRunner().invoke(cli, ["migrate", "assertions", "--company", "NOSUCH"])

    assert result.exit_code == 1
    assert "No repository for 'NOSUCH'" in result.output
