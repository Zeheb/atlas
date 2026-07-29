"""`atlas judgment add|list|supersede|delete`.

The commands exist to make one distinction operable at the terminal: a
thesis is derived and replaceable, a judgment is a historical fact about
the user and is not. So the tests are mostly about what the CLI *refuses*
to do -- overwrite, hide a superseded position, or delete without being
told twice. A judgment surface that quietly loses an earlier view is the
same surface as ``memory``, and the tier distinction is gone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from atlas.cli import cli

_TICKER = "TCS"


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    root = tmp_path / _TICKER
    root.mkdir()
    return root


def _add(runner: CliRunner, *extra: str, statement: str = "Margins compress.") -> str:
    result = runner.invoke(
        cli,
        ["judgment", "add", "--company", _TICKER, "--statement", statement, *extra],
    )
    assert result.exit_code == 0, result.output
    return result.output.split("Recorded judgment ")[1].split(" ")[0]


def _stored(repo_root: Path) -> list[dict[str, object]]:
    envelope = json.loads((repo_root / "judgments.json").read_text("utf-8"))
    records: list[dict[str, object]] = envelope["judgments"]
    return records


# --- add ---------------------------------------------------------------------


def test_add_writes_a_judgment(repo_root: Path) -> None:
    runner = CliRunner()
    judgment_id = _add(runner)
    records = _stored(repo_root)
    assert len(records) == 1
    assert records[0]["judgment_id"] == judgment_id
    assert records[0]["statement"] == "Margins compress."


def test_add_stamps_the_current_build_fingerprint(repo_root: Path) -> None:
    """What Atlas was showing at the time must stay recoverable."""
    from atlas.provenance import current_fingerprint

    runner = CliRunner()
    _add(runner)
    assert _stored(repo_root)[0]["fingerprint"] == current_fingerprint().digest()


def test_add_records_rationale_and_repeated_evidence(repo_root: Path) -> None:
    runner = CliRunner()
    _add(
        runner,
        "--rationale",
        "Wage inflation.",
        "--evidence",
        "ev-002",
        "--evidence",
        "ev-001",
    )
    record = _stored(repo_root)[0]
    assert record["rationale"] == "Wage inflation."
    assert record["evidence_ids"] == ["ev-001", "ev-002"]


def test_add_uppercases_the_ticker(repo_root: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["judgment", "add", "--company", "tcs", "--statement", "Fine."]
    )
    assert result.exit_code == 0, result.output
    assert (repo_root / "judgments.json").exists()


def test_add_fails_when_the_repository_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["judgment", "add", "--company", "NOPE", "--statement", "x"]
    )
    assert result.exit_code == 1
    assert "No repository for 'NOPE'" in result.output


def test_re_adding_identical_content_is_refused(repo_root: Path) -> None:
    """Append-only surfaced at the terminal: no silent second row."""
    runner = CliRunner()
    _add(runner)
    result = runner.invoke(
        cli,
        ["judgment", "add", "--company", _TICKER, "--statement", "Margins compress."],
    )
    assert result.exit_code == 1
    assert "Already recorded as" in result.output
    assert "supersede" in result.output
    assert len(_stored(repo_root)) == 1


# --- supersede ---------------------------------------------------------------


def test_supersede_keeps_both_judgments(repo_root: Path) -> None:
    runner = CliRunner()
    original = _add(runner)
    result = runner.invoke(
        cli,
        [
            "judgment",
            "supersede",
            original,
            "--company",
            _TICKER,
            "--statement",
            "Margins recover.",
        ],
    )
    assert result.exit_code == 0, result.output
    records = _stored(repo_root)
    assert len(records) == 2
    assert records[0]["judgment_id"] == original
    assert records[1]["supersedes"] == original


def test_supersede_reports_the_link(repo_root: Path) -> None:
    runner = CliRunner()
    original = _add(runner)
    result = runner.invoke(
        cli,
        [
            "judgment",
            "supersede",
            original,
            "--company",
            _TICKER,
            "--statement",
            "Margins recover.",
        ],
    )
    assert f"supersedes {original}" in result.output


def test_superseding_an_unknown_judgment_is_refused(repo_root: Path) -> None:
    """A dangling link would make later history look complete when it is not."""
    runner = CliRunner()
    _add(runner)
    result = runner.invoke(
        cli,
        [
            "judgment",
            "supersede",
            "0000000000000000",
            "--company",
            _TICKER,
            "--statement",
            "Margins recover.",
        ],
    )
    assert result.exit_code == 1
    assert "nothing to supersede" in result.output
    assert len(_stored(repo_root)) == 1


# --- list --------------------------------------------------------------------


def test_list_on_an_empty_store_says_how_to_start(repo_root: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["judgment", "list", "--company", _TICKER])
    assert result.exit_code == 0
    assert "No judgments recorded" in result.output
    assert "atlas judgment add" in result.output


def test_list_shows_statement_rationale_evidence_and_build(repo_root: Path) -> None:
    runner = CliRunner()
    judgment_id = _add(runner, "--rationale", "Wage inflation.", "--evidence", "ev-001")
    result = runner.invoke(cli, ["judgment", "list", "--company", _TICKER])
    assert result.exit_code == 0, result.output
    assert judgment_id in result.output
    assert "Margins compress." in result.output
    assert "Wage inflation." in result.output
    assert "ev-001" in result.output
    assert "build:" in result.output


def test_list_shows_superseded_entries_rather_than_hiding_them(
    repo_root: Path,
) -> None:
    """The earlier position staying visible is the whole point of Tier 0."""
    runner = CliRunner()
    original = _add(runner)
    runner.invoke(
        cli,
        [
            "judgment",
            "supersede",
            original,
            "--company",
            _TICKER,
            "--statement",
            "Margins recover.",
        ],
    )
    result = runner.invoke(cli, ["judgment", "list", "--company", _TICKER])
    assert "Margins compress." in result.output
    assert "Margins recover." in result.output
    assert "[superseded by " in result.output


def test_list_fails_when_the_repository_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    runner = CliRunner()
    result = runner.invoke(cli, ["judgment", "list", "--company", "NOPE"])
    assert result.exit_code == 1
    assert "No repository for 'NOPE'" in result.output


# --- delete ------------------------------------------------------------------


def test_delete_without_force_refuses_and_points_at_supersede(
    repo_root: Path,
) -> None:
    runner = CliRunner()
    judgment_id = _add(runner)
    result = runner.invoke(
        cli, ["judgment", "delete", judgment_id, "--company", _TICKER]
    )
    assert result.exit_code == 1
    assert "--force" in result.output
    assert "supersede" in result.output
    assert len(_stored(repo_root)) == 1


def test_delete_with_force_removes_the_judgment(repo_root: Path) -> None:
    runner = CliRunner()
    judgment_id = _add(runner)
    result = runner.invoke(
        cli, ["judgment", "delete", judgment_id, "--company", _TICKER, "--force"]
    )
    assert result.exit_code == 0, result.output
    assert "Margins compress." in result.output
    assert _stored(repo_root) == []


def test_delete_of_an_unknown_judgment_is_refused(repo_root: Path) -> None:
    runner = CliRunner()
    _add(runner)
    result = runner.invoke(
        cli,
        ["judgment", "delete", "0000000000000000", "--company", _TICKER, "--force"],
    )
    assert result.exit_code == 1
    assert "No judgment" in result.output
    assert len(_stored(repo_root)) == 1


def test_delete_of_a_superseded_judgment_is_refused(repo_root: Path) -> None:
    """Removing a link mid-chain would dangle the judgment that replaced it."""
    runner = CliRunner()
    original = _add(runner)
    runner.invoke(
        cli,
        [
            "judgment",
            "supersede",
            original,
            "--company",
            _TICKER,
            "--statement",
            "Margins recover.",
        ],
    )
    result = runner.invoke(
        cli, ["judgment", "delete", original, "--company", _TICKER, "--force"]
    )
    assert result.exit_code == 1
    assert "dangling supersedes link" in result.output
    assert len(_stored(repo_root)) == 2


def test_delete_then_recreate_is_allowed(repo_root: Path) -> None:
    """Deletion is the typo escape hatch; the id is free again afterwards."""
    runner = CliRunner()
    judgment_id = _add(runner)
    runner.invoke(
        cli, ["judgment", "delete", judgment_id, "--company", _TICKER, "--force"]
    )
    assert _add(runner) == judgment_id


# --- the tier distinction ----------------------------------------------------


def test_judgments_live_beside_theses_not_inside_them(repo_root: Path) -> None:
    """Two stores, two lifecycles -- see research/memory.py's docstring."""
    runner = CliRunner()
    _add(runner)
    assert (repo_root / "judgments.json").exists()
    assert not (repo_root / "theses.json").exists()
