"""`atlas store status --company X`.

The screen exists so nobody has to guess what is on disk. The one number that
cannot be inferred from the others is the fingerprint comparison: a store can
be full of rows and still be unreadable, because rows written by a build that
is no longer running are refused at read time. Every other line is a count;
that line is a diagnosis.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from atlas.assertions.model import Assertion, AssertionRun
from atlas.assertions.store import AssertionStore
from atlas.cli import cli
from atlas.knowledge.base import KnowledgeBase, ParsedDocument
from atlas.provenance import current_fingerprint

_TICKER = "TCS"


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    root = tmp_path / _TICKER
    root.mkdir()
    return root


def _run(
    *,
    evidence_id: str = "ev-1",
    fingerprint: str,
    status: str = "ok",
    analyzer_version: str = "1.0",
) -> AssertionRun:
    return AssertionRun(
        evidence_id=evidence_id,
        kind="financial_results",
        analyzer_version=analyzer_version,
        fingerprint=fingerprint,
        result_confidence="high",
        source_date=datetime(2026, 4, 9, tzinfo=timezone.utc),
        analyzed_at=datetime(2026, 7, 29, 10, 30, tzinfo=timezone.utc),
        warnings=(),
        status=status,  # type: ignore[arg-type]
        error="boom" if status == "failed" else None,
    )


def _assertion(run: AssertionRun, assertion_id: str) -> Assertion:
    return Assertion(
        assertion_id=assertion_id,
        evidence_id=run.evidence_id,
        kind="financial_revenue",
        value="64988",
        value_type="int",
        unit="crore_inr",
        period="2026-03-31",
        confidence="high",
        section="p_and_l",
        char_offset=10,
        excerpt="an excerpt",
        analyzer_version=run.analyzer_version,
        fingerprint=run.fingerprint,
        ordinal=0,
    )


def _status(ticker: str = _TICKER):
    return CliRunner().invoke(cli, ["store", "status", "--company", ticker])


def test_empty_repository_reports_zeros_not_an_error(repo_root: Path) -> None:
    """A repository with nothing analyzed is a normal state, not a failure."""
    result = _status()

    assert result.exit_code == 0, result.output
    assert "documents:        0" in result.output
    assert "nothing analyzed yet" in result.output


def test_counts_runs_assertions_and_documents(repo_root: Path) -> None:
    store = AssertionStore(repo_root)
    digest = current_fingerprint().digest()
    first = _run(evidence_id="ev-1", fingerprint=digest)
    second = _run(evidence_id="ev-2", fingerprint=digest)
    store.write_run(first, [_assertion(first, "a1"), _assertion(first, "a2")])
    store.write_run(second, [_assertion(second, "b1")])

    result = _status()

    assert "documents:        2" in result.output
    assert "runs:             2 (0 failed)" in result.output
    assert "assertions:       3" in result.output


def test_failed_runs_are_counted_separately(repo_root: Path) -> None:
    store = AssertionStore(repo_root)
    digest = current_fingerprint().digest()
    store.write_run(_run(fingerprint=digest, status="failed"), [])

    result = _status()

    assert "runs:             1 (1 failed)" in result.output


def test_current_fingerprint_is_marked_current(repo_root: Path) -> None:
    store = AssertionStore(repo_root)
    digest = current_fingerprint().digest()
    run = _run(fingerprint=digest)
    store.write_run(run, [_assertion(run, "a1")])

    result = _status()

    assert f"{digest} [current]" in result.output
    assert "another build" not in result.output


def test_a_store_written_by_another_build_is_called_out(repo_root: Path) -> None:
    """Full of rows and unreadable is the state no count would reveal."""
    store = AssertionStore(repo_root)
    run = _run(fingerprint="fp-from-an-older-build")
    store.write_run(run, [_assertion(run, "a1")])

    result = _status()

    assert "[STALE]" in result.output
    assert "Every stored run is from another build" in result.output
    assert "atlas analyze --company TCS" in result.output


def test_mixed_builds_show_both(repo_root: Path) -> None:
    store = AssertionStore(repo_root)
    digest = current_fingerprint().digest()
    fresh = _run(evidence_id="ev-1", fingerprint=digest)
    stale = _run(evidence_id="ev-2", fingerprint="fp-old")
    store.write_run(fresh, [_assertion(fresh, "a1")])
    store.write_run(stale, [_assertion(stale, "b1")])

    result = _status()

    assert "[current]" in result.output
    assert "[STALE]" in result.output
    # Some rows are readable, so the "re-analyze everything" advice is wrong.
    assert "Every stored run is from another build" not in result.output


def test_last_analyzed_is_reported(repo_root: Path) -> None:
    store = AssertionStore(repo_root)
    run = _run(fingerprint=current_fingerprint().digest())
    store.write_run(run, [_assertion(run, "a1")])

    result = _status()

    assert "2026-07-29T10:30" in result.output


def test_never_analyzed_says_never(repo_root: Path) -> None:
    assert "last analyzed:    never" in _status().output


def test_tier_zero_counts_come_from_the_knowledge_base(repo_root: Path) -> None:
    KnowledgeBase(repo_root)._upsert(
        ParsedDocument(
            evidence_id="ev-1",
            kind="financial_results",
            title="Q4 FY26 Results",
            source_date="2026-04-09T00:00:00+00:00",
            local_path="other/e1.pdf",
            parsed_at=datetime.now(timezone.utc),
            parser_version="test",
            status="ok",
            char_count=100,
        ),
        "some text",
    )

    result = _status()

    assert "parsed documents: 1" in result.output


def test_absent_files_are_reported_as_absent(repo_root: Path) -> None:
    """A missing profile is information, not an error."""
    result = _status()

    assert "profile.json:     absent" in result.output


def test_missing_repository_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")

    result = _status(ticker="NOSUCH")

    assert result.exit_code == 1
    assert "No repository for 'NOSUCH'" in result.output
