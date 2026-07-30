"""`atlas store verify` — #57.

The question is not what the tiers hold (that is `store status`) but whether
a rebuild would work right now. Four checks, ordered so that each one is
meaningful only if the previous passed, and each failure carrying the command
that fixes it.

Two properties matter more than the checks themselves:

Read-only  -- including on a repository with no store. AssertionStore creates
              its database on open, so a verifier that opened one first would
              report success at having built the thing it was asked to find
              missing.
Ordered    -- checks stop at the first failure. Three confident failures that
              all restate the first one bury the one that matters.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.assertions.store import DB_FILENAME, AssertionStore
from atlas.assertions.writer import write_result
from atlas.cli import cli
from atlas.provenance import current_fingerprint
from atlas.rebuild import PROFILE_FILENAME
from atlas.verify import verify_store
from tests.support.roundtrip import foreign_fingerprint, make_fact, make_result

_COMPANY = "TCS"


def _result(evidence_id: str = "ev-1", *, revenue: int = 64988) -> AnalysisResult:
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
        entities=[],
    )
    result.evidence_id = evidence_id
    result.source_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
    return result


def _write_profile(root: Path, results: list[AnalysisResult]) -> None:
    from atlas.company.builder import build_profile
    from atlas.company.store import CompanyStore

    CompanyStore(root / PROFILE_FILENAME, _COMPANY).save(
        build_profile(_COMPANY, results), results
    )


def _names(report: object) -> list[str]:
    return [check.name for check in report.checks]  # type: ignore[attr-defined]


# --- a healthy repository ----------------------------------------------------


def test_a_current_repository_passes_every_check(tmp_path: Path) -> None:
    results = [_result()]
    write_result(
        AssertionStore(tmp_path), results[0], fingerprint=current_fingerprint()
    )
    _write_profile(tmp_path, results)

    report = verify_store(tmp_path, _COMPANY)

    assert report.ok is True
    assert report.failure is None
    assert _names(report) == [
        "store exists",
        "schema current",
        "rows readable",
        "profile current",
    ]


def test_a_store_with_no_profile_still_passes(tmp_path: Path) -> None:
    """Nothing to compare against is not a failure; it is a repository mid-setup."""
    write_result(AssertionStore(tmp_path), _result(), fingerprint=current_fingerprint())

    report = verify_store(tmp_path, _COMPANY)

    assert report.ok is True


# --- the failing checks, in order --------------------------------------------


def test_a_missing_store_fails_first_and_stops(tmp_path: Path) -> None:
    """Later questions are unanswerable, not false."""
    report = verify_store(tmp_path, _COMPANY)

    assert report.ok is False
    assert _names(report) == ["store exists"]
    assert "migrate assertions" in report.failure.remedy  # type: ignore[union-attr]


def test_verifying_a_repository_without_a_store_creates_nothing(
    tmp_path: Path,
) -> None:
    """The constraint the check order exists to respect."""
    verify_store(tmp_path, _COMPANY)

    assert not (tmp_path / DB_FILENAME).exists()


def test_stale_rows_fail_and_point_at_stale_only(tmp_path: Path) -> None:
    write_result(AssertionStore(tmp_path), _result(), fingerprint=foreign_fingerprint())

    report = verify_store(tmp_path, _COMPANY)

    assert report.ok is False
    assert report.failure.name == "rows readable"  # type: ignore[union-attr]
    assert "--stale-only" in report.failure.remedy  # type: ignore[union-attr]


def test_a_stale_store_does_not_also_report_the_profile(tmp_path: Path) -> None:
    """The profile check would raise on a stale store; stopping is why it does not."""
    write_result(AssertionStore(tmp_path), _result(), fingerprint=foreign_fingerprint())
    _write_profile(tmp_path, [_result()])

    report = verify_store(tmp_path, _COMPANY)

    assert "profile current" not in _names(report)


def test_a_drifted_profile_fails_and_points_at_rebuild(tmp_path: Path) -> None:
    """Every row current and readable, and the number on screen still wrong."""
    write_result(AssertionStore(tmp_path), _result(), fingerprint=current_fingerprint())
    _write_profile(tmp_path, [_result(revenue=70000)])

    report = verify_store(tmp_path, _COMPANY)

    assert report.ok is False
    assert report.failure.name == "profile current"  # type: ignore[union-attr]
    assert "atlas rebuild" in report.failure.remedy  # type: ignore[union-attr]


def test_the_profile_check_writes_nothing(tmp_path: Path) -> None:
    """It serialises a candidate, and must not do it inside the repository."""
    results = [_result()]
    write_result(
        AssertionStore(tmp_path), results[0], fingerprint=current_fingerprint()
    )
    _write_profile(tmp_path, results)
    before = (tmp_path / PROFILE_FILENAME).read_bytes()

    verify_store(tmp_path, _COMPANY)

    assert (tmp_path / PROFILE_FILENAME).read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        DB_FILENAME,
        PROFILE_FILENAME,
    ]


# --- the command -------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    root = tmp_path / _COMPANY
    root.mkdir()
    return root


def _run(*args: str):
    return CliRunner().invoke(cli, ["store", "verify", "--company", _COMPANY, *args])


def test_the_command_exits_zero_on_a_healthy_repository(repo: Path) -> None:
    results = [_result()]
    write_result(AssertionStore(repo), results[0], fingerprint=current_fingerprint())
    _write_profile(repo, results)

    result = _run()

    assert result.exit_code == 0, result.output
    assert "Storage is usable by this build." in result.output


def test_the_command_exits_non_zero_and_prints_the_fix(repo: Path) -> None:
    """So it can gate a script, and so the next command is on screen."""
    result = _run()

    assert result.exit_code == 1
    assert "[FAIL] store exists" in result.output
    assert "Fix: atlas migrate assertions" in result.output


def test_a_missing_repository_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")

    result = CliRunner().invoke(cli, ["store", "verify", "--company", "NOSUCH"])

    assert result.exit_code == 1
    assert "No repository for 'NOSUCH'" in result.output
