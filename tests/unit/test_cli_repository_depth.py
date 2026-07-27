"""`atlas repository depth` (M-P0.2).

Reports how far back a company's acquired evidence reaches -- the measurement
the Phase-0 backfill is run against (Q33). The command reads the catalog only;
these tests seed a catalog directly rather than running a live acquisition.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from click.testing import CliRunner

from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.cli import cli


def _env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ATLAS_REPOSITORY_BASE_PATH", str(tmp_path))


def _repo(base: Path, ticker: str = "TCS") -> Path:
    root = base / ticker
    root.mkdir(parents=True, exist_ok=True)
    (root / "company.json").write_text("{}", encoding="utf-8")
    return root


def _entry(evidence_id: str, source_date: datetime,
           kind: EvidenceKind = EvidenceKind.ANNUAL_REPORT) -> CatalogEntry:
    return CatalogEntry(
        evidence_id=evidence_id, source=EvidenceSource.BSE.value, kind=kind.value,
        title="t", source_date=source_date.isoformat(), document_url=None,
        local_path=f"x/{evidence_id}.pdf", file_size_bytes=None,
        acquired_at=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
    )


def _seed(root: Path, entries: list[CatalogEntry]) -> None:
    cat = RepositoryCatalog(root)
    for e in entries:
        cat.add(e)
    cat.save()


def test_depth_missing_repository_errors(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    result = CliRunner().invoke(cli, ["repository", "depth", "TCS"])
    assert result.exit_code == 1
    assert "No repository for 'TCS'" in result.output


def test_depth_empty_catalog(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    _repo(tmp_path)
    result = CliRunner().invoke(cli, ["repository", "depth", "TCS"])
    assert result.exit_code == 0
    assert "No dated evidence" in result.output


def test_depth_reports_earliest_latest_span(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    root = _repo(tmp_path)
    _seed(root, [
        _entry("bse-old", datetime(2021, 3, 31, tzinfo=timezone.utc)),
        _entry("bse-new", datetime(2026, 3, 31, tzinfo=timezone.utc)),
    ])
    result = CliRunner().invoke(cli, ["repository", "depth", "TCS"])
    assert result.exit_code == 0
    assert "2021-03-31" in result.output
    assert "2026-03-31" in result.output
    assert "5.0 years" in result.output


def test_depth_since_reach_check(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    root = _repo(tmp_path)
    _seed(root, [_entry("bse-old", datetime(2020, 6, 1, tzinfo=timezone.utc))])
    reached = CliRunner().invoke(cli, ["repository", "depth", "TCS", "--since", "2021-03-31"])
    assert "Reaches 2021-03-31: yes" in reached.output
    missed = CliRunner().invoke(cli, ["repository", "depth", "TCS", "--since", "2019-01-01"])
    assert "Reaches 2019-01-01: no" in missed.output


def test_depth_invalid_since_errors(monkeypatch, tmp_path) -> None:
    _env(monkeypatch, tmp_path)
    root = _repo(tmp_path)
    _seed(root, [_entry("bse-old", datetime(2020, 6, 1, tzinfo=timezone.utc))])
    result = CliRunner().invoke(cli, ["repository", "depth", "TCS", "--since", "nope"])
    assert result.exit_code == 1
    assert "Invalid --since" in result.output
