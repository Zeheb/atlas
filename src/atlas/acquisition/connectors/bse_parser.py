import calendar
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
        "Outcome without intimation": EvidenceKind.BOARD_OUTCOME,
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
        # Regulatory filings (SAST disclosures, secretarial compliance)
        "Disclosures under Reg. 29(2) of SEBI (SAST) Regulations, 2011": EvidenceKind.REGULATORY_FILING,
        "Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011": EvidenceKind.REGULATORY_FILING,
        "Reg.24(A)-Annual Secretarial Compliance": EvidenceKind.REGULATORY_FILING,
        # News / Press
        "Press Release / Media Release": EvidenceKind.NEWS,
        "Press Release / Media Release (Revised)": EvidenceKind.NEWS,
    }

    _MONTH_MAP: dict[str, int] = {
        "January": 1, "February": 2, "March": 3, "April": 4,
        "May": 5, "June": 6, "July": 7, "August": 8,
        "September": 9, "October": 10, "November": 11, "December": 12,
    }

    _ATTACH_LIVE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{}"
    _ATTACH_HIS = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{}"
    # AnnualReport/w's file_name comes in two generations, discovered by
    # investigating why every bse-ar-* download was silently resolving to
    # BSE's Angular SPA shell (HTTP 200, but an HTML page, not a PDF — BSE
    # serves that shell for any unmatched route rather than a 404, which is
    # why this went undetected: no request ever failed).
    #
    # Filings up to ~2022 use a short legacy numeric/alphanumeric id
    # ("5325400319.pdf") and live under a *different* base path than the
    # one this template used to point at — "/AnnualReports/" (plural, no
    # prefix) is dead; the real path is "/bseplus/AnnualReport/" (singular,
    # under bseplus). Filings from ~2023 onward use a UUID id with a
    # doubled ".pdf.pdf" extension in the API response itself, and are only
    # reachable through the same corpfiling archive used for every other
    # BSE announcement (_ATTACH_HIS) — not the annual-report-specific path
    # at all — once the duplicate extension is trimmed to a single ".pdf".
    # Verified against TCS, Tata Steel, and SBI (all three affected
    # identically): both templates return real application/pdf bytes for
    # every entry when matched to the right filename generation.
    _ANNUAL_REPORT_LEGACY_CDN = "https://www.bseindia.com/bseplus/AnnualReport/{scrip_code}/{fname}"
    _RE_UUID_FILENAME = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf",
        re.IGNORECASE,
    )
    _CG_REPORT_BASE = "https://www.bseindia.com"

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

    def _annual_report_url(self, scrip_code: int, fname: str) -> str:
        """Resolve the real download URL for an AnnualReport/w file_name.

        See the class-level comment above _ANNUAL_REPORT_LEGACY_CDN for how
        this was determined and verified.
        """
        if self._RE_UUID_FILENAME.match(fname):
            clean = fname
            while clean.lower().endswith(".pdf.pdf"):
                clean = clean[:-4]
            return self._ATTACH_HIS.format(clean)
        return self._ANNUAL_REPORT_LEGACY_CDN.format(scrip_code=scrip_code, fname=fname)

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
                    document_url=self._annual_report_url(scrip_code, fname),
                    file_size_bytes=None,
                    report_period=year_str or None,
                )
            )
        return result

    def parse_shareholding_index(
        self, raw: Any, company_id: str, scrip_code: int
    ) -> list[Evidence]:
        """Parse a SHPQNewFormat/w response into Evidence instances.

        Rows with an empty XbrlFile are pre-XBRL-era filings (2004–2015) with
        no structured data available and are silently skipped.

        Revised filings have a fractional qtrid (e.g. 120.01 vs 120.0) and
        replace the original row in the BSE index. The evidence_id encodes
        the full qtrid so originals and revisions are distinct catalogue entries.

        The download URL https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/{XbrlFile}
        is valid for both new and revised filings.
        """
        table = raw.get("Table", []) if isinstance(raw, dict) else []
        result: list[Evidence] = []
        for rec in table:
            xbrl_file = (rec.get("XbrlFile") or "").strip()
            if not xbrl_file:
                continue
            qtrid = rec.get("qtrid")
            if qtrid is None:
                continue
            qtr_label = str(rec.get("qtr") or "")
            filing_dt = str(rec.get("filing_date_time") or "")
            revised_dt = str(rec.get("revised_date_time") or "")
            dt_str = revised_dt if revised_dt else filing_dt
            qtrid_str = str(int(qtrid)) if qtrid == int(qtrid) else str(qtrid).replace(".", "_")
            result.append(
                Evidence(
                    evidence_id=f"bse-shp-{scrip_code}-{qtrid_str}",
                    company_id=company_id,
                    source=EvidenceSource.BSE,
                    kind=EvidenceKind.SHAREHOLDING_PATTERN,
                    title=f"Shareholding Pattern {qtr_label}",
                    source_date=self._parse_shp_date(dt_str, qtr_label),
                    document_url=(
                        f"https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/{xbrl_file}"
                    ),
                    file_size_bytes=None,
                    file_extension="xml",
                    report_period=qtr_label or None,
                )
            )
        return result

    def parse_corporate_governance_index(
        self, raw: Any, company_id: str, scrip_code: int
    ) -> list[Evidence]:
        """Parse a CorporateGovReport/w response into Evidence instances.

        Each year-group contains up to 4 quarterly reports (Q1–Q4). Rows with
        filePath equal to "-", empty string, or None are placeholder entries
        and are silently skipped. ZIP files are preserved with file_extension="zip".
        """
        from pathlib import PurePosixPath

        result: list[Evidence] = []
        if not isinstance(raw, list):
            return result
        for year_group in raw:
            fin_year = str(year_group.get("finYear") or "")
            for report in year_group.get("lstCorporateGovReport") or []:
                file_path = (report.get("filePath") or "").strip()
                if not file_path or file_path == "-":
                    continue
                qtr = str(report.get("Qtr") or "").strip()
                if not qtr or qtr == "-":
                    continue
                suffix = PurePosixPath(file_path).suffix.lstrip(".").lower() or "pdf"
                fin_year_key = fin_year.replace("-", "_")
                result.append(
                    Evidence(
                        evidence_id=f"bse-cg-{scrip_code}-{fin_year_key}-{qtr}",
                        company_id=company_id,
                        source=EvidenceSource.BSE,
                        kind=EvidenceKind.CORPORATE_GOVERNANCE_REPORT,
                        title=f"Corporate Governance Report {fin_year} {qtr}",
                        source_date=self._cg_report_date(fin_year, qtr),
                        document_url=f"{self._CG_REPORT_BASE}{file_path}",
                        file_size_bytes=None,
                        file_extension=suffix,
                        report_period=f"{fin_year} {qtr}".strip() or None,
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
        title = str(record.get("HEADLINE") or "")
        return Evidence(
            evidence_id=f"bse-news-{newsid}",
            company_id=company_id,
            source=EvidenceSource.BSE,
            kind=self._classify_kind(str(record.get("SUBCATNAME") or ""), title),
            title=title,
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

    _RE_TRANSCRIPT_TITLE = re.compile(
        r"\b(?:transcript|call transcript|analyst\s+meet\s+transcript)\b",
        re.IGNORECASE,
    )

    def _classify_kind(self, subcatname: str, title: str) -> EvidenceKind:
        """Return EvidenceKind, with title-based refinement.

        A filing classified as INVESTOR_PRESENTATION by subcategory is
        reclassified as EARNINGS_TRANSCRIPT when the title contains the word
        "Transcript".  This handles banks and other companies that file
        earnings-call transcripts under the generic 'Analyst / Investor Meet'
        subcategory.
        """
        kind = self._to_kind(subcatname)
        if kind == EvidenceKind.INVESTOR_PRESENTATION and self._RE_TRANSCRIPT_TITLE.search(title):
            return EvidenceKind.EARNINGS_TRANSCRIPT
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

    def _parse_shp_date(self, dt_str: str, qtr_label: str) -> datetime:
        """Parse a shareholding pattern date; fall back to the quarter end date."""
        if dt_str:
            try:
                clean = dt_str.split(".")[0] if "." in dt_str else dt_str
                naive = datetime.fromisoformat(clean)
                return naive.replace(tzinfo=self._BSE_TZ).astimezone(timezone.utc)
            except (ValueError, TypeError):
                pass
        # Fall back: last day of the quarter month, e.g. "March 2026" → 2026-03-31
        parts = qtr_label.strip().split()
        if len(parts) == 2:
            month = self._MONTH_MAP.get(parts[0])
            try:
                year = int(parts[1])
                if month:
                    last_day = calendar.monthrange(year, month)[1]
                    return datetime(year, month, last_day, tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
        return datetime.now(timezone.utc)

    def _cg_report_date(self, fin_year: str, qtr: str) -> datetime:
        """Derive quarter-end date from finYear ("2025-2026") and Qtr ("Q1"–"Q4").

        Indian FY runs April–March: Q1=June 30, Q2=Sep 30, Q3=Dec 31, Q4=Mar 31.
        """
        try:
            parts = fin_year.split("-")
            start_year = int(parts[0].strip())
            end_year = int(parts[1].strip())
        except (ValueError, IndexError):
            return datetime.now(timezone.utc)
        quarter_ends = {
            "Q1": (start_year, 6, 30),
            "Q2": (start_year, 9, 30),
            "Q3": (start_year, 12, 31),
            "Q4": (end_year, 3, 31),
        }
        if qtr not in quarter_ends:
            return datetime.now(timezone.utc)
        y, m, d = quarter_ends[qtr]
        return datetime(y, m, d, tzinfo=timezone.utc)

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
