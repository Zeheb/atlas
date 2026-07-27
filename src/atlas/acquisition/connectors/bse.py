from datetime import date, datetime, timedelta, timezone

from atlas.acquisition.connectors.bse_http import BSEHttpClient
from atlas.acquisition.connectors.bse_parser import BSEParser
from atlas.acquisition.connectors.connector import (
    Company,
    DiscoveryResult,
    DiscoveryWarning,
)
from atlas.acquisition.evidence import Evidence, EvidenceSource
from atlas.config.settings import Settings

_WINDOW_DAYS = 182
_FLOOR_DATE = date(2000, 1, 1)
_BSE_KEY = "BSE"


class BSEConnector:
    """Orchestrates BSE data acquisition.

    Combines transport (BSEHttpClient) and parsing (BSEParser) to produce
    Atlas-native Evidence objects. Contains no HTTP mechanics and no
    BSE field names — those responsibilities belong to its collaborators.
    """

    def __init__(self, http: BSEHttpClient) -> None:
        self._http = http
        self._parser = BSEParser()

    @classmethod
    def from_settings(cls, settings: Settings) -> "BSEConnector":
        return cls(http=BSEHttpClient(settings))

    def discover(self, company: Company) -> DiscoveryResult:
        """Return all BSE evidence for a company.

        Resolves the BSE scrip code if not already cached in
        company.exchange_identities, then fetches from both the annual
        report archive and the full announcement stream.
        """
        scrip_code = self._get_scrip_code(company)
        annual_reports = self._get_annual_reports(company.id, scrip_code)
        announcements = self._get_announcements(company.id, scrip_code)
        shareholding = self._get_shareholding_patterns(company.id, scrip_code)
        cg_reports = self._get_corporate_governance_reports(company.id, scrip_code)
        evidence = [*annual_reports, *announcements, *shareholding, *cg_reports]
        warnings = [
            DiscoveryWarning(
                source=EvidenceSource.BSE,
                code="UNMAPPED_SUBCATEGORY",
                message="Unmapped BSE subcategory",
                metadata={"subcategory": name, "count": count},
            )
            for name, count in self._parser.unknown_subcategories.items()
        ]
        return DiscoveryResult(evidence=evidence, warnings=warnings)

    def fetch_bytes(self, url: str) -> bytes:
        """Fetch raw bytes from a URL (used to download PDF attachments)."""
        return self._http.get_bytes(url)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "BSEConnector":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Private                                                              #
    # ------------------------------------------------------------------ #

    def _get_scrip_code(self, company: Company) -> int:
        bse = company.exchange_identities.get(_BSE_KEY, {})
        cached = bse.get("scrip_code")
        if cached is not None:
            return int(cached)
        scrip_code = self._resolve_scrip_code(company.ticker)
        company.exchange_identities[_BSE_KEY] = {
            "scrip_code": scrip_code,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        return scrip_code

    def _get_annual_reports(self, company_id: str, scrip_code: int) -> list[Evidence]:
        """Return all annual reports from the BSE annual report archive.

        Single call to AnnualReport/w; no pagination required.
        """
        raw = self._http.get_json("AnnualReport/w", {"scripcode": scrip_code})
        return self._parser.parse_annual_reports(raw, company_id, scrip_code)

    def _get_announcements(self, company_id: str, scrip_code: int) -> list[Evidence]:
        """Return all PDF-bearing announcements from the BSE announcement stream.

        The stream caps at 50 records per request, so this method walks
        backwards through 6-month windows from today to the floor date,
        deduplicating by NEWSID.
        """
        all_evidence: list[Evidence] = []
        seen_ids: set[str] = set()
        window_end = date.today()

        while window_end > _FLOOR_DATE:
            window_start = max(window_end - timedelta(days=_WINDOW_DAYS), _FLOOR_DATE)
            page = 1
            while True:
                raw = self._http.get_json(
                    "AnnSubCategoryGetData/w",
                    {
                        "pageno": page,
                        "strCat": "-1",
                        "subcategory": "-1",
                        "strPrevDate": window_start.strftime("%Y%m%d"),
                        "strToDate": window_end.strftime("%Y%m%d"),
                        "strSearch": "P",
                        "strscrip": scrip_code,
                        "strType": "C",
                    },
                )
                for filing in self._parser.parse_filings(raw, company_id):
                    if filing.evidence_id not in seen_ids:
                        seen_ids.add(filing.evidence_id)
                        all_evidence.append(filing)
                if page >= self._parser.total_pages(raw):
                    break
                page += 1
            window_end = window_start

        return all_evidence

    def _get_shareholding_patterns(
        self, company_id: str, scrip_code: int
    ) -> list[Evidence]:
        """Return all XBRL shareholding pattern filings from SHPQNewFormat/w.

        Rows with an empty XbrlFile (pre-XBRL era, 2004–2015) are dropped by
        the parser. A single call returns the full history (~44 quarters for
        established companies).
        """
        raw = self._http.get_json("SHPQNewFormat/w", {"Scripcode": scrip_code})
        return self._parser.parse_shareholding_index(raw, company_id, scrip_code)

    def _get_corporate_governance_reports(
        self, company_id: str, scrip_code: int
    ) -> list[Evidence]:
        """Return all quarterly corporate governance reports from CorporateGovReport/w.

        Single call returns up to 10 financial years × 4 quarters. No pagination.
        """
        raw = self._http.get_json("CorporateGovReport/w", {"scripcode": scrip_code})
        return self._parser.parse_corporate_governance_index(
            raw, company_id, scrip_code
        )

    def _resolve_scrip_code(self, ticker: str) -> int:
        """Resolve a ticker symbol to its BSE scrip code via live lookup."""
        raw = self._http.get_json("PeerSmartSearch/w", {"Type": "EQ", "text": ticker})
        return self._parser.parse_scrip_code(raw, ticker)
