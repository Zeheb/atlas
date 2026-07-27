"""Unit tests for atlas.acquisition.multi_source.

Every scenario is synthetic (no real NSE connector exists yet) — these
tests prove the merge/dedup logic itself, so it's already correct on the
day a second real connector exists to feed it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.acquisition.connectors.connector import DiscoveryResult, DiscoveryWarning
from atlas.acquisition.evidence import Evidence, EvidenceKind, EvidenceSource
from atlas.acquisition.multi_source import resolve_multi_source


def _ev(
    evidence_id: str,
    source: EvidenceSource,
    kind: EvidenceKind = EvidenceKind.FINANCIAL_RESULTS,
    date: datetime = datetime(2026, 4, 9, tzinfo=timezone.utc),
    file_size_bytes: int | None = 100_000,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        company_id="cmp_tcs",
        source=source,
        kind=kind,
        title="Financial Results Q4 FY26",
        source_date=date,
        document_url=f"https://example.com/{evidence_id}",
        file_size_bytes=file_size_bytes,
    )


class TestSingleSourceIsNoOp:
    """The common case today: only BSE. Merging one source must be
    byte-for-byte identical to not merging at all."""

    def test_single_source_evidence_passes_through_unchanged(self):
        bse_result = DiscoveryResult(evidence=[_ev("bse-1", EvidenceSource.BSE)])
        merged = resolve_multi_source([bse_result])
        assert merged.evidence == [bse_result.evidence[0]]

    def test_single_source_multiple_documents_all_pass_through(self):
        docs = [
            _ev(
                "bse-1",
                EvidenceSource.BSE,
                date=datetime(2026, 4, 9, tzinfo=timezone.utc),
            ),
            _ev(
                "bse-2",
                EvidenceSource.BSE,
                date=datetime(2026, 1, 9, tzinfo=timezone.utc),
            ),
            _ev("bse-3", EvidenceSource.BSE, kind=EvidenceKind.ANNUAL_REPORT),
        ]
        bse_result = DiscoveryResult(evidence=docs)
        merged = resolve_multi_source([bse_result])
        assert len(merged.evidence) == 3
        assert set(e.evidence_id for e in merged.evidence) == {
            "bse-1",
            "bse-2",
            "bse-3",
        }

    def test_single_source_warnings_preserved(self):
        warning = DiscoveryWarning(source=EvidenceSource.BSE, code="test", message="x")
        bse_result = DiscoveryResult(
            evidence=[_ev("bse-1", EvidenceSource.BSE)], warnings=[warning]
        )
        merged = resolve_multi_source([bse_result])
        assert warning in merged.warnings

    def test_no_sources_returns_empty(self):
        merged = resolve_multi_source([])
        assert merged.evidence == []
        assert merged.warnings == []


class TestDeduplication:
    def test_same_filing_from_two_exchanges_deduplicated_to_one(self):
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        bse = DiscoveryResult(
            evidence=[_ev("bse-1", EvidenceSource.BSE, date=same_date)]
        )
        nse = DiscoveryResult(
            evidence=[_ev("nse-1", EvidenceSource.NSE, date=same_date)]
        )
        merged = resolve_multi_source([bse, nse])
        assert len(merged.evidence) == 1

    def test_larger_file_size_preferred(self):
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        bse = DiscoveryResult(
            evidence=[
                _ev("bse-1", EvidenceSource.BSE, date=same_date, file_size_bytes=100)
            ]
        )
        nse = DiscoveryResult(
            evidence=[
                _ev("nse-1", EvidenceSource.NSE, date=same_date, file_size_bytes=500)
            ]
        )
        merged = resolve_multi_source([bse, nse])
        assert merged.evidence[0].evidence_id == "nse-1"

    def test_equal_size_falls_back_to_bse(self):
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        bse = DiscoveryResult(
            evidence=[
                _ev("bse-1", EvidenceSource.BSE, date=same_date, file_size_bytes=100)
            ]
        )
        nse = DiscoveryResult(
            evidence=[
                _ev("nse-1", EvidenceSource.NSE, date=same_date, file_size_bytes=100)
            ]
        )
        merged = resolve_multi_source([bse, nse])
        assert merged.evidence[0].source == EvidenceSource.BSE

    def test_different_kinds_same_day_not_deduplicated(self):
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        bse = DiscoveryResult(
            evidence=[
                _ev(
                    "bse-1",
                    EvidenceSource.BSE,
                    kind=EvidenceKind.FINANCIAL_RESULTS,
                    date=same_date,
                )
            ]
        )
        nse = DiscoveryResult(
            evidence=[
                _ev(
                    "nse-1",
                    EvidenceSource.NSE,
                    kind=EvidenceKind.BOARD_OUTCOME,
                    date=same_date,
                )
            ]
        )
        merged = resolve_multi_source([bse, nse])
        assert len(merged.evidence) == 2

    def test_different_dates_not_deduplicated(self):
        bse = DiscoveryResult(
            evidence=[
                _ev(
                    "bse-1",
                    EvidenceSource.BSE,
                    date=datetime(2026, 4, 9, tzinfo=timezone.utc),
                )
            ]
        )
        nse = DiscoveryResult(
            evidence=[
                _ev(
                    "nse-1",
                    EvidenceSource.NSE,
                    date=datetime(2026, 1, 9, tzinfo=timezone.utc),
                )
            ]
        )
        merged = resolve_multi_source([bse, nse])
        assert len(merged.evidence) == 2

    def test_two_genuine_same_source_documents_not_collapsed(self):
        # Regression: the match key is (kind, date) alone, which two
        # distinct real filings from the *same* connector can share (e.g.
        # an original announcement and a same-day amendment) — these must
        # never be treated as duplicates of each other. Only a document
        # appearing under more than one distinct *source* is a real
        # cross-exchange duplicate.
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        bse = DiscoveryResult(
            evidence=[
                _ev("bse-1", EvidenceSource.BSE, date=same_date),
                _ev("bse-2", EvidenceSource.BSE, date=same_date),
            ]
        )
        merged = resolve_multi_source([bse])
        assert len(merged.evidence) == 2
        assert {e.evidence_id for e in merged.evidence} == {"bse-1", "bse-2"}

    def test_uneven_source_counts_not_collapsed(self):
        # BSE contributes 2 documents, NSE contributes 1, all same (kind,
        # date) — not a clean 1:1 cross-source overlap, so nothing is
        # suppressed rather than guessing which pairing is "the" duplicate.
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        bse = DiscoveryResult(
            evidence=[
                _ev("bse-1", EvidenceSource.BSE, date=same_date),
                _ev("bse-2", EvidenceSource.BSE, date=same_date),
            ]
        )
        nse = DiscoveryResult(
            evidence=[_ev("nse-1", EvidenceSource.NSE, date=same_date)]
        )
        merged = resolve_multi_source([bse, nse])
        assert len(merged.evidence) == 3

    def test_dedup_emits_provenance_warning(self):
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        bse = DiscoveryResult(
            evidence=[
                _ev("bse-1", EvidenceSource.BSE, date=same_date, file_size_bytes=500)
            ]
        )
        nse = DiscoveryResult(
            evidence=[
                _ev("nse-1", EvidenceSource.NSE, date=same_date, file_size_bytes=100)
            ]
        )
        merged = resolve_multi_source([bse, nse])
        dedup_warnings = [
            w for w in merged.warnings if w.code == "duplicate_across_exchanges"
        ]
        assert len(dedup_warnings) == 1
        assert dedup_warnings[0].metadata["kept_evidence_id"] == "bse-1"
        assert "nse-1" in dedup_warnings[0].metadata["suppressed_evidence_ids"]

    def test_suppressed_evidence_id_recoverable_from_warning_not_lost(self):
        # "Preserve provenance" — a suppressed duplicate must still be
        # findable, even though it isn't downloaded.
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        bse = DiscoveryResult(
            evidence=[
                _ev("bse-1", EvidenceSource.BSE, date=same_date, file_size_bytes=500)
            ]
        )
        nse = DiscoveryResult(
            evidence=[
                _ev("nse-1", EvidenceSource.NSE, date=same_date, file_size_bytes=100)
            ]
        )
        merged = resolve_multi_source([bse, nse])
        all_suppressed_ids = [
            eid
            for w in merged.warnings
            if w.code == "duplicate_across_exchanges"
            for eid in w.metadata["suppressed_evidence_ids"]
        ]
        assert "nse-1" in all_suppressed_ids

    def test_three_way_duplicate_keeps_exactly_one(self):
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        from atlas.acquisition.evidence import EvidenceSource as ES

        bse = DiscoveryResult(
            evidence=[_ev("bse-1", ES.BSE, date=same_date, file_size_bytes=100)]
        )
        nse = DiscoveryResult(
            evidence=[_ev("nse-1", ES.NSE, date=same_date, file_size_bytes=200)]
        )
        mca = DiscoveryResult(
            evidence=[_ev("mca-1", ES.MCA, date=same_date, file_size_bytes=50)]
        )
        merged = resolve_multi_source([bse, nse, mca])
        assert len(merged.evidence) == 1
        assert merged.evidence[0].evidence_id == "nse-1"


class TestCustomQualityPreference:
    def test_custom_preference_function_used(self):
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        bse = DiscoveryResult(
            evidence=[
                _ev("bse-1", EvidenceSource.BSE, date=same_date, file_size_bytes=500)
            ]
        )
        nse = DiscoveryResult(
            evidence=[
                _ev("nse-1", EvidenceSource.NSE, date=same_date, file_size_bytes=100)
            ]
        )

        def always_prefer_nse(a: Evidence, b: Evidence) -> Evidence:
            return a if a.source == EvidenceSource.NSE else b

        merged = resolve_multi_source(
            [bse, nse],
            quality_preference=always_prefer_nse,
        )
        assert merged.evidence[0].source == EvidenceSource.NSE
