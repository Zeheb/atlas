from datetime import timezone
from unittest.mock import MagicMock

from atlas.acquisition.connectors.bse import BSEConnector
from atlas.acquisition.connectors.connector import Company, DiscoveryResult
from atlas.acquisition.evidence import Evidence, EvidenceKind, EvidenceSource

COMPANY_ID = "cmp_tcs123"
SCRIP_CODE = 532540

_EMPTY_RESPONSE: dict = {"Table": [], "Table1": []}


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def make_announcement_record(
    subcatname: str = "Financial Results",
    newsid: str = "abc-def",
    old: int = 1,
    pages: int = 1,
) -> dict:
    return {
        "NEWSID": newsid,
        "HEADLINE": f"TCS {subcatname}",
        "SUBCATNAME": subcatname,
        "DT_TM": "2023-10-20T10:00:00",
        "PDFFLAG": 1,
        "OLD": old,
        "ATTACHMENTNAME": "report.pdf",
        "Fld_Attachsize": 1_000_000,
        "TotalPageCnt": pages,
    }


def make_announcement_response(*records: dict) -> dict:
    return {"Table": list(records), "Table1": [{"ROWCNT": len(records)}]}


def make_ar_record(year: str = "2025", fname: str = "report2025.pdf") -> dict:
    return {"year": year, "file_name": fname, "dt_tm": "2025-05-27"}


def make_ar_response(*records: dict) -> dict:
    return {"Table": list(records)}


def _many_empty(n: int = 120) -> list[dict]:
    """Return n empty announcement-stream responses to exhaust the window walk."""
    return [_EMPTY_RESPONSE] * n


def _make_company(scrip_code: int | None = None) -> Company:
    company = Company(id=COMPANY_ID, ticker="TCS")
    if scrip_code is not None:
        company.exchange_identities["BSE"] = {"scrip_code": scrip_code}
    return company


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_resolves_scrip_code_when_not_cached(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            {"bse_code": str(SCRIP_CODE)},  # PeerSmartSearch/w
            make_ar_response(),  # AnnualReport/w
            *_many_empty(),
        ]
        BSEConnector(http=http).discover(_make_company())
        first_path = http.get_json.call_args_list[0][0][0]
        assert first_path == "PeerSmartSearch/w"

    def test_skips_resolution_when_scrip_code_cached(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(),
            *_many_empty(),
        ]
        BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        paths = [call[0][0] for call in http.get_json.call_args_list]
        assert "PeerSmartSearch/w" not in paths

    def test_stores_resolved_scrip_code_in_company(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            {"bse_code": str(SCRIP_CODE)},
            make_ar_response(),
            *_many_empty(),
        ]
        company = _make_company()
        BSEConnector(http=http).discover(company)
        assert company.exchange_identities["BSE"]["scrip_code"] == SCRIP_CODE

    def test_stores_resolved_at_timestamp(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            {"bse_code": str(SCRIP_CODE)},
            make_ar_response(),
            *_many_empty(),
        ]
        company = _make_company()
        BSEConnector(http=http).discover(company)
        assert "resolved_at" in company.exchange_identities["BSE"]

    def test_calls_annual_report_endpoint(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(make_ar_record()),
            *_many_empty(),
        ]
        BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        paths = [call[0][0] for call in http.get_json.call_args_list]
        assert "AnnualReport/w" in paths

    def test_calls_announcement_stream_endpoint(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(),
            *_many_empty(),
        ]
        BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        paths = [call[0][0] for call in http.get_json.call_args_list]
        assert "AnnSubCategoryGetData/w" in paths

    def test_calls_corporate_gov_report_endpoint(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(),
            *_many_empty(),
        ]
        BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        paths = [call[0][0] for call in http.get_json.call_args_list]
        assert "CorporateGovReport/w" in paths

    def test_returns_combined_annual_reports_and_announcements(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(make_ar_record("2025")),
            make_announcement_response(make_announcement_record(newsid="ann-1")),
            *_many_empty(),
        ]
        result = BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        assert len(result.evidence) == 2

    def test_returns_all_evidence_without_profile_filtering(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(),
            make_announcement_response(
                make_announcement_record("Financial Results", newsid="fr-1"),
                make_announcement_record("AGM", newsid="agm-1"),
                make_announcement_record(
                    "Press Release / Media Release", newsid="pr-1"
                ),
            ),
            *_many_empty(),
        ]
        result = BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        kinds = {ev.kind for ev in result.evidence}
        assert EvidenceKind.FINANCIAL_RESULTS in kinds
        assert EvidenceKind.AGM_NOTICE in kinds
        assert EvidenceKind.NEWS in kinds

    def test_returns_discovery_result(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(make_ar_record()),
            *_many_empty(),
        ]
        result = BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        assert isinstance(result, DiscoveryResult)
        assert all(isinstance(ev, Evidence) for ev in result.evidence)

    def test_company_id_propagated_to_evidence(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(make_ar_record()),
            *_many_empty(),
        ]
        result = BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        assert result.evidence[0].company_id == COMPANY_ID

    def test_empty_source_returns_empty_evidence(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(),
            *_many_empty(),
        ]
        result = BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        assert result.evidence == []


# ---------------------------------------------------------------------------
# Discovery warnings
# ---------------------------------------------------------------------------


class TestDiscoverWarnings:
    def test_unknown_subcategory_produces_warning(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(),
            make_announcement_response(
                make_announcement_record(subcatname="Future Category", newsid="fc-1")
            ),
            *_many_empty(),
        ]
        result = BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        assert len(result.warnings) == 1
        assert result.warnings[0].code == "UNMAPPED_SUBCATEGORY"
        assert result.warnings[0].metadata["subcategory"] == "Future Category"

    def test_warning_count_reflects_occurrence_count(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(),
            make_announcement_response(
                make_announcement_record(subcatname="Future Category", newsid="fc-1"),
                make_announcement_record(subcatname="Future Category", newsid="fc-2"),
            ),
            *_many_empty(),
        ]
        result = BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        assert result.warnings[0].metadata["count"] == 2

    def test_multiple_distinct_unknowns_produce_separate_warnings(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(),
            make_announcement_response(
                make_announcement_record(subcatname="Cat A", newsid="ca-1"),
                make_announcement_record(subcatname="Cat B", newsid="cb-1"),
            ),
            *_many_empty(),
        ]
        result = BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        subcats = {w.metadata["subcategory"] for w in result.warnings}
        assert subcats == {"Cat A", "Cat B"}

    def test_no_warnings_for_known_subcategories(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(),
            make_announcement_response(
                make_announcement_record(subcatname="Financial Results", newsid="fr-1")
            ),
            *_many_empty(),
        ]
        result = BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        assert result.warnings == []

    def test_warning_source_is_bse(self) -> None:
        from atlas.acquisition.evidence import EvidenceSource

        http = MagicMock()
        http.get_json.side_effect = [
            make_ar_response(),
            make_announcement_response(
                make_announcement_record(subcatname="Future Category", newsid="fc-1")
            ),
            *_many_empty(),
        ]
        result = BSEConnector(http=http).discover(_make_company(scrip_code=SCRIP_CODE))
        assert result.warnings[0].source == EvidenceSource.BSE


# ---------------------------------------------------------------------------
# _get_annual_reports (internal — tested directly to verify endpoint behaviour)
# ---------------------------------------------------------------------------


class TestGetAnnualReports:
    def test_calls_annual_report_endpoint(self) -> None:
        http = MagicMock()
        http.get_json.return_value = make_ar_response(make_ar_record())
        BSEConnector(http=http)._get_annual_reports(COMPANY_ID, SCRIP_CODE)
        path = http.get_json.call_args[0][0]
        assert path == "AnnualReport/w"

    def test_passes_scrip_code_parameter(self) -> None:
        http = MagicMock()
        http.get_json.return_value = make_ar_response(make_ar_record())
        BSEConnector(http=http)._get_annual_reports(COMPANY_ID, SCRIP_CODE)
        params = http.get_json.call_args[0][1]
        assert params["scripcode"] == SCRIP_CODE

    def test_single_call_no_pagination(self) -> None:
        http = MagicMock()
        http.get_json.return_value = make_ar_response(
            make_ar_record("2025"), make_ar_record("2024", "report2024.pdf")
        )
        BSEConnector(http=http)._get_annual_reports(COMPANY_ID, SCRIP_CODE)
        assert http.get_json.call_count == 1

    def test_returns_evidence_list(self) -> None:
        http = MagicMock()
        http.get_json.return_value = make_ar_response(make_ar_record())
        result = BSEConnector(http=http)._get_annual_reports(COMPANY_ID, SCRIP_CODE)
        assert isinstance(result, list)
        assert isinstance(result[0], Evidence)

    def test_kind_is_annual_report(self) -> None:
        http = MagicMock()
        http.get_json.return_value = make_ar_response(make_ar_record())
        result = BSEConnector(http=http)._get_annual_reports(COMPANY_ID, SCRIP_CODE)
        assert result[0].kind == EvidenceKind.ANNUAL_REPORT

    def test_source_is_bse(self) -> None:
        http = MagicMock()
        http.get_json.return_value = make_ar_response(make_ar_record())
        result = BSEConnector(http=http)._get_annual_reports(COMPANY_ID, SCRIP_CODE)
        assert result[0].source == EvidenceSource.BSE

    def test_company_id_is_propagated(self) -> None:
        http = MagicMock()
        http.get_json.return_value = make_ar_response(make_ar_record())
        result = BSEConnector(http=http)._get_annual_reports(COMPANY_ID, SCRIP_CODE)
        assert result[0].company_id == COMPANY_ID

    def test_document_url_uses_annual_reports_cdn(self) -> None:
        http = MagicMock()
        http.get_json.return_value = make_ar_response(
            make_ar_record("2025", "report2025.pdf")
        )
        result = BSEConnector(http=http)._get_annual_reports(COMPANY_ID, SCRIP_CODE)
        assert result[0].document_url == (
            f"https://www.bseindia.com/AnnualReports/{SCRIP_CODE}/report2025.pdf"
        )

    def test_multiple_records_all_returned(self) -> None:
        http = MagicMock()
        http.get_json.return_value = make_ar_response(
            make_ar_record("2025"), make_ar_record("2024", "report2024.pdf")
        )
        result = BSEConnector(http=http)._get_annual_reports(COMPANY_ID, SCRIP_CODE)
        assert len(result) == 2

    def test_empty_table_returns_empty_list(self) -> None:
        http = MagicMock()
        http.get_json.return_value = {"Table": []}
        result = BSEConnector(http=http)._get_annual_reports(COMPANY_ID, SCRIP_CODE)
        assert result == []


# ---------------------------------------------------------------------------
# _get_announcements (internal — tested directly to verify endpoint behaviour)
# ---------------------------------------------------------------------------


class TestGetAnnouncements:
    def test_calls_ann_sub_category_endpoint(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_announcement_response(make_announcement_record()),
            *_many_empty(),
        ]
        BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        first_path = http.get_json.call_args_list[0][0][0]
        assert first_path == "AnnSubCategoryGetData/w"

    def test_uses_all_categories_filter(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_announcement_response(make_announcement_record()),
            *_many_empty(),
        ]
        BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        params = http.get_json.call_args_list[0][0][1]
        assert params["strCat"] == "-1"

    def test_passes_scrip_code(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_announcement_response(make_announcement_record()),
            *_many_empty(),
        ]
        BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        params = http.get_json.call_args_list[0][0][1]
        assert params["strscrip"] == SCRIP_CODE

    def test_returns_evidence_list(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_announcement_response(make_announcement_record()),
            *_many_empty(),
        ]
        result = BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        assert isinstance(result, list)
        assert isinstance(result[0], Evidence)

    def test_returns_all_pdf_records_regardless_of_kind(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_announcement_response(
                make_announcement_record("Financial Results", newsid="ev-1"),
                make_announcement_record("Analyst / Investor Meet", newsid="ev-2"),
                make_announcement_record("AGM", newsid="ev-3"),
            ),
            *_many_empty(),
        ]
        result = BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        assert len(result) == 3

    def test_deduplicates_by_newsid_across_windows(self) -> None:
        same_record = make_announcement_record(newsid="dup-id")
        http = MagicMock()
        http.get_json.side_effect = [
            make_announcement_response(same_record),
            make_announcement_response(same_record),
            *_many_empty(),
        ]
        result = BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        assert len(result) == 1

    def test_combines_records_from_different_windows(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_announcement_response(make_announcement_record(newsid="ev-1")),
            make_announcement_response(make_announcement_record(newsid="ev-2")),
            *_many_empty(),
        ]
        result = BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        assert len(result) == 2

    def test_paginates_within_window(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_announcement_response(
                make_announcement_record(newsid="ev-1", pages=2)
            ),
            make_announcement_response(
                make_announcement_record(newsid="ev-2", pages=2)
            ),
            *_many_empty(),
        ]
        result = BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        assert len(result) == 2

    def test_second_page_uses_incremented_pageno(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_announcement_response(
                make_announcement_record(newsid="ev-1", pages=2)
            ),
            make_announcement_response(
                make_announcement_record(newsid="ev-2", pages=2)
            ),
            *_many_empty(),
        ]
        BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        page_1 = http.get_json.call_args_list[0][0][1]["pageno"]
        page_2 = http.get_json.call_args_list[1][0][1]["pageno"]
        assert page_1 == 1
        assert page_2 == 2

    def test_empty_windows_return_empty_list(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = _many_empty()
        result = BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        assert result == []

    def test_source_date_is_utc(self) -> None:
        http = MagicMock()
        http.get_json.side_effect = [
            make_announcement_response(make_announcement_record()),
            *_many_empty(),
        ]
        result = BSEConnector(http=http)._get_announcements(COMPANY_ID, SCRIP_CODE)
        assert result[0].source_date.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_from_settings_returns_connector_instance(self) -> None:
        from pathlib import Path

        from atlas.config.settings import Settings

        settings = Settings(repository_base_path=Path("."))
        connector = BSEConnector.from_settings(settings)
        assert isinstance(connector, BSEConnector)

    def test_close_delegates_to_http(self) -> None:
        http = MagicMock()
        http.get_json.return_value = {"Table": [], "Table1": []}
        connector = BSEConnector(http=http)
        connector.close()
        http.close.assert_called_once()

    def test_context_manager_closes_http_on_exit(self) -> None:
        http = MagicMock()
        with BSEConnector(http=http) as connector:
            assert isinstance(connector, BSEConnector)
        http.close.assert_called_once()


# ---------------------------------------------------------------------------
# _resolve_scrip_code (internal — tested directly to verify endpoint behaviour)
# ---------------------------------------------------------------------------


class TestResolveScripCode:
    def test_calls_peer_smart_search_endpoint(self) -> None:
        http = MagicMock()
        http.get_json.return_value = {"bse_code": "532540"}
        BSEConnector(http=http)._resolve_scrip_code("TCS")
        assert http.get_json.call_args[0][0] == "PeerSmartSearch/w"

    def test_passes_ticker_as_text_param(self) -> None:
        http = MagicMock()
        http.get_json.return_value = {"bse_code": "532540"}
        BSEConnector(http=http)._resolve_scrip_code("TCS")
        assert http.get_json.call_args[0][1]["text"] == "TCS"

    def test_passes_equity_type(self) -> None:
        http = MagicMock()
        http.get_json.return_value = {"bse_code": "532540"}
        BSEConnector(http=http)._resolve_scrip_code("TCS")
        assert http.get_json.call_args[0][1]["Type"] == "EQ"

    def test_returns_scrip_code_as_int(self) -> None:
        http = MagicMock()
        http.get_json.return_value = {"bse_code": "532540"}
        result = BSEConnector(http=http)._resolve_scrip_code("TCS")
        assert result == 532540
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# fetch_bytes
# ---------------------------------------------------------------------------


class TestFetchBytes:
    def test_delegates_to_http_get_bytes(self) -> None:
        http = MagicMock()
        http.get_bytes.return_value = b"PDF content"
        result = BSEConnector(http=http).fetch_bytes("https://example.com/file.pdf")
        http.get_bytes.assert_called_once_with("https://example.com/file.pdf")
        assert result == b"PDF content"


# ---------------------------------------------------------------------------
# _get_corporate_governance_reports (internal — tested directly)
# ---------------------------------------------------------------------------


def _make_cg_response(fin_year: str = "2025-2026", qtr: str = "Q1") -> list:
    return [
        {
            "finYear": fin_year,
            "lstCorporateGovReport": [
                {"filePath": f"/downloads1/cg_{qtr}.pdf", "Qtr": qtr}
            ],
        }
    ]


class TestGetCorporateGovernanceReports:
    def test_calls_corporate_gov_report_endpoint(self) -> None:
        http = MagicMock()
        http.get_json.return_value = []
        BSEConnector(http=http)._get_corporate_governance_reports(COMPANY_ID, SCRIP_CODE)
        path = http.get_json.call_args[0][0]
        assert path == "CorporateGovReport/w"

    def test_passes_scripcode_parameter(self) -> None:
        http = MagicMock()
        http.get_json.return_value = []
        BSEConnector(http=http)._get_corporate_governance_reports(COMPANY_ID, SCRIP_CODE)
        params = http.get_json.call_args[0][1]
        assert params["scripcode"] == SCRIP_CODE

    def test_single_call_no_pagination(self) -> None:
        http = MagicMock()
        http.get_json.return_value = []
        BSEConnector(http=http)._get_corporate_governance_reports(COMPANY_ID, SCRIP_CODE)
        assert http.get_json.call_count == 1

    def test_returns_evidence_list(self) -> None:
        http = MagicMock()
        http.get_json.return_value = _make_cg_response()
        result = BSEConnector(http=http)._get_corporate_governance_reports(
            COMPANY_ID, SCRIP_CODE
        )
        assert isinstance(result, list)
        assert isinstance(result[0], Evidence)

    def test_kind_is_corporate_governance_report(self) -> None:
        http = MagicMock()
        http.get_json.return_value = _make_cg_response()
        result = BSEConnector(http=http)._get_corporate_governance_reports(
            COMPANY_ID, SCRIP_CODE
        )
        assert result[0].kind == EvidenceKind.CORPORATE_GOVERNANCE_REPORT

    def test_source_is_bse(self) -> None:
        http = MagicMock()
        http.get_json.return_value = _make_cg_response()
        result = BSEConnector(http=http)._get_corporate_governance_reports(
            COMPANY_ID, SCRIP_CODE
        )
        assert result[0].source == EvidenceSource.BSE

    def test_company_id_propagated(self) -> None:
        http = MagicMock()
        http.get_json.return_value = _make_cg_response()
        result = BSEConnector(http=http)._get_corporate_governance_reports(
            COMPANY_ID, SCRIP_CODE
        )
        assert result[0].company_id == COMPANY_ID

    def test_empty_response_returns_empty_list(self) -> None:
        http = MagicMock()
        http.get_json.return_value = []
        result = BSEConnector(http=http)._get_corporate_governance_reports(
            COMPANY_ID, SCRIP_CODE
        )
        assert result == []
