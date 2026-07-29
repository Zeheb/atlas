"""`atlas analyze --company X [--kind K]`.

The command's whole contract is: fill the assertion store and touch nothing
else. So the tests worth having are about what it writes, what it refuses,
and what it leaves alone -- specifically that no profile appears, since the
point of populating the store separately is that a bad analyzer run cannot
reach a profile before anyone has inspected it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.analysis.base import AnalysisResult
from atlas.assertions.store import AssertionStore
from atlas.cli import cli
from atlas.knowledge.base import KnowledgeBase, ParsedDocument

_TICKER = "TCS"
_EVIDENCE = "bse-news-e1"
_KIND = "financial_results"


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")
    root = tmp_path / _TICKER
    root.mkdir()
    return root


def _seed(root: Path, *, kind: str = _KIND, evidence_id: str = _EVIDENCE) -> None:
    """Put one catalog entry and one parsed document in place."""
    local_path = f"other/{evidence_id}.pdf"
    document = root / local_path
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"%PDF-1.4 not really a pdf")

    catalog = RepositoryCatalog(root)
    catalog.add(
        CatalogEntry(
            evidence_id=evidence_id,
            source="bse",
            kind=kind,
            title="Quarterly Results",
            source_date="2026-04-09T00:00:00+00:00",
            document_url=None,
            local_path=local_path,
            file_size_bytes=25,
            acquired_at="2026-04-10T00:00:00+00:00",
        )
    )
    catalog.save()

    kb = KnowledgeBase(root)
    kb._upsert(
        ParsedDocument(
            evidence_id=evidence_id,
            kind=kind,
            title="Quarterly Results",
            source_date="2026-04-09T00:00:00+00:00",
            local_path=local_path,
            parsed_at=datetime.now(timezone.utc),
            parser_version="test",
            status="ok",
            char_count=10,
        ),
        "some extracted text",
    )


def _stub_analysis(
    monkeypatch: pytest.MonkeyPatch, *, evidence_id: str = _EVIDENCE
) -> None:
    """Stand in for the real analyzer: the CLI is what is under test here."""

    def _analyze(target: str, kb: KnowledgeBase) -> AnalysisResult:
        return AnalysisResult(
            evidence_id=target,
            kind=_KIND,
            analyzer_version="1.0",
            confidence="high",
            source_date=datetime(2026, 4, 9, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("atlas.assertions.writer.analyze", _analyze)
    monkeypatch.setattr(
        "atlas.knowledge.base.KnowledgeBase.parse",
        lambda self, entry: self.get(entry.evidence_id),
    )


def test_analyze_writes_a_run_to_the_store(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo_root)
    _stub_analysis(monkeypatch)

    result = CliRunner().invoke(cli, ["analyze", "--company", "tcs"])

    assert result.exit_code == 0, result.output
    stored = AssertionStore(repo_root).read_run(_EVIDENCE, "1.0")
    assert stored is not None
    assert stored.run.status == "ok"


def test_analyze_writes_no_profile(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Populating the store must not have profile side effects."""
    _seed(repo_root)
    _stub_analysis(monkeypatch)

    CliRunner().invoke(cli, ["analyze", "--company", _TICKER])

    assert not (repo_root / "profile.json").exists()


def test_rerunning_replaces_rather_than_appends(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo_root)
    _stub_analysis(monkeypatch)
    runner = CliRunner()

    runner.invoke(cli, ["analyze", "--company", _TICKER])
    runner.invoke(cli, ["analyze", "--company", _TICKER])

    assert AssertionStore(repo_root).runs_for(_EVIDENCE) != ()
    assert len(AssertionStore(repo_root).runs_for(_EVIDENCE)) == 1


def test_kind_filter_selects_documents(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo_root)
    _stub_analysis(monkeypatch)

    result = CliRunner().invoke(
        cli, ["analyze", "--company", _TICKER, "--kind", "annual_report"]
    )

    assert result.exit_code == 1
    assert "Nothing to analyze" in result.output
    assert AssertionStore(repo_root).evidence_ids() == ()


def test_unknown_kind_is_rejected_with_the_supported_list(repo_root: Path) -> None:
    result = CliRunner().invoke(
        cli, ["analyze", "--company", _TICKER, "--kind", "haruspicy"]
    )

    assert result.exit_code == 1
    assert "No analyzer for kind 'haruspicy'" in result.output
    assert "financial_results" in result.output


def test_missing_repository_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-test")

    result = CliRunner().invoke(cli, ["analyze", "--company", "NOSUCH"])

    assert result.exit_code == 1
    assert "No repository for 'NOSUCH'" in result.output


def test_analyzer_failure_is_recorded_and_reported(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad document is not a bad run: the error lands in the store, and the
    command still exits 0 so a batch is not aborted by one filing."""
    _seed(repo_root)
    _stub_analysis(monkeypatch)

    def _explode(target: str, kb: KnowledgeBase) -> AnalysisResult:
        raise RuntimeError("no tables found")

    monkeypatch.setattr("atlas.assertions.writer.analyze", _explode)

    result = CliRunner().invoke(cli, ["analyze", "--company", _TICKER])

    assert result.exit_code == 0, result.output
    assert "no tables found" in result.output
    runs = AssertionStore(repo_root).runs_for(_EVIDENCE)
    assert [run.status for run in runs] == ["failed"]


def test_unsupported_kinds_are_skipped_not_failed(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo_root, kind="press_clipping")
    _stub_analysis(monkeypatch)

    result = CliRunner().invoke(cli, ["analyze", "--company", _TICKER])

    assert result.exit_code == 1
    assert "Skipped (unsupported kind): 1" in result.output


def test_store_path_is_reported(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(repo_root)
    _stub_analysis(monkeypatch)

    result = CliRunner().invoke(cli, ["analyze", "--company", _TICKER])

    assert "assertions.db" in result.output
