"""Balance Sheet & Capital Position — is the balance sheet resilient?

A verdict question, not a table-dump question — this section leads with a
synthesized sentence (net cash/debt level and direction, rating level and
trajectory) and only then shows the supporting tables, rather than showing
leverage()'s raw table with no top-line answer above it (v1's failure mode).

Capital returned to shareholders (dividends + buybacks) lives here too,
not in a separate "Capital Allocation" section — "how much cash has left
the business, and can the balance sheet keep doing that" is one resilience
question, not two.
"""
from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company import derived
from atlas.company.model import CompanyProfile
from atlas.query import engine
from atlas.research.citations import Finding
from atlas.research.model import ReportSection
from atlas.research.sections._shared import dedupe_identical_rows, drop_empty_rows

# Balance-sheet/solvency-relevant metrics for a sector where net cash/debt
# and generic leverage() don't apply — a bank's resilience is read through
# capital adequacy and asset quality, not cash-minus-debt. Deliberately
# narrower than "any financial metric" (which would pull in revenue/margin,
# already Business Quality's job) — this list is balance-sheet-specific.
_RESILIENCE_METRIC_FALLBACK = (
    "capital_adequacy_ratio", "gross_npa_ratio", "net_npa_ratio",
    "casa_ratio", "credit_cost", "provision_coverage_ratio",
)


def _net_cash_debt_verdict(profile: CompanyProfile) -> Finding | None:
    snaps = sorted(
        (s for s in profile.financial.snapshots if s.basis == "consolidated" and s.period_type == "annual"),
        key=lambda s: s.period,
    )
    points = [(s.period, nc) for s in snaps if (nc := derived.net_cash(s)) is not None]
    if not points:
        return None
    latest_period, latest_nc = points[-1]
    position = "net cash" if latest_nc >= 0 else "net debt"
    text = f"{position.title()} of {engine._fmt_crore(abs(latest_nc))} as of {engine._fmt_date(latest_period)}"
    if len(points) >= 2:
        prior_nc = points[-2][1]
        delta = latest_nc - prior_nc
        direction = "strengthening" if delta > 0 else "weakening" if delta < 0 else "unchanged"
        text += f", {direction} versus {engine._fmt_date(points[-2][0])} ({engine._fmt_crore(abs(prior_nc))})."
    else:
        text += "."
    return Finding(text=text, kind="synthesis")


def _rating_trajectory(profile: CompanyProfile) -> Finding | None:
    ratings = sorted(profile.credit_history.debt_ratings, key=lambda r: r.source_date, reverse=True)
    if not ratings:
        return None
    latest = ratings[0]
    action = (latest.action or "reaffirmed").lower()
    text = (
        f"Latest debt rating action: {latest.agency} {action} {latest.rating or ''}".strip()
        + f" ({engine._fmt_source_date(latest.source_date)})."
    )
    return Finding(text=text, evidence_ids=[latest.evidence_id] if latest.evidence_id else [], kind="fact")


def _shareholder_returns(profile: CompanyProfile) -> list[Finding]:
    ce = profile.capital_events
    findings = []
    if ce.dividends:
        findings.append(Finding(
            text=f"{len(ce.dividends)} dividend declaration(s) on record.",
            evidence_ids=[e.evidence_id for e in ce.dividends if e.evidence_id],
            kind="synthesis",
        ))
    buyback_total = sum(e.amount for e in ce.buybacks if e.amount is not None)
    if buyback_total:
        findings.append(Finding(
            text=f"Total disclosed buyback capital across all programs: {engine._fmt_crore(buyback_total)}.",
            evidence_ids=[e.evidence_id for e in ce.buybacks if e.evidence_id and e.amount],
            kind="synthesis",
        ))
    return findings


def build(profile: CompanyProfile, repo: Repository | None, ticker: str) -> ReportSection:
    findings: list[Finding] = []
    tables = []
    notes = []

    verdict = _net_cash_debt_verdict(profile)
    if verdict:
        findings.append(verdict)
    rating = _rating_trajectory(profile)
    if rating:
        findings.append(rating)
    findings.extend(_shareholder_returns(profile))

    lev_result = engine.leverage(profile)
    for sec in lev_result.sections:
        filtered = drop_empty_rows(sec)
        if filtered.rows:
            tables.append(filtered)

    ratings_result = engine.credit_ratings(profile)
    for sec in ratings_result.sections:
        if sec.rows:
            tables.append(sec)

    cap_result = engine.capital_allocation(profile)
    for sec in cap_result.sections:
        if sec.heading in ("Dividends", "Buybacks") and sec.rows:
            deduped = dedupe_identical_rows(sec)
            if deduped.rows:
                tables.append(deduped)

    if not findings and not tables:
        # net_cash/leverage()/ratings/shareholder-returns are all built
        # around an industrial company's balance sheet shape — found
        # during validation that this left the whole section empty for
        # SBI despite Atlas having real capital-adequacy/asset-quality data
        # for it. Falls back to whichever resilience-relevant banking
        # metric IS populated, generically, the same registry-driven
        # mechanism business_quality.py/esg_governance.py already use.
        for metric_key in _RESILIENCE_METRIC_FALLBACK:
            result = engine.timeline(profile, metric_key, repo=repo)
            if result.sections and result.sections[0].rows:
                tables.append(result.sections[0])
        if tables:
            notes.append(
                "No net cash/debt or dividend/buyback data found — showing whichever balance-"
                "sheet-relevant metrics this company's filings actually report instead (e.g. a "
                "bank's capital adequacy and asset-quality ratios rather than net cash/debt)."
            )
        else:
            notes.append("No balance sheet, credit rating, or capital return data found in profile.")

    return ReportSection(
        key="balance_sheet",
        title="Balance Sheet & Capital Position",
        findings=findings,
        tables=tables,
        notes=notes,
    )
