"""ESG / Governance — sustainability metrics (from the esg-domain metric
registry) plus board/audit governance facts.

Reuses metrics.METRICS' esg-domain entries via engine.timeline() — the same
generic mechanism business_quality.py/balance_sheet.py use, just filtered to
a different domain. Director changes and audit KAMs are read directly from
GovernanceProfile since they have no timeline/compare equivalent (they're
categorical, not a numeric series).
"""
from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.query import engine
from atlas.query import metrics as metrics_mod
from atlas.research.citations import DERIVED, Finding
from atlas.research.model import ReportSection
from atlas.research.signals import classify_metric_moves, top_movers

# The handful of ESG metrics most likely to have multi-period data across
# any sector Atlas covers (BRSR mandates these for every listed company);
# every other registered ESG metric is still queryable via `atlas query`,
# this is just the headline subset shown inline.
_HEADLINE_ESG_METRICS = (
    "workforce_headcount", "workforce_female_pct", "workforce_attrition_pct",
    "ghg_scope1", "ghg_scope2", "csr_spend",
)


def build(profile: CompanyProfile, repo: Repository | None, ticker: str) -> ReportSection:
    tables = []
    findings: list[Finding] = []
    notes = []

    for metric_key in _HEADLINE_ESG_METRICS:
        result = engine.timeline(profile, metric_key, repo=repo)
        if result.sections and result.sections[0].rows:
            tables.append(result.sections[0])

    if not tables:
        notes.append("No BRSR/ESG metrics found in profile.")

    # ESG-domain movers belong here, not in Business Quality/Balance Sheet —
    # signals.classify_metric_moves() is called with domains=("esg",) for
    # exactly this reason (an unfiltered call once let an ESG metric
    # outrank Operating Margin purely on raw percentage-point magnitude —
    # a domain mismatch, not a real prioritization).
    esg_signals = classify_metric_moves(profile, domains=("esg",))
    for sig in top_movers(esg_signals, "improving", n=2) + top_movers(esg_signals, "deteriorating", n=2):
        verb = "improved" if sig.direction == "improving" else "deteriorated"
        findings.append(Finding(
            text=(
                f"{sig.label} {verb} from {metrics_mod.format_value(sig.prior_value, metrics_mod.get_metric(sig.metric_key).unit)} "
                f"({engine._fmt_date(sig.prior_period)}) to "
                f"{metrics_mod.format_value(sig.latest_value, metrics_mod.get_metric(sig.metric_key).unit)} "
                f"({engine._fmt_date(sig.latest_period)})."
            ),
            evidence_ids=sig.sources,
            kind="fact",
        ))

    dir_changes = sorted(profile.governance.director_changes, key=lambda d: d.source_date, reverse=True)
    if dir_changes:
        findings.append(Finding(
            text=f"{len(dir_changes)} director/KMP change(s) on record; most recent: "
                 f"{dir_changes[0].change_type} — {engine._oneline(dir_changes[0].name)} "
                 f"({engine._fmt_source_date(dir_changes[0].source_date)}).",
            evidence_ids=[d.evidence_id for d in dir_changes[:5] if d.evidence_id],
            kind=DERIVED,
        ))

    if profile.governance.audit_kams:
        findings.append(Finding(
            text=f"Key Audit Matters on record: {'; '.join(profile.governance.audit_kams)}",
            evidence_ids=[],
            kind="fact",
        ))

    return ReportSection(
        key="esg_governance",
        title="ESG / Governance",
        findings=findings,
        tables=tables,
        notes=notes,
    )
