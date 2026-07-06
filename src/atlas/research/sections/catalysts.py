"""Catalysts — what happens next, and when?

Every other section looks backward (what already happened, what the
filings already show). This one looks for whatever forward-dated
commitments CompanyProfile already carries: an acquisition's stated
expected-completion date, or a board-authorized fundraise Atlas has no
record of being executed yet.

Deliberately does not claim whether a stated expected-completion date was
actually met — Atlas has no "completion confirmed" field, only what was
originally stated. A date already in the past when this report is
generated is still shown, labeled as stated, since whether it slipped or
completed quietly is exactly the kind of thing a reader should go check,
not something Atlas should guess at.
"""
from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.query import engine
from atlas.research.citations import Finding
from atlas.research.model import ReportSection


def build(profile: CompanyProfile, repo: Repository | None, ticker: str) -> ReportSection:
    findings: list[Finding] = []
    notes = []

    # Deduped on (target, expected_completion): the same pending
    # acquisition routinely gets recorded via both a Board Outcome and an
    # Acquisition Filing announcing the same deal — the same duplicate-
    # recording pattern _shared.collect_dated_events()/dedupe_identical_rows()
    # exist to fix elsewhere, missed here in the first pass.
    pending_acquisitions = [
        e for e in profile.capital_events.acquisitions if e.expected_completion
    ]
    merged: dict[tuple[str, str], list[str]] = {}
    order: list[tuple[str, str]] = []
    for e in pending_acquisitions:
        key = (" ".join(e.target_name.split()), e.expected_completion)
        if key not in merged:
            merged[key] = []
            order.append(key)
        if e.evidence_id and e.evidence_id not in merged[key]:
            merged[key].append(e.evidence_id)

    for target, completion in sorted(order, key=lambda k: k[1]):
        findings.append(Finding(
            text=(
                f"Acquisition of {target} — expected completion "
                f"{completion} as stated in the filing (not confirmed as completed)."
            ),
            evidence_ids=merged[(target, completion)],
            kind="fact",
        ))

    for e in sorted(profile.capital_events.fundraises, key=lambda e: e.source_date, reverse=True):
        findings.append(Finding(
            text=(
                f"Board-authorized {e.fundraise_type} fundraise"
                + (f" of up to {engine._fmt_crore(e.amount)}" if e.amount else "")
                + f" ({engine._fmt_source_date(e.source_date)}) — Atlas has no record of whether "
                "this authorization was subsequently executed."
            ),
            evidence_ids=[e.evidence_id] if e.evidence_id else [],
            kind="fact",
        ))

    if not findings:
        notes.append("No pending acquisition completions or unresolved fundraise authorizations found.")

    return ReportSection(
        key="catalysts",
        title="Catalysts",
        findings=findings,
        notes=notes,
    )
