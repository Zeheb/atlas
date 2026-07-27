"""Management Credibility — is management credible? Answered with three
genuinely deterministic, general signals, none of which require Atlas to
fabricate an opinion:

  1. Numeric targets repeated verbatim across 2+ dated guidance/aspiration
     filings — a real, new-this-round signal (detect_repeated_targets()):
     whether repetition means consistent commitment or a stale, un-updated
     line is left to the reader, who is shown every date it recurred.
  2. Risk factors repeated across multiple annual reports (exact-text
     match, not fuzzy) — consistent disclosure over time is itself a
     credibility-relevant, citable fact.
  3. AGM resolutions that did not pass — a shareholder pushback signal no
     amount of management narrative can spin away.

Deliberately does NOT attempt sentiment analysis or promise-vs-delivery
tracking — STRATEGY_GUIDANCE has no structured link to a target FactKind,
so "was this target met" can't be answered without parsing prose (the
fragile-heuristic pattern this codebase avoids elsewhere). Repetition is
a fact Atlas can state; whether it was *kept* is not.
"""

from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.query import engine
from atlas.research.citations import Finding
from atlas.research.model import ReportSection
from atlas.research.sections._shared import detect_repeated_targets, group_risks_by_text

_MIN_RECURRENCE = 2


def _repeated_targets(profile: CompanyProfile) -> list[Finding]:
    findings = []
    for t in detect_repeated_targets(profile):
        dates = ", ".join(engine._fmt_source_date(d) for d, _ in t.occurrences)
        findings.append(
            Finding(
                text=f'Target "{t.pattern}" repeated across {len(t.occurrences)} dated filings: {dates}.',
                evidence_ids=[eid for _, eid in t.occurrences if eid],
                kind="fact",
            )
        )
    return findings


def _recurring_risks(profile: CompanyProfile) -> list[Finding]:
    by_text = group_risks_by_text(profile)

    findings = []
    for entries in by_text.values():
        periods = sorted({e.period for e in entries})
        if len(periods) < _MIN_RECURRENCE:
            continue
        text = entries[0].text
        findings.append(
            Finding(
                text=(
                    f"Risk factor disclosed consistently across {len(periods)} annual reports "
                    f"({engine._fmt_date(periods[0])} to {engine._fmt_date(periods[-1])}): {text}"
                ),
                evidence_ids=list(
                    dict.fromkeys(e.evidence_id for e in entries if e.evidence_id)
                ),
                kind="fact",
            )
        )
    return sorted(findings, key=lambda f: f.text)


def _failed_resolutions(profile: CompanyProfile) -> list[Finding]:
    return [
        Finding(
            text=(
                f"AGM resolution did not pass: {r.title.strip()} "
                f"({engine._fmt_source_date(r.source_date)}"
                + (
                    f", {r.pct_against:.1f}% against"
                    if r.pct_against is not None
                    else ""
                )
                + ")"
            ),
            evidence_ids=[r.evidence_id] if r.evidence_id else [],
            kind="fact",
        )
        for r in profile.governance.resolutions
        if r.outcome == "not_passed"
    ]


def build(
    profile: CompanyProfile, repo: Repository | None, ticker: str
) -> ReportSection:
    findings: list[Finding] = []
    notes = []

    findings.extend(_repeated_targets(profile))
    findings.extend(_recurring_risks(profile))
    findings.extend(_failed_resolutions(profile))

    if not findings:
        notes.append(
            "No repeated targets, recurring risks, or failed resolutions found to assess."
        )

    return ReportSection(
        key="management_credibility",
        title="Management Credibility",
        findings=findings,
        notes=notes,
    )
