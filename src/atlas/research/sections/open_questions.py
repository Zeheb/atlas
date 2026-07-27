"""Open Questions — what Atlas could not resolve, stated plainly rather than
silently omitted.

Takes the other sections' own output as input (a gap-detection pass, not a
new data source) plus one direct profile check: registered metrics with
fewer than 2 datapoints, which signals.classify_metric_moves() already
silently skips — those skips deserve to be visible somewhere, not just
absent from Financial Performance without explanation.
"""

from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.query import metrics as metrics_mod
from atlas.research.citations import EVIDENCE_NOTE, Finding
from atlas.research.model import ReportSection

_MIN_DATAPOINTS_FOR_TREND = 2


def _thin_metrics(
    profile: CompanyProfile, basis: str = "consolidated", period_type: str = "annual"
) -> list[str]:
    thin = []
    for spec in sorted(metrics_mod.METRICS.values(), key=lambda s: s.key):
        if spec.higher_is_better is None:
            continue
        snaps = metrics_mod.domain_snapshots(profile, spec.domain)
        if spec.domain == "financial":
            snaps = [
                s for s in snaps if s.basis == basis and s.period_type == period_type
            ]
        count = sum(1 for s in snaps if metrics_mod.snapshot_value(spec, s) is not None)
        if 0 < count < _MIN_DATAPOINTS_FOR_TREND:
            thin.append(f"{spec.label} ({count} datapoint)")
    return thin


def build(
    profile: CompanyProfile,
    repo: Repository | None,
    ticker: str,
    other_sections: list[ReportSection] | None = None,
) -> ReportSection:
    findings: list[Finding] = []

    for sec in other_sections or []:
        if sec.key in ("open_questions", "the_call", "evidence_appendix", "valuation"):
            continue
        if sec.is_empty():
            findings.append(
                Finding(
                    text=f"No evidence found to populate '{sec.title}' — needs further acquisition or analysis.",
                    kind=EVIDENCE_NOTE,
                )
            )

    thin = _thin_metrics(profile)
    if thin:
        findings.append(
            Finding(
                text=(
                    "Insufficient history (fewer than 2 periods) to assess a trend for: "
                    + "; ".join(thin)
                    + "."
                ),
                kind=EVIDENCE_NOTE,
            )
        )

    notes = []
    if not findings:
        notes.append(
            "No material gaps identified in the data reviewed for this report."
        )

    return ReportSection(
        key="open_questions",
        title="Open Questions",
        findings=findings,
        notes=notes,
    )
