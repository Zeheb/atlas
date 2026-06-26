import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from atlas.acquisition.catalog import CatalogEntry
from atlas.knowledge import extractors as _ext

PARSER_VERSION = "1.0"

_CREATE_TABLES = """
    CREATE TABLE IF NOT EXISTS parsed_documents (
        evidence_id    TEXT PRIMARY KEY,
        kind           TEXT NOT NULL,
        title          TEXT NOT NULL,
        source_date    TEXT NOT NULL,
        local_path     TEXT NOT NULL,
        parsed_at      TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        status         TEXT NOT NULL,
        error          TEXT,
        char_count     INTEGER
    );
    CREATE TABLE IF NOT EXISTS document_contents (
        evidence_id TEXT PRIMARY KEY,
        content     TEXT
    );
"""


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
    error: str | None
    char_count: int | None


def _row_to_doc(row: sqlite3.Row) -> ParsedDocument:
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
        """Return evidence_ids whose last parse succeeded."""
        with self._db_conn() as conn:
            rows = conn.execute(
                "SELECT evidence_id FROM parsed_documents WHERE status = 'ok'"
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

        Dispatches on the file extension derived from local_path. Extensions
        not registered in the extractor map produce status='failed' and are
        retried on the next call, as are prior extraction failures.

        Never raises — all extraction errors are captured in status='failed'.
        """
        path = self._root / entry.local_path
        ext = Path(entry.local_path).suffix.lstrip(".").lower()
        extractor = _ext._EXTRACTORS.get(ext)
        parsed_at = datetime.now(timezone.utc)

        content: str | None = None
        status: Literal["ok", "failed"] = "ok"
        error: str | None = None
        char_count: int | None = None

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
        )
        self._upsert(doc, content)
        return doc

    def _upsert(self, doc: ParsedDocument, content: str | None) -> None:
        with self._db_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO parsed_documents
                    (evidence_id, kind, title, source_date, local_path,
                     parsed_at, parser_version, status, error, char_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO document_contents (evidence_id, content) VALUES (?, ?)",
                (doc.evidence_id, content),
            )
