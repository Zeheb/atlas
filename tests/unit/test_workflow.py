import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from atlas.acquisition.acquisitions import AcquisitionReport, save_acquisition_run
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
# Acquisition scope and profile filtering
# ---------------------------------------------------------------------------


class TestAcquisitionScope:
    def test_all_selected_evidence_attempted_when_catalog_empty(
        self, tmp_path: Path
    ) -> None:
        evidence = [_make_evidence("bse-news-001"), _make_evidence("bse-news-002")]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.downloaded == 2

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
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.downloaded == 1
        assert report.already_acquired == 1

    def test_empty_discovery_produces_empty_report(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        assert report.discovered == 0
        assert report.selected == 0
        assert report.downloaded == 0


# ---------------------------------------------------------------------------
# Acquisition profile — filtering is the workflow's responsibility
# ---------------------------------------------------------------------------


class TestAcquisitionProfileFiltering:
    def test_default_profile_filters_out_excluded_kinds(self, tmp_path: Path) -> None:
        allowed = _make_evidence("bse-news-001", kind=EvidenceKind.ANNUAL_REPORT)
        excluded = _make_evidence("bse-news-002", kind=EvidenceKind.NEWS)
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=[allowed, excluded]))
        assert report.discovered == 2
        assert report.selected == 1
        assert report.downloaded == 1

    def test_default_profile_includes_financial_results(self, tmp_path: Path) -> None:
        ev = _make_evidence("bse-news-001", kind=EvidenceKind.FINANCIAL_RESULTS)
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=[ev]))
        assert report.selected == 1

    def test_default_profile_includes_earnings_transcript(self, tmp_path: Path) -> None:
        ev = _make_evidence("bse-news-001", kind=EvidenceKind.EARNINGS_TRANSCRIPT)
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=[ev]))
        assert report.selected == 1

    def test_default_profile_includes_investor_presentation(
        self, tmp_path: Path
    ) -> None:
        ev = _make_evidence("bse-news-001", kind=EvidenceKind.INVESTOR_PRESENTATION)
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=[ev]))
        assert report.selected == 1

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
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.discovered == len(excluded_kinds)
        assert report.selected == 0

    def test_report_carries_profile_name(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        assert report.profile == "default"

    def test_annual_reports_and_announcements_combined_before_filter(
        self, tmp_path: Path
    ) -> None:
        evidence = [
            _make_evidence("bse-news-001", kind=EvidenceKind.ANNUAL_REPORT),
            _make_evidence("bse-news-002", kind=EvidenceKind.FINANCIAL_RESULTS),
            _make_evidence("bse-news-003", kind=EvidenceKind.NEWS),
        ]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.discovered == 3
        assert report.selected == 2


# ---------------------------------------------------------------------------
# Catalog updates
# ---------------------------------------------------------------------------


class TestCatalogUpdates:
    def test_successful_downloads_added_to_catalog(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        run_acquisition(
            root, _mock_connector(evidence=[_make_evidence("bse-news-001")])
        )
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
# AcquisitionReport
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
            _make_evidence("bse-news-001", kind=EvidenceKind.ANNUAL_REPORT),
            _make_evidence("bse-news-002", kind=EvidenceKind.NEWS),
        ]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.discovered == 2

    def test_report_selected_count(self, tmp_path: Path) -> None:
        evidence = [
            _make_evidence("bse-news-001", kind=EvidenceKind.ANNUAL_REPORT),
            _make_evidence("bse-news-002", kind=EvidenceKind.NEWS),
        ]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.selected == 1

    def test_report_downloaded_and_failed_counts(self, tmp_path: Path) -> None:
        evidence = [_make_evidence("bse-news-001"), _make_evidence("bse-news-002")]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.downloaded == 2
        assert report.failed == 0

    def test_report_new_is_selected_minus_already_acquired(
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
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        assert report.already_acquired == 1
        assert report.new == 1
        assert report.downloaded == 1

    def test_report_duration_is_nonnegative(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        assert report.duration_seconds >= 0

    def test_report_results_accessible_for_failure_details(
        self, tmp_path: Path
    ) -> None:
        root = _make_repo(tmp_path)
        connector = _mock_connector(evidence=[_make_evidence("bse-news-001")])
        connector.fetch_bytes.side_effect = OSError("network error")
        report = run_acquisition(root, connector)
        assert report.failed == 1
        failed = [r for r in report.results if not r.succeeded]
        assert len(failed) == 1
        assert failed[0].evidence.evidence_id == "bse-news-001"
        assert "network error" in (failed[0].error or "")

    def test_report_is_acquisition_report_instance(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        assert isinstance(report, AcquisitionReport)

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
# Acquisition run persistence (save_acquisition_run)
# ---------------------------------------------------------------------------


class TestAcquisitionRunPersistence:
    def test_run_file_written_to_acquisitions_directory(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        save_acquisition_run(report, root)
        assert (root / "acquisitions").is_dir()
        assert len(list((root / "acquisitions").glob("*.json"))) == 1

    def test_run_file_contains_correct_counts(self, tmp_path: Path) -> None:
        evidence = [_make_evidence("bse-news-001"), _make_evidence("bse-news-002")]
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector(evidence=evidence))
        save_acquisition_run(report, root)
        run_file = next((root / "acquisitions").glob("*.json"))
        data = json.loads(run_file.read_text(encoding="utf-8"))
        assert data["counts"]["discovered"] == 2
        assert data["counts"]["selected"] == 2
        assert data["counts"]["downloaded"] == 2
        assert data["counts"]["failed"] == 0

    def test_run_file_contains_profile_name(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        save_acquisition_run(report, root)
        run_file = next((root / "acquisitions").glob("*.json"))
        data = json.loads(run_file.read_text(encoding="utf-8"))
        assert data["profile"] == "default"

    def test_each_call_produces_a_separate_run_file(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        save_acquisition_run(report, root)
        save_acquisition_run(report, root)
        files = list((root / "acquisitions").glob("*.json"))
        assert len(files) == 2

    def test_run_record_path_is_set(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        report = run_acquisition(root, _mock_connector())
        acq_run = save_acquisition_run(report, root)
        assert acq_run.record_path.exists()

    def test_run_file_contains_failures(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        connector = _mock_connector(evidence=[_make_evidence("bse-news-001")])
        connector.fetch_bytes.side_effect = OSError("disk full")
        report = run_acquisition(root, connector)
        save_acquisition_run(report, root)
        run_file = next((root / "acquisitions").glob("*.json"))
        data = json.loads(run_file.read_text(encoding="utf-8"))
        assert len(data["failures"]) == 1
        assert data["failures"][0]["evidence_id"] == "bse-news-001"
        assert "disk full" in data["failures"][0]["error"]

    def test_run_file_contains_warnings(self, tmp_path: Path) -> None:
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
        report = run_acquisition(root, connector)
        save_acquisition_run(report, root)
        run_file = next((root / "acquisitions").glob("*.json"))
        data = json.loads(run_file.read_text(encoding="utf-8"))
        assert len(data["warnings"]) == 1
        assert data["warnings"][0]["code"] == "UNMAPPED_SUBCATEGORY"


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


# ---------------------------------------------------------------------------
# Inline classification — Stage 1 of the acquisition-hardening sprint:
# classification must happen automatically during acquisition, with no
# separate repair pass. These use a real (if minimal) generated PDF, since
# the classifier only sees text that KnowledgeBase.parse() actually extracts
# — a fake b"PDF" placeholder (used by _mock_connector() elsewhere in this
# file) never reaches classify() at all, because it fails to parse.
# ---------------------------------------------------------------------------


def _pdf_bytes(text: str) -> bytes:
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    data = pdf.tobytes()
    pdf.close()
    return data


class TestInlineClassification:
    def test_related_party_document_reclassified_with_no_repair_script(
        self, tmp_path: Path
    ) -> None:
        root = _make_repo(tmp_path)
        ev = _make_evidence("bse-news-rp1", kind=EvidenceKind.FINANCIAL_RESULTS)
        connector = _mock_connector(evidence=[ev])
        connector.fetch_bytes.return_value = _pdf_bytes(
            "Sub: Disclosure of Related Party Transactions pursuant to "
            "Regulation 23(9) of the SEBI (LODR) Regulations, 2015"
        )

        report = run_acquisition(root, connector)

        assert report.reclassified == 1
        from atlas.acquisition.catalog import RepositoryCatalog

        catalog = RepositoryCatalog(root)
        assert catalog.get_entry("bse-news-rp1").kind == "regulatory_filing"

    def test_real_financial_results_not_reclassified(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        ev = _make_evidence("bse-news-fr1", kind=EvidenceKind.FINANCIAL_RESULTS)
        connector = _mock_connector(evidence=[ev])
        connector.fetch_bytes.return_value = _pdf_bytes(
            "Sub: Financial Results for the year ended March 31, 2026"
        )

        report = run_acquisition(root, connector)

        assert report.classified == 1
        assert report.reclassified == 0
        from atlas.acquisition.catalog import RepositoryCatalog

        catalog = RepositoryCatalog(root)
        assert catalog.get_entry("bse-news-fr1").kind == "financial_results"

    def test_classification_report_counts_reflect_document_outcomes(
        self, tmp_path: Path
    ) -> None:
        root = _make_repo(tmp_path)
        ev1 = _make_evidence("bse-news-rp2", kind=EvidenceKind.FINANCIAL_RESULTS)
        ev2 = _make_evidence("bse-news-fr2", kind=EvidenceKind.FINANCIAL_RESULTS)
        connector = _mock_connector(evidence=[ev1, ev2])

        def _fetch(url: str) -> bytes:
            if "rp2" in url:
                return _pdf_bytes(
                    "Sub: Disclosure of Related Party Transactions pursuant to Regulation 23(9)"
                )
            return _pdf_bytes(
                "Sub: Financial Results for the year ended March 31, 2026"
            )

        connector.fetch_bytes.side_effect = _fetch

        report = run_acquisition(root, connector)

        assert report.downloaded == 2
        assert report.classified == 2
        assert report.reclassified == 1

    def test_parse_failure_keeps_original_kind_without_crashing(
        self, tmp_path: Path
    ) -> None:
        # A download that succeeds but isn't a real parseable PDF (the
        # existing _mock_connector default) must not crash the pipeline —
        # classification simply has nothing to classify without text.
        root = _make_repo(tmp_path)
        ev = _make_evidence("bse-news-bad1", kind=EvidenceKind.FINANCIAL_RESULTS)
        report = run_acquisition(root, _mock_connector(evidence=[ev]))

        assert report.downloaded == 1
        assert report.classified == 0
        from atlas.acquisition.catalog import RepositoryCatalog

        catalog = RepositoryCatalog(root)
        assert catalog.get_entry("bse-news-bad1").kind == "financial_results"

    def test_ocr_used_false_for_native_text_pdf(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        ev = _make_evidence("bse-news-native1", kind=EvidenceKind.FINANCIAL_RESULTS)
        connector = _mock_connector(evidence=[ev])
        connector.fetch_bytes.return_value = _pdf_bytes(
            "Sub: Financial Results for the year ended March 31, 2026"
        )
        report = run_acquisition(root, connector)
        assert report.ocr_used == 0


# ---------------------------------------------------------------------------
# Multi-connector orchestration — Stage 4 of the acquisition-hardening
# sprint: proves run_acquisition() itself (not just resolve_multi_source()
# in isolation) genuinely orchestrates more than one connector, using a
# second mock connector standing in for a future real second source (e.g.
# NSE). No source-specific code is added to make this work — additional_
# connectors is a plain list of anything satisfying the Connector protocol.
# ---------------------------------------------------------------------------


class TestMultiConnectorOrchestration:
    def test_evidence_from_second_connector_is_downloaded(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        primary = _mock_connector(evidence=[_make_evidence("bse-news-p1")])
        second = _mock_connector(
            evidence=[
                Evidence(
                    evidence_id="nse-news-s1",
                    company_id="cmp_test123",
                    source=EvidenceSource.NSE,
                    kind=EvidenceKind.FINANCIAL_RESULTS,
                    title="Financial Results from a second source",
                    source_date=datetime(2025, 6, 1, tzinfo=timezone.utc),
                    document_url="https://example.com/nse-news-s1.pdf",
                    file_size_bytes=2_000,
                )
            ]
        )

        report = run_acquisition(root, primary, additional_connectors=[second])

        assert report.discovered == 2
        assert report.downloaded == 2
        second.fetch_bytes.assert_called()

    def test_duplicate_across_connectors_is_suppressed(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path)
        same_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
        bse_copy = Evidence(
            evidence_id="bse-news-dup",
            company_id="cmp_test123",
            source=EvidenceSource.BSE,
            kind=EvidenceKind.FINANCIAL_RESULTS,
            title="Q4 Results",
            source_date=same_date,
            document_url="https://bse.example.com/dup.pdf",
            file_size_bytes=100,
        )
        nse_copy = Evidence(
            evidence_id="nse-news-dup",
            company_id="cmp_test123",
            source=EvidenceSource.NSE,
            kind=EvidenceKind.FINANCIAL_RESULTS,
            title="Q4 Results",
            source_date=same_date,
            document_url="https://nse.example.com/dup.pdf",
            file_size_bytes=500,  # larger -> preferred by the default tiebreak
        )
        primary = _mock_connector(evidence=[bse_copy])
        second = _mock_connector(evidence=[nse_copy])

        report = run_acquisition(root, primary, additional_connectors=[second])

        # Only the NSE copy (larger file) should have been kept and downloaded;
        # the BSE duplicate must never reach the download step at all.
        assert report.downloaded == 1
        assert report.results[0].evidence.evidence_id == "nse-news-dup"
        primary.fetch_bytes.assert_not_called()
        dedup_warnings = [
            w for w in report.warnings if w.code == "duplicate_across_exchanges"
        ]
        assert len(dedup_warnings) == 1

    def test_no_additional_connectors_behaves_exactly_as_before(
        self, tmp_path: Path
    ) -> None:
        # The default (no additional_connectors) must be indistinguishable
        # from every pre-multi-source-sprint acquisition run.
        root = _make_repo(tmp_path)
        evidence = [_make_evidence("bse-news-001"), _make_evidence("bse-news-002")]
        connector = _mock_connector(evidence=evidence)
        report = run_acquisition(root, connector)
        assert report.discovered == 2
        assert report.downloaded == 2
