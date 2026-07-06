"""Competitive Position — ranks this company against every peer profile
Atlas has on hand, for whatever metrics both happen to have data for.

No Competitor object and no sector taxonomy exist in Atlas today, so
"competitive position" can only mean one thing honestly: reuse screen()
against every other company under the same repository base. This is
genuinely useful once multiple same-sector names are covered and honestly
limited when they aren't (e.g. TCS/Tata Steel/SBI span three different
sectors today) — the section always states which peers it checked rather
than presenting a cross-sector ranking as if it meant something it doesn't.
"""
from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.query import metrics as metrics_mod
from atlas.query import screen as screen_mod
from atlas.research.model import ReportSection

# Metrics broad enough to be meaningful across sectors — leverage and
# ownership concepts apply to any listed company; margin/banking-specific
# metrics are deliberately excluded here since comparing a bank's NIM
# against an IT company's operating margin would be a false comparison,
# not a competitive one.
_CROSS_SECTOR_METRICS = ("net_debt", "promoter_pct", "fpi_pct", "dii_pct")


def build(
    profile: CompanyProfile,
    repo: Repository | None,
    ticker: str,
    peer_profiles: dict[str, CompanyProfile] | None = None,
) -> ReportSection:
    tables = []
    notes = []

    peers = {k: v for k, v in (peer_profiles or {}).items() if k != ticker}
    if not peers:
        notes.append(
            "No peer companies available in this Atlas instance — competitive "
            "positioning limited to management's own stated market-share or "
            "competitive commentary (see Management Credibility / Business Quality)."
        )
        return ReportSection(key="competitive_position", title="Competitive Position", notes=notes)

    all_profiles = {ticker: profile, **peers}
    for metric_key in _CROSS_SECTOR_METRICS:
        spec = metrics_mod.get_metric(metric_key)
        result = screen_mod.screen(all_profiles, metric_key)
        rows = [r for r in result.sections[0].rows if r]
        if rows:
            tables.append(result.sections[0])

    notes.append(
        f"Peers checked: {', '.join(sorted(peers))}. Cross-sector comparisons are "
        "limited to metrics that apply regardless of industry (leverage, ownership) "
        "— sector-specific metrics (margins, banking ratios) are not compared across "
        "different sectors here to avoid a misleading ranking."
    )
    return ReportSection(
        key="competitive_position",
        title="Competitive Position",
        tables=tables,
        notes=notes,
    )
