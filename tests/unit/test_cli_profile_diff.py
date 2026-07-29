"""`atlas profile diff` and the diff_profiles helper behind it.

An equivalence assertion that fails tells you two profiles disagree and
nothing else. This is what turns that into a location. It is used by the
rebuild equivalence gate, the assertion-store round trip, and the backfill
verification, so its own correctness matters more than its size suggests.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from atlas.cli import cli
from atlas.company.store import diff_profiles, load_profile_payload


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_identical_profiles_report_no_differences() -> None:
    profile = {"financial": {"snapshots": [{"period": "2024-09-30"}]}}
    assert diff_profiles(profile, dict(profile)) == []


def test_changed_value_is_reported_with_its_path() -> None:
    left = {"financial": {"snapshots": [{"facts": {"financial_revenue": 60000.0}}]}}
    right = {"financial": {"snapshots": [{"facts": {"financial_revenue": 59000.0}}]}}
    (line,) = diff_profiles(left, right)
    assert "financial.snapshots[0].facts.financial_revenue" in line
    assert "60000.0 -> 59000.0" in line


def test_keys_only_on_one_side_are_reported_directionally() -> None:
    left = {"a": 1, "only_left": "x"}
    right = {"a": 1, "only_right": "y"}
    lines = diff_profiles(left, right)
    assert any(line.startswith("- ") and "only_left" in line for line in lines)
    assert any(line.startswith("+ ") and "only_right" in line for line in lines)


def test_list_order_difference_is_visible() -> None:
    """Ordering is the failure mode this whole milestone is about, so the
    differ must surface it rather than treating lists as sets."""
    left = {"snapshots": [{"sources": ["fr-early", "fr-late"]}]}
    right = {"snapshots": [{"sources": ["fr-late", "fr-early"]}]}
    assert diff_profiles(left, right)


def test_load_profile_payload_unwraps_a_store_envelope(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "envelope.json",
        {"store_version": "1", "profile": {"company_id": "TCS"}},
    )
    assert load_profile_payload(path) == {"company_id": "TCS"}


def test_load_profile_payload_accepts_a_bare_profile(tmp_path: Path) -> None:
    path = _write(tmp_path / "bare.json", {"company_id": "TCS"})
    assert load_profile_payload(path) == {"company_id": "TCS"}


def test_cli_reports_equivalence_and_exits_zero(tmp_path: Path) -> None:
    payload: dict[str, object] = {"profile": {"company_id": "TCS"}}
    left = _write(tmp_path / "a.json", payload)
    right = _write(tmp_path / "b.json", payload)

    result = CliRunner().invoke(cli, ["profile", "diff", str(left), str(right)])
    assert result.exit_code == 0
    assert "equivalent" in result.output


def test_cli_lists_differences_and_exits_nonzero(tmp_path: Path) -> None:
    """Non-zero exit lets this be used as a check in a script, not just
    read by a human."""
    left = _write(tmp_path / "a.json", {"profile": {"company_id": "TCS"}})
    right = _write(tmp_path / "b.json", {"profile": {"company_id": "SBIN"}})

    result = CliRunner().invoke(cli, ["profile", "diff", str(left), str(right)])
    assert result.exit_code == 1
    assert "company_id" in result.output
