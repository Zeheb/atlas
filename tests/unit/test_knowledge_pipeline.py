from pathlib import Path

import pytest

import atlas.knowledge.extractors as ext_mod
from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.acquisition.repository import Repository
from atlas.knowledge.base import KnowledgeBase
from atlas.knowledge.pipeline import parse_incremental


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE_DATE = "2024-01-01T00:00:00+00:00"
_ACQUIRED_AT = "2024-06-01T00:00:00+00:00"


def _make_entry(
    evidence_id: str,
    local_path: str = "docs/report.txt",
    kind: EvidenceKind = EvidenceKind.ANNUAL_REPORT,
) -> CatalogEntry:
    return CatalogEntry(
        evidence_id=evidence_id,
        source=EvidenceSource.BSE.value,
        kind=kind.value,
        title="Test",
        source_date=_SOURCE_DATE,
        document_url=None,
        local_path=local_path,
        file_size_bytes=None,
        acquired_at=_ACQUIRED_AT,
    )


def _populate_catalog(root: Path, entries: list[CatalogEntry]) -> None:
    catalog = RepositoryCatalog(root)
    for entry in entries:
        catalog.add(entry)
    catalog.save()


def _write(root: Path, rel_path: str, content: str = "text") -> None:
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------


class TestParseIncrementalBasic:
    def test_empty_catalog_returns_empty(self, tmp_path: Path) -> None:
        repo = Repository(tmp_path)
        kb = KnowledgeBase(tmp_path)
        assert parse_incremental(repo, kb) == []

    def test_parses_new_entry(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        _populate_catalog(tmp_path, [_make_entry("bse-p-a", "docs/a.txt")])
        repo = Repository(tmp_path)
        kb = KnowledgeBase(tmp_path)
        results = parse_incremental(repo, kb)
        assert len(results) == 1

    def test_returns_parsed_document_instances(self, tmp_path: Path) -> None:
        from atlas.knowledge.base import ParsedDocument

        _write(tmp_path, "docs/a.txt")
        _populate_catalog(tmp_path, [_make_entry("bse-p-a", "docs/a.txt")])
        results = parse_incremental(Repository(tmp_path), KnowledgeBase(tmp_path))
        assert isinstance(results[0], ParsedDocument)

    def test_result_evidence_id_matches_catalog(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        _populate_catalog(tmp_path, [_make_entry("bse-p-a", "docs/a.txt")])
        results = parse_incremental(Repository(tmp_path), KnowledgeBase(tmp_path))
        assert results[0].evidence_id == "bse-p-a"


# ---------------------------------------------------------------------------
# Skip already-ok entries
# ---------------------------------------------------------------------------


class TestParseIncrementalSkipsOk:
    def test_skips_already_ok_entry(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        entry = _make_entry("bse-p-a", "docs/a.txt")
        _populate_catalog(tmp_path, [entry])
        kb = KnowledgeBase(tmp_path)
        kb.parse(entry)  # pre-parse
        results = parse_incremental(Repository(tmp_path), kb)
        assert results == []

    def test_all_ok_returns_empty(self, tmp_path: Path) -> None:
        for name in ("a", "b", "c"):
            _write(tmp_path, f"docs/{name}.txt")
        entries = [_make_entry(f"bse-p-{n}", f"docs/{n}.txt") for n in ("a", "b", "c")]
        _populate_catalog(tmp_path, entries)
        kb = KnowledgeBase(tmp_path)
        for e in entries:
            kb.parse(e)
        results = parse_incremental(Repository(tmp_path), kb)
        assert results == []

    def test_parses_only_new_entries(self, tmp_path: Path) -> None:
        for name in ("a", "b"):
            _write(tmp_path, f"docs/{name}.txt")
        entry_a = _make_entry("bse-p-a", "docs/a.txt")
        entry_b = _make_entry("bse-p-b", "docs/b.txt")
        _populate_catalog(tmp_path, [entry_a, entry_b])
        kb = KnowledgeBase(tmp_path)
        kb.parse(entry_a)  # only a is pre-parsed
        results = parse_incremental(Repository(tmp_path), kb)
        assert len(results) == 1
        assert results[0].evidence_id == "bse-p-b"


# ---------------------------------------------------------------------------
# Retry failed entries
# ---------------------------------------------------------------------------


class TestParseIncrementalRetryFailed:
    def test_retries_failed_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write(tmp_path, "docs/a.txt", "recovered content")
        entry = _make_entry("bse-p-a", "docs/a.txt")
        _populate_catalog(tmp_path, [entry])
        kb = KnowledgeBase(tmp_path)

        # First run: extractor fails.
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
        parse_incremental(Repository(tmp_path), kb)
        assert kb.get("bse-p-a") is not None
        assert kb.get("bse-p-a").status == "failed"  # type: ignore[union-attr]

        # Second run: extractor fixed.
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", lambda p: p.read_text(encoding="utf-8"))
        results = parse_incremental(Repository(tmp_path), kb)
        assert len(results) == 1
        assert results[0].status == "ok"

    def test_retries_unknown_extension_after_extractor_added(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write(tmp_path, "docs/a.zip", "zip content")
        entry = _make_entry("bse-p-a", "docs/a.zip")
        _populate_catalog(tmp_path, [entry])
        kb = KnowledgeBase(tmp_path)

        # First run: zip has no extractor → failed.
        parse_incremental(Repository(tmp_path), kb)
        assert kb.get("bse-p-a") is not None
        assert kb.get("bse-p-a").status == "failed"  # type: ignore[union-attr]

        # Second run: extractor registered.
        monkeypatch.setitem(ext_mod._EXTRACTORS, "zip", lambda p: p.read_text(encoding="utf-8"))
        results = parse_incremental(Repository(tmp_path), kb)
        assert len(results) == 1
        assert results[0].status == "ok"
