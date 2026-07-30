"""Deterministic, rule-based investor query engine operating on CompanyProfile.

All query functions are pure: they accept a CompanyProfile and return a
QueryResult containing pre-formatted tabular data.  No KB access, no raw
documents, no LLM calls. An optional `repo` (catalog metadata only, never a
raw document body) lets timeline/compare/summary/drilldown resolve
human-readable citations instead of raw evidence_ids — when omitted (e.g.
in unit tests that construct a synthetic CompanyProfile with no backing
repository), those functions fall back to showing the raw evidence_id, so
every existing caller and test keeps working unchanged.

Each QueryResult is a list of TableSections; the CLI render layer (render.py)
turns them into text tables.  Test code can inspect rows directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Callable

from atlas.acquisition.repository import Repository
from atlas.analysis.base import FactKind, FactUnit
from atlas.citation import build_citation
from atlas.company import derived
from atlas.company.model import (
    AcquisitionEvent,
    CompanyProfile,
    CreditRatingEntry,
    OwnershipSnapshot,
    StrategyEntry,
)
from atlas.knowledge.entities import EntityResolver
from atlas.provenance import current_fingerprint
from atlas.query import metrics

# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------


@dataclass
class TableSection:
    """One labelled table within a QueryResult."""

    heading: str
    columns: list[str]
    rows: list[list[str]]


@lru_cache(maxsize=1)
def _build_digest() -> str:
    """The running build's digest, computed once per process.

    ``current_fingerprint()`` shells out to ``git describe`` for ``code_rev``,
    and a query result is built for every query a session runs. Caching turns
    that into one subprocess per process instead of one per result. Nothing it
    reads can change while the process is alive: the digest covers five
    declared version constants, all of them module-level.
    """
    return current_fingerprint().digest()


@dataclass
class QueryResult:
    """The output of a single investor query.

    ``fingerprint`` records which build answered (#51). It defaults to the
    running build's digest rather than being passed in at each of the nineteen
    construction sites, and that is a deliberate departure from how M6 pinned
    ``ReasoningResult``:

    * a ``ReasoningResult`` is stored and re-loaded, so it needs
      ``fingerprint=None`` to mean "written before pinning existed". A
      ``QueryResult`` is never serialised -- there is no ``json``, ``asdict``
      or store path anywhere in ``src`` -- so it is always built by running
      code, and an unpinned one could only ever mean a construction site
      someone forgot;
    * one of those sites is ``query/screen.py``, which is not registered in
      ``_QUERIES`` and which #53's inventory test therefore cannot see. A
      default covers it, and covers the next surface added the same way.

    Pass it explicitly to describe some other build; nothing in ``src`` does.
    """

    query: str
    company_id: str
    title: str
    sections: list[TableSection] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    fingerprint: str = field(default_factory=_build_digest)

    def is_empty(self) -> bool:
        return all(not s.rows for s in self.sections)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_crore(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:,.0f} cr"


def _fmt_pct(v: float | None, decimals: int = 1) -> str:
    if v is None:
        return "-"
    return f"{v:.{decimals}f}%"


def _fmt_date(s: str | None) -> str:
    """ISO date string -> 'Mar 2024' abbreviated label."""
    if not s:
        return "-"
    try:
        d = datetime.strptime(s[:10], "%Y-%m-%d")
        return d.strftime("%b %Y")
    except ValueError:
        return s


def _fmt_source_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _yoy_delta(current: float | None, prior: float | None) -> str:
    if current is None or prior is None or prior == 0:
        return "-"
    pct = (current - prior) / abs(prior) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _pp_delta(current: float | None, prior: float | None) -> str:
    """Percentage-point change between two percent values."""
    if current is None or prior is None:
        return "-"
    delta = current - prior
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.2f}pp"


# ---------------------------------------------------------------------------
# Ownership signal detection
# ---------------------------------------------------------------------------

_OWNERSHIP_THRESHOLDS: dict[FactKind, float] = {
    FactKind.OWNERSHIP_FPI_PCT: 0.50,
    FactKind.OWNERSHIP_DII_PCT: 0.50,
    FactKind.OWNERSHIP_MF_PCT: 0.30,
    FactKind.OWNERSHIP_INSURANCE_PCT: 0.30,
    FactKind.OWNERSHIP_PROMOTER_PCT: 0.05,
    FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT: 0.001,
}
_OWNERSHIP_STREAK = 3
_OWNERSHIP_TRACKED = tuple(_OWNERSHIP_THRESHOLDS)


def _ownership_label(kind: FactKind) -> str:
    return kind.value.removeprefix("ownership_").replace("_", " ")


def _ownership_signals(snaps_asc: list[OwnershipSnapshot]) -> list[str]:
    """Derive ownership trend signals from OwnershipSnapshots sorted oldest-first.

    Mirrors the signal logic in shareholding_trend.py but operates directly
    on the OwnershipSnapshot objects already present in CompanyProfile.
    """
    if len(snaps_asc) < 2:
        return []
    signals: list[str] = []

    # Build per-kind delta series: (from_period, to_period, v0, v1, delta)
    kind_series: dict[FactKind, list[tuple[str, str, float, float, float]]] = {
        k: [] for k in _OWNERSHIP_TRACKED
    }
    for prev, curr in zip(snaps_asc, snaps_asc[1:]):
        for kind in _OWNERSHIP_TRACKED:
            v0 = prev.facts.get(kind)
            v1 = curr.facts.get(kind)
            if v0 is not None and v1 is not None:
                kind_series[kind].append(
                    (
                        prev.period,
                        curr.period,
                        float(v0),
                        float(v1),
                        round(float(v1) - float(v0), 4),
                    )
                )

    # Single-period notable moves
    for kind, series in kind_series.items():
        thr = _OWNERSHIP_THRESHOLDS[kind]
        for from_p, to_p, v0, v1, delta in series:
            if abs(delta) >= thr:
                direction = "increased" if delta > 0 else "decreased"
                signals.append(
                    f"{_ownership_label(kind)} {direction} {abs(delta):.2f}pp "
                    f"({v0:.2f}% -> {v1:.2f}%) {from_p} -> {to_p}"
                )

    # Streak detection: N+ consecutive same-direction moves
    for kind, series in kind_series.items():
        n = len(series)
        if n < _OWNERSHIP_STREAK:
            continue
        emitted_up = emitted_dn = False
        for i in range(_OWNERSHIP_STREAK - 1, n):
            window = series[i - _OWNERSHIP_STREAK + 1 : i + 1]
            all_up = all(w[4] > 0 for w in window)
            all_dn = all(w[4] < 0 for w in window)
            if all_up and not emitted_up:
                signals.append(
                    f"{_ownership_label(kind)} rising for {_OWNERSHIP_STREAK}+ "
                    f"consecutive quarters ({window[0][0]} -> {window[-1][1]})"
                )
                emitted_up = True
            elif all_dn and not emitted_dn:
                signals.append(
                    f"{_ownership_label(kind)} falling for {_OWNERSHIP_STREAK}+ "
                    f"consecutive quarters ({window[0][0]} -> {window[-1][1]})"
                )
                emitted_dn = True

    # Pledging transitions
    pledge = [
        (s.period, s.facts.get(FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT))
        for s in snaps_asc
    ]
    for (p0, v0), (p1, v1) in zip(pledge, pledge[1:]):
        if v0 is not None and v1 is not None:
            if v0 == 0.0 and v1 > 0.0:
                signals.append(f"promoter pledged pct appeared: {v1:.2f}% as of {p1}")
            elif v0 > 0.0 and v1 == 0.0:
                signals.append(
                    f"promoter pledged pct cleared: was {v0:.2f}% as of {p0}"
                )

    return signals


# ---------------------------------------------------------------------------
# 1. Revenue evolution
# ---------------------------------------------------------------------------


def revenue(
    profile: CompanyProfile,
    basis: str = "consolidated",
    period_type: str = "annual",
) -> QueryResult:
    """Revenue, PAT, and margins over time.

    Filters to *basis* + *period_type* snapshots sorted oldest-first.
    Adds YoY revenue growth (%) column.
    """
    snaps = sorted(
        [
            s
            for s in profile.financial.snapshots
            if s.basis == basis and s.period_type == period_type
        ],
        key=lambda s: s.period,
    )

    columns = [
        "Period",
        "Revenue (cr)",
        "PAT (cr)",
        "PAT Margin",
        "EBIT Margin",
        "YoY Rev",
    ]
    rows: list[list[str]] = []
    prev_rev: float | None = None

    for snap in snaps:
        rev = snap.facts.get(FactKind.FINANCIAL_REVENUE)
        pat = snap.facts.get(FactKind.FINANCIAL_PAT)
        rows.append(
            [
                _fmt_date(snap.period),
                _fmt_crore(rev),
                _fmt_crore(pat),
                _fmt_pct(derived.pat_margin_pct(snap)),
                _fmt_pct(derived.ebit_margin_pct(snap)),
                _yoy_delta(rev, prev_rev),
            ]
        )
        prev_rev = rev

    notes = []
    if not snaps:
        notes.append(f"No {period_type} {basis} snapshots found.")
    elif basis == "consolidated" and not snaps:
        notes.append("Falling back to standalone - no consolidated data available.")

    section = TableSection(
        heading=f"{basis.title()} {period_type.title()} P&L",
        columns=columns,
        rows=rows,
    )
    return QueryResult(
        query="revenue",
        company_id=profile.company_id,
        title="Revenue Evolution",
        sections=[section],
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 2. Capital allocation events
# ---------------------------------------------------------------------------


def capital_allocation(profile: CompanyProfile) -> QueryResult:
    """All capital allocation events across every sub-ledger."""
    ce = profile.capital_events
    sections: list[TableSection] = []

    # Dividends
    div_rows = [
        [
            _fmt_source_date(e.source_date),
            e.dividend_type or "-",
            f"{e.per_share:.2f}/share",
            e.record_date or "-",
        ]
        for e in reversed(ce.dividends)
    ]
    sections.append(
        TableSection(
            heading="Dividends",
            columns=["Date", "Type", "Per Share", "Record Date"],
            rows=div_rows,
        )
    )

    # Buybacks
    bb_rows = [
        [
            _fmt_source_date(e.source_date),
            e.sub_type,
            _fmt_crore(e.amount),
            (
                _fmt_crore(e.price_per_share).replace(" cr", "/share")
                if e.price_per_share
                else "-"
            ),
        ]
        for e in reversed(ce.buybacks)
    ]
    sections.append(
        TableSection(
            heading="Buybacks",
            columns=["Date", "Sub-type", "Amount", "Price/Share"],
            rows=bb_rows,
        )
    )

    # Acquisitions
    def _ev(e: AcquisitionEvent) -> str:
        if e.enterprise_value is None:
            return "-"
        unit_label = e.enterprise_value_unit.value if e.enterprise_value_unit else ""
        return f"{e.enterprise_value:,.1f} {unit_label}".strip()

    acq_rows = [
        [
            _fmt_source_date(e.source_date),
            e.target_name,
            e.consideration_type or "-",
            _ev(e),
            _fmt_pct(e.stake_pct) if e.stake_pct is not None else "-",
        ]
        for e in reversed(ce.acquisitions)
    ]
    sections.append(
        TableSection(
            heading="Acquisitions & Incorporations",
            columns=["Date", "Target", "Consideration", "EV", "Stake"],
            rows=acq_rows,
        )
    )

    # Investments
    inv_rows = [
        [
            _fmt_source_date(e.source_date),
            e.target_name,
            (
                f"{e.amount:,.1f} {e.amount_unit.value}"
                if e.amount and e.amount_unit
                else _fmt_crore(e.amount) if e.amount else "-"
            ),
        ]
        for e in reversed(ce.investments)
    ]
    sections.append(
        TableSection(
            heading="Investments",
            columns=["Date", "Target", "Amount"],
            rows=inv_rows,
        )
    )

    # Fundraises
    fund_rows = [
        [
            _fmt_source_date(e.source_date),
            e.fundraise_type,
            _fmt_crore(e.amount),
        ]
        for e in reversed(ce.fundraises)
    ]
    sections.append(
        TableSection(
            heading="Fundraising",
            columns=["Date", "Type", "Max Amount"],
            rows=fund_rows,
        )
    )

    notes = []
    total = sum(len(s.rows) for s in sections)
    if total == 0:
        notes.append("No capital allocation events found in profile.")

    return QueryResult(
        query="capital",
        company_id=profile.company_id,
        title="Capital Allocation Events",
        sections=sections,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 3. Strategy
# ---------------------------------------------------------------------------


def strategy(
    profile: CompanyProfile,
    keyword: str | None = None,
) -> QueryResult:
    """Management strategy entries, optionally filtered by keyword.

    Groups entries by kind (priority / guidance / aspiration).
    Returns most-recent first within each group.
    """
    entries = profile.strategy.entries
    if keyword:
        kw = keyword.lower()
        entries = [e for e in entries if kw in e.text.lower()]

    by_kind: dict[str, list[StrategyEntry]] = {
        "priority": [],
        "guidance": [],
        "aspiration": [],
    }
    for e in entries:
        bucket = by_kind.get(e.kind)
        if bucket is not None:
            bucket.append(e)

    sections: list[TableSection] = []
    for kind, label in [
        ("priority", "Strategic Priorities"),
        ("guidance", "Guidance"),
        ("aspiration", "Aspirations"),
    ]:
        bucket = sorted(by_kind[kind], key=lambda e: e.source_date, reverse=True)
        rows = [[_fmt_source_date(e.source_date), e.text] for e in bucket]
        sections.append(
            TableSection(heading=label, columns=["Date", "Statement"], rows=rows)
        )

    notes = []
    if keyword and all(not s.rows for s in sections):
        notes.append(f"No strategy entries match keyword {keyword!r}.")

    # CSAT scores (unaffected by keyword filter — not a strategy entry)
    csat_rows = [
        [_fmt_date(c.period), _fmt_pct(c.score)]
        for c in sorted(profile.strategy.csat, key=lambda c: c.period, reverse=True)
    ]
    if csat_rows:
        sections.append(
            TableSection(
                heading="Customer Satisfaction (CSAT)",
                columns=["Period", "Score"],
                rows=csat_rows,
            )
        )

    return QueryResult(
        query="strategy",
        company_id=profile.company_id,
        title=f"Strategy{f' - filter: {keyword!r}' if keyword else ''}",
        sections=sections,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 4. Acquisitions detail
# ---------------------------------------------------------------------------


def acquisitions(profile: CompanyProfile) -> QueryResult:
    """Acquisition and subsidiary formation events in detail, most-recent first."""
    rows: list[list[str]] = []
    for e in reversed(profile.capital_events.acquisitions):
        ev_str = "-"
        if e.enterprise_value is not None:
            unit_label = (
                e.enterprise_value_unit.value if e.enterprise_value_unit else ""
            )
            ev_str = f"{e.enterprise_value:,.1f} {unit_label}".strip()
        rows.append(
            [
                _fmt_source_date(e.source_date),
                e.target_name,
                e.consideration_type or "-",
                ev_str,
                _fmt_pct(e.stake_pct) if e.stake_pct is not None else "-",
                e.expected_completion or "-",
            ]
        )

    notes = []
    if not rows:
        notes.append("No acquisitions found in profile.")

    return QueryResult(
        query="acquisitions",
        company_id=profile.company_id,
        title="Acquisitions & Incorporations",
        sections=[
            TableSection(
                heading="All Events",
                columns=[
                    "Date",
                    "Target",
                    "Consideration",
                    "EV",
                    "Stake",
                    "Expected Close",
                ],
                rows=rows,
            )
        ],
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 5. Ownership time-series
# ---------------------------------------------------------------------------


def ownership(profile: CompanyProfile, last_n: int = 8) -> QueryResult:
    """Shareholding pattern, most-recent first, with QoQ delta for promoter and FPI.

    Also surfaces trend signals derived from the full ownership history:
    consecutive-direction streaks, large single-quarter moves, and pledging
    transitions appear as a second "Ownership Signals" section.
    """
    snaps = sorted(profile.ownership.snapshots, key=lambda s: s.period, reverse=True)[
        :last_n
    ]

    # Build ordered list oldest-first so we can compute deltas forward, then reverse for display
    snaps_asc = list(reversed(snaps))
    rows: list[list[str]] = []
    for i, snap in enumerate(snaps_asc):
        prior = snaps_asc[i - 1] if i > 0 else None
        promoter = snap.facts.get(FactKind.OWNERSHIP_PROMOTER_PCT)
        fpi = snap.facts.get(FactKind.OWNERSHIP_FPI_PCT)
        dii = snap.facts.get(FactKind.OWNERSHIP_DII_PCT)
        mf = snap.facts.get(FactKind.OWNERSHIP_MF_PCT)
        public = snap.facts.get(FactKind.OWNERSHIP_PUBLIC_PCT)
        pledged = snap.facts.get(FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT)

        prior_promoter = (
            prior.facts.get(FactKind.OWNERSHIP_PROMOTER_PCT) if prior else None
        )
        prior_fpi = prior.facts.get(FactKind.OWNERSHIP_FPI_PCT) if prior else None

        promoter_str = (
            f"{promoter:.2f}% ({_pp_delta(promoter, prior_promoter)})"
            if promoter is not None
            else "-"
        )
        fpi_str = (
            f"{fpi:.2f}% ({_pp_delta(fpi, prior_fpi)})" if fpi is not None else "-"
        )

        rows.append(
            [
                _fmt_date(snap.period),
                promoter_str,
                fpi_str,
                _fmt_pct(dii, 2),
                _fmt_pct(mf, 2),
                _fmt_pct(public, 2),
                _fmt_pct(pledged, 2),
            ]
        )

    # Reverse to show most-recent first
    rows.reverse()

    # Compute signals from ALL available snapshots (not limited by last_n)
    all_snaps_asc = sorted(profile.ownership.snapshots, key=lambda s: s.period)
    signals = _ownership_signals(all_snaps_asc)

    sections: list[TableSection] = [
        TableSection(
            heading=f"Shareholding Pattern (last {last_n} quarters)",
            columns=[
                "Period",
                "Promoter (QoQ)",
                "FPI (QoQ)",
                "DII",
                "MF",
                "Public",
                "Pledged",
            ],
            rows=rows,
        )
    ]
    if signals:
        sections.append(
            TableSection(
                heading="Ownership Signals",
                columns=["Signal"],
                rows=[[sig] for sig in signals],
            )
        )

    notes = []
    if not rows:
        notes.append("No ownership snapshots found.")

    return QueryResult(
        query="ownership",
        company_id=profile.company_id,
        title="Ownership Structure",
        sections=sections,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 6. Leverage evolution
# ---------------------------------------------------------------------------


def leverage(
    profile: CompanyProfile,
    basis: str = "consolidated",
    period_type: str = "annual",
) -> QueryResult:
    """Cash, debt, and net cash/debt position over time."""
    snaps = sorted(
        [
            s
            for s in profile.financial.snapshots
            if s.basis == basis and s.period_type == period_type
        ],
        key=lambda s: s.period,
    )

    columns = ["Period", "Cash (cr)", "Total Debt (cr)", "Net Cash/Debt (cr)"]
    rows: list[list[str]] = []
    for snap in snaps:
        cash = snap.facts.get(FactKind.FINANCIAL_CASH_AND_EQUIVALENTS)
        debt = snap.facts.get(FactKind.FINANCIAL_TOTAL_DEBT)
        nc = derived.net_cash(snap)
        nc_str = "-"
        if nc is not None:
            label = "net cash" if nc >= 0 else "net debt"
            nc_str = f"{abs(nc):,.0f} cr ({label})"
        rows.append(
            [
                _fmt_date(snap.period),
                _fmt_crore(cash),
                _fmt_crore(debt),
                nc_str,
            ]
        )

    notes = []
    if not rows:
        notes.append(
            f"No {period_type} {basis} snapshots with balance sheet data found."
        )

    return QueryResult(
        query="leverage",
        company_id=profile.company_id,
        title="Leverage Evolution",
        sections=[
            TableSection(
                heading=f"{basis.title()} {period_type.title()} Balance Sheet",
                columns=columns,
                rows=rows,
            )
        ],
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 7. Credit ratings
# ---------------------------------------------------------------------------


def credit_ratings(profile: CompanyProfile) -> QueryResult:
    """Current credit and ESG ratings — latest entry per (agency, instrument)."""

    def _latest(entries: list[CreditRatingEntry]) -> list[CreditRatingEntry]:
        seen: dict[tuple[str, str | None], CreditRatingEntry] = {}
        for e in entries:
            key = (e.agency, e.instrument)
            if key not in seen or e.source_date > seen[key].source_date:
                seen[key] = e
        return sorted(seen.values(), key=lambda e: e.source_date, reverse=True)

    def _rating_rows(entries: list[CreditRatingEntry]) -> list[list[str]]:
        return [
            [
                _fmt_source_date(e.source_date),
                e.agency,
                e.instrument or "-",
                e.rating or "-",
                e.outlook or "-",
                e.action or "-",
            ]
            for e in entries
        ]

    esg_latest = _latest(profile.credit_history.esg_ratings)
    debt_latest = _latest(profile.credit_history.debt_ratings)

    cols = ["Date", "Agency", "Instrument", "Rating/Score", "Outlook", "Action"]
    sections = [
        TableSection(
            heading="ESG Ratings", columns=cols, rows=_rating_rows(esg_latest)
        ),
        TableSection(
            heading="Debt Ratings", columns=cols, rows=_rating_rows(debt_latest)
        ),
    ]

    notes = []
    if not esg_latest and not debt_latest:
        notes.append("No credit or ESG ratings found.")

    return QueryResult(
        query="ratings",
        company_id=profile.company_id,
        title="Credit & ESG Ratings (Latest per Agency)",
        sections=sections,
        notes=notes,
    )


def auditor_history(profile: CompanyProfile) -> QueryResult:
    """Statutory auditor firm and opinion across filings, most-recent first
    (M-P3.2, Q42) -- multi-year continuity/changes readable directly from the
    row order."""
    entries = sorted(
        profile.governance.auditor_history, key=lambda a: a.source_date, reverse=True
    )
    rows = [
        [_fmt_source_date(a.source_date), a.firm or "-", a.opinion or "-"]
        for a in entries
    ]

    notes = []
    if not rows:
        notes.append(
            "No auditor firm/opinion found. Annual filings must be analyzed and ingested first."
        )

    return QueryResult(
        query="auditor_history",
        company_id=profile.company_id,
        title="Auditor History",
        sections=[
            TableSection(
                heading="Auditor firm and opinion (most recent first)",
                columns=["Date", "Firm", "Opinion"],
                rows=rows,
            )
        ],
        notes=notes,
    )


def related_party_disclosures(profile: CompanyProfile) -> QueryResult:
    """Related-party amounts disclosed in notes to accounts, most-recent
    period first (M-P3.3, Q44).

    ``kind`` distinguishes a period FLOW ("transaction") from a period-end
    STOCK ("balance") per Ind AS 24 -- never conflated. Only "balance" rows
    are populated in this milestone (the per-counterparty transaction table
    is deferred; see AGENT.md / ADR-0012 for why).
    """
    entries = sorted(
        profile.governance.related_parties, key=lambda rp: rp.period, reverse=True
    )
    rows = [
        [rp.period, rp.kind, rp.category, f"{rp.amount:,.2f}", rp.counterparty or "-"]
        for rp in entries
    ]

    notes = []
    if not rows:
        notes.append(
            "No related-party disclosures found. Annual filings must be analyzed and ingested first."
        )

    return QueryResult(
        query="related_party_disclosures",
        company_id=profile.company_id,
        title="Related-Party Disclosures",
        sections=[
            TableSection(
                heading="Related-party amounts (most recent period first)",
                columns=["Period", "Kind", "Category", "Amount (Cr)", "Counterparty"],
                rows=rows,
            )
        ],
        notes=notes,
    )


_RE_RPT_RESOLUTION = re.compile(r"related party transactions?", re.IGNORECASE)
_RE_RPT_COUNTERPARTY = re.compile(r"\bwith\s+(.+?)(?:\.\s*$|\.$|$)", re.IGNORECASE)


def rpt_resolutions(profile: CompanyProfile) -> QueryResult:
    """AGM resolutions that approve related-party transactions, tagged by
    classifying ``AGMResolution.title`` text (M-P3.3, Q44).

    A derived query, not a persisted field: RPT-ness and the named
    counterparty (when the title states one) are computed at query time from
    the existing resolution title, never stored as a separate fact.
    """
    entries = sorted(
        profile.governance.resolutions, key=lambda r: r.source_date, reverse=True
    )
    rows: list[list[str]] = []
    for r in entries:
        if not _RE_RPT_RESOLUTION.search(r.title):
            continue
        m = _RE_RPT_COUNTERPARTY.search(r.title)
        counterparty = m.group(1).strip().rstrip(".") if m else "-"
        rows.append(
            [
                _fmt_source_date(r.source_date),
                _oneline(r.title),
                counterparty,
                r.outcome or "-",
            ]
        )

    notes = []
    if not rows:
        notes.append(
            "No related-party-transaction resolutions found among AGM resolutions on record."
        )

    return QueryResult(
        query="rpt_resolutions",
        company_id=profile.company_id,
        title="Related-Party-Transaction AGM Resolutions",
        sections=[
            TableSection(
                heading="RPT resolutions (most recent first)",
                columns=["Date", "Title", "Counterparty", "Outcome"],
                rows=rows,
            )
        ],
        notes=notes,
    )


def rating_risk_timeline(profile: CompanyProfile) -> QueryResult:
    """Debt rating actions annotated with the risk factors from the most
    recent PRECEDING annual-report period (M-P2.3, Q41).

    A temporal association, not a causal claim: each row shows what the
    filings said shortly before an action, never that the risks CAUSED it.
    Deliberately DEBT ratings only (``credit_history.debt_ratings``) --
    ESG ratings use an unrelated scale and are never mixed in here.

    Ratings from different agencies use different, non-comparable scales
    (AA+ domestic vs. BBB- vs. Baa2). This query never compares a rating
    action against a PRIOR action to infer an upgrade/downgrade across
    agencies -- it reports each agency's own stated ``action`` verbatim.
    Under-emit: if no debt rating exists, the result says so rather than
    guessing from ESG ratings or other proxies.
    """
    actions = sorted(profile.credit_history.debt_ratings, key=lambda e: e.source_date)

    # Risk factors by period, so each action can look up the single latest
    # period strictly BEFORE it -- not a cumulative history.
    periods = sorted({r.period for r in profile.governance.risk_factors})

    def _preceding_period(action_date: str) -> str | None:
        candidates = [p for p in periods if p < action_date]
        return candidates[-1] if candidates else None

    rows: list[list[str]] = []
    for e in actions:
        action_date = e.source_date.date().isoformat()
        period = _preceding_period(action_date)
        if period is None:
            risk_text = "(no preceding annual-report risk factors on record)"
        else:
            texts = [
                r.text for r in profile.governance.risk_factors if r.period == period
            ]
            risk_text = "; ".join(_oneline(t) for t in texts[:3])
            if len(texts) > 3:
                risk_text += f" (+{len(texts) - 3} more)"

        rows.append(
            [
                _fmt_source_date(e.source_date),
                e.agency,
                e.rating or "-",
                e.action or "-",
                _fmt_date(period) if period else "-",
                risk_text,
            ]
        )

    notes = [
        "Temporal association only: risk factors shown are what was on file "
        "before the action, not a claimed cause. Ratings are never compared "
        "across agencies or scales — each action is the agency's own stated "
        "call, not an inferred upgrade/downgrade.",
    ]
    if not actions:
        notes.append("No debt rating actions found for this company.")

    return QueryResult(
        query="rating_risk_timeline",
        company_id=profile.company_id,
        title="Rating Actions and Preceding Risk Factors",
        sections=[
            TableSection(
                heading="Debt rating actions (chronological)",
                columns=[
                    "Date",
                    "Agency",
                    "Rating",
                    "Action",
                    "Preceding Risk Period",
                    "Risk Factors on File",
                ],
                rows=rows,
            )
        ],
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 8. Recurring risk factors
# ---------------------------------------------------------------------------


def risks(profile: CompanyProfile) -> QueryResult:
    """Risk factors extracted from annual reports, deduplicated by text."""
    rf = profile.governance.risk_factors

    # Deduplicate by lower-cased text, keeping the most-recent period per unique text.
    seen: dict[str, tuple[str, str]] = {}  # normalised_text -> (period, text)
    for r in rf:
        key = r.text.lower().strip()
        if key not in seen or r.period > seen[key][0]:
            seen[key] = (r.period, r.text)

    # Sort most-recent filing first
    deduped = sorted(seen.values(), key=lambda t: t[0], reverse=True)

    rows = [[_fmt_date(period), text] for period, text in deduped]

    notes = []
    if not rows:
        notes.append(
            "No risk factors found. Annual reports must be analyzed and ingested first."
        )

    return QueryResult(
        query="risks",
        company_id=profile.company_id,
        title="Recurring Risk Factors",
        sections=[
            TableSection(
                heading="Risk Factors (deduplicated, most-recent first)",
                columns=["Period", "Risk Factor"],
                rows=rows,
            )
        ],
        notes=notes,
    )


_RE_RISK_PUNCT = re.compile(r"[^\w\s]")
_RE_RISK_WS = re.compile(r"\s+")


def _normalize_risk_text(text: str) -> str:
    """Presentation-only normalization for risk-factor grouping (M-P2.6):
    lowercase, strip punctuation, collapse whitespace. Deliberately no
    stemming, synonym expansion, fuzzy matching, or semantic grouping --
    two risk statements group together only if they are the same words,
    modulo case/punctuation/whitespace."""
    lowered = text.lower()
    no_punct = _RE_RISK_PUNCT.sub(" ", lowered)
    return _RE_RISK_WS.sub(" ", no_punct).strip()


@dataclass
class _RiskGroup:
    """One presentation-normalized risk-factor group's running state."""

    display: str
    latest_period: str
    periods: set[str]


def risk_recurrence(profile: CompanyProfile) -> QueryResult:
    """Which risk factors keep appearing across reporting periods (M-P2.6, Q22).

    Groups RiskEntry.text by presentation-normalized form (case/punctuation/
    whitespace only) and counts DISTINCT reporting periods each group appears
    in -- repeated rows within the same period do not inflate the count.
    Only groups appearing in 2+ distinct periods are "recurring"; the rest are
    under-emitted (excluded) rather than padded in to force a result.

    Complements, and does not modify, risks() -- that query lists individual
    statements deduplicated to their latest occurrence; this one answers a
    different question (which risks keep coming back, and how often).
    """
    groups: dict[str, _RiskGroup] = {}
    for r in profile.governance.risk_factors:
        key = _normalize_risk_text(r.text)
        if not key:
            continue
        if key not in groups:
            groups[key] = _RiskGroup(
                display=r.text, latest_period=r.period, periods={r.period}
            )
        else:
            group = groups[key]
            group.periods.add(r.period)
            if (
                r.period >= group.latest_period
            ):  # keep the verbatim form of the latest period seen
                group.display, group.latest_period = r.text, r.period

    recurring = [
        (group.display, group.periods)
        for group in groups.values()
        if len(group.periods) >= 2
    ]

    # Three stable passes in REVERSE priority order (lowest priority first) --
    # Python's sort is stable, so each pass preserves the ordering already
    # established by the previous (higher-priority) pass among equal keys.
    # Net effect: count desc, then most-recent-period desc, then text asc.
    recurring.sort(key=lambda item: item[0])  # 3. text asc
    recurring.sort(key=lambda item: max(item[1]), reverse=True)  # 2. period desc
    recurring.sort(key=lambda item: len(item[1]), reverse=True)  # 1. count desc

    rows = [
        [str(len(periods)), _fmt_date(max(periods)), _oneline(display)]
        for display, periods in recurring
    ]

    notes: list[str] = []
    if not rows:
        notes.append(
            "No risk factor recurs across multiple reporting periods "
            "(presentation-normalized text match only)."
        )

    return QueryResult(
        query="risk_recurrence",
        company_id=profile.company_id,
        title="Recurring Risk Factors Across Periods",
        sections=[
            TableSection(
                heading="Risks appearing in 2+ distinct reporting periods",
                columns=["Occurrences", "Most Recent Period", "Risk Factor"],
                rows=rows,
            )
        ],
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 9. Generic metric timeline
# ---------------------------------------------------------------------------


def timeline(
    profile: CompanyProfile,
    metric: str,
    basis: str = "consolidated",
    period_type: str | None = None,
    repo: Repository | None = None,
) -> QueryResult:
    """Time series for any metric registered in query.metrics.

    Unlike revenue()/leverage() (hand-written, multi-column, kept as-is),
    this reads the metric registry generically — it's how ~70 previously
    unqueryable FactKinds (banking ratios, ESG, TCV, ROE, production
    volume, derived margins) become accessible without a bespoke function
    each. basis/period_type only apply to financial-domain metrics; esg and
    ownership snapshots carry no such distinction.

    Raises ValueError if *metric* is not registered.
    """
    spec = metrics.get_metric(metric)
    snaps = metrics.domain_snapshots(profile, spec.domain)
    if spec.domain == "financial":
        snaps = [
            s
            for s in snaps
            if s.basis == basis
            and (period_type is None or s.period_type == period_type)
        ]
    snaps = sorted(snaps, key=lambda s: s.period)

    columns = ["Period", spec.label, "Change", "Sources"]
    rows: list[list[str]] = []
    prev_value: float | None = None
    for snap in snaps:
        value = metrics.snapshot_value(spec, snap)
        if value is None:
            continue
        delta = (
            _pp_delta(value, prev_value)
            if spec.unit == FactUnit.PERCENT
            else _yoy_delta(value, prev_value)
        )
        rows.append(
            [
                _fmt_date(snap.period),
                metrics.format_value(value, spec.unit),
                delta,
                _cite_sources(snap.sources, profile, repo),
            ]
        )
        prev_value = value

    notes = []
    if not rows:
        notes.append(f"No data found for metric {metric!r} ({spec.label}).")

    heading = spec.label
    if spec.domain == "financial":
        heading += f" - {basis}" + (f" {period_type}" if period_type else "")

    return QueryResult(
        query="timeline",
        company_id=profile.company_id,
        title=f"Timeline: {spec.label}",
        sections=[TableSection(heading=heading, columns=columns, rows=rows)],
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 10. Period-over-period comparison
# ---------------------------------------------------------------------------


def compare(
    profile: CompanyProfile,
    metric: str,
    n: int = 2,
    basis: str = "consolidated",
    period_type: str | None = None,
    repo: Repository | None = None,
) -> QueryResult:
    """Last *n* periods of one metric side-by-side, each vs. its predecessor.

    Reuses timeline()'s data selection; differs only in framing the result
    as an explicit period-over-period comparison rather than a full series.
    """
    spec = metrics.get_metric(metric)
    snaps = metrics.domain_snapshots(profile, spec.domain)
    if spec.domain == "financial":
        snaps = [
            s
            for s in snaps
            if s.basis == basis
            and (period_type is None or s.period_type == period_type)
        ]
    snaps = sorted(snaps, key=lambda s: s.period)

    points: list[tuple[str, float, list[str]]] = []
    for snap in snaps:
        value = metrics.snapshot_value(spec, snap)
        if value is not None:
            points.append((snap.period, value, snap.sources))
    points = points[-n:]

    columns = ["Period", spec.label, "Change vs Prior", "Sources"]
    rows: list[list[str]] = []
    for i, (period, value, sources) in enumerate(points):
        prior_value = points[i - 1][1] if i > 0 else None
        delta = (
            _pp_delta(value, prior_value)
            if spec.unit == FactUnit.PERCENT
            else _yoy_delta(value, prior_value)
        )
        rows.append(
            [
                _fmt_date(period),
                metrics.format_value(value, spec.unit),
                delta,
                _cite_sources(sources, profile, repo),
            ]
        )

    notes = []
    if not points:
        notes.append(f"No data found for metric {metric!r} ({spec.label}).")
    elif len(points) < 2:
        notes.append("Only one period with data - nothing to compare against yet.")

    return QueryResult(
        query="compare",
        company_id=profile.company_id,
        title=f"Period Comparison: {spec.label}",
        sections=[
            TableSection(
                heading=f"Last {len(points)} periods", columns=columns, rows=rows
            )
        ],
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 11. Company summary
# ---------------------------------------------------------------------------


def summary(profile: CompanyProfile, repo: Repository | None = None) -> QueryResult:
    """One-page overview: latest financials, ownership, ratings, guidance,
    recent capital events, ESG headline, and recent board changes.

    Pure aggregation of data already in CompanyProfile — no new extraction,
    every section reuses logic already validated by an existing query.
    Guidance and capital events get a Source column (a citation when repo
    is given, "-" otherwise) — this is new capability, not a UUID being
    hidden, since summary() never showed a raw evidence_id before.
    """
    sections: list[TableSection] = []

    def _cite_one(evidence_id: str) -> str:
        if repo is None:
            return "-"
        entry = repo.get(evidence_id)
        return (
            build_citation(entry, profile.company_id, profile).citation_short
            if entry
            else "-"
        )

    fin_snaps = sorted(
        [
            s
            for s in profile.financial.snapshots
            if s.basis == "consolidated" and s.period_type == "annual"
        ],
        key=lambda s: s.period,
    )
    if fin_snaps:
        latest_fin = fin_snaps[-1]
        rows = [
            [
                _fmt_date(latest_fin.period),
                _fmt_crore(latest_fin.facts.get(FactKind.FINANCIAL_REVENUE)),
                _fmt_crore(latest_fin.facts.get(FactKind.FINANCIAL_PAT)),
                _fmt_pct(derived.pat_margin_pct(latest_fin)),
                _fmt_pct(derived.ebit_margin_pct(latest_fin)),
            ]
        ]
        sections.append(
            TableSection(
                heading="Latest Annual Financials",
                columns=["Period", "Revenue", "PAT", "PAT Margin", "EBIT Margin"],
                rows=rows,
            )
        )

    own_snaps = sorted(profile.ownership.snapshots, key=lambda s: s.period)
    if own_snaps:
        latest_own = own_snaps[-1]
        rows = [
            [
                _fmt_date(latest_own.period),
                _fmt_pct(latest_own.facts.get(FactKind.OWNERSHIP_PROMOTER_PCT), 2),
                _fmt_pct(latest_own.facts.get(FactKind.OWNERSHIP_FPI_PCT), 2),
                _fmt_pct(latest_own.facts.get(FactKind.OWNERSHIP_DII_PCT), 2),
            ]
        ]
        sections.append(
            TableSection(
                heading="Latest Ownership",
                columns=["Period", "Promoter", "FPI", "DII"],
                rows=rows,
            )
        )

    ratings_result = credit_ratings(profile)
    for sec in ratings_result.sections:
        if sec.rows:
            sections.append(
                TableSection(
                    heading=f"Latest {sec.heading}",
                    columns=sec.columns,
                    rows=sec.rows[:3],
                )
            )

    guidance = sorted(
        [e for e in profile.strategy.entries if e.kind == "guidance"],
        key=lambda e: e.source_date,
        reverse=True,
    )[:3]
    if guidance:
        rows = [
            [_fmt_source_date(e.source_date), e.text, _cite_one(e.evidence_id)]
            for e in guidance
        ]
        sections.append(
            TableSection(
                heading="Recent Guidance",
                columns=["Date", "Statement", "Source"],
                rows=rows,
            )
        )

    events: list[tuple[datetime, str, str]] = []
    ce = profile.capital_events
    for dividend in ce.dividends:
        events.append(
            (
                dividend.source_date,
                f"Dividend: {dividend.dividend_type} {dividend.per_share:.2f}/share",
                dividend.evidence_id,
            )
        )
    for buyback in ce.buybacks:
        amt = f" ({buyback.amount:,.0f} cr)" if buyback.amount else ""
        events.append(
            (
                buyback.source_date,
                f"Buyback: {buyback.sub_type}{amt}",
                buyback.evidence_id,
            )
        )
    for acquisition in ce.acquisitions:
        events.append(
            (
                acquisition.source_date,
                f"Acquisition: {_oneline(acquisition.target_name)}",
                acquisition.evidence_id,
            )
        )
    for investment in ce.investments:
        events.append(
            (
                investment.source_date,
                f"Investment: {_oneline(investment.target_name)}",
                investment.evidence_id,
            )
        )
    for fundraise in ce.fundraises:
        events.append(
            (
                fundraise.source_date,
                f"Fundraise: {fundraise.fundraise_type}",
                fundraise.evidence_id,
            )
        )
    events.sort(key=lambda t: t[0], reverse=True)
    if events:
        rows = [
            [_fmt_source_date(d), text, _cite_one(eid)] for d, text, eid in events[:5]
        ]
        sections.append(
            TableSection(
                heading="Recent Capital Events",
                columns=["Date", "Event", "Source"],
                rows=rows,
            )
        )

    # SBTi commitment facts (ESG_CLIMATE_SBTI_SCOPE12/3_REDUCTION_PCT) are
    # stored with period = target year, not report year (a company's 2050
    # net-zero target snapshot can be chronologically "latest" while
    # carrying none of the actual reporting-year facts below it). Anchor on
    # workforce headcount specifically — present in every real BRSR-sourced
    # annual snapshot, absent from a bare forward-target-only snapshot — so
    # "latest" means the latest real report, not the latest target date.
    esg_snaps = sorted(
        [
            s
            for s in profile.esg.snapshots
            if FactKind.ESG_WORKFORCE_HEADCOUNT in s.facts
        ],
        key=lambda s: s.period,
    )
    if esg_snaps:
        latest_esg = esg_snaps[-1]
        headcount = latest_esg.facts.get(FactKind.ESG_WORKFORCE_HEADCOUNT)
        female_pct = latest_esg.facts.get(FactKind.ESG_WORKFORCE_FEMALE_PCT)
        scope1 = latest_esg.facts.get(FactKind.ESG_GHG_SCOPE1)
        scope2 = latest_esg.facts.get(FactKind.ESG_GHG_SCOPE2)
        rows = [
            [
                _fmt_date(latest_esg.period),
                f"{headcount:,.0f}" if headcount is not None else "-",
                _fmt_pct(female_pct) if female_pct is not None else "-",
                f"{scope1:,.0f} tCO2e" if scope1 is not None else "-",
                f"{scope2:,.0f} tCO2e" if scope2 is not None else "-",
            ]
        ]
        sections.append(
            TableSection(
                heading="ESG Headline",
                columns=[
                    "Period",
                    "Headcount",
                    "Female %",
                    "GHG Scope 1",
                    "GHG Scope 2",
                ],
                rows=rows,
            )
        )

    dir_changes = sorted(
        profile.governance.director_changes, key=lambda d: d.source_date, reverse=True
    )[:3]
    if dir_changes:
        rows = [
            [
                _fmt_source_date(d.source_date),
                d.change_type,
                _oneline(d.name),
                _oneline(d.role) if d.role else "-",
            ]
            for d in dir_changes
        ]
        sections.append(
            TableSection(
                heading="Recent Board Changes",
                columns=["Date", "Type", "Name", "Role"],
                rows=rows,
            )
        )

    notes = []
    risk_count = len({r.text.lower().strip() for r in profile.governance.risk_factors})
    if risk_count:
        notes.append(
            f"{risk_count} unique risk factors tracked - see 'risks' query for detail."
        )
    if not sections:
        notes.append("No data found in profile.")

    return QueryResult(
        query="summary",
        company_id=profile.company_id,
        title="Company Summary",
        sections=sections,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# 12. Provenance-aware drill-down
# ---------------------------------------------------------------------------


def drilldown(
    profile: CompanyProfile, evidence_id: str, repo: Repository | None = None
) -> QueryResult:
    """Every fact and event in the profile traced back to one evidence_id.

    Snapshots and events already track their source evidence_ids (sources /
    .evidence_id) — this was assembled during ingestion but never read by
    any query until now. Scans every container in CompanyProfile.

    The evidence_id argument itself is unchanged (drilldown is still looked
    up by the same immutable internal identifier) — repo only changes how
    the result is *titled*: a human-readable citation when available,
    falling back to the raw evidence_id when repo is omitted or the id
    isn't in the catalog.
    """
    sections: list[TableSection] = []

    def _facts_str(facts: dict[FactKind, float]) -> str:
        return "; ".join(
            f"{k.value}={v}"
            for k, v in sorted(facts.items(), key=lambda kv: kv[0].value)
        )

    rows = [
        [_fmt_date(s.period), s.period_type, s.basis, _facts_str(s.facts)]
        for s in profile.financial.snapshots
        if evidence_id in s.sources
    ]
    if rows:
        sections.append(
            TableSection(
                heading="Financial Snapshots",
                columns=["Period", "Type", "Basis", "Facts"],
                rows=rows,
            )
        )

    rows = [
        [_fmt_date(s.period), _facts_str(s.facts)]
        for s in profile.esg.snapshots
        if evidence_id in s.sources
    ]
    if rows:
        sections.append(
            TableSection(
                heading="ESG Snapshots", columns=["Period", "Facts"], rows=rows
            )
        )

    rows = [
        [_fmt_date(s.period), _facts_str(s.facts)]
        for s in profile.ownership.snapshots
        if evidence_id in s.sources
    ]
    if rows:
        sections.append(
            TableSection(
                heading="Ownership Snapshots", columns=["Period", "Facts"], rows=rows
            )
        )

    rows = [
        [
            _fmt_date(e.period),
            e.name,
            _fmt_crore(e.revenue),
            _fmt_crore(e.ebit),
            _fmt_pct(e.growth_pct),
        ]
        for e in profile.segments.entries
        if e.evidence_id == evidence_id
    ]
    if rows:
        sections.append(
            TableSection(
                heading="Segments",
                columns=["Period", "Segment", "Revenue", "EBIT", "Growth"],
                rows=rows,
            )
        )

    ce = profile.capital_events
    rows = [
        [
            _fmt_source_date(e.source_date),
            "Dividend",
            f"{e.dividend_type} {e.per_share:.2f}/share",
        ]
        for e in ce.dividends
        if e.evidence_id == evidence_id
    ]
    rows += [
        [_fmt_source_date(e.source_date), "Buyback", e.sub_type]
        for e in ce.buybacks
        if e.evidence_id == evidence_id
    ]
    rows += [
        [_fmt_source_date(e.source_date), "Acquisition", _oneline(e.target_name)]
        for e in ce.acquisitions
        if e.evidence_id == evidence_id
    ]
    rows += [
        [_fmt_source_date(e.source_date), "Investment", _oneline(e.target_name)]
        for e in ce.investments
        if e.evidence_id == evidence_id
    ]
    rows += [
        [_fmt_source_date(e.source_date), "Fundraise", e.fundraise_type]
        for e in ce.fundraises
        if e.evidence_id == evidence_id
    ]
    if rows:
        sections.append(
            TableSection(
                heading="Capital Events", columns=["Date", "Type", "Detail"], rows=rows
            )
        )

    rows = [
        [
            _fmt_source_date(e.source_date),
            e.agency,
            e.instrument or "-",
            e.rating or "-",
            e.action or "-",
        ]
        for e in profile.credit_history.debt_ratings
        + profile.credit_history.esg_ratings
        if e.evidence_id == evidence_id
    ]
    if rows:
        sections.append(
            TableSection(
                heading="Credit/ESG Ratings",
                columns=["Date", "Agency", "Instrument", "Rating", "Action"],
                rows=rows,
            )
        )

    rows = [
        [_fmt_source_date(e.source_date), e.kind, e.text]
        for e in profile.strategy.entries
        if e.evidence_id == evidence_id
    ]
    if rows:
        sections.append(
            TableSection(
                heading="Strategy Statements",
                columns=["Date", "Kind", "Text"],
                rows=rows,
            )
        )

    rows = [
        [
            _fmt_source_date(d.source_date),
            d.change_type,
            _oneline(d.name),
            _oneline(d.role) if d.role else "-",
        ]
        for d in profile.governance.director_changes
        if d.evidence_id == evidence_id
    ]
    if rows:
        sections.append(
            TableSection(
                heading="Director Changes",
                columns=["Date", "Type", "Name", "Role"],
                rows=rows,
            )
        )

    rows = [
        [_fmt_source_date(r.source_date), _oneline(r.title), r.outcome or "-"]
        for r in profile.governance.resolutions
        if r.evidence_id == evidence_id
    ]
    if rows:
        sections.append(
            TableSection(
                heading="AGM Resolutions",
                columns=["Date", "Title", "Outcome"],
                rows=rows,
            )
        )

    rows = [
        [_fmt_date(r.period), _oneline(r.text)]
        for r in profile.governance.risk_factors
        if r.evidence_id == evidence_id
    ]
    if rows:
        sections.append(
            TableSection(heading="Risk Factors", columns=["Period", "Text"], rows=rows)
        )

    notes = []
    if not sections:
        notes.append(f"No facts found for evidence_id {evidence_id!r} in this profile.")

    title = f"Drilldown: {evidence_id}"
    if repo is not None:
        entry = repo.get(evidence_id)
        if entry is not None:
            citation = build_citation(entry, profile.company_id, profile)
            title = f"Drilldown: {citation.citation_standard}"
            notes.append(f"evidence_id: {evidence_id}")

    return QueryResult(
        query="drilldown",
        company_id=profile.company_id,
        title=title,
        sections=sections,
        notes=notes,
    )


def _oneline(text: str) -> str:
    """Collapse embedded newlines/whitespace so a value can't break a table row.

    Some extracted text fields (acquisition target names, director roles)
    carry embedded newlines from the source PDF's layout — pre-existing in
    the extraction pipeline (confirmed present in the existing acquisitions()
    query too, not introduced here). summary() and drilldown() are new
    surfaces for those same fields, so they sanitize defensively rather than
    let a raw multi-line value visually break the table.
    """
    return " ".join(text.split())


def _fmt_sources(sources: list[str]) -> str:
    if not sources:
        return "-"
    if len(sources) == 1:
        return sources[0]
    return f"{sources[0]} (+{len(sources) - 1} more)"


def _cite_sources(
    sources: list[str], profile: CompanyProfile, repo: Repository | None
) -> str:
    """Human-readable citation(s) for a Sources column, or the raw
    evidence_id fallback when no repo is available to resolve one.

    Never exposes a raw evidence_id when repo is given and the lookup
    succeeds — this is the one behavioral difference from _fmt_sources,
    which always shows the bare ID. repo is optional so every existing
    caller (including every test constructing a synthetic CompanyProfile
    with no backing catalog) keeps working exactly as before.
    """
    if repo is None or not sources:
        return _fmt_sources(sources)
    labels = []
    for eid in sources:
        entry = repo.get(eid)
        if entry is None:
            labels.append(eid)
        else:
            labels.append(
                build_citation(entry, profile.company_id, profile).citation_short
            )
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]} (+{len(labels) - 1} more)"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def former_answerers(profile: CompanyProfile) -> QueryResult:
    """Q45 — management who answered on earnings calls and have since departed.

    A derived query: it cross-references transcript management participants
    (role="management") against board-outcome director resignations. Identity
    is established by a single ephemeral, query-time application of the existing
    entity-resolution primitive — management names and resignation names are
    resolved together in one pass and matched on the ids produced within it.
    No cross-document id is stored; the document-scoped semantics of stored
    entity_ids are untouched (see the M-P1.5 STEP 0 classification).
    """
    mgmt = [p for p in profile.participants if p.role == "management"]
    resignations = [
        dc
        for dc in profile.governance.director_changes
        if dc.change_type == "resignation"
    ]

    resolver = EntityResolver()
    # Resolve resignations first, then management, in one shared pass.
    resigned: dict[str, object] = {}  # entity_id -> DirectorChange
    for dc in resignations:
        resigned[resolver.resolve(dc.name, "person").entity_id] = dc

    matched: dict[str, tuple[str, set[str], object]] = {}
    for p in mgmt:
        eid = resolver.resolve(p.canonical_name, "person").entity_id
        matched_dc = resigned.get(eid)
        if matched_dc is None:
            continue
        if eid not in matched:
            matched[eid] = (p.canonical_name, set(), matched_dc)
        matched[eid][1].add(p.evidence_id)

    rows = [
        [
            name,
            str(len(calls)),
            _fmt_date(_dc_date(dc)),
            _oneline(getattr(dc, "role", "") or ""),
        ]
        for name, calls, dc in sorted(matched.values(), key=lambda t: t[0])
    ]

    notes: list[str] = []
    if not mgmt:
        notes.append(
            "No management participants recorded. Transcripts with a printed "
            "management roster must be analyzed and ingested first."
        )
    elif not rows:
        notes.append(
            "No management answerer has a matching director-resignation record."
        )

    return QueryResult(
        query="former_answerers",
        company_id=profile.company_id,
        title="Management Answerers Who Have Since Departed",
        sections=[
            TableSection(
                heading="Departed answerers",
                columns=["Name", "Calls", "Departed", "Role"],
                rows=rows,
            )
        ],
        notes=notes,
    )


def _dc_date(dc: object) -> str:
    d = getattr(dc, "source_date", "")
    return d.date().isoformat() if hasattr(d, "date") else str(d)


_QUERIES: dict[str, Callable[..., QueryResult]] = {
    "revenue": revenue,
    "former_answerers": former_answerers,
    "capital": capital_allocation,
    "strategy": strategy,
    "acquisitions": acquisitions,
    "ownership": ownership,
    "leverage": leverage,
    "ratings": credit_ratings,
    "auditor_history": auditor_history,
    "related_party_disclosures": related_party_disclosures,
    "rpt_resolutions": rpt_resolutions,
    "rating_risk_timeline": rating_risk_timeline,
    "risks": risks,
    "risk_recurrence": risk_recurrence,
    "summary": summary,
    "timeline": timeline,
    "compare": compare,
    "drilldown": drilldown,
}


def run_query(query: str, profile: CompanyProfile, **kwargs: object) -> QueryResult:
    """Dispatch a named query to the appropriate function.

    *kwargs* are forwarded to the query function (e.g. ``basis=``, ``keyword=``).

    Raises ``ValueError`` when *query* is not a registered query name.
    """
    fn = _QUERIES.get(query)
    if fn is None:
        raise ValueError(f"Unknown query {query!r}. Available: {sorted(_QUERIES)}")
    return fn(profile, **kwargs)


def available_queries() -> list[str]:
    """Return sorted list of registered query names."""
    return sorted(_QUERIES)
