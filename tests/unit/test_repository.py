from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.acquisition.catalog import CatalogEntry, RepositoryCatalog
from atlas.acquisition.evidence import EvidenceKind, EvidenceSource
from atlas.acquisition.profile import (
    COMPREHENSIVE_PROFILE,
    DEFAULT_PROFILE,
    KindFilterProfile,
)
from atlas.acquisition.repository import Repository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# All IDs start with "bse-" to avoid the legacy "bse-news-" migration.

_D2020 = datetime(2020, 1, 1, tzinfo=timezone.utc)
_D2021 = datetime(2021, 1, 1, tzinfo=timezone.utc)
_D2022 = datetime(2022, 1, 1, tzinfo=timezone.utc)
_D2023 = datetime(2023, 1, 1, tzinfo=timezone.utc)
_D2024 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _make_entry(
    evidence_id: str = "bse-r-ar-001",
    kind: EvidenceKind = EvidenceKind.ANNUAL_REPORT,
    source_date: datetime = _D2024,
    title: str = "Test Report",
    local_path: str | None = None,
) -> CatalogEntry:
    return CatalogEntry(
        evidence_id=evidence_id,
        source=EvidenceSource.BSE.value,
        kind=kind.value,
        title=title,
        source_date=source_date.isoformat(),
        document_url=None,
        local_path=local_path or f"annual_reports/{evidence_id}.pdf",
        file_size_bytes=None,
        acquired_at=_D2024.isoformat(),
    )


def _populate(root: Path, entries: list[CatalogEntry]) -> None:
    catalog = RepositoryCatalog(root)
    for entry in entries:
        catalog.add(entry)
    catalog.save()


def _write_file(root: Path, relative_path: str, content: bytes = b"PDF") -> Path:
    """Create a file at root / relative_path and return its absolute path."""
    abs_path = root / relative_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    return abs_path


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestRepositoryConstruction:
    def test_root_property_matches_supplied_path(self, tmp_path: Path) -> None:
        repo = Repository(tmp_path)
        assert repo.root == tmp_path

    def test_empty_repository_is_valid(self, tmp_path: Path) -> None:
        repo = Repository(tmp_path)
        assert repo.list_evidence() == []

    def test_missing_catalog_is_valid(self, tmp_path: Path) -> None:
        repo = Repository(tmp_path / "nonexistent")
        assert repo.list_evidence() == []


# ---------------------------------------------------------------------------
# list_evidence
# ---------------------------------------------------------------------------


class TestRepositoryListEvidence:
    def test_no_filters_returns_all_entries(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-a"), _make_entry("bse-r-b")])
        repo = Repository(tmp_path)
        assert len(repo.list_evidence()) == 2

    def test_returns_catalog_entry_instances(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry()])
        result = Repository(tmp_path).list_evidence()
        assert isinstance(result[0], CatalogEntry)

    def test_kind_filter_includes_matching(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-ar", kind=EvidenceKind.ANNUAL_REPORT)])
        result = Repository(tmp_path).list_evidence(kinds={EvidenceKind.ANNUAL_REPORT})
        assert len(result) == 1

    def test_kind_filter_excludes_non_matching(self, tmp_path: Path) -> None:
        _populate(
            tmp_path, [_make_entry("bse-r-fr", kind=EvidenceKind.FINANCIAL_RESULTS)]
        )
        result = Repository(tmp_path).list_evidence(kinds={EvidenceKind.ANNUAL_REPORT})
        assert result == []

    def test_since_filter_excludes_older(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-r-old", source_date=_D2020),
                _make_entry("bse-r-new", source_date=_D2023),
            ],
        )
        result = Repository(tmp_path).list_evidence(since=_D2022)
        assert len(result) == 1
        assert result[0].evidence_id == "bse-r-new"

    def test_until_filter_excludes_newer(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-r-old", source_date=_D2020),
                _make_entry("bse-r-new", source_date=_D2024),
            ],
        )
        result = Repository(tmp_path).list_evidence(until=_D2022)
        assert len(result) == 1
        assert result[0].evidence_id == "bse-r-old"

    def test_profile_filter(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-r-ar", kind=EvidenceKind.ANNUAL_REPORT),
                _make_entry("bse-r-news", kind=EvidenceKind.NEWS),
            ],
        )
        result = Repository(tmp_path).list_evidence(profile=DEFAULT_PROFILE)
        assert len(result) == 1
        assert result[0].evidence_id == "bse-r-ar"

    def test_kinds_and_profile_raises(self, tmp_path: Path) -> None:
        repo = Repository(tmp_path)
        with pytest.raises(ValueError, match="at most one"):
            repo.list_evidence(
                kinds={EvidenceKind.ANNUAL_REPORT}, profile=DEFAULT_PROFILE
            )

    def test_results_sorted_ascending_by_source_date(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-r-y3", source_date=_D2023),
                _make_entry("bse-r-y1", source_date=_D2021),
                _make_entry("bse-r-y2", source_date=_D2022),
            ],
        )
        result = Repository(tmp_path).list_evidence()
        ids = [e.evidence_id for e in result]
        assert ids == ["bse-r-y1", "bse-r-y2", "bse-r-y3"]

    def test_uses_catalog_snapshot_at_construction_time(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-initial")])
        repo = Repository(tmp_path)
        # Add a new entry after construction; Repository should not see it.
        _populate(tmp_path, [_make_entry("bse-r-initial"), _make_entry("bse-r-after")])
        result = repo.list_evidence()
        ids = {e.evidence_id for e in result}
        assert "bse-r-initial" in ids
        assert "bse-r-after" not in ids


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestRepositoryGet:
    def test_returns_entry_for_known_id(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-x")])
        result = Repository(tmp_path).get("bse-r-x")
        assert result is not None
        assert result.evidence_id == "bse-r-x"

    def test_returns_none_for_unknown_id(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-x")])
        assert Repository(tmp_path).get("bse-r-unknown") is None

    def test_returns_none_on_empty_catalog(self, tmp_path: Path) -> None:
        assert Repository(tmp_path).get("bse-r-any") is None

    def test_all_entry_fields_returned(self, tmp_path: Path) -> None:
        entry = _make_entry("bse-r-full", title="Full Report", source_date=_D2023)
        _populate(tmp_path, [entry])
        result = Repository(tmp_path).get("bse-r-full")
        assert result is not None
        assert result.title == "Full Report"
        assert result.source_date == _D2023.isoformat()


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


class TestRepositoryExists:
    def test_returns_true_for_known_id(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-x")])
        assert Repository(tmp_path).exists("bse-r-x") is True

    def test_returns_false_for_unknown_id(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-x")])
        assert Repository(tmp_path).exists("bse-r-unknown") is False

    def test_returns_false_on_empty_catalog(self, tmp_path: Path) -> None:
        assert Repository(tmp_path).exists("bse-r-any") is False

    def test_does_not_check_filesystem(self, tmp_path: Path) -> None:
        # exists() reports catalog presence, not file presence.
        entry = _make_entry("bse-r-missing-file", local_path="annual_reports/gone.pdf")
        _populate(tmp_path, [entry])
        # No file on disk — exists() should still return True.
        assert Repository(tmp_path).exists("bse-r-missing-file") is True


# ---------------------------------------------------------------------------
# open
# ---------------------------------------------------------------------------


class TestRepositoryOpen:
    def test_returns_absolute_path_to_existing_file(self, tmp_path: Path) -> None:
        local = "annual_reports/bse-r-x.pdf"
        _write_file(tmp_path, local)
        _populate(tmp_path, [_make_entry("bse-r-x", local_path=local)])
        path = Repository(tmp_path).open("bse-r-x")
        assert path.is_absolute()
        assert path.exists()

    def test_returned_path_resolves_under_repo_root(self, tmp_path: Path) -> None:
        local = "annual_reports/bse-r-x.pdf"
        _write_file(tmp_path, local)
        _populate(tmp_path, [_make_entry("bse-r-x", local_path=local)])
        path = Repository(tmp_path).open("bse-r-x")
        assert path == tmp_path / local

    def test_raises_key_error_for_unknown_id(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError):
            Repository(tmp_path).open("bse-r-nonexistent")

    def test_key_error_contains_evidence_id(self, tmp_path: Path) -> None:
        with pytest.raises(KeyError, match="bse-r-missing"):
            Repository(tmp_path).open("bse-r-missing")

    def test_raises_file_not_found_when_file_missing_from_disk(
        self, tmp_path: Path
    ) -> None:
        local = "annual_reports/deleted.pdf"
        entry = _make_entry("bse-r-deleted", local_path=local)
        _populate(tmp_path, [entry])
        # No file on disk.
        with pytest.raises(FileNotFoundError):
            Repository(tmp_path).open("bse-r-deleted")

    def test_file_not_found_message_includes_path(self, tmp_path: Path) -> None:
        local = "annual_reports/deleted.pdf"
        _populate(tmp_path, [_make_entry("bse-r-del", local_path=local)])
        with pytest.raises(FileNotFoundError, match="deleted.pdf"):
            Repository(tmp_path).open("bse-r-del")

    def test_key_error_not_file_not_found_for_missing_catalog_entry(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(KeyError):
            Repository(tmp_path).open("bse-r-any")

    def test_open_works_for_zip_file(self, tmp_path: Path) -> None:
        local = "corporate_governance_reports/bse-r-cg.zip"
        _write_file(tmp_path, local, content=b"PK\x03\x04")
        entry = _make_entry(
            "bse-r-cg",
            kind=EvidenceKind.CORPORATE_GOVERNANCE_REPORT,
            local_path=local,
        )
        _populate(tmp_path, [entry])
        path = Repository(tmp_path).open("bse-r-cg")
        assert path.suffix == ".zip"


# ---------------------------------------------------------------------------
# latest
# ---------------------------------------------------------------------------


class TestRepositoryLatest:
    def test_returns_most_recent_entry_of_kind(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry(
                    "bse-r-ar-2020", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2020
                ),
                _make_entry(
                    "bse-r-ar-2022", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2022
                ),
                _make_entry(
                    "bse-r-ar-2024", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2024
                ),
            ],
        )
        result = Repository(tmp_path).latest(EvidenceKind.ANNUAL_REPORT)
        assert result is not None
        assert result.evidence_id == "bse-r-ar-2024"

    def test_returns_none_when_no_entries_of_kind(self, tmp_path: Path) -> None:
        _populate(
            tmp_path, [_make_entry("bse-r-fr", kind=EvidenceKind.FINANCIAL_RESULTS)]
        )
        result = Repository(tmp_path).latest(EvidenceKind.ANNUAL_REPORT)
        assert result is None

    def test_returns_none_on_empty_catalog(self, tmp_path: Path) -> None:
        result = Repository(tmp_path).latest(EvidenceKind.ANNUAL_REPORT)
        assert result is None

    def test_ignores_other_kinds(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry(
                    "bse-r-ar", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2020
                ),
                _make_entry(
                    "bse-r-fr", kind=EvidenceKind.FINANCIAL_RESULTS, source_date=_D2024
                ),
            ],
        )
        result = Repository(tmp_path).latest(EvidenceKind.ANNUAL_REPORT)
        assert result is not None
        assert result.kind == EvidenceKind.ANNUAL_REPORT.value

    def test_single_entry_is_returned_as_latest(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-ar", kind=EvidenceKind.ANNUAL_REPORT)])
        result = Repository(tmp_path).latest(EvidenceKind.ANNUAL_REPORT)
        assert result is not None
        assert result.evidence_id == "bse-r-ar"

    def test_since_bound_respected(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry(
                    "bse-r-ar-2020", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2020
                ),
                _make_entry(
                    "bse-r-ar-2022", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2022
                ),
            ],
        )
        result = Repository(tmp_path).latest(EvidenceKind.ANNUAL_REPORT, since=_D2023)
        assert result is None

    def test_since_bound_narrows_to_later_entry(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry(
                    "bse-r-ar-2020", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2020
                ),
                _make_entry(
                    "bse-r-ar-2022", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2022
                ),
                _make_entry(
                    "bse-r-ar-2024", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2024
                ),
            ],
        )
        result = Repository(tmp_path).latest(EvidenceKind.ANNUAL_REPORT, since=_D2022)
        assert result is not None
        assert result.evidence_id == "bse-r-ar-2024"


# ---------------------------------------------------------------------------
# Snapshot semantics
# ---------------------------------------------------------------------------


class TestRepositorySnapshotSemantics:
    def test_new_instance_sees_new_data(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-initial")])
        _ = Repository(tmp_path)  # first snapshot
        _populate(tmp_path, [_make_entry("bse-r-initial"), _make_entry("bse-r-after")])
        repo2 = Repository(tmp_path)
        ids = {e.evidence_id for e in repo2.list_evidence()}
        assert "bse-r-after" in ids

    def test_exists_uses_snapshot(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-x")])
        repo = Repository(tmp_path)
        _populate(tmp_path, [_make_entry("bse-r-x"), _make_entry("bse-r-y")])
        assert repo.exists("bse-r-y") is False

    def test_get_uses_snapshot(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-r-x")])
        repo = Repository(tmp_path)
        _populate(tmp_path, [_make_entry("bse-r-x"), _make_entry("bse-r-y")])
        assert repo.get("bse-r-y") is None
