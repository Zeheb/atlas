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

    def _load(
        root: Path,
        *,
        source: object = None,
        on_error: object = None,
        only: object = None,
    ):
        if source == "assertions":
            from atlas.assertions.reader import results_for

            return LoadReport(results=results_for(root), source="assertions")
        wanted = (
            list(results)
            if only is None
            else [r for r in results if r.evidence_id in set(only)]  # type: ignore[arg-type]
        )
        return LoadReport(results=wanted, source="analyzers", parsed=len(wanted))

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


# --- --stale-only (#49) ------------------------------------------------------


def test_stale_only_reports_nothing_to_do_on_a_current_store(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    """Zero is printed, not omitted: it is the answer the flag exists to give."""
    _run("--from", "evidence")

    result = _run("--from", "evidence", "--stale-only")

    assert result.exit_code == 0, result.output
    assert "stale only" in result.output
    assert "Re-analyzed: 0" in result.output


def test_stale_only_names_what_it_re_analyzed(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    from atlas.assertions.store import AssertionStore
    from atlas.assertions.writer import write_result
    from tests.support.roundtrip import foreign_fingerprint

    write_result(
        AssertionStore(tmp_path / _TICKER), _result(), fingerprint=foreign_fingerprint()
    )

    result = _run("--from", "evidence", "--stale-only")

    assert result.exit_code == 0, result.output
    assert "Re-analyzed: 1" in result.output
    assert "ev-1" in result.output


def test_stale_only_does_not_pick_up_a_never_analyzed_document(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    """The boundary of the flag, stated rather than discovered.

    A document with no run is not stale — nothing produced rows that this
    build cannot serve. Ingesting new evidence is what a full --from evidence
    rebuild is for, and quietly widening --stale-only to cover it would make
    the flag's cost unpredictable.
    """
    result = _run("--from", "evidence", "--stale-only")

    assert result.exit_code == 0, result.output
    assert "Re-analyzed: 0" in result.output
    assert "Documents: 0" in result.output


def test_stale_only_requires_from_evidence(
    tmp_path: Path, repo: list[AnalysisResult]
) -> None:
    """Reading the assertion store again returns the same stale rows."""
    result = _run("--stale-only")

    assert result.exit_code == 1
    assert "needs --from evidence" in result.output
