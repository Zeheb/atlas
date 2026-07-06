"""Business Quality — is the underlying business good?

Not "what were last quarter's numbers" (that's What Changed) but whether
margin levels are durable and growth is consistent — a multi-year question,
which is why this reads the FULL available history for the headline
margin/revenue metrics rather than the latest-vs-prior comparison
signals.py already does elsewhere. A margin held for 8 years is a
structurally different fact than one hit once; distinguishing them needs
more than two datapoints.

Segment concentration (how much of revenue sits in the single largest
segment) is a structural fact about business quality — a company where one
segment is 80% of revenue carries different risk than one spread evenly
across five — read directly from CompanyProfile.segments, no new extraction.
"""
from __future__ import annotations

from datetime import datetime

from atlas.acquisition.repository import Repository
from atlas.analysis.base import FactKind
from atlas.company.model import CompanyProfile
from atlas.query import engine
from atlas.query import metrics as metrics_mod
from atlas.research.citations import Finding
from atlas.research.model import ReportSection

# Checked in order; the first with >=2 datapoints is used as the headline
# margin for the stability read. operating_margin is the most broadly
# reported; net_interest_margin is its banking-sector equivalent (a bank's
# P&L doesn't have a "revenue" or generic operating-margin line — see
# balance_sheet.py's NII-fallback for the same reasoning).
_MARGIN_CANDIDATES = ("operating_margin", "nim", "ebit_margin")


def _margin_stability(profile: CompanyProfile, repo: Repository | None) -> tuple[Finding | None, engine.TableSection | None]:
    for period_type, unit_label in (("annual", "years"), ("quarterly", "quarters")):
        for key in _MARGIN_CANDIDATES:
            spec = metrics_mod.get_metric(key)
            snaps = sorted(
                (s for s in profile.financial.snapshots if s.basis == "consolidated" and s.period_type == period_type),
                key=lambda s: s.period,
            )
            points = [(s.period, v) for s in snaps if (v := metrics_mod.snapshot_value(spec, s)) is not None]
            if len(points) < 2:
                continue
            values = [v for _, v in points]
            low, high = min(values), max(values)
            spread = high - low
            # SBI's NIM (found during validation) only exists at quarterly
            # granularity — no annual figure has been extracted for it —
            # so falling back to quarterly here is what actually surfaces
            # a bank's margin stability read at all, not a design choice
            # to prefer quarterly generally.
            period_note = f" (quarterly data — no annual figure extracted)" if period_type == "quarterly" else ""
            finding = Finding(
                text=(
                    f"{spec.label} ranged {metrics_mod.format_value(low, spec.unit)} to "
                    f"{metrics_mod.format_value(high, spec.unit)} over {len(points)} {unit_label} "
                    f"({engine._fmt_date(points[0][0])}–{engine._fmt_date(points[-1][0])}){period_note}, "
                    f"a spread of {spread:.1f} percentage points — "
                    + ("stable" if spread < 3 else "moderately variable" if spread < 8 else "wide-ranging")
                    + " over the period."
                ),
                kind="synthesis",
            )
            result = engine.timeline(profile, key, period_type=period_type, repo=repo)
            table = result.sections[0] if result.sections and result.sections[0].rows else None
            return finding, table
    return None, None


def _growth_consistency(profile: CompanyProfile) -> Finding | None:
    snaps = sorted(
        (s for s in profile.financial.snapshots if s.basis == "consolidated" and s.period_type == "annual"),
        key=lambda s: s.period,
    )
    points = [(s.period, s.facts[FactKind.FINANCIAL_REVENUE]) for s in snaps if FactKind.FINANCIAL_REVENUE in s.facts]
    if len(points) < 3:
        return None
    yoy_positive = sum(1 for (_, prev), (_, curr) in zip(points, points[1:]) if curr > prev)
    total_transitions = len(points) - 1
    first, last = points[0][1], points[-1][1]
    years = (
        datetime.strptime(points[-1][0][:10], "%Y-%m-%d")
        - datetime.strptime(points[0][0][:10], "%Y-%m-%d")
    ).days / 365.25
    cagr = ((last / first) ** (1 / years) - 1) * 100 if first > 0 and years > 0 else None
    cagr_str = f", a {cagr:.1f}% CAGR" if cagr is not None else ""
    return Finding(
        text=(
            f"Revenue grew year-over-year in {yoy_positive} of the last {total_transitions} "
            f"annual comparisons available{cagr_str}."
        ),
        kind="synthesis",
    )


def _segment_concentration(profile: CompanyProfile) -> Finding | None:
    if not profile.segments.entries:
        return None
    latest_period = max(e.period for e in profile.segments.entries)
    latest = [e for e in profile.segments.entries if e.period == latest_period and e.revenue is not None]
    total = sum(e.revenue for e in latest)
    if not latest or not total:
        return None
    largest = max(latest, key=lambda e: e.revenue)
    pct = largest.revenue / total * 100
    return Finding(
        text=(
            f"Largest segment ({largest.name}) accounted for {pct:.0f}% of segment revenue "
            f"as of {engine._fmt_date(latest_period)}, across {len(latest)} reported segments."
        ),
        evidence_ids=[largest.evidence_id] if largest.evidence_id else [],
        kind="fact",
    )


def build(profile: CompanyProfile, repo: Repository | None, ticker: str) -> ReportSection:
    findings: list[Finding] = []
    tables = []
    notes = []

    margin_finding, margin_table = _margin_stability(profile, repo)
    if margin_finding:
        findings.append(margin_finding)
    if margin_table:
        tables.append(margin_table)

    growth_finding = _growth_consistency(profile)
    if growth_finding:
        findings.append(growth_finding)

    segment_finding = _segment_concentration(profile)
    if segment_finding:
        findings.append(segment_finding)

    if not findings:
        notes.append(
            "Not enough multi-year margin, revenue, or segment history available to assess "
            "business quality (need >=2 years of margin data or >=3 of revenue)."
        )

    return ReportSection(
        key="business_quality",
        title="Business Quality",
        findings=findings,
        tables=tables,
        notes=notes,
    )
