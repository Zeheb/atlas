"""Deterministic, rule-based investor query engine operating on CompanyProfile.

All query functions are pure: they accept a CompanyProfile and return a
QueryResult containing pre-formatted tabular data.  No KB access, no raw
documents, no LLM calls.

Each QueryResult is a list of TableSections; the CLI render layer (render.py)
turns them into text tables.  Test code can inspect rows directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from atlas.analysis.base import FactKind
from atlas.company import derived
from atlas.company.model import (
    AcquisitionEvent,
    CompanyProfile,
    CreditRatingEntry,
    FinancialSnapshot,
)

# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------


@dataclass
class TableSection:
    """One labelled table within a QueryResult."""

    heading: str
    columns: list[str]
    rows: list[list[str]]


@dataclass
class QueryResult:
    """The output of a single investor query."""

    query: str
    company_id: str
    title: str
    sections: list[TableSection] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

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
    FactKind.OWNERSHIP_FPI_PCT:              0.50,
    FactKind.OWNERSHIP_DII_PCT:              0.50,
    FactKind.OWNERSHIP_MF_PCT:               0.30,
    FactKind.OWNERSHIP_INSURANCE_PCT:        0.30,
    FactKind.OWNERSHIP_PROMOTER_PCT:         0.05,
    FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT: 0.001,
}
_OWNERSHIP_STREAK = 3
_OWNERSHIP_TRACKED = tuple(_OWNERSHIP_THRESHOLDS)


def _ownership_label(kind: FactKind) -> str:
    return kind.value.removeprefix("ownership_").replace("_", " ")


def _ownership_signals(snaps_asc: list) -> list[str]:
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
                kind_series[kind].append((
                    prev.period, curr.period,
                    float(v0), float(v1),
                    round(float(v1) - float(v0), 4),
                ))

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
                signals.append(f"promoter pledged pct cleared: was {v0:.2f}% as of {p0}")

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
        [s for s in profile.financial.snapshots
         if s.basis == basis and s.period_type == period_type],
        key=lambda s: s.period,
    )

    columns = ["Period", "Revenue (cr)", "PAT (cr)", "PAT Margin", "EBIT Margin", "YoY Rev"]
    rows: list[list[str]] = []
    prev_rev: float | None = None

    for snap in snaps:
        rev = snap.facts.get(FactKind.FINANCIAL_REVENUE)
        pat = snap.facts.get(FactKind.FINANCIAL_PAT)
        rows.append([
            _fmt_date(snap.period),
            _fmt_crore(rev),
            _fmt_crore(pat),
            _fmt_pct(derived.pat_margin_pct(snap)),
            _fmt_pct(derived.ebit_margin_pct(snap)),
            _yoy_delta(rev, prev_rev),
        ])
        prev_rev = rev

    notes = []
    if not snaps:
        notes.append(f"No {period_type} {basis} snapshots found.")
    elif basis == "consolidated" and not snaps:
        notes.append("Falling back to standalone — no consolidated data available.")

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
    sections.append(TableSection(
        heading="Dividends",
        columns=["Date", "Type", "Per Share", "Record Date"],
        rows=div_rows,
    ))

    # Buybacks
    bb_rows = [
        [
            _fmt_source_date(e.source_date),
            e.sub_type,
            _fmt_crore(e.amount),
            _fmt_crore(e.price_per_share).replace(" cr", "/share") if e.price_per_share else "-",
        ]
        for e in reversed(ce.buybacks)
    ]
    sections.append(TableSection(
        heading="Buybacks",
        columns=["Date", "Sub-type", "Amount", "Price/Share"],
        rows=bb_rows,
    ))

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
    sections.append(TableSection(
        heading="Acquisitions & Incorporations",
        columns=["Date", "Target", "Consideration", "EV", "Stake"],
        rows=acq_rows,
    ))

    # Investments
    inv_rows = [
        [
            _fmt_source_date(e.source_date),
            e.target_name,
            (f"{e.amount:,.1f} {e.amount_unit.value}" if e.amount and e.amount_unit
             else _fmt_crore(e.amount) if e.amount else "-"),
        ]
        for e in reversed(ce.investments)
    ]
    sections.append(TableSection(
        heading="Investments",
        columns=["Date", "Target", "Amount"],
        rows=inv_rows,
    ))

    # Fundraises
    fund_rows = [
        [
            _fmt_source_date(e.source_date),
            e.fundraise_type,
            _fmt_crore(e.amount),
        ]
        for e in reversed(ce.fundraises)
    ]
    sections.append(TableSection(
        heading="Fundraising",
        columns=["Date", "Type", "Max Amount"],
        rows=fund_rows,
    ))

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

    by_kind: dict[str, list] = {"priority": [], "guidance": [], "aspiration": []}
    for e in entries:
        bucket = by_kind.get(e.kind)
        if bucket is not None:
            bucket.append(e)

    sections: list[TableSection] = []
    for kind, label in [("priority", "Strategic Priorities"), ("guidance", "Guidance"), ("aspiration", "Aspirations")]:
        bucket = sorted(by_kind[kind], key=lambda e: e.source_date, reverse=True)
        rows = [[_fmt_source_date(e.source_date), e.text] for e in bucket]
        sections.append(TableSection(heading=label, columns=["Date", "Statement"], rows=rows))

    notes = []
    if keyword and all(not s.rows for s in sections):
        notes.append(f"No strategy entries match keyword {keyword!r}.")

    # CSAT scores (unaffected by keyword filter — not a strategy entry)
    csat_rows = [
        [_fmt_date(c.period), _fmt_pct(c.score)]
        for c in sorted(profile.strategy.csat, key=lambda c: c.period, reverse=True)
    ]
    if csat_rows:
        sections.append(TableSection(
            heading="Customer Satisfaction (CSAT)",
            columns=["Period", "Score"],
            rows=csat_rows,
        ))

    return QueryResult(
        query="strategy",
        company_id=profile.company_id,
        title=f"Strategy{f' — filter: {keyword!r}' if keyword else ''}",
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
            unit_label = e.enterprise_value_unit.value if e.enterprise_value_unit else ""
            ev_str = f"{e.enterprise_value:,.1f} {unit_label}".strip()
        rows.append([
            _fmt_source_date(e.source_date),
            e.target_name,
            e.consideration_type or "-",
            ev_str,
            _fmt_pct(e.stake_pct) if e.stake_pct is not None else "-",
            e.expected_completion or "-",
        ])

    notes = []
    if not rows:
        notes.append("No acquisitions found in profile.")

    return QueryResult(
        query="acquisitions",
        company_id=profile.company_id,
        title="Acquisitions & Incorporations",
        sections=[TableSection(
            heading="All Events",
            columns=["Date", "Target", "Consideration", "EV", "Stake", "Expected Close"],
            rows=rows,
        )],
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
    snaps = sorted(profile.ownership.snapshots, key=lambda s: s.period, reverse=True)[:last_n]

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

        prior_promoter = prior.facts.get(FactKind.OWNERSHIP_PROMOTER_PCT) if prior else None
        prior_fpi = prior.facts.get(FactKind.OWNERSHIP_FPI_PCT) if prior else None

        promoter_str = (
            f"{promoter:.2f}% ({_pp_delta(promoter, prior_promoter)})"
            if promoter is not None else "-"
        )
        fpi_str = (
            f"{fpi:.2f}% ({_pp_delta(fpi, prior_fpi)})"
            if fpi is not None else "-"
        )

        rows.append([
            _fmt_date(snap.period),
            promoter_str,
            fpi_str,
            _fmt_pct(dii, 2),
            _fmt_pct(mf, 2),
            _fmt_pct(public, 2),
            _fmt_pct(pledged, 2),
        ])

    # Reverse to show most-recent first
    rows.reverse()

    # Compute signals from ALL available snapshots (not limited by last_n)
    all_snaps_asc = sorted(profile.ownership.snapshots, key=lambda s: s.period)
    signals = _ownership_signals(all_snaps_asc)

    sections: list[TableSection] = [TableSection(
        heading=f"Shareholding Pattern (last {last_n} quarters)",
        columns=["Period", "Promoter (QoQ)", "FPI (QoQ)", "DII", "MF", "Public", "Pledged"],
        rows=rows,
    )]
    if signals:
        sections.append(TableSection(
            heading="Ownership Signals",
            columns=["Signal"],
            rows=[[sig] for sig in signals],
        ))

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
        [s for s in profile.financial.snapshots
         if s.basis == basis and s.period_type == period_type],
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
        rows.append([
            _fmt_date(snap.period),
            _fmt_crore(cash),
            _fmt_crore(debt),
            nc_str,
        ])

    notes = []
    if not rows:
        notes.append(f"No {period_type} {basis} snapshots with balance sheet data found.")

    return QueryResult(
        query="leverage",
        company_id=profile.company_id,
        title="Leverage Evolution",
        sections=[TableSection(
            heading=f"{basis.title()} {period_type.title()} Balance Sheet",
            columns=columns,
            rows=rows,
        )],
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
        TableSection(heading="ESG Ratings", columns=cols, rows=_rating_rows(esg_latest)),
        TableSection(heading="Debt Ratings", columns=cols, rows=_rating_rows(debt_latest)),
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
        sections=[TableSection(
            heading="Risk Factors (deduplicated, most-recent first)",
            columns=["Period", "Risk Factor"],
            rows=rows,
        )],
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_QUERIES: dict[str, Callable[..., QueryResult]] = {
    "revenue":      revenue,
    "capital":      capital_allocation,
    "strategy":     strategy,
    "acquisitions": acquisitions,
    "ownership":    ownership,
    "leverage":     leverage,
    "ratings":      credit_ratings,
    "risks":        risks,
}


def run_query(query: str, profile: CompanyProfile, **kwargs: object) -> QueryResult:
    """Dispatch a named query to the appropriate function.

    *kwargs* are forwarded to the query function (e.g. ``basis=``, ``keyword=``).

    Raises ``ValueError`` when *query* is not a registered query name.
    """
    fn = _QUERIES.get(query)
    if fn is None:
        raise ValueError(
            f"Unknown query {query!r}. Available: {sorted(_QUERIES)}"
        )
    return fn(profile, **kwargs)


def available_queries() -> list[str]:
    """Return sorted list of registered query names."""
    return sorted(_QUERIES)
