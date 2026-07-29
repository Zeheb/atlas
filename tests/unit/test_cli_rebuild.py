"""`atlas rebuild --company X [--from ...] [--verify]` (#30).

Two things this command must get right, because both are ways of quietly
lying to whoever ran it:

Verify writes nothing -- asserted on mtime and bytes, not on the absence of a
message. A check that can modify what it checks is worse than no check.

Verify's exit code means something -- non-zero when the profile would change,
so the command can be a gate in a script. A rebuild that legitimately changed
a profile has succeeded and exits zero; a verify that found a change has found
what it was run to find.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.cli import cli
from atlas.company.store import LoadReport
from atlas.rebuild import PROFILE_FILENAME
from tests.support.roundtrip import make_fact, make_result

_TICKER = "TCS"


def _result(revenue: int = 64988) -> AnalysisResult:
    result = make_result(
        "financial_results",
        facts=[
            make_fact(
                FactKind.FINANCIAL_REVENUE,
                revenue,
                unit=FactUnit.CRORE_INR,
                period="2026-03-31",
                section="consolidated_p_and_l",
            )
        ],
    )
    result.evidence_id = "ev-1"
    result.source_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
    return result


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[AnalysisResult]:
    """A repository whose analyzer stage returns a list the test can edit."""
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    (tmp_path / _TICKER).mkdir()
    results = [_result()]

    def _load(root: Path, *, source: object = None, on_error: object = None):
        if source == "assertions":
            from atlas.assertions.reader import results_for

            return LoadReport(results=results_for(root), source="assertions")
        return LoadReport(
            results=list(results), source="analyzers", parsed=len(results)
        )

    monkeypatch.setattr("atlas.rebuild.load_results", _load)
    return results


def _run(*args: str):
    return CliRunner().invoke(cli, ["rebuild", "--company", _TICKER, *args])


def _profile_path(tmp_path: Path) -> Path:
    return tmp_path / _TICKER / PROFILE_FILENAME


def test_rebuild_from_evidence_writes_a_profile(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    result = _run("--from", "evidence")

    assert result.exit_code == 0, result.output
    assert _profile_path(tmp_path).exists()
    assert "Documents: 1" in result.output


def test_a_first_build_says_there_was_nothing_to_compare(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    result = _run("--from", "evidence")

    assert "No previous profile" in result.output


def test_an_unchanged_rebuild_says_so(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    _run("--from", "evidence")

    result = _run("--from", "evidence")

    assert result.exit_code == 0
    assert "Profile unchanged" in result.output


def test_a_changed_rebuild_lists_the_differences(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    _run("--from", "evidence")
    repo[:] = [_result(revenue=70000)]

    result = _run("--from", "evidence")

    assert result.exit_code == 0, "a rebuild that changed a profile has succeeded"
    assert "difference(s)" in result.output
    assert "financial_revenue" in result.output


def test_verify_leaves_the_profile_untouched(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    _run("--from", "evidence")
    path = _profile_path(tmp_path)
    before_mtime = path.stat().st_mtime_ns
    before_bytes = path.read_bytes()

    _run("--from", "evidence", "--verify")

    assert path.stat().st_mtime_ns == before_mtime
    assert path.read_bytes() == before_bytes


def test_verify_exits_non_zero_when_the_profile_would_change(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    """What makes it usable as a gate."""
    _run("--from", "evidence")
    repo[:] = [_result(revenue=70000)]

    result = _run("--from", "evidence", "--verify")

    assert result.exit_code == 1
    assert "financial_revenue" in result.output


def test_verify_exits_zero_when_nothing_would_change(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    _run("--from", "evidence")

    result = _run("--from", "evidence", "--verify")

    assert result.exit_code == 0
    assert "Profile unchanged" in result.output


def test_verify_writes_nothing_on_a_repository_with_no_profile(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    result = _run("--from", "evidence", "--verify")

    assert result.exit_code == 0
    assert not _profile_path(tmp_path).exists()


def test_the_default_source_is_assertions(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    """The fast path is the default; --from evidence is the deliberate one."""
    result = _run()

    assert "from assertions" in result.output


def test_missing_repository_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")

    result = CliRunner().invoke(cli, ["rebuild", "--company", "NOSUCH"])

    assert result.exit_code == 1
    assert "No repository for 'NOSUCH'" in result.output


def test_an_unknown_source_is_rejected(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    result = _run("--from", "vibes")

    assert result.exit_code != 0
    assert "vibes" in result.output
