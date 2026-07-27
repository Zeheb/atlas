"""Human-readable citations for evidence — additive, not a storage redesign.

Atlas has four distinct notions of evidence identity that were previously
conflated into one raw string (the evidence_id) shown everywhere, including
in front of an investor reading a research report:

  evidence_id       Immutable internal identifier ("bse-news-7ff81737-...").
                     Unchanged by this module — every existing analyzer,
                     CompanyStore file, and Repository lookup keeps working
                     exactly as before.
  canonical_name    Stable, structured, machine-readable name
                     ("TCS/EARNINGS_TRANSCRIPT/2026-03-31") — for
                     cross-referencing and logs, not prose.
  display_name      Human-readable title ("TCS Q4 FY2026 Earnings Call
                     Transcript") — what a person expects to read.
  citation_*        Formatted presentations of display_name at three levels
                     of detail (short/standard/full), computed as properties
                     from the fields above — never stored, so there is
                     nothing to keep in sync.

Where the metadata comes from
------------------------------
CatalogEntry (catalog.json) carries no fiscal-year/quarter/agency fields,
and this module does not add any — BSE's generic announcement stream (which
most document kinds arrive through) has no structured period field at all,
only a free-text headline, and parsing that headline with a fresh regex
would be exactly the "fragile title parsing" this design avoids.

Instead: earnings_transcript.py, financial_results.py, and
investor_presentation.py already reliably compute REPORT_PERIOD_END /
REPORT_PERIOD_TYPE during analysis, and those facts already flow into
CompanyProfile's snapshots, which already carry evidence_id back-links via
`sources`. credit_rating.py's CREDIT_AGENCY fact similarly flows into
CreditRatingEntry.agency. This module's resolve_period()/resolve_agency()
recover that metadata by scanning CompanyProfile for those back-links —
the same reverse-lookup pattern query.engine.drilldown() already uses —
rather than duplicating what analyzers already extracted.

Some evidence kinds are inherently point-in-time, not period-covering (a
board outcome or a credit rating action happens ON a date; it doesn't
"cover" a fiscal quarter the way an earnings call does). Their CompanyProfile
containers reflect this — DividendEvent, CreditRatingEntry, DirectorChange
etc. carry source_date, not period — so display_name for those kinds is
built from source_date's month/year rather than a resolved fiscal period.
This is a design distinction, not a gap: no amount of period-resolution
would give a board outcome a fiscal quarter it doesn't semantically have.

Page numbers are never fabricated. Atlas has no page-tracking infrastructure
(Provenance carries a section label and a char_offset, not a page number);
citation_full simply omits the page line when none is available rather than
approximate one from char_offset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from atlas.acquisition.catalog import CatalogEntry
from atlas.company.model import CompanyProfile

# ---------------------------------------------------------------------------
# Fiscal period helpers
# ---------------------------------------------------------------------------

_MONTH_TO_FISCAL_QUARTER = {6: 1, 9: 2, 12: 3, 3: 4}


def _fiscal_quarter_and_year(period_iso: str) -> tuple[int, int] | None:
    """(quarter 1-4, fiscal year) from a period-end ISO date, or None.

    Indian FY runs April-March; FYyy labels the year the FY *ends* in — a
    period ending 2026-03-31 is Q4 FY2026, one ending 2025-09-30 is Q2 FY2026
    (mirrors earnings_transcript.py's quarter-label convention, inverted).
    """
    try:
        d = datetime.strptime(period_iso[:10], "%Y-%m-%d")
    except ValueError:
        return None
    quarter = _MONTH_TO_FISCAL_QUARTER.get(d.month)
    if quarter is None:
        return None
    fiscal_year = d.year if quarter == 4 else d.year + 1
    return quarter, fiscal_year


def _fiscal_year_only(period_iso: str) -> int | None:
    q_fy = _fiscal_quarter_and_year(period_iso)
    return q_fy[1] if q_fy else None


def _month_year(source_date: str) -> str:
    try:
        d = datetime.strptime(source_date[:10], "%Y-%m-%d")
    except ValueError:
        return source_date[:10]
    return d.strftime("%b %Y")


# ---------------------------------------------------------------------------
# Resolving period / agency from CompanyProfile back-links
# ---------------------------------------------------------------------------


def resolve_period(
    evidence_id: str,
    profile: CompanyProfile | None,
) -> tuple[str | None, str | None, bool]:
    """(period, period_type, spans_multiple_periods) for evidence_id.

    Scans the snapshot-style containers (financial/esg/ownership) that carry
    both a period and a `sources` back-link list. This is the same reverse
    lookup query.engine.drilldown() already performs — reused here, not
    duplicated as a fresh index.

    period is the *latest* period this evidence contributed to (snapshots
    are sorted ASC after build_profile(), so the last match, not the first,
    is most recent — relevant for a document that supplements several
    periods at once).

    spans_multiple_periods is True when the same evidence_id appears in more
    than one distinct period's snapshot — the structural signature of a
    multi-year reference table (e.g. a strategy deck's 5-year ROE/FCF table),
    not a single quarter's results. _build_display_name uses this to avoid
    mislabelling a multi-year reference document as if it were that one
    quarter's earnings deck.
    """
    if profile is None:
        return None, None, False
    for container in (
        profile.financial.snapshots,
        profile.esg.snapshots,
        profile.ownership.snapshots,
    ):
        matches = [s for s in container if evidence_id in s.sources]
        if not matches:
            continue
        matches = sorted(matches, key=lambda s: s.period)
        latest = matches[-1]
        period_type = getattr(latest, "period_type", None)
        spans_multiple = len({s.period for s in matches}) > 1
        return latest.period, period_type, spans_multiple
    return None, None, False


def resolve_agency(evidence_id: str, profile: CompanyProfile | None) -> str | None:
    """Rating agency name for a credit_rating_report evidence_id, or None."""
    if profile is None:
        return None
    for entry in (
        profile.credit_history.debt_ratings + profile.credit_history.esg_ratings
    ):
        if entry.evidence_id == evidence_id:
            return entry.agency
    return None


# ---------------------------------------------------------------------------
# Per-kind display-name templates
# ---------------------------------------------------------------------------

_KIND_LABEL = {
    "annual_report": "Annual Report",
    "financial_results": "Financial Results",
    "earnings_transcript": "Earnings Call Transcript",
    "investor_presentation": "Investor Presentation",
    "dividend": "Dividend Announcement",
    "buyback": "Buyback",
    "acquisition": "Acquisition Filing",
    "agm_notice": "AGM Notice",
    "board_outcome": "Board Outcome",
    "brsr": "BRSR",
    "credit_rating_report": "Credit Rating Report",
    "regulatory_filing": "Regulatory Filing",
    "shareholding_pattern": "Shareholding Pattern",
    "corporate_governance_report": "Corporate Governance Report",
    "research_report": "Research Report",
    "news": "News",
    "discussion": "Discussion",
    "other": "Document",
}

_SHORT_ABBREV = {
    "annual_report": "AR",
    "financial_results": "Results",
    "earnings_transcript": "Transcript",
    "investor_presentation": "IR Deck",
    "dividend": "Dividend",
    "buyback": "Buyback",
    "acquisition": "Acquisition",
    "agm_notice": "AGM",
    "board_outcome": "Board Outcome",
    "brsr": "BRSR",
    "credit_rating_report": "Rating",
    "regulatory_filing": "Reg. Filing",
    "shareholding_pattern": "SHP",
    "corporate_governance_report": "CG Report",
    "research_report": "Research",
    "news": "News",
    "discussion": "Discussion",
    "other": "Doc",
}

# Kinds whose documents cover a fiscal quarter (shown as "Q{n} FY{yyyy}").
_QUARTER_COVERING_KINDS = {
    "financial_results",
    "earnings_transcript",
    "investor_presentation",
}
# Kinds whose documents cover a full fiscal year only (shown as "FY{yyyy}").
_YEAR_COVERING_KINDS = {"annual_report", "brsr"}
# Everything else is a point-in-time event, shown as "{Kind} - {Mon YYYY}".


def _build_display_name(
    ticker: str,
    kind: str,
    source_date: str,
    period: str | None,
    period_type: str | None,
    spans_multiple_periods: bool = False,
) -> str:
    label = _KIND_LABEL.get(kind, kind.replace("_", " ").title())

    # A document whose evidence_id backs more than one distinct period is
    # structurally a multi-year reference table (e.g. a strategy deck's
    # 5-year ROE/FCF history), not that one quarter's earnings deck — label
    # it by its own filing date instead of the historical period it happens
    # to also cite.
    if kind in _QUARTER_COVERING_KINDS and period and not spans_multiple_periods:
        q_fy = _fiscal_quarter_and_year(period)
        if q_fy:
            # A quarter-end date always has a real quarter identity, whether
            # or not the same call *also* reports full-year figures (a Q4
            # call is annual-scoped in period_type but still happened in a
            # specific quarter) — always show it, never drop it because
            # period_type says "annual".
            quarter, fy = q_fy
            return f"{ticker} Q{quarter} FY{fy} {label}"

    if kind in _YEAR_COVERING_KINDS and not spans_multiple_periods:
        fy = _fiscal_year_only(period) if period else None
        if fy is None:
            # Fall back to the filing year — an FY-covering document's own
            # filing date is a reasonable proxy when no period was resolved
            # (e.g. analysis hasn't run yet), still never fabricating a page
            # or a quarter it doesn't have.
            try:
                fy = datetime.strptime(source_date[:10], "%Y-%m-%d").year
            except ValueError:
                fy = None
        return f"{ticker} FY{fy} {label}" if fy else f"{ticker} {label}"

    # Point-in-time event: month/year from source_date, matching the
    # convention in the user-specified examples (board outcome, credit
    # rating, shareholding pattern all use "- Mon YYYY", not a fiscal quarter).
    return f"{ticker} {label} - {_month_year(source_date)}"


# ---------------------------------------------------------------------------
# Citation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Citation:
    """Everything needed to present one piece of evidence to a human.

    citation_short/standard/full are computed properties, not stored fields —
    there is nothing here to fall out of sync with display_name.
    """

    evidence_id: str
    canonical_name: str
    display_name: str
    kind: str
    source_date: str
    period: str | None = None
    period_type: str | None = None
    section: str | None = None
    page: int | None = None

    @property
    def citation_short(self) -> str:
        """A compact bracketed tag, derived from display_name — not a
        second, independently-computed period calculation. Whatever
        display_name decided (Q-and-FY, FY-only, or month/year) is reused
        as-is, just with the kind spelled out as its abbreviation and the
        fiscal year compacted ("FY2026" -> "FY26")."""
        label = _KIND_LABEL.get(self.kind, self.kind.replace("_", " ").title())
        abbrev = _SHORT_ABBREV.get(self.kind, self.kind)
        short = self.display_name.replace(label, abbrev, 1)
        short = re.sub(r"FY(\d{4})\b", lambda m: f"FY{m.group(1)[-2:]}", short)
        return f"[{short}]"

    @property
    def citation_standard(self) -> str:
        return self.display_name

    @property
    def citation_full(self) -> str:
        lines = [self.display_name, f"Published: {_month_year(self.source_date)}"]
        if self.section:
            lines.append(f"Section: {self.section}")
        if self.page is not None:
            lines.append(f"Page {self.page}")
        return "\n".join(lines)


def build_citation(
    entry: CatalogEntry,
    ticker: str,
    profile: CompanyProfile | None = None,
    section: str | None = None,
    page: int | None = None,
) -> Citation:
    """Build a Citation for one CatalogEntry.

    period/period_type/agency are resolved lazily from `profile` (when
    given) via evidence_id back-links already present in CompanyProfile —
    nothing is parsed from `entry.title`.
    """
    period, period_type, spans_multiple = resolve_period(entry.evidence_id, profile)
    kind = entry.kind
    display_name = _build_display_name(
        ticker,
        kind,
        entry.source_date,
        period,
        period_type,
        spans_multiple,
    )

    if kind == "credit_rating_report":
        agency = resolve_agency(entry.evidence_id, profile)
        if agency:
            display_name = f"{ticker} Credit Rating Report ({agency}) - {_month_year(entry.source_date)}"

    canonical_name = f"{ticker}/{kind.upper()}/{period or entry.source_date[:10]}"

    return Citation(
        evidence_id=entry.evidence_id,
        canonical_name=canonical_name,
        display_name=display_name,
        kind=kind,
        source_date=entry.source_date,
        period=period,
        period_type=period_type,
        section=section,
        page=page,
    )


def citation_for(
    evidence_id: str,
    entries_by_id: dict[str, CatalogEntry],
    ticker: str,
    profile: CompanyProfile | None = None,
    section: str | None = None,
    page: int | None = None,
) -> Citation | None:
    """Look up a CatalogEntry by evidence_id and build its Citation, or None
    if the evidence_id isn't in the catalog (e.g. a stale/removed entry)."""
    entry = entries_by_id.get(evidence_id)
    if entry is None:
        return None
    return build_citation(entry, ticker, profile, section=section, page=page)
