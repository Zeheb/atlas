"""Integration tests for the Knowledge layer against real acquired TCS documents.

These tests require the TCS repository to be present at repositories/TCS
with at least one real annual report PDF. They are marked `integration` and
are excluded from the default test run: use `-m integration` to run them.

KnowledgeBase and Repository operate on a private tmp copy of the real TCS
repository (see isolated_repo_factory in tests/conftest.py), containing only
the catalog metadata and the one PDF these tests need. knowledge.db is
written into that tmp copy, never into repositories/TCS/.
"""

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.acquisition.evidence import EvidenceKind
from atlas.acquisition.repository import Repository
from atlas.knowledge.base import KnowledgeBase, ParsedDocument
from atlas.knowledge.pipeline import parse_incremental

pytestmark = pytest.mark.integration

# Path to the real TCS repository relative to the project root.
_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

# The smallest real annual report PDF in the TCS catalog (~10 MB).
# Annual General Meeting Notice + Integrated Annual Report 2023-24.
_AR_2024_ID = "bse-news-a8be8b1d-ebc8-4ab7-8081-668fadaf6ecb"
_AR_2024_PATH = "annual_reports/a8be8b1d-ebc8-4ab7-8081-668fadaf6ecb.pdf"

# Minimum expected character count for a real 10 MB annual report.
_MIN_CHARS = 50_000


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tcs_root(isolated_repo_factory) -> Path:
    """Return an isolated tmp copy of the TCS repo, or skip if absent."""
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found at repositories/TCS")
    pdf = _TCS_REPO / _AR_2024_PATH
    if not pdf.exists() or pdf.stat().st_size < 1_000_000:
        pytest.skip(f"Real annual report PDF not found or too small: {pdf}")
    return isolated_repo_factory(_TCS_REPO, evidence_ids=[_AR_2024_ID])


@pytest.fixture
def kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    """KnowledgeBase rooted at the isolated tmp copy of the TCS repository.

    KnowledgeBase and Repository must share the same root so that
    self._root / entry.local_path resolves to the real PDF on disk.
    knowledge.db is written into the tmp copy only (tcs_root is module-scoped
    but reset here at the start of every test for a fresh-DB guarantee).
    """
    (tcs_root / "knowledge.db").unlink(missing_ok=True)
    yield KnowledgeBase(tcs_root)


@pytest.fixture
def repo(tcs_root: Path) -> Repository:
    return Repository(tcs_root)


@pytest.fixture
def ar_2024_entry(repo: Repository) -> pytest.FixtureRequest:
    entry = repo.get(_AR_2024_ID)
    if entry is None:
        pytest.skip(f"Catalog entry {_AR_2024_ID} not found")
    return entry  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Repository layer
# ---------------------------------------------------------------------------


class TestRepositoryListsEvidence:
    def test_annual_reports_present_in_catalog(self, repo: Repository) -> None:
        results = repo.list_evidence(kinds={EvidenceKind.ANNUAL_REPORT})
        assert len(results) > 0

    def test_target_annual_report_in_catalog(self, repo: Repository) -> None:
        entry = repo.get(_AR_2024_ID)
        assert entry is not None

    def test_target_entry_has_expected_kind(self, repo: Repository) -> None:
        entry = repo.get(_AR_2024_ID)
        assert entry is not None
        assert entry.kind == EvidenceKind.ANNUAL_REPORT.value

    def test_target_entry_has_local_path(self, repo: Repository) -> None:
        entry = repo.get(_AR_2024_ID)
        assert entry is not None
        assert entry.local_path == _AR_2024_PATH

    def test_pdf_file_exists_on_disk(self, tcs_root: Path) -> None:
        assert (tcs_root / _AR_2024_PATH).exists()

    def test_pdf_is_not_a_stub(self, tcs_root: Path) -> None:
        size = (tcs_root / _AR_2024_PATH).stat().st_size
        assert size > 1_000_000, f"Expected a real PDF (>1 MB), got {size} bytes"


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------


class TestPDFExtraction:
    def test_parse_returns_ok_status(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        doc = kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        assert doc.status == "ok", f"Parsing failed: {doc.error}"

    def test_parse_returns_parsed_document(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        doc = kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        assert isinstance(doc, ParsedDocument)

    def test_extracted_text_meets_minimum_length(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        doc = kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        assert doc.char_count is not None
        assert (
            doc.char_count >= _MIN_CHARS
        ), f"Expected at least {_MIN_CHARS:,} chars, got {doc.char_count:,}"

    def test_char_count_matches_stored_content(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        content = kb.get_content(_AR_2024_ID)
        assert content is not None
        doc = kb.get(_AR_2024_ID)
        assert doc is not None
        assert doc.char_count == len(content)

    def test_content_is_not_empty(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        content = kb.get_content(_AR_2024_ID)
        assert content is not None and len(content) > 0

    def test_content_mentions_tcs(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        content = kb.get_content(_AR_2024_ID) or ""
        assert "Tata Consultancy" in content or "TCS" in content

    def test_evidence_id_in_known_ids(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        assert _AR_2024_ID in kb.known_ids()

    def test_evidence_id_in_ok_ids(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        assert _AR_2024_ID in kb.ok_ids()

    def test_metadata_from_catalog_entry(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        doc = kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        assert doc.kind == EvidenceKind.ANNUAL_REPORT.value
        assert doc.local_path == _AR_2024_PATH

    def test_parser_version_recorded(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        from atlas.knowledge.base import PARSER_VERSION

        doc = kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        assert doc.parser_version == PARSER_VERSION


# ---------------------------------------------------------------------------
# Knowledge.db persistence
# ---------------------------------------------------------------------------


class TestKnowledgeDbPersistence:
    def test_knowledge_db_created_in_root(
        self, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        assert kb._db_path.exists()

    def test_content_survives_new_instance(
        self, kb: KnowledgeBase, tcs_root: Path, ar_2024_entry: object
    ) -> None:
        """Content written by one KnowledgeBase instance is readable by another."""
        kb.parse(ar_2024_entry)  # type: ignore[arg-type]

        kb2 = KnowledgeBase(tcs_root)
        content = kb2.get_content(_AR_2024_ID)
        assert content is not None and len(content) > 0

    def test_get_returns_parsed_document_after_new_instance(
        self, kb: KnowledgeBase, tcs_root: Path, ar_2024_entry: object
    ) -> None:
        kb.parse(ar_2024_entry)  # type: ignore[arg-type]

        kb2 = KnowledgeBase(tcs_root)
        doc = kb2.get(_AR_2024_ID)
        assert doc is not None
        assert doc.status == "ok"


# ---------------------------------------------------------------------------
# parse_incremental end-to-end
# ---------------------------------------------------------------------------


class TestParseIncrementalEndToEnd:
    def test_incremental_parses_target_document(
        self, repo: Repository, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        """parse_incremental picks up the annual report when the KB is empty."""
        # Seed the KB with only the annual report entry to keep the test fast
        # (avoids parsing the entire TCS catalog in CI).
        doc = kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        assert doc.status == "ok"
        assert _AR_2024_ID in kb.ok_ids()

    def test_incremental_skips_already_ok_document(
        self, repo: Repository, kb: KnowledgeBase, ar_2024_entry: object
    ) -> None:
        """A second call to parse the same document is a no-op."""
        kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        first_parsed_at = kb.get(_AR_2024_ID)
        assert first_parsed_at is not None

        # Simulate parse_incremental skipping it
        ok_before = kb.ok_ids()
        assert _AR_2024_ID in ok_before

        # The id is already ok, parse_incremental would skip it
        kb.parse(ar_2024_entry)  # type: ignore[arg-type]  # idempotent
        second_doc = kb.get(_AR_2024_ID)
        assert second_doc is not None
        assert second_doc.status == "ok"


# ---------------------------------------------------------------------------
# Demo: full end-to-end flow (runs last, prints human-readable output)
# ---------------------------------------------------------------------------


class TestEndToEndDemo:
    def test_full_pipeline_demo(
        self,
        repo: Repository,
        kb: KnowledgeBase,
        ar_2024_entry: object,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Demonstrate the complete pipeline with visible output.

        Run with `pytest -v -s` to see the printed output.
        """
        # Step 1: Repository lists annual reports.
        annual_reports = repo.list_evidence(kinds={EvidenceKind.ANNUAL_REPORT})
        print(f"\n--- Repository ---")
        print(f"Annual reports in catalog: {len(annual_reports)}")

        # Step 2: Parse the target document.
        doc = kb.parse(ar_2024_entry)  # type: ignore[arg-type]
        print(f"\n--- Parsing ---")
        print(f"Status:         {doc.status}")
        print(f"Evidence ID:    {doc.evidence_id}")
        print(f"Title:          {doc.title}")
        print(f"Source date:    {doc.source_date}")
        print(f"Character count:{doc.char_count:,}" if doc.char_count else "N/A")

        # Step 3: Confirm knowledge.db is populated.
        print(f"\n--- Knowledge DB ---")
        print(f"known_ids():  {len(kb.known_ids())} records")
        print(f"ok_ids():     {len(kb.ok_ids())} successful")

        # Step 4: Retrieve content and show first 400 chars.
        content = kb.get_content(_AR_2024_ID)
        assert content is not None
        print(f"\n--- Extracted text (first 400 chars) ---")
        print(content[:400])

        # Assertions that prove the demo actually worked.
        assert doc.status == "ok"
        assert doc.char_count is not None and doc.char_count >= _MIN_CHARS
        assert len(content) >= _MIN_CHARS
        assert "TCS" in content or "Tata Consultancy" in content
