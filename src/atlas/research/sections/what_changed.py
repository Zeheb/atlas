"""What Changed — the single most universal question across every
investment-memo genre studied for this redesign: nobody re-reads the whole
company each time, they read the delta since the last look.

v1's Timeline was the opposite of this: every dated event ever recorded,
undeduplicated by priority, positioned last in the report. This shows only
events within a recent window (anchored to the most recent event in the
profile, not real-world "today" — a company whose last filing was months
ago should still show its last real window of activity, not an empty
section because wall-clock time moved on).

The full chronological history is not lost — every event here is still
individually queryable via `atlas query <TICKER> summary`, and every
evidence_id still appears in the Appendix — this section is a deliberately
narrow, prioritized front door, not the only way to see history.
"""

from __future__ import annotations

from datetime import timedelta

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.query import engine
from atlas.research.citations import Finding
from atlas.research.model import ReportSection
from atlas.research.sections._shared import collect_dated_events

_WINDOW_DAYS = 120  # roughly one fiscal quarter plus reporting lag


def build(
    profile: CompanyProfile, repo: Repository | None, ticker: str
) -> ReportSection:
    events = collect_dated_events(profile)
    if not events:
        return ReportSection(
            key="what_changed",
            title="What Changed",
            notes=["No dated events found in profile."],
        )

    events.sort(key=lambda e: e[0], reverse=True)
    most_recent = events[0][0]
    cutoff = most_recent - timedelta(days=_WINDOW_DAYS)
    recent = [e for e in events if e[0] >= cutoff]

    findings = [
        Finding(
            text=f"{engine._fmt_source_date(date)} — {category}: {desc}",
            evidence_ids=tuple(eids),
            kind="fact",
        )
        for date, category, desc, eids in recent
    ]

    notes = [
        f"Showing events since {engine._fmt_source_date(cutoff)} ({len(recent)} of {len(events)} "
        "total on record) — the full history is queryable via `atlas query TICKER summary` and "
        "every event's evidence is still listed in the Appendix."
    ]

    return ReportSection(
        key="what_changed",
        title="What Changed",
        findings=findings,
        notes=notes,
    )
