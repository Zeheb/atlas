import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from atlas.acquisition.evidence import Evidence, EvidenceKind, EvidenceSource

_log = logging.getLogger(__name__)


class BSEParser:
    """Translates raw BSE API responses into Atlas domain objects.

    This class is the single isolation boundary between BSE and Atlas.
    BSE field names (NEWSID, PDFFLAG, DT_TM, …) appear nowhere else in
    the codebase. All type coercions, timezone normalisations, and
    BSE-subcategory-to-EvidenceKind mappings live here.

    Input:  raw Python dicts straight from the BSE JSON API.
    Output: Evidence instances that carry no BSE field names.
    """

    _BSE_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(self) -> None:
        self._unknown_subcats: Counter[str] = Counter()

    # Maps BSE SUBCATNAME strings to Atlas EvidenceKind values.
    # Unmapped subcategories fall through to EvidenceKind.OTHER.
    _SUBCATNAME_TO_KIND: dict[str, EvidenceKind] = {
        # Annual Reports (announcement stream; canonical source is AnnualReport/w)
        "Reg. 34 (1) Annual Report": EvidenceKind.ANNUAL_REPORT,
        "Annual Report": EvidenceKind.ANNUAL_REPORT,
        "Annual Report - Revised": EvidenceKind.ANNUAL_REPORT,
        # Financial Results
        "Financial Results": EvidenceKind.FINANCIAL_RESULTS,
        "Financial Results - Revised": EvidenceKind.FINANCIAL_RESULTS,
        # Investor Presentations
        "Analyst / Investor Meet": EvidenceKind.INVESTOR_PRESENTATION,
        "Investor Presentation": EvidenceKind.INVESTOR_PRESENTATION,
        # Earnings Transcripts
        "Earnings Call Transcript": EvidenceKind.EARNINGS_TRANSCRIPT,
        # BRSR
        "Business Responsibility and Sustainability Reporting (BRSR)": EvidenceKind.BRSR,
        # AGM / EGM
        "AGM/EGM Notice": EvidenceKind.AGM_NOTICE,
        "Notice of AGM": EvidenceKind.AGM_NOTICE,
        "AGM": EvidenceKind.AGM_NOTICE,
        "Book Closure / AGM": EvidenceKind.AGM_NOTICE,
        "EGM": EvidenceKind.AGM_NOTICE,
        "Postal Ballot": EvidenceKind.AGM_NOTICE,
        # Board
        "Outcome of Board Meeting": EvidenceKind.BOARD_OUTCOME,
        # Dividends
        "Dividend": EvidenceKind.DIVIDEND,
        # Buybacks
        "Buy back": EvidenceKind.BUYBACK,
        "Public Announcement-Buyback of Shares": EvidenceKind.BUYBACK,
        "Closure of Buy Back": EvidenceKind.BUYBACK,
        "Post Buyback Public Announcement": EvidenceKind.BUYBACK,
        # Acquisitions / M&A
        "Acquisition": EvidenceKind.ACQUISITION,
        "Amalgamation / Merger / Demerger": EvidenceKind.ACQUISITION,
        # Credit Ratings
        "Credit Rating": EvidenceKind.CREDIT_RATING_REPORT,
        # News / Press
        "Press Release / Media Release": EvidenceKind.NEWS,
        "Press Release / Media Release (Revised)": EvidenceKind.NEWS,
    }

    _ATTACH_LIVE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{}"
    _ATTACH_HIS = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{}"
    _ANNUAL_REPORT_CDN = "https://www.bseindia.com/AnnualReports/{scrip_code}/{fname}"

    # ------------------------------------------------------------------ #
    # Public interface                                                      #
    # ------------------------------------------------------------------ #

    def parse_filings(self, raw: dict[str, Any], company_id: str) -> list[Evidence]:
        """Parse an AnnSubCategoryGetData/w response.

        Records without a PDF attachment (PDFFLAG != 1) are silently dropped.
        """
        return [
            evidence
            for record in raw.get("Table", [])
            if (evidence := self._parse_record(record, company_id)) is not None
        ]

    def parse_annual_reports(
        self, raw: Any, company_id: str, scrip_code: int
    ) -> list[Evidence]:
        """Parse an AnnualReport/w response into Evidence instances.

        Each record is identified by a stable compound key
        (scrip_code + file_name) so incremental acquisitions never
        re-download the same file.
        """
        table = raw.get("Table", []) if isinstance(raw, dict) else []
        result: list[Evidence] = []
        for rec in table:
            fname = (rec.get("file_name") or "").lstrip("\\")
            if not fname:
                continue
            year_str = str(rec.get("year") or "")
            dt_str = str(rec.get("dt_tm") or "")
            result.append(
                Evidence(
                    evidence_id=f"bse-ar-{scrip_code}-{fname}",
                    company_id=company_id,
                    source=EvidenceSource.BSE,
                    kind=EvidenceKind.ANNUAL_REPORT,
                    title=f"Annual Report {year_str}",
                    source_date=self._parse_ar_date(dt_str, year_str),
                    document_url=self._ANNUAL_REPORT_CDN.format(
                        scrip_code=scrip_code, fname=fname
                    ),
                    file_size_bytes=None,
                )
            )
        return result

    def total_pages(self, raw: dict[str, Any]) -> int:
        """Extract the total page count from an AnnSubCategoryGetData/w response."""
        table = raw.get("Table", [])
        if not table:
            return 1
        return int(table[0].get("TotalPageCnt", 1))

    def parse_scrip_code(self, raw: Any, ticker: str) -> int:
        """Extract a BSE scrip code from a PeerSmartSearch/w response.

        Handles multiple response shapes observed in the wild:
        - JSON-wrapped HTML string with onclick="liclick('SCRIP_CD','...')" (live behaviour)
        - single dict with bse_code (string)
        - dict with Table list containing SCRIP_CD or SecurityCode
        - bare list with SCRIP_CD or bse_code per element
        """
        # Live: endpoint returns a JSON string whose value is HTML.
        # Extract the first scrip code from onclick="liclick('SCRIP_CD','...')".
        if isinstance(raw, str):
            match = re.search(r"liclick\('(\d+)'", raw)
            if match:
                return int(match.group(1))
            raise ValueError(
                f"Cannot resolve BSE scrip code for {ticker!r}. "
                f"No liclick() found in HTML response: {raw[:200]!r}"
            )

        candidate: Any = raw

        if isinstance(candidate, dict):
            if "Table" in candidate and candidate["Table"]:
                candidate = candidate["Table"][0]
            for field_name in ("bse_code", "SecurityCode", "SCRIP_CD"):
                value = candidate.get(field_name)
                if value is not None:
                    return int(value)

        if isinstance(candidate, list) and candidate:
            first = candidate[0]
            for field_name in ("SCRIP_CD", "bse_code", "SecurityCode"):
                value = first.get(field_name)
                if value is not None:
                    return int(value)

        raise ValueError(
            f"Cannot resolve BSE scrip code for {ticker!r}. "
            f"Unexpected response shape: {raw!r}"
        )

    # ------------------------------------------------------------------ #
    # Private helpers                                                       #
    # ------------------------------------------------------------------ #

    def _parse_record(self, record: dict[str, Any], company_id: str) -> Evidence | None:
        if not record.get("PDFFLAG"):
            return None
        newsid = record.get("NEWSID")
        if not newsid:
            return None
        filename = str(record.get("ATTACHMENTNAME") or "")
        return Evidence(
            evidence_id=f"bse-news-{newsid}",
            company_id=company_id,
            source=EvidenceSource.BSE,
            kind=self._to_kind(str(record.get("SUBCATNAME") or "")),
            title=str(record.get("HEADLINE") or ""),
            source_date=self._parse_timestamp(str(record.get("DT_TM") or "")),
            document_url=self._build_url(filename, int(record.get("OLD", 0))),
            file_size_bytes=record.get("Fld_Attachsize"),
        )

    @property
    def unknown_subcategories(self) -> dict[str, int]:
        return dict(self._unknown_subcats)

    def _to_kind(self, subcatname: str) -> EvidenceKind:
        kind = self._SUBCATNAME_TO_KIND.get(subcatname)
        if kind is None:
            if subcatname not in self._unknown_subcats:
                _log.warning("Unmapped BSE subcategory %r — filed as OTHER", subcatname)
            self._unknown_subcats[subcatname] += 1
            return EvidenceKind.OTHER
        return kind

    def _build_url(self, filename: str, old: int) -> str | None:
        if not filename:
            return None
        template = self._ATTACH_HIS if old else self._ATTACH_LIVE
        return template.format(filename)

    def _parse_timestamp(self, raw: str) -> datetime:
        """Parse a BSE timestamp string (IST, no tzinfo) into a UTC datetime."""
        if not raw:
            return datetime.now(timezone.utc)
        try:
            # BSE format: "2023-10-20T23:44:22.95"
            # Discard sub-second precision; fromisoformat handles the rest.
            clean = raw.split(".")[0] if "." in raw else raw
            naive = datetime.fromisoformat(clean)
            return naive.replace(tzinfo=self._BSE_TZ).astimezone(timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)

    def _parse_ar_date(self, dt_str: str, year_str: str) -> datetime:
        """Parse an AnnualReport/w date field; fall back to April 1 of the filing year."""
        if dt_str:
            try:
                clean = (
                    dt_str.split(".")[0].strip() if "." in dt_str else dt_str.strip()
                )
                # Handle bare date "2026-05-15" or datetime "2026-05-15 00:00:00"
                if len(clean) == 10:
                    parts = clean.split("-")
                    naive = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
                else:
                    naive = datetime.fromisoformat(clean)
                return naive.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError, IndexError):
                pass
        try:
            return datetime(int(year_str), 4, 1, tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return datetime.now(timezone.utc)
