import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from atlas.acquisition.connectors.connector import (
    Company,
    DiscoveryResult,
    DiscoveryWarning,
)
from atlas.acquisition.evidence import Evidence, EvidenceKind, EvidenceSource
from atlas.acquisition.workflow import run_acquisition


def _make_repo(
    tmp_path: Path,
    exchange_identities: dict | None = None,
) -> Path:
    root = tmp_path / "TCS"
    root.mkdir()
    company_data: dict = {
        "id": "cmp_test123",
        "ticker": "TCS",
        "created_at": "2026-01-01T00:00:00+00:00",
        "atlas_version": "0.1.0",
    }
    if exchange_identities is not None:
        company_data["exchange_identities"] = exchange_identities
    (root / "company.json").write_text(json.dumps(company_data), encoding="utf-8")
    (root / "catalog.json").write_text('{"schema_version": "1"}', encoding="utf-8")
    return root


def _make_evidence(
    evidence_id: str = "bse-news-001",
    kind: EvidenceKind = EvidenceKind.ANNUAL_REPORT,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        company_id="cmp_test123",
        source=EvidenceSource.BSE,
        kind=kind,
        title=f"Report {evidence_id}",
        source_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        document_url=f"https://example.com/{evidence_id}.pdf",
        file_size_bytes=1_000,
    )


def _mock_connector(evidence: list[Evidence] | None = None) -> MagicMock:
    connector = MagicMock()
    connector.discover.return_value = DiscoveryResult(
        evidence=evidence if evidence is not None else []
    )
    connector.fetch_bytes.return_value = b"PDF"
    return connector


# ---------------------------------------------------------------------------
# Company passthrough
# ---------------------------------------------------------------------------


class TestCompanyPassthrough:
    def test_discover_called_with_company_id(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        connector = _mock_connector()
        run_acquisition(root, connector)
        company_arg: Company = connector.discover.call_args[0][0]
        assert company_arg.id == "cmp_test123"

    def test_discover_called_with_ticker(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        connector = _mock_connector()
        run_acquisition(root, connector)
        company_arg: Company = connector.discover.call_args[0][0]
        assert company_arg.ticker == "TCS"

    def test_exchange_identities_from_company_json_passed_to_connector(
        self, tmp_path: Path
    ) -> None:
        ids = {"BSE": {"scrip_code": 532540}}
        root = _make_repo(tmp_path, exchange_identities=ids)
        connector = _mock_connector()
        run_acquisition(root, connector)
        company_arg: Company = connector.discover.call_args[0][0]
        assert company_arg.exchange_identities == ids

    def test_connector_identity_mutations_persisted_to_company_json(
        self, tmp_path: Path
    ) -> None:
        root = _make_repo(tmp_path)
        connector = _mock_connector()

        def _discover_with_mutation(company: Company) -> DiscoveryResult:
            company.exchange_identities["BSE"] = {"scrip_code": 532540}
            return DiscoveryResult(evidence=[])

        connector.discover.side_effect = _discover_with_mutation
        run_acquisition(root, connector)
        data = json.loads((root / "company.json").read_text(encoding="utf-8"))
        assert data["exchange_identities"]["BSE"]["scrip_code"] == 532540


# ---------------------------------------------------------------------------
# Acquisition scope and policy filtering
# ---------------------------------------------------------------------------


class TestAcquisitionScope:
    def test_all_selected_evidence_attempted_when_catalog_empty(
        self, tmp_path: Path
    ) -> None:
        evidence = [_make_evidence("bse-news-001"), _make_evidence("bse-news-002")]
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector(evidence=evidence))
        assert record.downloaded == 2

    def test_already_cataloged_evidence_not_downloaded(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        (root / "catalog.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "items": [
                        {
                            "evidence_id": "bse-news-001",
                            "source": "BSE",
                            "kind": "annual_report",
                            "title": "Old Report",
                            "source_date": "2024-01-01T00:00:00+00:00",
                            "document_url": None,
                            "local_path": "annual_reports/bse-news-001.pdf",
                            "file_size_bytes": 1000,
                            "acquired_at": "2026-01-01T00:00:00+00:00",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        evidence = [_make_evidence("bse-news-001"), _make_evidence("bse-news-002")]
        record = run_acquisition(root, _mock_connector(evidence=evidence))
        assert record.downloaded == 1
        assert record.already_acquired == 1

    def test_empty_discovery_produces_empty_record(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector())
        assert record.discovered == 0
        assert record.selected == 0
        assert record.downloaded == 0


# ---------------------------------------------------------------------------
# Acquisition policy — filtering is the workflow's responsibility
# ---------------------------------------------------------------------------


class TestAcquisitionPolicy:
    def test_default_policy_filters_out_excluded_kinds(self, tmp_path: Path) -> None:
        allowed = _make_evidence("bse-news-001", kind=EvidenceKind.ANNUAL_REPORT)
        excluded = _make_evidence("bse-news-002", kind=EvidenceKind.NEWS)
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector(evidence=[allowed, excluded]))
        assert record.discovered == 2  # connector returned both
        assert record.selected == 1   # only ANNUAL_REPORT matches DEFAULT
        assert record.downloaded == 1  # only the matching item downloaded

    def test_default_policy_includes_financial_results(self, tmp_path: Path) -> None:
        ev = _make_evidence("bse-news-001", kind=EvidenceKind.FINANCIAL_RESULTS)
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector(evidence=[ev]))
        assert record.selected == 1

    def test_default_policy_includes_earnings_transcript(self, tmp_path: Path) -> None:
        ev = _make_evidence("bse-news-001", kind=EvidenceKind.EARNINGS_TRANSCRIPT)
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector(evidence=[ev]))
        assert record.selected == 1

    def test_default_policy_includes_investor_presentation(
        self, tmp_path: Path
    ) -> None:
        ev = _make_evidence("bse-news-001", kind=EvidenceKind.INVESTOR_PRESENTATION)
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector(evidence=[ev]))
        assert record.selected == 1

    def test_connector_returns_non_default_kinds_unfiltered(
        self, tmp_path: Path
    ) -> None:
        excluded_kinds = [
            EvidenceKind.NEWS,
            EvidenceKind.AGM_NOTICE,
            EvidenceKind.DIVIDEND,
            EvidenceKind.BRSR,
        ]
        evidence = [
            _make_evidence(f"bse-news-{i:03d}", kind=k)
            for i, k in enumerate(excluded_kinds)
        ]
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector(evidence=evidence))
        assert record.discovered == len(excluded_kinds)
        assert record.selected == 0

    def test_record_carries_policy_name(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector())
        assert record.policy_name == "default"

    def test_annual_reports_and_announcements_combined_before_filter(
        self, tmp_path: Path
    ) -> None:
        evidence = [
            _make_evidence("bse-news-001", kind=EvidenceKind.ANNUAL_REPORT),
            _make_evidence("bse-news-002", kind=EvidenceKind.FINANCIAL_RESULTS),
            _make_evidence("bse-news-003", kind=EvidenceKind.NEWS),  # filtered out
        ]
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector(evidence=evidence))
        assert record.discovered == 3
        assert record.selected == 2


# ---------------------------------------------------------------------------
# Catalog updates
# ---------------------------------------------------------------------------


class TestCatalogUpdates:
    def test_successful_downloads_added_to_catalog(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        run_acquisition(root, _mock_connector(evidence=[_make_evidence("bse-news-001")]))
        data = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        ids = [item["evidence_id"] for item in data.get("items", [])]
        assert "bse-news-001" in ids

    def test_failed_downloads_not_added_to_catalog(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        connector = _mock_connector(evidence=[_make_evidence("bse-news-001")])
        connector.fetch_bytes.side_effect = OSError("connection refused")
        run_acquisition(root, connector)
        data = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        assert data.get("items", []) == []


# ---------------------------------------------------------------------------
# Acquisition record
# ---------------------------------------------------------------------------


class TestAcquisitionRecord:
    def test_record_ticker(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector())
        assert record.ticker == "TCS"

    def test_record_company_id(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector())
        assert record.company_id == "cmp_test123"

    def test_record_discovered_count(self, tmp_path: Path) -> None:
        evidence = [
            _make_evidence("bse-news-001", kind=EvidenceKind.ANNUAL_REPORT),
            _make_evidence("bse-news-002", kind=EvidenceKind.NEWS),
        ]
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector(evidence=evidence))
        assert record.discovered == 2

    def test_record_selected_count(self, tmp_path: Path) -> None:
        evidence = [
            _make_evidence("bse-news-001", kind=EvidenceKind.ANNUAL_REPORT),
            _make_evidence("bse-news-002", kind=EvidenceKind.NEWS),
        ]
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector(evidence=evidence))
        assert record.selected == 1

    def test_record_downloaded_and_failed_counts(self, tmp_path: Path) -> None:
        evidence = [_make_evidence("bse-news-001"), _make_evidence("bse-news-002")]
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector(evidence=evidence))
        assert record.downloaded == 2
        assert record.failed == 0

    def test_record_new_is_selected_minus_already_acquired(
        self, tmp_path: Path
    ) -> None:
        root = _make_repo(tmp_path)
        (root / "catalog.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "items": [
                        {
                            "evidence_id": "bse-news-001",
                            "source": "BSE",
                            "kind": "annual_report",
                            "title": "Old",
                            "source_date": "2024-01-01T00:00:00+00:00",
                            "document_url": None,
                            "local_path": "annual_reports/bse-news-001.pdf",
                            "file_size_bytes": 1000,
                            "acquired_at": "2026-01-01T00:00:00+00:00",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        evidence = [_make_evidence("bse-news-001"), _make_evidence("bse-news-002")]
        record = run_acquisition(root, _mock_connector(evidence=evidence))
        assert record.already_acquired == 1
        assert record.new == 1
        assert record.downloaded == 1

    def test_record_duration_is_nonnegative(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector())
        assert record.duration_seconds >= 0

    def test_record_saved_to_acquisitions_directory(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        run_acquisition(root, _mock_connector())
        acq_dir = root / "acquisitions"
        assert acq_dir.is_dir()
        records = list(acq_dir.glob("*.json"))
        assert len(records) == 1

    def test_record_path_set_on_returned_record(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector())
        assert record.record_path is not None
        assert record.record_path.exists()

    def test_record_file_contains_correct_counts(self, tmp_path: Path) -> None:
        evidence = [_make_evidence("bse-news-001"), _make_evidence("bse-news-002")]
        root = _make_repo(tmp_path)
        run_acquisition(root, _mock_connector(evidence=evidence))
        record_file = next((root / "acquisitions").glob("*.json"))
        data = json.loads(record_file.read_text(encoding="utf-8"))
        assert data["counts"]["discovered"] == 2
        assert data["counts"]["selected"] == 2
        assert data["counts"]["downloaded"] == 2
        assert data["counts"]["failed"] == 0

    def test_record_file_contains_policy_name(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        run_acquisition(root, _mock_connector())
        record_file = next((root / "acquisitions").glob("*.json"))
        data = json.loads(record_file.read_text(encoding="utf-8"))
        assert data["policy"] == "default"

    def test_each_run_produces_a_separate_record_file(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        run_acquisition(root, _mock_connector())
        run_acquisition(root, _mock_connector())
        records = list((root / "acquisitions").glob("*.json"))
        assert len(records) == 2

    def test_failed_download_appears_in_record_failures(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        connector = _mock_connector(evidence=[_make_evidence("bse-news-001")])
        connector.fetch_bytes.side_effect = OSError("network error")
        record = run_acquisition(root, connector)
        assert record.failed == 1
        assert record.failures[0].evidence_id == "bse-news-001"
        assert "network error" in record.failures[0].error

    def test_progress_callback_receives_messages(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        messages: list[str] = []
        run_acquisition(root, _mock_connector(), on_progress=messages.append)
        assert len(messages) > 0

    def test_no_progress_callback_runs_without_error(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        run_acquisition(root, _mock_connector())


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_second_run_downloads_nothing_when_catalog_unchanged(
        self, tmp_path: Path
    ) -> None:
        evidence = [_make_evidence("bse-news-001"), _make_evidence("bse-news-002")]
        root = _make_repo(tmp_path)
        connector = _mock_connector(evidence=evidence)
        run_acquisition(root, connector)
        second = run_acquisition(root, connector)
        assert second.downloaded == 0
        assert second.already_acquired == 2
        assert second.new == 0

    def test_second_run_still_runs_discovery(self, tmp_path: Path) -> None:
        evidence = [_make_evidence("bse-news-001")]
        root = _make_repo(tmp_path)
        connector = _mock_connector(evidence=evidence)
        run_acquisition(root, connector)
        run_acquisition(root, connector)
        assert connector.discover.call_count == 2


# ---------------------------------------------------------------------------
# Discovery warnings propagation
# ---------------------------------------------------------------------------


class TestAcquisitionWarnings:
    def test_warnings_from_discover_appear_in_record(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        warning = DiscoveryWarning(
            source=EvidenceSource.BSE,
            code="UNMAPPED_SUBCATEGORY",
            message="Unmapped BSE subcategory",
            metadata={"subcategory": "Company Update", "count": 5},
        )
        connector = _mock_connector()
        connector.discover.return_value = DiscoveryResult(
            evidence=[], warnings=[warning]
        )
        record = run_acquisition(root, connector)
        assert len(record.warnings) == 1
        assert record.warnings[0].code == "UNMAPPED_SUBCATEGORY"
        assert record.warnings[0].metadata["subcategory"] == "Company Update"

    def test_no_warnings_when_discovery_clean(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        record = run_acquisition(root, _mock_connector())
        assert record.warnings == []

    def test_warnings_emitted_via_progress_callback(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        warning = DiscoveryWarning(
            source=EvidenceSource.BSE,
            code="UNMAPPED_SUBCATEGORY",
            message="Unmapped BSE subcategory",
            metadata={"subcategory": "Company Update", "count": 3},
        )
        connector = _mock_connector()
        connector.discover.return_value = DiscoveryResult(
            evidence=[], warnings=[warning]
        )
        messages: list[str] = []
        run_acquisition(root, connector, on_progress=messages.append)
        assert any("Company Update" in m for m in messages)

    def test_warnings_serialized_in_record_file(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        warning = DiscoveryWarning(
            source=EvidenceSource.BSE,
            code="UNMAPPED_SUBCATEGORY",
            message="Unmapped BSE subcategory",
            metadata={"subcategory": "Company Update", "count": 2},
        )
        connector = _mock_connector()
        connector.discover.return_value = DiscoveryResult(
            evidence=[], warnings=[warning]
        )
        run_acquisition(root, connector)
        record_file = next((root / "acquisitions").glob("*.json"))
        data = json.loads(record_file.read_text(encoding="utf-8"))
        assert len(data["warnings"]) == 1
        assert data["warnings"][0]["code"] == "UNMAPPED_SUBCATEGORY"
