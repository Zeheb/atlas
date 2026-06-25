import logging
from datetime import datetime, timezone

import pytest

from atlas.acquisition.connectors.bse_parser import BSEParser
from atlas.acquisition.evidence import Evidence, EvidenceKind, EvidenceSource

COMPANY_ID = "cmp_abc123"
SCRIP_CODE = 532540

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

FILING_RECORD: dict = {
    "NEWSID": "6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae",
    "HEADLINE": "TCS Annual Report 2023-24",
    "SUBCATNAME": "Annual Report",
    "DT_TM": "2023-10-20T23:44:22",
    "PDFFLAG": 1,
    "OLD": 0,
    "ATTACHMENTNAME": "aab502e1-3e05-4fdc-bc10-ecbb436cab8d.pdf",
    "Fld_Attachsize": 5242880,
    "TotalPageCnt": 3,
}

HISTORICAL_FILING_RECORD: dict = {**FILING_RECORD, "OLD": 1}

NON_PDF_RECORD: dict = {**FILING_RECORD, "PDFFLAG": 0}

AGM_NOTICE_RECORD: dict = {**FILING_RECORD, "SUBCATNAME": "AGM/EGM Notice"}

FRACTIONAL_TIMESTAMP_RECORD: dict = {**FILING_RECORD, "DT_TM": "2023-10-20T23:44:22.95"}

REVISED_ANNUAL_REPORT_RECORD: dict = {
    **FILING_RECORD,
    "SUBCATNAME": "Annual Report - Revised",
}

UNKNOWN_SUBCATEGORY_RECORD: dict = {
    **FILING_RECORD,
    "SUBCATNAME": "Some Future Category",
}


def make_response(*records: dict, total_pages: int = 1) -> dict:
    patched = [{**r, "TotalPageCnt": total_pages} for r in records]
    return {"Table": patched, "Table1": [{"ROWCNT": len(records)}]}


# ---------------------------------------------------------------------------
# parse_filings
# ---------------------------------------------------------------------------


class TestParseFilings:
    def test_returns_one_filing_for_valid_record(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(make_response(FILING_RECORD), COMPANY_ID)
        assert len(result) == 1

    def test_drops_non_pdf_records(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(make_response(NON_PDF_RECORD), COMPANY_ID)
        assert result == []

    def test_empty_table_returns_empty_list(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings({"Table": [], "Table1": []}, COMPANY_ID)
        assert result == []

    def test_missing_table_key_returns_empty_list(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings({}, COMPANY_ID)
        assert result == []

    def test_propagates_company_id_to_all_filings(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(
            make_response(FILING_RECORD, REVISED_ANNUAL_REPORT_RECORD), COMPANY_ID
        )
        assert all(e.company_id == COMPANY_ID for e in result)

    def test_mixed_pdf_and_non_pdf_keeps_only_pdf(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(
            make_response(FILING_RECORD, NON_PDF_RECORD), COMPANY_ID
        )
        assert len(result) == 1

    def test_returns_evidence_instances(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(make_response(FILING_RECORD), COMPANY_ID)
        assert isinstance(result[0], Evidence)


class TestParseFilingFields:
    def setup_method(self) -> None:
        self.parser = BSEParser()
        self.evidence = self.parser.parse_filings(
            make_response(FILING_RECORD), COMPANY_ID
        )[0]

    def test_evidence_id(self) -> None:
        assert self.evidence.evidence_id == "6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae"

    def test_source_is_bse_enum(self) -> None:
        assert self.evidence.source == EvidenceSource.BSE

    def test_kind_is_annual_report_enum(self) -> None:
        assert self.evidence.kind == EvidenceKind.ANNUAL_REPORT

    def test_title(self) -> None:
        assert self.evidence.title == "TCS Annual Report 2023-24"

    def test_file_size_bytes(self) -> None:
        assert self.evidence.file_size_bytes == 5242880

    def test_document_url_is_attach_live_when_old_is_zero(self) -> None:
        assert self.evidence.document_url == (
            "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
            "aab502e1-3e05-4fdc-bc10-ecbb436cab8d.pdf"
        )

    def test_source_date_is_utc(self) -> None:
        assert self.evidence.source_date.tzinfo == timezone.utc

    def test_source_date_converts_ist_to_utc(self) -> None:
        # 23:44:22 IST = 18:14:22 UTC (IST is UTC+5:30)
        assert self.evidence.source_date == datetime(
            2023, 10, 20, 18, 14, 22, tzinfo=timezone.utc
        )


# ---------------------------------------------------------------------------
# EvidenceKind mapping
# ---------------------------------------------------------------------------


class TestEvidenceKindMapping:
    def test_annual_report_subcatname_maps_to_annual_report_kind(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(make_response(FILING_RECORD), COMPANY_ID)
        assert result[0].kind == EvidenceKind.ANNUAL_REPORT

    def test_revised_annual_report_maps_to_annual_report_kind(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(
            make_response(REVISED_ANNUAL_REPORT_RECORD), COMPANY_ID
        )
        assert result[0].kind == EvidenceKind.ANNUAL_REPORT

    def test_reg34_annual_report_maps_to_annual_report_kind(self) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "Reg. 34 (1) Annual Report"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.ANNUAL_REPORT

    def test_agm_notice_maps_to_agm_notice_kind(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(make_response(AGM_NOTICE_RECORD), COMPANY_ID)
        assert result[0].kind == EvidenceKind.AGM_NOTICE

    def test_financial_results_maps_to_financial_results_kind(self) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "Financial Results"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.FINANCIAL_RESULTS

    def test_analyst_investor_meet_maps_to_investor_presentation(self) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "Analyst / Investor Meet"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.INVESTOR_PRESENTATION

    def test_investor_presentation_subcatname_maps_to_investor_presentation(
        self,
    ) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "Investor Presentation"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.INVESTOR_PRESENTATION

    def test_earnings_call_transcript_maps_to_earnings_transcript(self) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "Earnings Call Transcript"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.EARNINGS_TRANSCRIPT

    def test_brsr_maps_to_brsr_kind(self) -> None:
        parser = BSEParser()
        record = {
            **FILING_RECORD,
            "SUBCATNAME": "Business Responsibility and Sustainability Reporting (BRSR)",
        }
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.BRSR

    def test_dividend_maps_to_dividend_kind(self) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "Dividend"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.DIVIDEND

    def test_buyback_maps_to_buyback_kind(self) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "Buy back"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.BUYBACK

    def test_acquisition_maps_to_acquisition_kind(self) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "Acquisition"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.ACQUISITION

    def test_outcome_of_board_meeting_maps_to_board_outcome(self) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "Outcome of Board Meeting"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.BOARD_OUTCOME

    def test_agm_subcatname_maps_to_agm_notice(self) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "AGM"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.AGM_NOTICE

    def test_press_release_maps_to_news(self) -> None:
        parser = BSEParser()
        record = {**FILING_RECORD, "SUBCATNAME": "Press Release / Media Release"}
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].kind == EvidenceKind.NEWS

    def test_unknown_subcatname_maps_to_other_kind(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(
            make_response(UNKNOWN_SUBCATEGORY_RECORD), COMPANY_ID
        )
        assert result[0].kind == EvidenceKind.OTHER


# ---------------------------------------------------------------------------
# Unknown subcategory observability
# ---------------------------------------------------------------------------


class TestUnknownSubcategory:
    def test_unknown_subcategory_is_counted(self) -> None:
        parser = BSEParser()
        parser.parse_filings(make_response(UNKNOWN_SUBCATEGORY_RECORD), COMPANY_ID)
        assert parser.unknown_subcategories["Some Future Category"] == 1

    def test_repeated_unknown_subcategory_accumulates_count(self) -> None:
        record1 = {**UNKNOWN_SUBCATEGORY_RECORD, "NEWSID": "id-1"}
        record2 = {**UNKNOWN_SUBCATEGORY_RECORD, "NEWSID": "id-2"}
        parser = BSEParser()
        parser.parse_filings(make_response(record1, record2), COMPANY_ID)
        assert parser.unknown_subcategories["Some Future Category"] == 2

    def test_multiple_distinct_unknowns_each_counted_separately(self) -> None:
        record1 = {
            **UNKNOWN_SUBCATEGORY_RECORD,
            "NEWSID": "id-1",
            "SUBCATNAME": "Cat A",
        }
        record2 = {
            **UNKNOWN_SUBCATEGORY_RECORD,
            "NEWSID": "id-2",
            "SUBCATNAME": "Cat B",
        }
        parser = BSEParser()
        parser.parse_filings(make_response(record1, record2), COMPANY_ID)
        assert parser.unknown_subcategories["Cat A"] == 1
        assert parser.unknown_subcategories["Cat B"] == 1

    def test_known_subcategory_not_counted(self) -> None:
        parser = BSEParser()
        parser.parse_filings(make_response(FILING_RECORD), COMPANY_ID)
        assert parser.unknown_subcategories == {}

    def test_unknown_subcategory_logged_on_first_encounter(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        record1 = {**UNKNOWN_SUBCATEGORY_RECORD, "NEWSID": "id-1"}
        record2 = {**UNKNOWN_SUBCATEGORY_RECORD, "NEWSID": "id-2"}
        with caplog.at_level(
            logging.WARNING,
            logger="atlas.acquisition.connectors.bse_parser",
        ):
            parser = BSEParser()
            parser.parse_filings(make_response(record1, record2), COMPANY_ID)
        warnings = [r for r in caplog.records if "Some Future Category" in r.message]
        assert len(warnings) == 1

    def test_different_unknowns_each_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        record1 = {
            **UNKNOWN_SUBCATEGORY_RECORD,
            "NEWSID": "id-1",
            "SUBCATNAME": "Cat A",
        }
        record2 = {
            **UNKNOWN_SUBCATEGORY_RECORD,
            "NEWSID": "id-2",
            "SUBCATNAME": "Cat B",
        }
        with caplog.at_level(
            logging.WARNING,
            logger="atlas.acquisition.connectors.bse_parser",
        ):
            parser = BSEParser()
            parser.parse_filings(make_response(record1, record2), COMPANY_ID)
        messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Cat A" in m for m in messages)
        assert any("Cat B" in m for m in messages)


# ---------------------------------------------------------------------------
# Attachment URL construction
# ---------------------------------------------------------------------------


class TestAttachmentUrl:
    def test_old_zero_produces_attach_live_url(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(make_response(FILING_RECORD), COMPANY_ID)
        assert result[0].document_url is not None
        assert "AttachLive" in result[0].document_url

    def test_old_one_produces_attach_his_url(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(
            make_response(HISTORICAL_FILING_RECORD), COMPANY_ID
        )
        assert result[0].document_url is not None
        assert "AttachHis" in result[0].document_url

    def test_missing_attachment_name_produces_none_url(self) -> None:
        record = {**FILING_RECORD, "ATTACHMENTNAME": ""}
        parser = BSEParser()
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].document_url is None

    def test_null_attachment_name_produces_none_url(self) -> None:
        record = {**FILING_RECORD, "ATTACHMENTNAME": None}
        parser = BSEParser()
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        assert result[0].document_url is None


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


class TestTimestampParsing:
    def test_plain_timestamp_converts_to_utc(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(make_response(FILING_RECORD), COMPANY_ID)
        assert result[0].source_date.tzinfo == timezone.utc

    def test_fractional_seconds_are_discarded_without_error(self) -> None:
        parser = BSEParser()
        result = parser.parse_filings(
            make_response(FRACTIONAL_TIMESTAMP_RECORD), COMPANY_ID
        )
        assert result[0].source_date == datetime(
            2023, 10, 20, 18, 14, 22, tzinfo=timezone.utc
        )

    def test_empty_timestamp_falls_back_to_current_utc(self) -> None:
        record = {**FILING_RECORD, "DT_TM": ""}
        parser = BSEParser()
        before = datetime.now(timezone.utc)
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        after = datetime.now(timezone.utc)
        assert before <= result[0].source_date <= after

    def test_malformed_timestamp_falls_back_to_current_utc(self) -> None:
        record = {**FILING_RECORD, "DT_TM": "not-a-date"}
        parser = BSEParser()
        before = datetime.now(timezone.utc)
        result = parser.parse_filings(make_response(record), COMPANY_ID)
        after = datetime.now(timezone.utc)
        assert before <= result[0].source_date <= after


# ---------------------------------------------------------------------------
# total_pages
# ---------------------------------------------------------------------------


class TestTotalPages:
    def test_extracts_total_page_count(self) -> None:
        parser = BSEParser()
        raw = make_response(FILING_RECORD, total_pages=5)
        assert parser.total_pages(raw) == 5

    def test_empty_table_returns_one(self) -> None:
        parser = BSEParser()
        assert parser.total_pages({"Table": [], "Table1": []}) == 1

    def test_missing_total_page_cnt_defaults_to_one(self) -> None:
        record = {k: v for k, v in FILING_RECORD.items() if k != "TotalPageCnt"}
        parser = BSEParser()
        assert parser.total_pages({"Table": [record]}) == 1


# ---------------------------------------------------------------------------
# parse_annual_reports
# ---------------------------------------------------------------------------

AR_TABLE_RECORD: dict = {
    "year": "2025",
    "file_name": "bb9f9e0a-e4ce-4a4e-997e-0b5de8c2bec0.pdf.pdf",
    "dt_tm": "2025-05-27",
}

AR_TABLE_RECORD_WITH_BACKSLASH: dict = {
    "year": "2023",
    "file_name": "\\3837c1b7-abcd-1234-5678-abcdef012345.pdf.pdf",
    "dt_tm": "2023-06-07",
}

AR_TABLE_RECORD_LEGACY: dict = {
    "year": "2010",
    "file_name": "5325400310.pdf",
    "dt_tm": "2012-03-26",
}

AR_TABLE_RECORD_NO_DATE: dict = {
    "year": "2019",
    "file_name": "5325400319.pdf",
    "dt_tm": "",
}

AR_TABLE_RECORD_NO_FILENAME: dict = {
    "year": "2020",
    "file_name": "",
    "dt_tm": "2020-06-10",
}


def make_ar_response(*records: dict) -> dict:
    return {"Table": list(records)}


class TestParseAnnualReports:
    def test_returns_one_evidence_per_record(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD), COMPANY_ID, SCRIP_CODE
        )
        assert len(result) == 1

    def test_returns_evidence_instances(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD), COMPANY_ID, SCRIP_CODE
        )
        assert isinstance(result[0], Evidence)

    def test_kind_is_annual_report(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD), COMPANY_ID, SCRIP_CODE
        )
        assert result[0].kind == EvidenceKind.ANNUAL_REPORT

    def test_source_is_bse(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD), COMPANY_ID, SCRIP_CODE
        )
        assert result[0].source == EvidenceSource.BSE

    def test_company_id_propagated(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD), COMPANY_ID, SCRIP_CODE
        )
        assert result[0].company_id == COMPANY_ID

    def test_evidence_id_is_stable_compound_key(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD), COMPANY_ID, SCRIP_CODE
        )
        fname = AR_TABLE_RECORD["file_name"]
        assert result[0].evidence_id == f"bse-ar-{SCRIP_CODE}-{fname}"

    def test_leading_backslash_stripped_from_filename(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD_WITH_BACKSLASH), COMPANY_ID, SCRIP_CODE
        )
        assert "\\" not in result[0].evidence_id
        assert "\\" not in (result[0].document_url or "")

    def test_document_url_uses_annual_reports_cdn(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD), COMPANY_ID, SCRIP_CODE
        )
        expected_url = (
            f"https://www.bseindia.com/AnnualReports/{SCRIP_CODE}/"
            f"{AR_TABLE_RECORD['file_name']}"
        )
        assert result[0].document_url == expected_url

    def test_title_includes_year(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD), COMPANY_ID, SCRIP_CODE
        )
        assert "2025" in result[0].title

    def test_source_date_parsed_from_dt_tm(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD), COMPANY_ID, SCRIP_CODE
        )
        assert result[0].source_date == datetime(2025, 5, 27, tzinfo=timezone.utc)

    def test_source_date_falls_back_to_april_when_dt_tm_empty(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD_NO_DATE), COMPANY_ID, SCRIP_CODE
        )
        assert result[0].source_date == datetime(2019, 4, 1, tzinfo=timezone.utc)

    def test_records_with_empty_filename_are_skipped(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD_NO_FILENAME, AR_TABLE_RECORD),
            COMPANY_ID,
            SCRIP_CODE,
        )
        assert len(result) == 1

    def test_legacy_filename_format_handled(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD_LEGACY), COMPANY_ID, SCRIP_CODE
        )
        assert result[0].document_url == (
            f"https://www.bseindia.com/AnnualReports/{SCRIP_CODE}/5325400310.pdf"
        )

    def test_empty_table_returns_empty_list(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports({"Table": []}, COMPANY_ID, SCRIP_CODE)
        assert result == []

    def test_non_dict_raw_returns_empty_list(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports([], COMPANY_ID, SCRIP_CODE)
        assert result == []

    def test_multiple_records_all_returned(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD, AR_TABLE_RECORD_LEGACY),
            COMPANY_ID,
            SCRIP_CODE,
        )
        assert len(result) == 2

    def test_file_size_bytes_is_none(self) -> None:
        parser = BSEParser()
        result = parser.parse_annual_reports(
            make_ar_response(AR_TABLE_RECORD), COMPANY_ID, SCRIP_CODE
        )
        assert result[0].file_size_bytes is None


# ---------------------------------------------------------------------------
# parse_scrip_code
# ---------------------------------------------------------------------------


class TestParseScripCode:
    def test_parses_html_string_with_liclick(self) -> None:
        parser = BSEParser()
        html = (
            "<li class='quotemenu quotemenuselect'"
            " onclick=\"liclick('532540','Tata Consultancy Services Ltd')\">"
            "<a>TATA CONSULTANCY SERVICES LTD</a></li>"
        )
        assert parser.parse_scrip_code(html, "TCS") == 532540

    def test_html_string_takes_first_liclick_match(self) -> None:
        parser = BSEParser()
        html = (
            "<li onclick=\"liclick('532540','TCS Ltd')\"></li>"
            "<li onclick=\"liclick('500444','Other Ltd')\"></li>"
        )
        assert parser.parse_scrip_code(html, "TCS") == 532540

    def test_raises_for_html_with_no_liclick(self) -> None:
        import pytest

        parser = BSEParser()
        with pytest.raises(ValueError, match="No liclick"):
            parser.parse_scrip_code("<html>no matches here</html>", "TCS")

    def test_parses_bse_code_string(self) -> None:
        parser = BSEParser()
        assert (
            parser.parse_scrip_code({"bse_code": "532540", "symbol": "TCS"}, "TCS")
            == 532540
        )

    def test_parses_scrip_cd_int(self) -> None:
        parser = BSEParser()
        assert parser.parse_scrip_code({"SCRIP_CD": 532540}, "TCS") == 532540

    def test_parses_security_code_string(self) -> None:
        parser = BSEParser()
        assert parser.parse_scrip_code({"SecurityCode": "532540"}, "TCS") == 532540

    def test_parses_table_based_response(self) -> None:
        parser = BSEParser()
        assert (
            parser.parse_scrip_code({"Table": [{"SCRIP_CD": 532540}]}, "TCS") == 532540
        )

    def test_parses_list_response(self) -> None:
        parser = BSEParser()
        assert (
            parser.parse_scrip_code([{"SCRIP_CD": 532540, "short_name": "TCS"}], "TCS")
            == 532540
        )

    def test_raises_for_unknown_shape(self) -> None:
        import pytest

        parser = BSEParser()
        with pytest.raises(ValueError, match="Cannot resolve BSE scrip code"):
            parser.parse_scrip_code({"unknown_field": "foo"}, "TCS")

    def test_raises_for_empty_table(self) -> None:
        import pytest

        parser = BSEParser()
        with pytest.raises(ValueError, match="Cannot resolve BSE scrip code"):
            parser.parse_scrip_code({"Table": []}, "TCS")
