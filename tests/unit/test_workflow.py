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
from atlas.acquisition.profile import AcquisitionProfile
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
    evidence_id: str = "ev-001",
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
# Acquisition scope and profile filtering
# ---------------------------------------------------------------------------


class TestAcquisitionScope:
    def test_all_selected_evidence_attempted_when_catalog_empty(
        self, tmp_path: Path
    ) -> None:
        evidence = [_make_evidence("ev-001"), _make_evidence("ev-002")]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert len(report.results) == 2

    def test_already_cataloged_evidence_not_downloaded(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        (root / "catalog.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "items": [
                        {
                            "evidence_id": "ev-001",
                            "source": "BSE",
                            "kind": "annual_report",
                            "title": "Old Report",
                            "source_date": "2024-01-01T00:00:00+00:00",
                            "document_url": None,
                            "local_path": "annual_reports/ev-001.pdf",
                            "file_size_bytes": 1000,
                            "acquired_at": "2026-01-01T00:00:00+00:00",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        evidence = [_make_evidence("ev-001"), _make_evidence("ev-002")]
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert len(report.results) == 1
        assert report.already_acquired == 1

    def test_empty_discovery_produces_empty_report(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        assert report.discovered == 0
        assert report.profile_selected == 0
        assert report.succeeded == 0


# ---------------------------------------------------------------------------
# Acquisition profile — filtering is the workflow's responsibility
# ---------------------------------------------------------------------------


class TestAcquisitionProfile:
    def test_default_profile_filters_out_excluded_kinds(self, tmp_path: Path) -> None:
        allowed = _make_evidence("ev-001", kind=EvidenceKind.ANNUAL_REPORT)
        excluded = _make_evidence("ev-002", kind=EvidenceKind.NEWS)
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=[allowed, excluded]))
        assert report.discovered == 2  # connector returned both
        assert report.profile_selected == 1  # only ANNUAL_REPORT matches DEFAULT
        assert len(report.results) == 1  # only the matching item downloaded

    def test_default_profile_includes_financial_results(self, tmp_path: Path) -> None:
        ev = _make_evidence("ev-001", kind=EvidenceKind.FINANCIAL_RESULTS)
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=[ev]))
        assert report.profile_selected == 1

    def test_default_profile_includes_earnings_transcript(self, tmp_path: Path) -> None:
        ev = _make_evidence("ev-001", kind=EvidenceKind.EARNINGS_TRANSCRIPT)
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=[ev]))
        assert report.profile_selected == 1

    def test_default_profile_includes_investor_presentation(
        self, tmp_path: Path
    ) -> None:
        ev = _make_evidence("ev-001", kind=EvidenceKind.INVESTOR_PRESENTATION)
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=[ev]))
        assert report.profile_selected == 1

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
            _make_evidence(f"ev-{i:03d}", kind=k) for i, k in enumerate(excluded_kinds)
        ]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.discovered == len(excluded_kinds)
        assert report.profile_selected == 0

    def test_report_carries_profile(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        assert report.profile == AcquisitionProfile.DEFAULT

    def test_annual_reports_and_announcements_combined_before_filter(
        self, tmp_path: Path
    ) -> None:
        evidence = [
            _make_evidence("ev-001", kind=EvidenceKind.ANNUAL_REPORT),
            _make_evidence("ev-002", kind=EvidenceKind.FINANCIAL_RESULTS),
            _make_evidence("ev-003", kind=EvidenceKind.NEWS),  # filtered out
        ]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.discovered == 3
        assert report.profile_selected == 2


# ---------------------------------------------------------------------------
# Catalog updates
# ---------------------------------------------------------------------------


class TestCatalogUpdates:
    def test_successful_downloads_added_to_catalog(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        run_acquisition(root, _mock_connector(evidence=[_make_evidence("ev-001")]))
        data = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        ids = [item["evidence_id"] for item in data.get("items", [])]
        assert "ev-001" in ids

    def test_failed_downloads_not_added_to_catalog(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        connector = _mock_connector(evidence=[_make_evidence("ev-001")])
        connector.fetch_bytes.side_effect = OSError("connection refused")
        run_acquisition(root, connector)
        data = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        assert data.get("items", []) == []


# ---------------------------------------------------------------------------
# Acquisition report
# ---------------------------------------------------------------------------


class TestAcquisitionReport:
    def test_report_ticker(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        assert report.ticker == "TCS"

    def test_report_company_id(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        assert report.company_id == "cmp_test123"

    def test_report_discovered_count(self, tmp_path: Path) -> None:
        evidence = [
            _make_evidence("ev-001", kind=EvidenceKind.ANNUAL_REPORT),
            _make_evidence("ev-002", kind=EvidenceKind.NEWS),  # filtered by profile
        ]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.discovered == 2

    def test_report_profile_selected_count(self, tmp_path: Path) -> None:
        evidence = [
            _make_evidence("ev-001", kind=EvidenceKind.ANNUAL_REPORT),
            _make_evidence("ev-002", kind=EvidenceKind.NEWS),
        ]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.profile_selected == 1

    def test_report_succeeded_and_failed_counts(self, tmp_path: Path) -> None:
        evidence = [_make_evidence("ev-001"), _make_evidence("ev-002")]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.succeeded == 2
        assert report.failed == 0

    def test_report_duration_is_nonnegative(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        assert report.duration_seconds >= 0

    def test_progress_callback_receives_messages(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        messages: list[str] = []
        run_acquisition(root, _mock_connector(), on_progress=messages.append)
        assert len(messages) > 0

    def test_no_progress_callback_runs_without_error(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        run_acquisition(root, _mock_connector())


# ---------------------------------------------------------------------------
# Discovery warnings propagation
# ---------------------------------------------------------------------------


class TestAcquisitionWarnings:
    def test_warnings_from_discover_appear_in_report(self, tmp_path: Path) -> None:
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
        report = run_acquisition(root, connector)
        assert len(report.warnings) == 1
        assert report.warnings[0].code == "UNMAPPED_SUBCATEGORY"
        assert report.warnings[0].metadata["subcategory"] == "Company Update"

    def test_no_warnings_when_discovery_clean(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        assert report.warnings == []

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
