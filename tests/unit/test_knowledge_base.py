from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

import atlas.knowledge.extractors as ext_mod
from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.knowledge.base import PARSER_VERSION, KnowledgeBase, ParsedDocument


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raises(exc: Exception) -> Callable[[Path], str]:
    """Return an extractor that always raises exc. Used with monkeypatch.setitem."""
    def _extractor(_: Path) -> str:
        raise exc
    return _extractor

_SOURCE_DATE = "2024-01-01T00:00:00+00:00"
_ACQUIRED_AT = "2024-06-01T00:00:00+00:00"


def _make_entry(
    evidence_id: str = "bse-k-ar-001",
    local_path: str = "docs/report.txt",
    kind: EvidenceKind = EvidenceKind.ANNUAL_REPORT,
    title: str = "Test Document",
    source_date: str = _SOURCE_DATE,
) -> CatalogEntry:
    return CatalogEntry(
        evidence_id=evidence_id,
        source=EvidenceSource.BSE.value,
        kind=kind.value,
        title=title,
        source_date=source_date,
        document_url=None,
        local_path=local_path,
        file_size_bytes=None,
        acquired_at=_ACQUIRED_AT,
    )


def _write(root: Path, rel_path: str, content: str = "hello world") -> Path:
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestKnowledgeBaseConstruction:
    def test_creates_knowledge_db_in_root(self, tmp_path: Path) -> None:
        KnowledgeBase(tmp_path)
        assert (tmp_path / "knowledge.db").exists()

    def test_second_construction_does_not_raise(self, tmp_path: Path) -> None:
        KnowledgeBase(tmp_path)
        KnowledgeBase(tmp_path)  # idempotent schema init

    def test_known_ids_empty_on_new_db(self, tmp_path: Path) -> None:
        assert KnowledgeBase(tmp_path).known_ids() == frozenset()

    def test_ok_ids_empty_on_new_db(self, tmp_path: Path) -> None:
        assert KnowledgeBase(tmp_path).ok_ids() == frozenset()


# ---------------------------------------------------------------------------
# known_ids / ok_ids
# ---------------------------------------------------------------------------


class TestKnowledgeBaseKnownIds:
    def test_contains_id_after_successful_parse(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert "bse-k-a" in kb.known_ids()

    def test_contains_id_after_failed_parse(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(RuntimeError("boom")))
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert "bse-k-a" in kb.known_ids()

    def test_contains_id_for_unknown_extension(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.zip", b"PK".decode())
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.zip"))
        assert "bse-k-a" in kb.known_ids()

    def test_multiple_ids_all_present(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        _write(tmp_path, "docs/b.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        kb.parse(_make_entry("bse-k-b", "docs/b.txt"))
        assert kb.known_ids() == {"bse-k-a", "bse-k-b"}


class TestKnowledgeBaseOkIds:
    def test_contains_id_after_successful_parse(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert "bse-k-a" in kb.ok_ids()

    def test_excludes_id_after_failed_parse(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(RuntimeError("boom")))
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert "bse-k-a" not in kb.ok_ids()

    def test_excludes_id_for_unknown_extension(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.zip", b"PK".decode())
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.zip"))
        assert "bse-k-a" not in kb.ok_ids()

    def test_selects_only_ok_when_mixed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write(tmp_path, "docs/good.txt")
        _write(tmp_path, "docs/bad.zip")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-good", "docs/good.txt"))
        kb.parse(_make_entry("bse-k-bad", "docs/bad.zip"))
        assert kb.ok_ids() == {"bse-k-good"}


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestKnowledgeBaseGet:
    def test_returns_none_for_unknown_id(self, tmp_path: Path) -> None:
        assert KnowledgeBase(tmp_path).get("bse-k-missing") is None

    def test_returns_parsed_document_after_parse(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        result = kb.get("bse-k-a")
        assert isinstance(result, ParsedDocument)

    def test_evidence_id_matches(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert kb.get("bse-k-a") is not None
        assert kb.get("bse-k-a").evidence_id == "bse-k-a"  # type: ignore[union-attr]

    def test_returns_none_on_empty_db(self, tmp_path: Path) -> None:
        assert KnowledgeBase(tmp_path).get("bse-k-any") is None


# ---------------------------------------------------------------------------
# get_content
# ---------------------------------------------------------------------------


class TestKnowledgeBaseGetContent:
    def test_returns_none_for_unknown_id(self, tmp_path: Path) -> None:
        assert KnowledgeBase(tmp_path).get_content("bse-k-missing") is None

    def test_returns_text_after_successful_parse(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt", "hello world")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert kb.get_content("bse-k-a") == "hello world"

    def test_returns_none_after_failed_parse(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(RuntimeError("boom")))
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert kb.get_content("bse-k-a") is None

    def test_returns_none_for_unknown_extension(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.zip")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.zip"))
        assert kb.get_content("bse-k-a") is None

    def test_content_round_trips_unicode(self, tmp_path: Path) -> None:
        text = "₹ crore — FY2024 अनुपालन"
        _write(tmp_path, "docs/a.txt", text)
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert kb.get_content("bse-k-a") == text


# ---------------------------------------------------------------------------
# parse — successful extraction
# ---------------------------------------------------------------------------


class TestKnowledgeBaseParseSuccess:
    def test_status_ok(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt", "content")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.status == "ok"

    def test_error_is_none(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt", "content")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.error is None

    def test_char_count_matches_content(self, tmp_path: Path) -> None:
        text = "hello world"
        _write(tmp_path, "docs/a.txt", text)
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.char_count == len(text)

    def test_local_path_stored(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.local_path == "docs/a.txt"

    def test_parser_version_stored(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.parser_version == PARSER_VERSION

    def test_metadata_from_catalog_entry(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        entry = _make_entry(
            "bse-k-a",
            "docs/a.txt",
            kind=EvidenceKind.EARNINGS_TRANSCRIPT,
            title="Q1 Transcript",
            source_date="2023-07-31T00:00:00+00:00",
        )
        doc = KnowledgeBase(tmp_path).parse(entry)
        assert doc.kind == EvidenceKind.EARNINGS_TRANSCRIPT.value
        assert doc.title == "Q1 Transcript"
        assert doc.source_date == "2023-07-31T00:00:00+00:00"

    def test_parsed_at_is_set(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        before = datetime.now(timezone.utc)
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        after = datetime.now(timezone.utc)
        assert before <= doc.parsed_at <= after

    def test_empty_file_gives_zero_char_count(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt", "")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.status == "ok"
        assert doc.char_count == 0


# ---------------------------------------------------------------------------
# parse — unknown extension
# ---------------------------------------------------------------------------


class TestKnowledgeBaseParseUnknownExtension:
    def test_status_failed(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.zip")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.zip"))
        assert doc.status == "failed"

    def test_error_mentions_extension(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.zip")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.zip"))
        assert doc.error is not None
        assert ".zip" in doc.error

    def test_char_count_is_none(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.zip")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.zip"))
        assert doc.char_count is None

    def test_id_recorded_in_known_ids(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.zip")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.zip"))
        assert "bse-k-a" in kb.known_ids()

    def test_no_extension_error_mentions_none(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/noext")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/noext"))
        assert doc.status == "failed"
        assert doc.error is not None
        assert "(none)" in doc.error


# ---------------------------------------------------------------------------
# parse — extractor raises
# ---------------------------------------------------------------------------


class TestKnowledgeBaseParseExtractorRaises:
    def test_status_failed_on_exception(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(OSError("disk error")))
        _write(tmp_path, "docs/a.txt")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.status == "failed"

    def test_error_message_captured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(OSError("disk error")))
        _write(tmp_path, "docs/a.txt")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.error == "disk error"

    def test_char_count_is_none_on_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(ValueError("bad")))
        _write(tmp_path, "docs/a.txt")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.char_count is None

    def test_does_not_raise_to_caller(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(RuntimeError("crash")))
        _write(tmp_path, "docs/a.txt")
        # Must not propagate the exception.
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.status == "failed"


# ---------------------------------------------------------------------------
# parse — idempotence and retry
# ---------------------------------------------------------------------------


class TestKnowledgeBaseParseidempotence:
    def test_second_ok_parse_replaces_first(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt", "v1")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        (tmp_path / "docs/a.txt").write_text("v2", encoding="utf-8")
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert kb.get_content("bse-k-a") == "v2"

    def test_failed_becomes_ok_on_retry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(RuntimeError("boom")))
        _write(tmp_path, "docs/a.txt", "recovered")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert kb.get("bse-k-a") is not None
        assert kb.get("bse-k-a").status == "failed"  # type: ignore[union-attr]

        # Restore a working extractor and re-parse.
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", lambda p: p.read_text(encoding="utf-8"))
        doc = kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.status == "ok"
        assert kb.get_content("bse-k-a") == "recovered"

    def test_id_still_in_known_ids_after_retry(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert "bse-k-a" in kb.known_ids()

    def test_parse_returns_document_on_reparse(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        doc = kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert isinstance(doc, ParsedDocument)


# ---------------------------------------------------------------------------
# Text extraction — real .txt and .xml files (no monkeypatching)
# ---------------------------------------------------------------------------


class TestKnowledgeBaseTextExtractors:
    def test_txt_file_content_extracted(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/report.txt", "annual revenue: 100")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-x", "docs/report.txt"))
        assert doc.status == "ok"
        assert "annual revenue" in (KnowledgeBase(tmp_path).get_content("bse-k-x") or "")

    def test_xml_file_content_extracted(self, tmp_path: Path) -> None:
        xml = "<root><value>42</value></root>"
        _write(tmp_path, "filings/data.xml", xml)
        entry = _make_entry("bse-k-xml", "filings/data.xml")
        kb = KnowledgeBase(tmp_path)
        doc = kb.parse(entry)
        assert doc.status == "ok"
        assert "42" in (kb.get_content("bse-k-xml") or "")

    def test_json_file_content_extracted(self, tmp_path: Path) -> None:
        _write(tmp_path, "data/result.json", '{"key": "value"}')
        entry = _make_entry("bse-k-json", "data/result.json")
        kb = KnowledgeBase(tmp_path)
        kb.parse(entry)
        assert "value" in (kb.get_content("bse-k-json") or "")

    def test_csv_file_content_extracted(self, tmp_path: Path) -> None:
        _write(tmp_path, "data/table.csv", "quarter,revenue\nQ1,100\nQ2,200")
        entry = _make_entry("bse-k-csv", "data/table.csv")
        kb = KnowledgeBase(tmp_path)
        kb.parse(entry)
        assert "revenue" in (kb.get_content("bse-k-csv") or "")

    def test_missing_file_produces_failed_status(self, tmp_path: Path) -> None:
        entry = _make_entry("bse-k-gone", "docs/gone.txt")
        doc = KnowledgeBase(tmp_path).parse(entry)
        assert doc.status == "failed"
        assert doc.error is not None
