"""What Could Go Wrong — risks, prioritized, not a flat dump of every risk
factor ever mentioned across 14 years of annual reports.

Atlas has no severity/impact estimate for risk-factor text, so there's no
honest way to rank "most dangerous" — sorted instead by (confidence desc,
recurrence desc, recency desc), where confidence is
is_high_confidence_risk() (recurring across years, or genuine risk
vocabulary). Recency alone was tried first and found unreliable: TCS's
plausibility-filtered list had zero recurring entries at all, so
recency-only tie-breaking surfaced a slide heading as the top "risk".
Nothing is dropped, only reordered — the full list still follows.
"""

from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.research.citations import Finding
from atlas.research.model import ReportSection
from atlas.research.sections._shared import (
    RISK_RELIABILITY_CAVEAT,
    group_risks_by_text,
    is_high_confidence_risk,
)

_LEAD_COUNT = 8


def build(
    profile: CompanyProfile, repo: Repository | None, ticker: str
) -> ReportSection:
    by_text = group_risks_by_text(profile)
    entries_by_group = []

    for entries in by_text.values():
        latest = max(entries, key=lambda e: e.period)
        periods = sorted({e.period for e in entries})
        confident = is_high_confidence_risk(latest.text, len(periods))
        entries_by_group.append(
            (confident, len(periods), latest.period, latest, periods)
        )

    # High-confidence entries (recurring, or genuine risk-vocabulary) lead
    # regardless of recency — see is_high_confidence_risk()'s docstring for
    # why recency alone was an unreliable tiebreaker among single-mention,
    # unfiltered-noise-prone entries.
    entries_by_group.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)

    findings: list[Finding] = []
    for confident, recurrence, _, latest, periods in entries_by_group:
        recurrence_str = (
            f" (disclosed in {recurrence} annual report(s))" if recurrence > 1 else ""
        )
        confidence_tag = "" if confident else " [low confidence — see caveat below]"
        findings.append(
            Finding(
                text=f"{latest.text.strip()}{recurrence_str}{confidence_tag}",
                evidence_ids=(latest.evidence_id,) if latest.evidence_id else (),
                kind="fact",
            )
        )

    notes = []
    if not findings:
        notes.append(
            "No risk factors found. Annual reports must be analyzed and ingested first."
        )
    else:
        if len(findings) > _LEAD_COUNT:
            notes.append(
                f"Sorted by confidence (recurring or genuine risk vocabulary), then recurrence, "
                f"then recency — the first {_LEAD_COUNT} of {len(findings)} are the most reliable/"
                "current; the remainder follows."
            )
        notes.append(RISK_RELIABILITY_CAVEAT)

    return ReportSection(
        key="risks",
        title="What Could Go Wrong",
        findings=findings,
        notes=notes,
    )
