from datetime import datetime, timezone
from pathlib import Path

from atlas.acquisition.downloader import download_evidence
from atlas.acquisition.evidence import Evidence, EvidenceKind, EvidenceSource


def _make_evidence(
    evidence_id: str = "ev-001",
    kind: EvidenceKind = EvidenceKind.ANNUAL_REPORT,
    document_url: str | None = "https://example.com/report.pdf",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        company_id="cmp_abc",
        source=EvidenceSource.BSE,
        kind=kind,
        title="Annual Report 2023-24",
        source_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        document_url=document_url,
        file_size_bytes=1_000_000,
    )


class TestDownloadEvidenceSuccess:
    def test_creates_file_at_correct_path(self, tmp_path: Path) -> None:
        download_evidence(_make_evidence(), tmp_path, lambda _: b"PDF content")
        assert (tmp_path / "annual_reports" / "ev-001.pdf").exists()

    def test_returns_succeeded_result(self, tmp_path: Path) -> None:
        result = download_evidence(_make_evidence(), tmp_path, lambda _: b"PDF")
        assert result.succeeded is True

    def test_returns_correct_file_size(self, tmp_path: Path) -> None:
        content = b"X" * 1024
        result = download_evidence(_make_evidence(), tmp_path, lambda _: content)
        assert result.file_size_bytes == 1024

    def test_returns_relative_local_path(self, tmp_path: Path) -> None:
        result = download_evidence(_make_evidence(), tmp_path, lambda _: b"PDF")
        assert result.local_path == "annual_reports/ev-001.pdf"

    def test_error_is_none_on_success(self, tmp_path: Path) -> None:
        result = download_evidence(_make_evidence(), tmp_path, lambda _: b"PDF")
        assert result.error is None

    def test_creates_subdir_if_not_present(self, tmp_path: Path) -> None:
        ev = _make_evidence(kind=EvidenceKind.FINANCIAL_RESULTS)
        download_evidence(ev, tmp_path, lambda _: b"PDF")
        assert (tmp_path / "financial_results" / "ev-001.pdf").exists()


class TestDownloadEvidenceNoUrl:
    def test_returns_error_result_when_no_url(self, tmp_path: Path) -> None:
        ev = _make_evidence(document_url=None)
        result = download_evidence(ev, tmp_path, lambda _: b"")
        assert result.succeeded is False
        assert result.error == "no document URL"
        assert result.local_path is None


class TestDownloadEvidenceFailure:
    def test_returns_error_result_when_fetch_raises(self, tmp_path: Path) -> None:
        def boom(url: str) -> bytes:
            raise OSError("network error")

        result = download_evidence(_make_evidence(), tmp_path, boom)
        assert result.succeeded is False
        assert "network error" in (result.error or "")

    def test_does_not_create_file_on_fetch_failure(self, tmp_path: Path) -> None:
        def boom(url: str) -> bytes:
            raise OSError("network error")

        download_evidence(_make_evidence(), tmp_path, boom)
        assert not (tmp_path / "annual_reports" / "ev-001.pdf").exists()


class TestKindToSubdir:
    def test_annual_report_uses_annual_reports_subdir(self, tmp_path: Path) -> None:
        result = download_evidence(_make_evidence(), tmp_path, lambda _: b"PDF")
        assert result.local_path == "annual_reports/ev-001.pdf"

    def test_financial_results_uses_financial_results_subdir(
        self, tmp_path: Path
    ) -> None:
        ev = _make_evidence(kind=EvidenceKind.FINANCIAL_RESULTS)
        result = download_evidence(ev, tmp_path, lambda _: b"PDF")
        assert result.local_path == "financial_results/ev-001.pdf"

    def test_earnings_transcript_uses_earnings_transcripts_subdir(
        self, tmp_path: Path
    ) -> None:
        ev = _make_evidence(kind=EvidenceKind.EARNINGS_TRANSCRIPT)
        result = download_evidence(ev, tmp_path, lambda _: b"PDF")
        assert result.local_path == "earnings_transcripts/ev-001.pdf"

    def test_investor_presentation_uses_investor_presentations_subdir(
        self, tmp_path: Path
    ) -> None:
        ev = _make_evidence(kind=EvidenceKind.INVESTOR_PRESENTATION)
        result = download_evidence(ev, tmp_path, lambda _: b"PDF")
        assert result.local_path == "investor_presentations/ev-001.pdf"

    def test_regulatory_filing_uses_regulatory_filings_subdir(
        self, tmp_path: Path
    ) -> None:
        ev = _make_evidence(kind=EvidenceKind.REGULATORY_FILING)
        result = download_evidence(ev, tmp_path, lambda _: b"PDF")
        assert result.local_path == "regulatory_filings/ev-001.pdf"

    def test_dividend_uses_corporate_actions_subdir(self, tmp_path: Path) -> None:
        ev = _make_evidence(kind=EvidenceKind.DIVIDEND)
        result = download_evidence(ev, tmp_path, lambda _: b"PDF")
        assert result.local_path == "corporate_actions/ev-001.pdf"

    def test_buyback_uses_corporate_actions_subdir(self, tmp_path: Path) -> None:
        ev = _make_evidence(kind=EvidenceKind.BUYBACK)
        result = download_evidence(ev, tmp_path, lambda _: b"PDF")
        assert result.local_path == "corporate_actions/ev-001.pdf"

    def test_agm_notice_uses_agm_notices_subdir(self, tmp_path: Path) -> None:
        ev = _make_evidence(kind=EvidenceKind.AGM_NOTICE)
        result = download_evidence(ev, tmp_path, lambda _: b"PDF")
        assert result.local_path == "agm_notices/ev-001.pdf"

    def test_unknown_kind_uses_other_subdir(self, tmp_path: Path) -> None:
        ev = _make_evidence(kind=EvidenceKind.OTHER)
        result = download_evidence(ev, tmp_path, lambda _: b"PDF")
        assert result.local_path == "other/ev-001.pdf"


class TestFileExtension:
    def test_default_extension_is_pdf(self, tmp_path: Path) -> None:
        result = download_evidence(_make_evidence(), tmp_path, lambda _: b"data")
        assert result.local_path == "annual_reports/ev-001.pdf"

    def test_xml_extension_produces_xml_file(self, tmp_path: Path) -> None:
        ev = Evidence(
            evidence_id="ev-002",
            company_id="cmp_abc",
            source=EvidenceSource.BSE,
            kind=EvidenceKind.REGULATORY_FILING,
            title="Filing",
            source_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            document_url="https://example.com/filing.xml",
            file_size_bytes=None,
            file_extension="xml",
        )
        result = download_evidence(ev, tmp_path, lambda _: b"<xml/>")
        assert result.local_path == "regulatory_filings/ev-002.xml"
        assert (tmp_path / "regulatory_filings" / "ev-002.xml").exists()

    def test_json_extension_produces_json_file(self, tmp_path: Path) -> None:
        ev = Evidence(
            evidence_id="ev-003",
            company_id="cmp_abc",
            source=EvidenceSource.BSE,
            kind=EvidenceKind.REGULATORY_FILING,
            title="Data",
            source_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            document_url="https://example.com/data.json",
            file_size_bytes=None,
            file_extension="json",
        )
        result = download_evidence(ev, tmp_path, lambda _: b"{}")
        assert result.local_path == "regulatory_filings/ev-003.json"
