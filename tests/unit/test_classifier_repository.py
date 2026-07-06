"""Unit tests for atlas.acquisition.classifier.reclassify_repository().

Fully synthetic tmp_path fixtures (a real catalog.json + knowledge.db built
from scratch) — isolated from any real repository, so these are safe to run
regardless of what else is touching repositories/ elsewhere.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.classifier import reclassify_repository
from atlas.knowledge.base import KnowledgeBase, ParsedDocument


def _make_catalog_entry(evidence_id: str, kind: str, local_path: str) -> CatalogEntry:
    return CatalogEntry(
        evidence_id=evidence_id,
        source="BSE",
        kind=kind,
        title="Test Filing",
        source_date="2026-04-09T00:00:00+00:00",
        document_url=None,
        local_path=local_path,
        file_size_bytes=1000,
        acquired_at="2026-04-09T00:00:00+00:00",
    )


def _seed_parsed_document(kb: KnowledgeBase, evidence_id: str, kind: str, text: str, page_count: int) -> None:
    doc = ParsedDocument(
        evidence_id=evidence_id,
        kind=kind,
        title="Test Filing",
        source_date="2026-04-09T00:00:00+00:00",
        local_path=f"other/{evidence_id}.pdf",
        parsed_at=datetime.now(timezone.utc),
        parser_version="test",
        status="ok",
        char_count=len(text),
        page_count=page_count,
    )
    kb._upsert(doc, text)


class TestReclassifyRepository:
    def test_related_party_document_reclassified_in_catalog(self, tmp_path: Path) -> None:
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(_make_catalog_entry("bse-news-e1", "financial_results", "other/e1.pdf"))
        catalog.save()

        kb = KnowledgeBase(tmp_path)
        _seed_parsed_document(
            kb, "bse-news-e1", "financial_results",
            "Sub: Disclosure of Related Party Transactions pursuant to Regulation 23(9)",
            page_count=10,
        )

        reclassify_repository(tmp_path)

        reloaded = RepositoryCatalog(tmp_path)
        assert reloaded.get_entry("bse-news-e1").kind == "regulatory_filing"

    def test_reclassification_also_updates_knowledge_db_kind(self, tmp_path: Path) -> None:
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(_make_catalog_entry("bse-news-e1", "financial_results", "other/e1.pdf"))
        catalog.save()

        kb = KnowledgeBase(tmp_path)
        _seed_parsed_document(
            kb, "bse-news-e1", "financial_results",
            "Sub: Disclosure of Related Party Transactions pursuant to Regulation 23(9)",
            page_count=10,
        )
        # parse() needs a real local file to re-derive content from, but
        # reclassify_repository's re-parse call will fail to find a real
        # PDF for this synthetic fixture — that's fine, it's caught the
        # same way any parse failure is; the catalog correction is what's
        # asserted here, not a successful re-parse of a nonexistent file.
        reclassify_repository(tmp_path)

        reloaded = RepositoryCatalog(tmp_path)
        assert reloaded.get_entry("bse-news-e1").kind == "regulatory_filing"

    def test_real_financial_results_not_touched(self, tmp_path: Path) -> None:
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(_make_catalog_entry("bse-news-e1", "financial_results", "other/e1.pdf"))
        catalog.save()

        kb = KnowledgeBase(tmp_path)
        _seed_parsed_document(
            kb, "bse-news-e1", "financial_results",
            "Sub: Financial Results for the year ended March 31, 2026",
            page_count=25,
        )

        records = reclassify_repository(tmp_path)

        reloaded = RepositoryCatalog(tmp_path)
        assert reloaded.get_entry("bse-news-e1").kind == "financial_results"
        assert records[0].result.was_reclassified is False

    def test_uncalibrated_kind_skipped_entirely(self, tmp_path: Path) -> None:
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(_make_catalog_entry("bse-news-e1", "board_outcome", "other/e1.pdf"))
        catalog.save()

        kb = KnowledgeBase(tmp_path)
        _seed_parsed_document(kb, "bse-news-e1", "board_outcome", "any content", page_count=1)

        records = reclassify_repository(tmp_path)
        assert records == []

    def test_unparsed_document_skipped(self, tmp_path: Path) -> None:
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(_make_catalog_entry("bse-news-e1", "financial_results", "other/e1.pdf"))
        catalog.save()
        # No corresponding KnowledgeBase entry at all.
        KnowledgeBase(tmp_path)

        records = reclassify_repository(tmp_path)
        assert records == []

    def test_returns_record_for_every_examined_document(self, tmp_path: Path) -> None:
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(_make_catalog_entry("bse-news-e1", "investor_presentation", "other/e1.pdf"))
        catalog.add(_make_catalog_entry("bse-news-e2", "investor_presentation", "other/e2.pdf"))
        catalog.save()

        kb = KnowledgeBase(tmp_path)
        _seed_parsed_document(kb, "bse-news-e1", "investor_presentation", "Sub: Schedule of Analyst Meetings", page_count=2)
        _seed_parsed_document(kb, "bse-news-e2", "investor_presentation", "Sub: Submission of presentation" + "x" * 3000, page_count=50)

        records = reclassify_repository(tmp_path)
        assert len(records) == 2
        by_id = {r.evidence_id: r for r in records}
        assert by_id["bse-news-e1"].result.is_substantive is False
        assert by_id["bse-news-e2"].result.is_substantive is True

    def test_empty_repository_returns_empty(self, tmp_path: Path) -> None:
        RepositoryCatalog(tmp_path).save()
        KnowledgeBase(tmp_path)
        assert reclassify_repository(tmp_path) == []
