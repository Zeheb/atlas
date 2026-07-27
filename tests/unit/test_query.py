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
from atlas.acquisition.query import query_evidence

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# All evidence IDs start with "bse-" to avoid the legacy migration that
# prefixes bare BSE IDs with "bse-news-".


def _make_entry(
    evidence_id: str = "bse-q-ar-001",
    kind: EvidenceKind = EvidenceKind.ANNUAL_REPORT,
    source_date: datetime = datetime(2024, 1, 1, tzinfo=timezone.utc),
    title: str = "Test Report",
) -> CatalogEntry:
    return CatalogEntry(
        evidence_id=evidence_id,
        source=EvidenceSource.BSE.value,
        kind=kind.value,
        title=title,
        source_date=source_date.isoformat(),
        document_url=None,
        local_path=f"annual_reports/{evidence_id}.pdf",
        file_size_bytes=None,
        acquired_at=datetime(2024, 6, 1, tzinfo=timezone.utc).isoformat(),
    )


def _populate(repo_root: Path, entries: list[CatalogEntry]) -> None:
    catalog = RepositoryCatalog(repo_root)
    for entry in entries:
        catalog.add(entry)
    catalog.save()


_D2020 = datetime(2020, 1, 1, tzinfo=timezone.utc)
_D2021 = datetime(2021, 1, 1, tzinfo=timezone.utc)
_D2022 = datetime(2022, 1, 1, tzinfo=timezone.utc)
_D2023 = datetime(2023, 1, 1, tzinfo=timezone.utc)
_D2024 = datetime(2024, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Basic retrieval
# ---------------------------------------------------------------------------


class TestQueryEvidenceBasic:
    def test_empty_catalog_returns_empty_list(self, tmp_path: Path) -> None:
        result = query_evidence(tmp_path)
        assert result == []

    def test_missing_catalog_returns_empty_list(self, tmp_path: Path) -> None:
        result = query_evidence(tmp_path / "nonexistent")
        assert result == []

    def test_no_filters_returns_all_entries(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [_make_entry("bse-q-a"), _make_entry("bse-q-b")],
        )
        result = query_evidence(tmp_path)
        assert len(result) == 2

    def test_returns_catalog_entry_instances(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry()])
        result = query_evidence(tmp_path)
        assert isinstance(result[0], CatalogEntry)

    def test_entry_fields_are_preserved(self, tmp_path: Path) -> None:
        entry = _make_entry("bse-q-specific", title="Specific Report")
        _populate(tmp_path, [entry])
        result = query_evidence(tmp_path)
        assert result[0].evidence_id == "bse-q-specific"
        assert result[0].title == "Specific Report"


# ---------------------------------------------------------------------------
# Kind filter
# ---------------------------------------------------------------------------


class TestQueryEvidenceKindFilter:
    def test_kind_filter_includes_matching(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-q-ar", kind=EvidenceKind.ANNUAL_REPORT)])
        result = query_evidence(tmp_path, kinds={EvidenceKind.ANNUAL_REPORT})
        assert len(result) == 1

    def test_kind_filter_excludes_non_matching(self, tmp_path: Path) -> None:
        _populate(
            tmp_path, [_make_entry("bse-q-fr", kind=EvidenceKind.FINANCIAL_RESULTS)]
        )
        result = query_evidence(tmp_path, kinds={EvidenceKind.ANNUAL_REPORT})
        assert result == []

    def test_kind_filter_with_multiple_kinds(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-q-ar", kind=EvidenceKind.ANNUAL_REPORT),
                _make_entry("bse-q-fr", kind=EvidenceKind.FINANCIAL_RESULTS),
                _make_entry("bse-q-news", kind=EvidenceKind.NEWS),
            ],
        )
        result = query_evidence(
            tmp_path,
            kinds={EvidenceKind.ANNUAL_REPORT, EvidenceKind.FINANCIAL_RESULTS},
        )
        assert len(result) == 2
        ids = {e.evidence_id for e in result}
        assert ids == {"bse-q-ar", "bse-q-fr"}

    def test_kind_filter_empty_set_returns_empty(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry()])
        result = query_evidence(tmp_path, kinds=set())
        assert result == []

    def test_unknown_kind_string_excluded_when_kind_filter_active(
        self, tmp_path: Path
    ) -> None:
        bad_entry = CatalogEntry(
            evidence_id="bse-q-future",
            source="BSE",
            kind="future_unknown_kind",
            title="Unknown",
            source_date=_D2024.isoformat(),
            document_url=None,
            local_path="other/bse-q-future.pdf",
            file_size_bytes=None,
            acquired_at=_D2024.isoformat(),
        )
        _populate(tmp_path, [bad_entry])
        result = query_evidence(tmp_path, kinds={EvidenceKind.ANNUAL_REPORT})
        assert result == []

    def test_unknown_kind_string_included_when_no_kind_filter(
        self, tmp_path: Path
    ) -> None:
        bad_entry = CatalogEntry(
            evidence_id="bse-q-future",
            source="BSE",
            kind="future_unknown_kind",
            title="Unknown",
            source_date=_D2024.isoformat(),
            document_url=None,
            local_path="other/bse-q-future.pdf",
            file_size_bytes=None,
            acquired_at=_D2024.isoformat(),
        )
        _populate(tmp_path, [bad_entry])
        result = query_evidence(tmp_path)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Date filter
# ---------------------------------------------------------------------------


class TestQueryEvidenceDateFilter:
    def test_since_excludes_older_entries(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-q-old", source_date=_D2020),
                _make_entry("bse-q-new", source_date=_D2023),
            ],
        )
        result = query_evidence(tmp_path, since=_D2022)
        assert len(result) == 1
        assert result[0].evidence_id == "bse-q-new"

    def test_since_is_inclusive(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-q-exact", source_date=_D2022)])
        result = query_evidence(tmp_path, since=_D2022)
        assert len(result) == 1

    def test_until_excludes_newer_entries(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-q-old", source_date=_D2020),
                _make_entry("bse-q-new", source_date=_D2024),
            ],
        )
        result = query_evidence(tmp_path, until=_D2022)
        assert len(result) == 1
        assert result[0].evidence_id == "bse-q-old"

    def test_until_is_inclusive(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-q-exact", source_date=_D2022)])
        result = query_evidence(tmp_path, until=_D2022)
        assert len(result) == 1

    def test_since_and_until_together(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-q-a", source_date=_D2020),
                _make_entry("bse-q-b", source_date=_D2022),
                _make_entry("bse-q-c", source_date=_D2024),
            ],
        )
        result = query_evidence(tmp_path, since=_D2021, until=_D2023)
        assert len(result) == 1
        assert result[0].evidence_id == "bse-q-b"

    def test_since_after_until_returns_empty(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-q-x", source_date=_D2022)])
        result = query_evidence(tmp_path, since=_D2024, until=_D2020)
        assert result == []

    def test_entry_with_unparseable_date_excluded_when_date_filter_active(
        self, tmp_path: Path
    ) -> None:
        bad_entry = CatalogEntry(
            evidence_id="bse-q-baddate",
            source="BSE",
            kind=EvidenceKind.ANNUAL_REPORT.value,
            title="Bad Date",
            source_date="not-a-date",
            document_url=None,
            local_path="annual_reports/bse-q-baddate.pdf",
            file_size_bytes=None,
            acquired_at=_D2024.isoformat(),
        )
        _populate(tmp_path, [bad_entry])
        result = query_evidence(tmp_path, since=_D2020)
        assert result == []

    def test_entry_with_unparseable_date_included_when_no_date_filter(
        self, tmp_path: Path
    ) -> None:
        bad_entry = CatalogEntry(
            evidence_id="bse-q-baddate",
            source="BSE",
            kind=EvidenceKind.ANNUAL_REPORT.value,
            title="Bad Date",
            source_date="not-a-date",
            document_url=None,
            local_path="annual_reports/bse-q-baddate.pdf",
            file_size_bytes=None,
            acquired_at=_D2024.isoformat(),
        )
        _populate(tmp_path, [bad_entry])
        result = query_evidence(tmp_path)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Profile filter
# ---------------------------------------------------------------------------


class TestQueryEvidenceProfileFilter:
    def test_profile_restricts_to_profile_kinds(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-q-ar", kind=EvidenceKind.ANNUAL_REPORT),
                _make_entry("bse-q-news", kind=EvidenceKind.NEWS),
            ],
        )
        result = query_evidence(tmp_path, profile=DEFAULT_PROFILE)
        assert len(result) == 1
        assert result[0].evidence_id == "bse-q-ar"

    def test_comprehensive_profile_includes_more_kinds(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-q-ar", kind=EvidenceKind.ANNUAL_REPORT),
                _make_entry("bse-q-shp", kind=EvidenceKind.SHAREHOLDING_PATTERN),
                _make_entry("bse-q-news", kind=EvidenceKind.NEWS),
            ],
        )
        result = query_evidence(tmp_path, profile=COMPREHENSIVE_PROFILE)
        assert len(result) == 2
        ids = {e.evidence_id for e in result}
        assert ids == {"bse-q-ar", "bse-q-shp"}

    def test_custom_profile_applies_its_kinds(self, tmp_path: Path) -> None:
        cg_profile = KindFilterProfile(
            "cg-only",
            frozenset({EvidenceKind.CORPORATE_GOVERNANCE_REPORT}),
        )
        _populate(
            tmp_path,
            [
                _make_entry("bse-q-ar", kind=EvidenceKind.ANNUAL_REPORT),
                _make_entry("bse-q-cg", kind=EvidenceKind.CORPORATE_GOVERNANCE_REPORT),
            ],
        )
        result = query_evidence(tmp_path, profile=cg_profile)
        assert len(result) == 1
        assert result[0].evidence_id == "bse-q-cg"

    def test_kinds_and_profile_together_raises_value_error(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="at most one"):
            query_evidence(
                tmp_path,
                kinds={EvidenceKind.ANNUAL_REPORT},
                profile=DEFAULT_PROFILE,
            )


# ---------------------------------------------------------------------------
# Combined filters
# ---------------------------------------------------------------------------


class TestQueryEvidenceCombinedFilters:
    def test_kind_and_date_combined(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry(
                    "bse-q-ar-old", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2020
                ),
                _make_entry(
                    "bse-q-ar-new", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2024
                ),
                _make_entry(
                    "bse-q-fr", kind=EvidenceKind.FINANCIAL_RESULTS, source_date=_D2022
                ),
            ],
        )
        result = query_evidence(
            tmp_path,
            kinds={EvidenceKind.ANNUAL_REPORT},
            since=_D2022,
        )
        assert len(result) == 1
        assert result[0].evidence_id == "bse-q-ar-new"

    def test_profile_and_date_combined(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry(
                    "bse-q-ar-old", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2020
                ),
                _make_entry(
                    "bse-q-ar-new", kind=EvidenceKind.ANNUAL_REPORT, source_date=_D2024
                ),
                _make_entry("bse-q-news", kind=EvidenceKind.NEWS, source_date=_D2024),
            ],
        )
        result = query_evidence(tmp_path, profile=DEFAULT_PROFILE, since=_D2022)
        assert len(result) == 1
        assert result[0].evidence_id == "bse-q-ar-new"


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class TestQueryEvidenceSorting:
    def test_results_sorted_ascending_by_source_date(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-q-y3", source_date=_D2023),
                _make_entry("bse-q-y1", source_date=_D2021),
                _make_entry("bse-q-y2", source_date=_D2022),
            ],
        )
        result = query_evidence(tmp_path)
        dates = [e.source_date for e in result]
        assert dates == sorted(dates)

    def test_oldest_entry_first(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-q-recent", source_date=_D2024),
                _make_entry("bse-q-oldest", source_date=_D2020),
            ],
        )
        result = query_evidence(tmp_path)
        assert result[0].evidence_id == "bse-q-oldest"

    def test_newest_entry_last(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry("bse-q-oldest", source_date=_D2020),
                _make_entry("bse-q-newest", source_date=_D2024),
            ],
        )
        result = query_evidence(tmp_path)
        assert result[-1].evidence_id == "bse-q-newest"

    def test_single_entry_returns_in_list(self, tmp_path: Path) -> None:
        _populate(tmp_path, [_make_entry("bse-q-solo")])
        result = query_evidence(tmp_path)
        assert len(result) == 1
        assert result[0].evidence_id == "bse-q-solo"

    def test_many_entries_sorted_correctly(self, tmp_path: Path) -> None:
        entries = [
            _make_entry(
                f"bse-q-e{i}",
                source_date=datetime(2020 + i, 1, 1, tzinfo=timezone.utc),
            )
            for i in range(5)
        ]
        _populate(tmp_path, list(reversed(entries)))
        result = query_evidence(tmp_path)
        assert [e.evidence_id for e in result] == [f"bse-q-e{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# history_depth (M-P0.2) -- per-company corpus depth, the measurement the
# backfill is run against (Q33).
# ---------------------------------------------------------------------------
from atlas.acquisition.query import (
    HistoryDepth,
    history_depth,
    repository_history_depth,
)


class TestHistoryDepth:
    def test_empty_catalog_is_zero_depth(self) -> None:
        hd = history_depth([])
        assert hd.entry_count == 0 and hd.dated_count == 0
        assert hd.earliest is None and hd.latest is None
        assert hd.span_days is None and hd.span_years is None

    def test_earliest_latest_and_span(self) -> None:
        entries = [
            _make_entry(
                "bse-a", source_date=datetime(2021, 3, 31, tzinfo=timezone.utc)
            ),
            _make_entry(
                "bse-b", source_date=datetime(2026, 3, 31, tzinfo=timezone.utc)
            ),
            _make_entry("bse-c", source_date=datetime(2023, 6, 1, tzinfo=timezone.utc)),
        ]
        hd = history_depth(entries)
        assert hd.entry_count == 3 and hd.dated_count == 3
        assert hd.earliest == datetime(2021, 3, 31, tzinfo=timezone.utc)
        assert hd.latest == datetime(2026, 3, 31, tzinfo=timezone.utc)
        assert hd.span_years == 5.0

    def test_reaches_cutoff(self) -> None:
        hd = history_depth(
            [
                _make_entry(
                    "bse-old", source_date=datetime(2020, 6, 1, tzinfo=timezone.utc)
                ),
            ]
        )
        assert hd.reaches(datetime(2021, 3, 31, tzinfo=timezone.utc)) is True
        assert hd.reaches(datetime(2019, 1, 1, tzinfo=timezone.utc)) is False

    def test_reaches_tolerates_naive_cutoff(self) -> None:
        hd = history_depth(
            [
                _make_entry(
                    "bse-old", source_date=datetime(2020, 6, 1, tzinfo=timezone.utc)
                ),
            ]
        )
        # naive cutoff must not raise on aware/naive comparison
        assert hd.reaches(datetime(2021, 3, 31)) is True

    def test_earliest_by_kind(self) -> None:
        entries = [
            _make_entry(
                "bse-ar1",
                kind=EvidenceKind.ANNUAL_REPORT,
                source_date=datetime(2022, 1, 1, tzinfo=timezone.utc),
            ),
            _make_entry(
                "bse-ar2",
                kind=EvidenceKind.ANNUAL_REPORT,
                source_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
            _make_entry(
                "bse-fr1",
                kind=EvidenceKind.FINANCIAL_RESULTS,
                source_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ),
        ]
        hd = history_depth(entries)
        assert hd.earliest_by_kind[EvidenceKind.ANNUAL_REPORT.value] == datetime(
            2020, 1, 1, tzinfo=timezone.utc
        )
        assert hd.earliest_by_kind[EvidenceKind.FINANCIAL_RESULTS.value] == datetime(
            2024, 1, 1, tzinfo=timezone.utc
        )

    def test_undated_entry_counted_but_excluded_from_date_math(self) -> None:
        good = _make_entry(
            "bse-ok", source_date=datetime(2023, 1, 1, tzinfo=timezone.utc)
        )
        bad = _make_entry("bse-bad")
        bad.source_date = "not-a-date"
        hd = history_depth([good, bad])
        assert hd.entry_count == 2 and hd.dated_count == 1
        assert hd.earliest == datetime(2023, 1, 1, tzinfo=timezone.utc)

    def test_repository_history_depth_missing_catalog_is_empty(
        self, tmp_path: Path
    ) -> None:
        hd = repository_history_depth(tmp_path)
        assert isinstance(hd, HistoryDepth)
        assert hd.entry_count == 0

    def test_repository_history_depth_reads_catalog(self, tmp_path: Path) -> None:
        _populate(
            tmp_path,
            [
                _make_entry(
                    "bse-x", source_date=datetime(2021, 1, 1, tzinfo=timezone.utc)
                ),
            ],
        )
        hd = repository_history_depth(tmp_path)
        assert hd.dated_count == 1
        assert hd.earliest == datetime(2021, 1, 1, tzinfo=timezone.utc)
