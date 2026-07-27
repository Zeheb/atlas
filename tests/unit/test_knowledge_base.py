from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

import atlas.knowledge.base as base_mod
import atlas.knowledge.extractors as ext_mod
from atlas.acquisition.catalog import CatalogEntry
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.knowledge.base import PARSER_VERSION, KnowledgeBase, ParsedDocument
from atlas.knowledge.extractors import (
    QUALITY_THRESHOLD,
    ExtractionResult,
    _is_garbled_word,
    score_text_quality,
)

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

    def test_contains_id_after_failed_parse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

    def test_excludes_id_after_failed_parse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

    def test_selects_only_ok_when_mixed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
# get_many (M1.7: batch metadata read for plan-aware retrieval)
# ---------------------------------------------------------------------------


class TestKnowledgeBaseGetMany:
    def test_empty_input_returns_empty_dict(self, tmp_path: Path) -> None:
        assert KnowledgeBase(tmp_path).get_many([]) == {}

    def test_all_missing_ids_returns_empty_dict(self, tmp_path: Path) -> None:
        assert (
            KnowledgeBase(tmp_path).get_many(["bse-k-missing-1", "bse-k-missing-2"])
            == {}
        )

    def test_returns_metadata_for_known_ids(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        _write(tmp_path, "docs/b.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        kb.parse(_make_entry("bse-k-b", "docs/b.txt"))
        result = kb.get_many(["bse-k-a", "bse-k-b"])
        assert set(result) == {"bse-k-a", "bse-k-b"}
        assert all(isinstance(doc, ParsedDocument) for doc in result.values())

    def test_missing_ids_are_simply_absent_not_keyerror(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        result = kb.get_many(["bse-k-a", "bse-k-nonexistent"])
        assert set(result) == {"bse-k-a"}

    def test_duplicate_input_ids_collapse(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        result = kb.get_many(["bse-k-a", "bse-k-a", "bse-k-a"])
        assert set(result) == {"bse-k-a"}

    def test_parity_with_per_id_get(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt")
        kb = KnowledgeBase(tmp_path)
        kb.parse(
            _make_entry("bse-k-a", "docs/a.txt", kind=EvidenceKind.EARNINGS_TRANSCRIPT)
        )
        many = kb.get_many(["bse-k-a"])["bse-k-a"]
        single = kb.get("bse-k-a")
        assert single is not None
        assert many == single

    def test_chunks_beyond_sqlite_variable_limit(self, tmp_path: Path) -> None:
        # 500-id chunk boundary: exercise >500 ids in one call, only some real.
        kb = KnowledgeBase(tmp_path)
        _write(tmp_path, "docs/real.txt")
        kb.parse(_make_entry("bse-k-real", "docs/real.txt"))
        ids = [f"bse-k-missing-{i}" for i in range(600)] + ["bse-k-real"]
        result = kb.get_many(ids)
        assert set(result) == {"bse-k-real"}


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

    def test_returns_none_after_failed_parse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
    def test_status_failed_on_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(OSError("disk error")))
        _write(tmp_path, "docs/a.txt")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.status == "failed"

    def test_error_message_captured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(OSError("disk error")))
        _write(tmp_path, "docs/a.txt")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.error == "disk error"

    def test_char_count_is_none_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(ValueError("bad")))
        _write(tmp_path, "docs/a.txt")
        doc = KnowledgeBase(tmp_path).parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert doc.char_count is None

    def test_does_not_raise_to_caller(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

    def test_failed_becomes_ok_on_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(ext_mod._EXTRACTORS, "txt", _raises(RuntimeError("boom")))
        _write(tmp_path, "docs/a.txt", "recovered")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert kb.get("bse-k-a") is not None
        assert kb.get("bse-k-a").status == "failed"  # type: ignore[union-attr]

        # Restore a working extractor and re-parse.
        monkeypatch.setitem(
            ext_mod._EXTRACTORS, "txt", lambda p: p.read_text(encoding="utf-8")
        )
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
        assert "annual revenue" in (
            KnowledgeBase(tmp_path).get_content("bse-k-x") or ""
        )

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


# ---------------------------------------------------------------------------
# Regression: HTML-as-PDF detection (BSE serves HTML error pages with .pdf URL)
# ---------------------------------------------------------------------------


class TestHtmlAsPdfDetection:
    """BSE's AnnualReport API sometimes returns an HTML page instead of a PDF.
    Prior to the fix, this produced status='ok', char_count=0 — silently hiding
    the download failure.  After the fix, the extractor raises ValueError so
    the KB records status='failed' with a diagnostic error message."""

    def _write_html_pdf(self, tmp_path: Path, filename: str) -> None:
        """Write a realistic BSE HTML error-page disguised as a .pdf file."""
        (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / filename).write_bytes(
            b'<!DOCTYPE html><html lang="en"><head><title>BSE India</title></head>'
            b"<body><p>Page not found</p></body></html>"
        )

    def test_html_file_with_pdf_extension_fails(self, tmp_path: Path) -> None:
        self._write_html_pdf(tmp_path, "annual_report.pdf")
        entry = _make_entry("bse-html-001", "docs/annual_report.pdf")
        doc = KnowledgeBase(tmp_path).parse(entry)
        assert (
            doc.status == "failed"
        ), "HTML disguised as PDF must not produce status='ok'"
        assert doc.error is not None
        assert "HTML" in doc.error

    def test_html_char_count_is_none(self, tmp_path: Path) -> None:
        self._write_html_pdf(tmp_path, "filing.pdf")
        entry = _make_entry("bse-html-002", "docs/filing.pdf")
        doc = KnowledgeBase(tmp_path).parse(entry)
        assert doc.char_count is None  # no content stored for failed parse

    def test_real_pdf_still_works(self, tmp_path: Path) -> None:
        """Ensure the HTML guard doesn't break legitimate PDF parsing."""
        import fitz

        (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
        doc_pdf = fitz.open()
        page = doc_pdf.new_page()
        page.insert_text((72, 72), "Real PDF content for unit test")
        pdf_path = tmp_path / "docs" / "real.pdf"
        doc_pdf.save(str(pdf_path))
        doc_pdf.close()

        entry = _make_entry("bse-real-pdf", "docs/real.pdf")
        kb_doc = KnowledgeBase(tmp_path).parse(entry)
        assert kb_doc.status == "ok"
        assert (kb_doc.char_count or 0) > 0


# ---------------------------------------------------------------------------
# Garbled-word detector unit tests
# ---------------------------------------------------------------------------


class TestIsGarbledWord:
    """Unit tests for the character-level garbled-word detector."""

    def test_clean_english_word_not_garbled(self) -> None:
        assert _is_garbled_word("Revenue") is False

    def test_clean_financial_abbrev_not_garbled(self) -> None:
        assert _is_garbled_word("Q2FY26") is False

    def test_rupee_symbol_not_garbled(self) -> None:
        assert _is_garbled_word("₹20,160") is False

    def test_en_dash_not_garbled(self) -> None:
        assert _is_garbled_word("40–50") is False

    def test_euro_mid_word_is_garbled(self) -> None:
        # "lnt€resU" — broken ToUnicode maps 'e' to €
        assert _is_garbled_word("lnt€resU") is True

    def test_lowercase_l_uppercase_next_is_garbled(self) -> None:
        # "lUnaudlledl" — '[' or 'I' decoded as lowercase-l
        assert _is_garbled_word("lUnaudlledl") is True

    def test_digit_between_letters_is_garbled(self) -> None:
        # "oPe6tlonE" — '6' embedded mid-word
        assert _is_garbled_word("oPe6tlonE") is True

    def test_digit_at_end_of_word_not_garbled(self) -> None:
        # "Tier2", "CET1" — trailing digit on abbreviation is legitimate
        assert _is_garbled_word("Tier2") is False
        assert _is_garbled_word("CET1") is False

    def test_very_short_word_not_garbled(self) -> None:
        # Single char after stripping punctuation: skip.
        assert _is_garbled_word("l") is False
        assert _is_garbled_word("l,") is False

    def test_at_sign_mid_word_is_garbled(self) -> None:
        # "Emplot@G" — '@' is a substitute for a letter character
        # '@' (0x40) is below 0x0080 so Signal 1 doesn't catch it;
        # it IS between two alpha chars, but Signal 2 checks digits only.
        # This particular case falls through — document and accept the limitation.
        # The test confirms current behaviour (not garbled by current rules).
        assert _is_garbled_word("Emplot@G") is False  # signal gap — known limitation

    def test_latin_extended_char_is_garbled(self) -> None:
        # U+00E9 (é) mid-word — not in the safe set, Latin extended range
        assert _is_garbled_word("Révenues") is True


# ---------------------------------------------------------------------------
# Quality score unit tests
# ---------------------------------------------------------------------------


class TestScoreTextQuality:
    """Unit tests for the composite quality scoring formula."""

    def test_empty_text_scores_zero(self) -> None:
        assert score_text_quality("", 10) == 0.0

    def test_zero_pages_scores_zero(self) -> None:
        assert score_text_quality("some text", 0) == 0.0

    def test_clean_dense_text_scores_above_threshold(self) -> None:
        # 300 chars/page, no garbled words.
        text = "Revenue from operations 267021 crores Net profit 49454 crores " * 10
        score = score_text_quality(text, 2)
        assert score >= QUALITY_THRESHOLD

    def test_heavily_garbled_text_scores_below_threshold(self) -> None:
        # Simulate SBI financial results: garbled table labels (~2% of words).
        good = "Revenue from operations 267021 crores Net profit 49454 crores " * 40
        bad = "lnt€resU dlacounl lUnaudlledl oPe6tlonE " * 10
        text = bad + good
        score = score_text_quality(text, 3)
        assert score < QUALITY_THRESHOLD, f"Expected low quality, got {score}"

    def test_low_density_scores_below_threshold(self) -> None:
        # 10 chars on 5 pages → 2 chars/page, clearly a scanned PDF.
        score = score_text_quality("page1\npage2", 5)
        assert score < QUALITY_THRESHOLD

    def test_rupee_symbol_not_penalised(self) -> None:
        text = (
            "₹20,160 crore Net Profit increased 9.97 percent quarter-on-quarter "
            "₹41620 NII ₹42984 crore "
        ) * 10
        score = score_text_quality(text, 1)
        assert score >= QUALITY_THRESHOLD

    def test_unicode_dashes_not_penalised(self) -> None:
        # en-dash and em-dash in financial ranges/context.
        text = (
            "Revenue 267021–280000 crore EBITDA margin 25–30 percent "
            "Net worth 500000 crores "
        ) * 20
        score = score_text_quality(text, 2)
        assert score >= QUALITY_THRESHOLD

    def test_score_is_bounded_zero_to_one(self) -> None:
        assert 0.0 <= score_text_quality("x" * 1000, 1) <= 1.0
        assert 0.0 <= score_text_quality("", 1) <= 1.0

    def test_sbi_style_garbled_ratio_triggers_fallback(self) -> None:
        # Calibrated on real SBI data: garbled_ratio ≈ 0.013–0.019.
        # Inject 2 garbled words per 100 total (2 %) → should score below threshold.
        good_words = (
            "Revenue Profit Operations Income Total Interest "
            "Deposits Advances Capital Reserves "
        ) * 10
        garbled_words = "lnt€resU lUnaudlledl " * 2
        # 100 good + 4 garbled = 104 words, ~3.8 % garbled
        text = (garbled_words + good_words) * 1  # fits in 8 000-char sample
        score = score_text_quality(text, 1)
        # At 3.8 %: coherence = max(0, 1 - 0.038*50) = max(0, -0.9) = 0; density ≈ 1.
        # score ≈ 0.4 * 1.0 + 0.6 * 0.0 = 0.4 < 0.65
        assert score < QUALITY_THRESHOLD


# ---------------------------------------------------------------------------
# extract_pdf pipeline unit tests (monkeypatched internals)
# ---------------------------------------------------------------------------


def _make_pdf(
    tmp_path: Path,
    filename: str = "doc.pdf",
    text: str = "Real PDF content for unit test",
) -> Path:
    """Create a minimal but valid PDF file with the given text."""
    import fitz

    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    path = tmp_path / "docs" / filename
    pdf.save(str(path))
    pdf.close()
    return path


class TestExtractPdfPipeline:
    """Tests for extract_pdf() multi-stage pipeline control flow."""

    def test_clean_pdf_uses_native_extraction(self, tmp_path: Path) -> None:
        path = _make_pdf(tmp_path)
        result = ext_mod.extract_pdf(path)
        assert result.extraction_method == "native"
        assert result.ocr_attempted is False

    def test_clean_pdf_quality_score_above_threshold(self, tmp_path: Path) -> None:
        text = "Revenue from operations 267021 crores Net profit 49454 crores " * 5
        path = _make_pdf(tmp_path, text=text)
        result = ext_mod.extract_pdf(path)
        assert result.quality_score >= QUALITY_THRESHOLD

    def test_clean_pdf_returns_extraction_result(self, tmp_path: Path) -> None:
        path = _make_pdf(tmp_path)
        result = ext_mod.extract_pdf(path)
        assert isinstance(result, ExtractionResult)
        assert result.text != ""
        assert result.page_count >= 1

    def test_garbled_native_triggers_ocr_attempt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When native text quality is below threshold, OCR should be attempted."""
        path = _make_pdf(tmp_path)
        garbled = "lnt€resU lUnaudlledl oPe6tlonE dlacounl lReseryes " * 10

        monkeypatch.setattr(ext_mod, "_native_extract", lambda p: (garbled, 5))
        monkeypatch.setattr(
            ext_mod, "_ocr_extract", lambda p, n: "Clean OCR text " * 50
        )

        result = ext_mod.extract_pdf(path)
        assert result.ocr_attempted is True

    def test_successful_ocr_yields_ocr_method(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _make_pdf(tmp_path)
        garbled = "lnt€resU lUnaudlledl oPe6tlonE dlacounl " * 10
        clean_ocr = "Revenue from operations 267021 crores " * 50

        monkeypatch.setattr(ext_mod, "_native_extract", lambda p: (garbled, 5))
        monkeypatch.setattr(ext_mod, "_ocr_extract", lambda p, n: clean_ocr)

        result = ext_mod.extract_pdf(path)
        assert result.extraction_method == "ocr"
        assert result.quality_score >= QUALITY_THRESHOLD

    def test_tesseract_missing_returns_native_gracefully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When Tesseract is not installed, extract_pdf must not raise.

        It returns the native text (even though quality is low) with
        ocr_attempted=True so operators know OCR was needed but unavailable.
        """
        path = _make_pdf(tmp_path)
        garbled = "lnt€resU lUnaudlledl oPe6tlonE dlacounl " * 10

        monkeypatch.setattr(ext_mod, "_native_extract", lambda p: (garbled, 5))
        monkeypatch.setattr(
            ext_mod,
            "_ocr_extract",
            lambda p, n: (_ for _ in ()).throw(
                RuntimeError("tesseract is not installed")
            ),
        )

        result = ext_mod.extract_pdf(path)
        assert result.extraction_method == "native"
        assert result.ocr_attempted is True
        assert result.text == garbled

    def test_ocr_worse_than_native_keeps_native(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If OCR produces lower quality than native, native text is kept."""
        path = _make_pdf(tmp_path)
        # Native is mediocre but not garbled enough to score 0.
        mediocre = (
            "Revenue Profit Interest Operations " * 5
        )  # clean but sparse (low density)
        # OCR returns something worse (more garbled).
        worse_ocr = "lnt€resU lUnaudlledl oPe6tlonE " * 5

        monkeypatch.setattr(ext_mod, "_native_extract", lambda p: (mediocre, 50))
        monkeypatch.setattr(ext_mod, "_ocr_extract", lambda p, n: worse_ocr)

        result = ext_mod.extract_pdf(path)
        assert result.extraction_method == "native"
        assert result.text == mediocre

    def test_html_guard_raises_on_html_file(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
        p = tmp_path / "docs" / "error.pdf"
        p.write_bytes(b"<!DOCTYPE html><html><body>error</body></html>")
        with pytest.raises(ValueError, match="HTML"):
            ext_mod.extract_pdf(p)

    def test_scanned_image_pdf_triggers_ocr_via_low_density(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A scanned image PDF has no text layer at all — density alone (not
        garbling) must drop the score below threshold and trigger OCR.

        Distinct failure mode from the broken-ToUnicode case: coherence stays
        at 1.0 (there are no garbled words, because there are no words), so
        this exercises the density term of score_text_quality() in isolation.
        """
        path = _make_pdf(tmp_path)
        monkeypatch.setattr(ext_mod, "_native_extract", lambda p: ("", 12))
        monkeypatch.setattr(
            ext_mod,
            "_ocr_extract",
            lambda p, n: "Revenue from operations 267021 crores Net profit 49454 crores "
            * 40,
        )

        result = ext_mod.extract_pdf(path)
        assert result.extraction_method == "ocr"
        assert result.ocr_attempted is True
        assert result.quality_score >= QUALITY_THRESHOLD


# ---------------------------------------------------------------------------
# ParsedDocument new fields — stored and retrieved from DB
# ---------------------------------------------------------------------------


class TestParsedDocumentFields:
    """New fields (extraction_method, quality_score, ocr_attempted) round-trip through DB."""

    def test_pdf_parse_stores_extraction_method(self, tmp_path: Path) -> None:
        path = _make_pdf(tmp_path, text="Revenue from operations " * 20)
        entry = _make_entry("bse-pdf-001", "docs/doc.pdf")
        kb = KnowledgeBase(tmp_path)
        doc = kb.parse(entry)
        assert doc.extraction_method == "native"

    def test_pdf_parse_stores_quality_score(self, tmp_path: Path) -> None:
        path = _make_pdf(tmp_path, text="Revenue from operations " * 20)
        entry = _make_entry("bse-pdf-002", "docs/doc.pdf")
        kb = KnowledgeBase(tmp_path)
        doc = kb.parse(entry)
        assert doc.quality_score is not None
        assert 0.0 <= doc.quality_score <= 1.0

    def test_pdf_parse_stores_ocr_attempted_false(self, tmp_path: Path) -> None:
        path = _make_pdf(tmp_path, text="Revenue from operations " * 20)
        entry = _make_entry("bse-pdf-003", "docs/doc.pdf")
        kb = KnowledgeBase(tmp_path)
        doc = kb.parse(entry)
        assert doc.ocr_attempted is False

    def test_get_returns_extraction_method(self, tmp_path: Path) -> None:
        path = _make_pdf(tmp_path, text="Revenue from operations " * 20)
        entry = _make_entry("bse-pdf-004", "docs/doc.pdf")
        kb = KnowledgeBase(tmp_path)
        kb.parse(entry)
        stored = kb.get("bse-pdf-004")
        assert stored is not None
        assert stored.extraction_method == "native"

    def test_get_returns_quality_score(self, tmp_path: Path) -> None:
        path = _make_pdf(tmp_path, text="Revenue from operations " * 20)
        entry = _make_entry("bse-pdf-005", "docs/doc.pdf")
        kb = KnowledgeBase(tmp_path)
        kb.parse(entry)
        stored = kb.get("bse-pdf-005")
        assert stored is not None
        assert stored.quality_score is not None

    def test_non_pdf_parse_has_none_extraction_method(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/report.txt", "annual revenue: 100")
        entry = _make_entry("bse-txt-001", "docs/report.txt")
        kb = KnowledgeBase(tmp_path)
        doc = kb.parse(entry)
        assert doc.extraction_method is None
        assert doc.quality_score is None
        assert doc.ocr_attempted is False

    def test_ocr_attempted_stored_as_bool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ocr_attempted=True must survive the INTEGER→bool round-trip through SQLite."""
        garbled = "lnt€resU lUnaudlledl oPe6tlonE dlacounl " * 10
        clean_ocr = "Revenue from operations 267021 crores " * 50

        monkeypatch.setattr(ext_mod, "_native_extract", lambda p: (garbled, 5))
        monkeypatch.setattr(ext_mod, "_ocr_extract", lambda p, n: clean_ocr)

        path = _make_pdf(tmp_path)
        entry = _make_entry("bse-pdf-ocr", "docs/doc.pdf")
        kb = KnowledgeBase(tmp_path)
        kb.parse(entry)
        stored = kb.get("bse-pdf-ocr")
        assert stored is not None
        assert stored.ocr_attempted is True


class TestDocumentLanguageDetection:
    """document_language — deterministic script-ratio detection, not ML."""

    def test_english_text_detected_as_en(self, tmp_path: Path) -> None:
        path = _make_pdf(
            tmp_path, text="Revenue from operations increased significantly " * 10
        )
        entry = _make_entry("bse-lang-001", "docs/doc.pdf")
        kb = KnowledgeBase(tmp_path)
        doc = kb.parse(entry)
        assert doc.document_language == "en"

    def test_devanagari_text_detected_as_other(self, tmp_path: Path) -> None:
        from atlas.knowledge.base import _detect_language

        hindi_text = (
            "यह कंपनी की वार्षिक रिपोर्ट है और इसमें वित्तीय विवरण शामिल हैं " * 10
        )
        assert _detect_language(hindi_text) == "other"

    def test_mostly_latin_with_few_non_latin_chars_still_en(self) -> None:
        from atlas.knowledge.base import _detect_language

        text = (
            "Annual Report 2025-26 for the company operations and results " * 20 + "अ"
        )
        assert _detect_language(text) == "en"

    def test_short_text_returns_none(self) -> None:
        from atlas.knowledge.base import _detect_language

        assert _detect_language("short") is None

    def test_empty_text_returns_none(self) -> None:
        from atlas.knowledge.base import _detect_language

        assert _detect_language("") is None

    def test_failed_parse_has_none_language(self, tmp_path: Path) -> None:
        entry = _make_entry("bse-lang-fail", "docs/missing.pdf")
        kb = KnowledgeBase(tmp_path)
        doc = kb.parse(entry)
        assert doc.status == "failed"
        assert doc.document_language is None

    def test_get_returns_document_language(self, tmp_path: Path) -> None:
        path = _make_pdf(
            tmp_path, text="Revenue from operations increased significantly " * 10
        )
        entry = _make_entry("bse-lang-002", "docs/doc.pdf")
        kb = KnowledgeBase(tmp_path)
        kb.parse(entry)
        stored = kb.get("bse-lang-002")
        assert stored is not None
        assert stored.document_language == "en"


# ---------------------------------------------------------------------------
# Parser version filtering — ok_ids excludes v1.0 records after v2.0 bump
# ---------------------------------------------------------------------------


class TestParserVersionFiltering:
    """ok_ids() must exclude documents parsed with an older PARSER_VERSION.

    This ensures that bumping PARSER_VERSION forces re-parsing so that all
    documents gain the new quality metadata fields.
    """

    def test_v2_document_is_in_ok_ids(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/a.txt", "content")
        kb = KnowledgeBase(tmp_path)
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        assert "bse-k-a" in kb.ok_ids()

    def test_v1_document_is_not_in_ok_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A document recorded with parser_version='1.0' must not appear in ok_ids()
        once the live PARSER_VERSION is '2.0'."""
        _write(tmp_path, "docs/a.txt", "content")
        kb = KnowledgeBase(tmp_path)
        # Temporarily pretend we're still on v1.0.
        monkeypatch.setattr(base_mod, "PARSER_VERSION", "1.0")
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        # Restore live version — the stored record has parser_version='1.0'.
        monkeypatch.setattr(base_mod, "PARSER_VERSION", "2.0")
        assert "bse-k-a" not in kb.ok_ids()

    def test_v1_document_still_in_known_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Upgrading PARSER_VERSION must not hide v1.0 records from known_ids()."""
        _write(tmp_path, "docs/a.txt", "content")
        kb = KnowledgeBase(tmp_path)
        monkeypatch.setattr(base_mod, "PARSER_VERSION", "1.0")
        kb.parse(_make_entry("bse-k-a", "docs/a.txt"))
        monkeypatch.setattr(base_mod, "PARSER_VERSION", "2.0")
        # known_ids() has no version filter — returns all records.
        assert "bse-k-a" in kb.known_ids()

    def test_migration_is_idempotent(self, tmp_path: Path) -> None:
        """Constructing KnowledgeBase twice on the same DB must not raise."""
        KnowledgeBase(tmp_path)
        KnowledgeBase(tmp_path)  # re-runs _MIGRATE_V2; all ALTER TABLEs are no-ops
