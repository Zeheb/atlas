import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from atlas.acquisition.catalog import CatalogEntry
from atlas.knowledge import extractors as _ext

PARSER_VERSION = "2.0"

_CREATE_TABLES = """
    CREATE TABLE IF NOT EXISTS parsed_documents (
        evidence_id       TEXT PRIMARY KEY,
        kind              TEXT NOT NULL,
        title             TEXT NOT NULL,
        source_date       TEXT NOT NULL,
        local_path        TEXT NOT NULL,
        parsed_at         TEXT NOT NULL,
        parser_version    TEXT NOT NULL,
        status            TEXT NOT NULL,
        error             TEXT,
        char_count        INTEGER,
        extraction_method TEXT,
        quality_score     REAL,
        ocr_attempted     INTEGER NOT NULL DEFAULT 0,
        page_count        INTEGER,
        document_language TEXT
    );
    CREATE TABLE IF NOT EXISTS document_contents (
        evidence_id TEXT PRIMARY KEY,
        content     TEXT
    );
"""

# Columns added in parser_version 2.0.  Applied as a migration when the DB
# was originally created by parser_version 1.0.
_MIGRATE_V2 = [
    "ALTER TABLE parsed_documents ADD COLUMN extraction_method TEXT",
    "ALTER TABLE parsed_documents ADD COLUMN quality_score REAL",
    "ALTER TABLE parsed_documents ADD COLUMN ocr_attempted INTEGER NOT NULL DEFAULT 0",
]

# Column added in parser_version 3.0 — page_count was already computed by
# extract_pdf() (needed for its own OCR-fallback quality scoring) but
# discarded before reaching ParsedDocument, the same "computed then thrown
# away" pattern found in bse_parser.py's fiscal-year/quarter handling.
# Needed as a real, persisted signal for the document classifier (Stage 2):
# a 1-2 page "document" is structurally very unlikely to be the investor
# deck / transcript / annual report its title claims, regardless of what
# the title says.
_MIGRATE_V3 = [
    "ALTER TABLE parsed_documents ADD COLUMN page_count INTEGER",
]

# Column added in parser_version 4.0 — the acquisition-hardening sprint's
# metadata-completeness pass (Stage 2). Detected deterministically from
# extracted text (see _detect_language()), not ML — a coarse Latin-vs-other
# script ratio, sufficient to flag the (currently unobserved, but possible)
# case of a vernacular-language filing without pretending to identify which
# language it is.
_MIGRATE_V4 = [
    "ALTER TABLE parsed_documents ADD COLUMN document_language TEXT",
]

# Devanagari (Hindi/Marathi), Bengali, Tamil, Telugu, Gujarati unicode
# blocks — the scripts most likely to appear in an Indian regulatory
# filing that isn't in English. Not exhaustive of every Indian script;
# covers the common ones without pretending to be a real language
# detector.
_NON_LATIN_SCRIPT_RANGES = (
    (0x0900, 0x097F),  # Devanagari
    (0x0980, 0x09FF),  # Bengali
    (0x0B80, 0x0BFF),  # Tamil
    (0x0C00, 0x0C7F),  # Telugu
    (0x0A80, 0x0AFF),  # Gujarati
)


def _detect_language(text: str) -> str | None:
    """Classify extracted text as "en" or "other" by script composition.

    Deterministic character-range counting, not ML — counts alphabetic
    characters falling in known non-Latin Indian-script Unicode blocks
    against total alphabetic characters. Returns None if there isn't
    enough alphabetic content to judge (e.g. a near-empty extraction).
    """
    non_latin = 0
    total_alpha = 0
    for ch in text:
        if not ch.isalpha():
            continue
        total_alpha += 1
        codepoint = ord(ch)
        if any(lo <= codepoint <= hi for lo, hi in _NON_LATIN_SCRIPT_RANGES):
            non_latin += 1
    if total_alpha < 50:
        return None
    return "other" if (non_latin / total_alpha) > 0.3 else "en"


@dataclass
class ParsedDocument:
    evidence_id: str
    kind: str
    title: str
    source_date: str
    local_path: str
    parsed_at: datetime
    parser_version: str
    status: Literal["ok", "failed"]
    error: str | None = None
    char_count: int | None = None
    extraction_method: Literal["native", "ocr"] | None = None
    quality_score: float | None = None
    ocr_attempted: bool = False
    page_count: int | None = None
    document_language: str | None = None


def _row_to_doc(row: sqlite3.Row) -> ParsedDocument:
    keys = row.keys()
    return ParsedDocument(
        evidence_id=row["evidence_id"],
        kind=row["kind"],
        title=row["title"],
        source_date=row["source_date"],
        local_path=row["local_path"],
        parsed_at=datetime.fromisoformat(row["parsed_at"]),
        parser_version=row["parser_version"],
        status=row["status"],
        error=row["error"],
        char_count=row["char_count"],
        extraction_method=row["extraction_method"] if "extraction_method" in keys else None,
        quality_score=row["quality_score"] if "quality_score" in keys else None,
        ocr_attempted=bool(row["ocr_attempted"]) if "ocr_attempted" in keys else False,
        page_count=row["page_count"] if "page_count" in keys else None,
        document_language=row["document_language"] if "document_language" in keys else None,
    )


class KnowledgeBase:
    """Content extraction and persistence layer for acquired evidence.

    Stores extracted text alongside parsing metadata in a SQLite database
    at {root}/knowledge.db, keyed by evidence_id.

    Parsing is idempotent: calling parse() again replaces any prior record,
    including failures, allowing retries after adding a new extractor or
    fixing a broken file.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._db_path = root / "knowledge.db"
        self._init_db()

    @contextmanager
    def _db_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.executescript(_CREATE_TABLES)
            # Idempotent migrations: add columns from later parser_versions
            # to databases created by an earlier one.
            for stmt in _MIGRATE_V2 + _MIGRATE_V3 + _MIGRATE_V4:
                try:
                    conn.execute(stmt)
                    conn.commit()
                except sqlite3.OperationalError:
                    # Column already exists — silently skip.
                    pass
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Existence queries
    # ------------------------------------------------------------------

    def known_ids(self) -> frozenset[str]:
        """Return all evidence_ids with a parsing record (any status)."""
        with self._db_conn() as conn:
            rows = conn.execute(
                "SELECT evidence_id FROM parsed_documents"
            ).fetchall()
        return frozenset(row[0] for row in rows)

    def ok_ids(self) -> frozenset[str]:
        """Return evidence_ids whose last parse produced usable content.

        Two exclusion rules:
        1. char_count = 0 — HTML-as-PDF or empty files that silently produced
           no text; must be re-parsed after the HTML-detection fix.
        2. parser_version != PARSER_VERSION — documents parsed by an older
           pipeline version must be re-processed to populate quality metadata
           (extraction_method, quality_score) introduced in v2.0.
        """
        with self._db_conn() as conn:
            rows = conn.execute(
                "SELECT evidence_id FROM parsed_documents"
                " WHERE status = 'ok'"
                " AND COALESCE(char_count, 0) > 0"
                " AND parser_version = ?",
                (PARSER_VERSION,),
            ).fetchall()
        return frozenset(row[0] for row in rows)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, evidence_id: str) -> ParsedDocument | None:
        """Return parsing metadata for an evidence ID, or None if not recorded."""
        with self._db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM parsed_documents WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        return _row_to_doc(row) if row is not None else None

    def get_content(self, evidence_id: str) -> str | None:
        """Return extracted content for an evidence ID.

        Returns None if the evidence has never been parsed, if parsing failed,
        or if the document yielded no extractable text.
        """
        with self._db_conn() as conn:
            row = conn.execute(
                "SELECT content FROM document_contents WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        return row[0] if row is not None else None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse(self, entry: CatalogEntry) -> ParsedDocument:
        """Extract content from entry.local_path and persist the result.

        PDFs go through the multi-stage quality pipeline in extract_pdf():
        native extraction → quality scoring → OCR fallback.  All other
        formats use the single-function extractors in _EXTRACTORS.

        Never raises — all extraction errors are captured in status='failed'.
        """
        path = self._root / entry.local_path
        ext = Path(entry.local_path).suffix.lstrip(".").lower()
        parsed_at = datetime.now(timezone.utc)

        content: str | None = None
        status: Literal["ok", "failed"] = "ok"
        error: str | None = None
        char_count: int | None = None
        extraction_method: Literal["native", "ocr"] | None = None
        quality_score: float | None = None
        ocr_attempted: bool = False
        page_count: int | None = None

        if ext == "pdf":
            try:
                result = _ext.extract_pdf(path)
                content = result.text
                char_count = len(content)
                extraction_method = result.extraction_method
                quality_score = result.quality_score
                ocr_attempted = result.ocr_attempted
                page_count = result.page_count
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                error = str(exc)
        else:
            extractor = _ext._EXTRACTORS.get(ext)
            if extractor is None:
                status = "failed"
                label = f".{ext}" if ext else "(none)"
                error = f"No extractor registered for extension '{label}'"
            else:
                try:
                    content = extractor(path)
                    char_count = len(content)
                except Exception as exc:  # noqa: BLE001
                    status = "failed"
                    error = str(exc)

        doc = ParsedDocument(
            evidence_id=entry.evidence_id,
            kind=entry.kind,
            title=entry.title,
            source_date=entry.source_date,
            local_path=entry.local_path,
            parsed_at=parsed_at,
            parser_version=PARSER_VERSION,
            status=status,
            error=error,
            char_count=char_count,
            extraction_method=extraction_method,
            quality_score=quality_score,
            ocr_attempted=ocr_attempted,
            page_count=page_count,
            document_language=_detect_language(content) if content else None,
        )
        self._upsert(doc, content)
        return doc

    def _upsert(self, doc: ParsedDocument, content: str | None) -> None:
        with self._db_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO parsed_documents
                    (evidence_id, kind, title, source_date, local_path,
                     parsed_at, parser_version, status, error, char_count,
                     extraction_method, quality_score, ocr_attempted, page_count,
                     document_language)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc.evidence_id,
                    doc.kind,
                    doc.title,
                    doc.source_date,
                    doc.local_path,
                    doc.parsed_at.isoformat(),
                    doc.parser_version,
                    doc.status,
                    doc.error,
                    doc.char_count,
                    doc.extraction_method,
                    doc.quality_score,
                    int(doc.ocr_attempted),
                    doc.page_count,
                    doc.document_language,
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO document_contents (evidence_id, content) VALUES (?, ?)",
                (doc.evidence_id, content),
            )
