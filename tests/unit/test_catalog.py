import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.evidence import Evidence, EvidenceKind, EvidenceSource


def _make_catalog_json(root: Path, items: list[dict] | None = None) -> None:
    data: dict = {"schema_version": "1"}
    if items is not None:
        data["items"] = items
    (root / "catalog.json").write_text(json.dumps(data), encoding="utf-8")


def _make_evidence(evidence_id: str = "bse-news-ev-001") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        company_id="cmp_abc",
        source=EvidenceSource.BSE,
        kind=EvidenceKind.ANNUAL_REPORT,
        title="Annual Report 2023-24",
        source_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        document_url="https://example.com/report.pdf",
        file_size_bytes=1_000_000,
    )


_SAMPLE_ITEM: dict = {
    "evidence_id": "bse-news-ev-001",
    "source": "BSE",
    "kind": "annual_report",
    "title": "Report",
    "source_date": "2024-01-01T00:00:00+00:00",
    "document_url": None,
    "local_path": "annual_reports/bse-news-ev-001.pdf",
    "file_size_bytes": 1000,
    "acquired_at": "2026-01-01T00:00:00+00:00",
}


class TestRepositoryCatalogLoad:
    def test_loads_empty_catalog(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path)
        catalog = RepositoryCatalog(tmp_path)
        assert catalog.known_ids() == frozenset()

    def test_loads_catalog_without_items_key(self, tmp_path: Path) -> None:
        (tmp_path / "catalog.json").write_text(
            '{"schema_version": "1"}', encoding="utf-8"
        )
        catalog = RepositoryCatalog(tmp_path)
        assert catalog.known_ids() == frozenset()

    def test_loads_existing_item(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path, [_SAMPLE_ITEM])
        catalog = RepositoryCatalog(tmp_path)
        assert "bse-news-ev-001" in catalog.known_ids()

    def test_missing_catalog_file_loads_empty(self, tmp_path: Path) -> None:
        catalog = RepositoryCatalog(tmp_path)
        assert catalog.known_ids() == frozenset()


class TestRepositoryCatalogAdd:
    def test_add_makes_id_known(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path)
        catalog = RepositoryCatalog(tmp_path)
        entry = CatalogEntry.from_evidence(
            _make_evidence("bse-news-ev-001"), "annual_reports/bse-news-ev-001.pdf"
        )
        catalog.add(entry)
        assert "bse-news-ev-001" in catalog.known_ids()

    def test_add_overwrites_duplicate_id(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path)
        catalog = RepositoryCatalog(tmp_path)
        ev = _make_evidence("bse-news-ev-001")
        catalog.add(
            CatalogEntry.from_evidence(ev, "annual_reports/bse-news-ev-001.pdf")
        )
        catalog.add(
            CatalogEntry.from_evidence(ev, "annual_reports/bse-news-ev-001-v2.pdf")
        )
        assert len(catalog.known_ids()) == 1


class TestRepositoryCatalogSave:
    def test_save_and_reload_roundtrip(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path)
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(
            CatalogEntry.from_evidence(
                _make_evidence("bse-news-ev-001"), "annual_reports/bse-news-ev-001.pdf"
            )
        )
        catalog.save()
        reloaded = RepositoryCatalog(tmp_path)
        assert "bse-news-ev-001" in reloaded.known_ids()

    def test_save_preserves_schema_version(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path)
        RepositoryCatalog(tmp_path).save()
        data = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
        assert data["schema_version"] == "1"

    def test_save_writes_items_array(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path)
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(
            CatalogEntry.from_evidence(
                _make_evidence("bse-news-ev-001"), "annual_reports/bse-news-ev-001.pdf"
            )
        )
        catalog.save()
        data = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
        assert len(data["items"]) == 1
        assert data["items"][0]["evidence_id"] == "bse-news-ev-001"


class TestAtomicSave:
    """Verify that save() never corrupts catalog.json on failure."""

    def test_failed_temp_write_leaves_catalog_unchanged(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path, [_SAMPLE_ITEM])
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(
            CatalogEntry.from_evidence(
                _make_evidence("bse-news-ev-new"), "annual_reports/bse-news-ev-new.pdf"
            )
        )

        _original_write = Path.write_text

        def _fail_on_tmp(self: Path, *args: object, **kwargs: object) -> object:
            if self.suffix == ".tmp":
                raise OSError("simulated disk full")
            return _original_write(self, *args, **kwargs)

        with patch.object(Path, "write_text", _fail_on_tmp):
            with pytest.raises(OSError, match="disk full"):
                catalog.save()

        reloaded = RepositoryCatalog(tmp_path)
        assert "bse-news-ev-001" in reloaded.known_ids()
        assert "bse-news-ev-new" not in reloaded.known_ids()

    def test_failed_rename_leaves_catalog_unchanged(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path, [_SAMPLE_ITEM])
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(
            CatalogEntry.from_evidence(
                _make_evidence("bse-news-ev-new"), "annual_reports/bse-news-ev-new.pdf"
            )
        )

        def _fail_replace(self: Path, target: Path) -> None:
            raise OSError("simulated rename failure")

        with patch.object(Path, "replace", _fail_replace):
            with pytest.raises(OSError, match="rename failure"):
                catalog.save()

        reloaded = RepositoryCatalog(tmp_path)
        assert "bse-news-ev-001" in reloaded.known_ids()
        assert "bse-news-ev-new" not in reloaded.known_ids()

    def test_no_temp_file_remains_after_successful_save(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path)
        RepositoryCatalog(tmp_path).save()
        assert not (tmp_path / "catalog.tmp").exists()

    def test_stale_temp_file_is_not_loaded_as_catalog(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path)
        stale = {"schema_version": "1", "items": [_SAMPLE_ITEM]}
        (tmp_path / "catalog.tmp").write_text(json.dumps(stale), encoding="utf-8")
        catalog = RepositoryCatalog(tmp_path)
        assert "bse-news-ev-001" not in catalog.known_ids()

    def test_stale_temp_file_does_not_prevent_save(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path)
        (tmp_path / "catalog.tmp").write_text("stale garbage", encoding="utf-8")
        catalog = RepositoryCatalog(tmp_path)
        catalog.add(
            CatalogEntry.from_evidence(
                _make_evidence("bse-news-ev-001"), "annual_reports/bse-news-ev-001.pdf"
            )
        )
        catalog.save()
        reloaded = RepositoryCatalog(tmp_path)
        assert "bse-news-ev-001" in reloaded.known_ids()


class TestCatalogEntryFromEvidence:
    def test_source_is_enum_value(self) -> None:
        entry = CatalogEntry.from_evidence(
            _make_evidence(), "annual_reports/ev-001.pdf"
        )
        assert entry.source == "BSE"

    def test_kind_is_enum_value(self) -> None:
        entry = CatalogEntry.from_evidence(
            _make_evidence(), "annual_reports/ev-001.pdf"
        )
        assert entry.kind == "annual_report"

    def test_local_path_is_preserved(self) -> None:
        entry = CatalogEntry.from_evidence(
            _make_evidence(), "annual_reports/ev-001.pdf"
        )
        assert entry.local_path == "annual_reports/ev-001.pdf"

    def test_acquired_at_is_set(self) -> None:
        entry = CatalogEntry.from_evidence(
            _make_evidence(), "annual_reports/ev-001.pdf"
        )
        assert entry.acquired_at != ""

    def test_checksum_propagated_when_given(self) -> None:
        entry = CatalogEntry.from_evidence(
            _make_evidence(), "annual_reports/ev-001.pdf", checksum="abc123"
        )
        assert entry.checksum == "abc123"

    def test_checksum_none_by_default(self) -> None:
        entry = CatalogEntry.from_evidence(
            _make_evidence(), "annual_reports/ev-001.pdf"
        )
        assert entry.checksum is None

    def test_report_period_propagated_from_evidence(self) -> None:
        ev = _make_evidence()
        ev.report_period = "2025-26"
        entry = CatalogEntry.from_evidence(ev, "annual_reports/ev-001.pdf")
        assert entry.report_period == "2025-26"

    def test_report_period_none_when_evidence_has_none(self) -> None:
        entry = CatalogEntry.from_evidence(
            _make_evidence(), "annual_reports/ev-001.pdf"
        )
        assert entry.report_period is None

    def test_checksum_and_report_period_survive_to_dict_from_dict_round_trip(
        self,
    ) -> None:
        entry = CatalogEntry.from_evidence(
            _make_evidence(), "annual_reports/ev-001.pdf", checksum="deadbeef"
        )
        entry.report_period = "2025-26"
        restored = CatalogEntry.from_dict(entry.to_dict())
        assert restored.checksum == "deadbeef"
        assert restored.report_period == "2025-26"

    def test_from_dict_defaults_missing_checksum_and_period_to_none(self) -> None:
        # Backward compatibility: a catalog.json written before these fields
        # existed has neither key.
        legacy_dict = {**_SAMPLE_ITEM}
        legacy_dict.pop("checksum", None)
        legacy_dict.pop("report_period", None)
        restored = CatalogEntry.from_dict(legacy_dict)
        assert restored.checksum is None
        assert restored.report_period is None


# ---------------------------------------------------------------------------
# NEWSID migration
# ---------------------------------------------------------------------------

_BSE_ITEM_BARE_UUID: dict = {
    **_SAMPLE_ITEM,
    "evidence_id": "6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae",
    "source": "BSE",
}

_BSE_ITEM_BARE_INT: dict = {
    **_SAMPLE_ITEM,
    "evidence_id": "12345678",
    "source": "BSE",
}

_BSE_ITEM_ALREADY_PREFIXED: dict = {
    **_SAMPLE_ITEM,
    "evidence_id": "bse-news-6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae",
    "source": "BSE",
}

_BSE_AR_ITEM: dict = {
    **_SAMPLE_ITEM,
    "evidence_id": "bse-ar-532540-report.pdf",
    "source": "BSE",
}

_NON_BSE_ITEM: dict = {
    **_SAMPLE_ITEM,
    "evidence_id": "some-nse-id",
    "source": "NSE",
}


class TestNewsidMigration:
    def test_bare_uuid_bse_entry_migrated_to_prefixed_form(
        self, tmp_path: Path
    ) -> None:
        _make_catalog_json(tmp_path, [_BSE_ITEM_BARE_UUID])
        catalog = RepositoryCatalog(tmp_path)
        assert "bse-news-6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae" in catalog.known_ids()
        assert "6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae" not in catalog.known_ids()

    def test_bare_integer_bse_entry_migrated_to_prefixed_form(
        self, tmp_path: Path
    ) -> None:
        _make_catalog_json(tmp_path, [_BSE_ITEM_BARE_INT])
        catalog = RepositoryCatalog(tmp_path)
        assert "bse-news-12345678" in catalog.known_ids()
        assert "12345678" not in catalog.known_ids()

    def test_already_prefixed_entry_not_double_prefixed(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path, [_BSE_ITEM_ALREADY_PREFIXED])
        catalog = RepositoryCatalog(tmp_path)
        assert "bse-news-6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae" in catalog.known_ids()
        assert (
            "bse-news-bse-news-6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae"
            not in catalog.known_ids()
        )

    def test_bse_ar_entry_not_migrated(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path, [_BSE_AR_ITEM])
        catalog = RepositoryCatalog(tmp_path)
        assert "bse-ar-532540-report.pdf" in catalog.known_ids()

    def test_non_bse_entry_not_migrated(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path, [_NON_BSE_ITEM])
        catalog = RepositoryCatalog(tmp_path)
        assert "some-nse-id" in catalog.known_ids()

    def test_migration_persisted_to_disk_immediately(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path, [_BSE_ITEM_BARE_UUID])
        RepositoryCatalog(tmp_path)  # triggers migration and save
        reloaded = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
        ids = [item["evidence_id"] for item in reloaded.get("items", [])]
        assert "bse-news-6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae" in ids
        assert "6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae" not in ids

    def test_migration_is_idempotent(self, tmp_path: Path) -> None:
        _make_catalog_json(tmp_path, [_BSE_ITEM_BARE_UUID])
        RepositoryCatalog(tmp_path)  # first load — migrates
        RepositoryCatalog(tmp_path)  # second load — no-op
        reloaded = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
        ids = [item["evidence_id"] for item in reloaded.get("items", [])]
        assert ids.count("bse-news-6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae") == 1
