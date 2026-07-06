"""The Call — does this deserve another hour?

Built last (needs every other section's own output) but rendered first —
the decision page every real investment-memo genre puts up front, whether
it's a hedge fund pitch's "Long/Short, N% target return" or a
quality-compounder letter's opening paragraph. v1's Executive Summary
failed this test: it was a list of pointers ("36 risks — see Risks"),
which means a reader has to visit five other sections to know if this is
interesting, exactly backwards from the goal.

Every line here restates a finding that already exists, with its own
citation, in another section — this must never become a second,
independent source of claims. Where a question has no answer (valuation),
the disclosure says so directly rather than omitting it.
"""
from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.research.citations import Finding
from atlas.research.model import ReportSection
from atlas.research.signals import classify_metric_moves, top_movers


def build(
    profile: CompanyProfile,
    repo: Repository | None,
    ticker: str,
    other_sections: list[ReportSection] | None = None,
) -> ReportSection:
    findings: list[Finding] = []
    sections_by_key = {s.key: s for s in (other_sections or [])}

    # Most material recent change — What Changed's own leading (most
    # recent) event, not re-derived.
    changed_sec = sections_by_key.get("what_changed")
    if changed_sec and changed_sec.findings:
        findings.append(Finding(
            text=f"Most recent development: {changed_sec.findings[0].text}",
            evidence_ids=changed_sec.findings[0].evidence_ids,
            kind="synthesis",
        ))

    # Biggest signal move — financial-domain first, same priority rule as
    # Business Quality/Balance Sheet use, falling back to any domain only
    # if no financial signal exists at all.
    financial_signals = classify_metric_moves(profile, domains=("financial",))
    improving = top_movers(financial_signals, "improving", n=1)
    deteriorating = top_movers(financial_signals, "deteriorating", n=1)
    if not improving and not deteriorating:
        other_signals = classify_metric_moves(profile, domains=("esg", "ownership"))
        improving = top_movers(other_signals, "improving", n=1)
        deteriorating = top_movers(other_signals, "deteriorating", n=1)
    for sig in improving:
        findings.append(Finding(
            text=f"Improving: {sig.label} ({sig.prior_period} → {sig.latest_period}).",
            evidence_ids=sig.sources, kind="synthesis",
        ))
    for sig in deteriorating:
        findings.append(Finding(
            text=f"Deteriorating: {sig.label} ({sig.prior_period} → {sig.latest_period}).",
            evidence_ids=sig.sources, kind="synthesis",
        ))

    # Balance sheet verdict — balance_sheet.py's own first finding IS the
    # net cash/debt verdict sentence (see its build(), the verdict is
    # always appended first); reused verbatim, not recomputed.
    bs_sec = sections_by_key.get("balance_sheet")
    if bs_sec and bs_sec.findings:
        findings.append(Finding(
            text=f"Balance sheet: {bs_sec.findings[0].text}",
            evidence_ids=bs_sec.findings[0].evidence_ids,
            kind="synthesis",
        ))

    # Credibility verdict — a count, pointing at Management Credibility's
    # own (now substantive, not just a volume count) findings.
    cred_sec = sections_by_key.get("management_credibility")
    if cred_sec and cred_sec.findings:
        findings.append(Finding(
            text=f"{len(cred_sec.findings)} management-credibility signal(s) found — see Management Credibility.",
            kind="synthesis",
        ))

    # Single most severe open risk — risks.py sorts confidence-first, so
    # its leading finding is the best candidate, but headline it only when
    # genuinely reliable. Found during validation: TCS's risk-factor
    # extraction is unreliable enough that every entry was a single
    # mention with no risk-vocabulary at all — confidently headlining
    # whichever one sorted first (a slide heading, in that case) would
    # have been worse than admitting no reliable pick exists.
    risks_sec = sections_by_key.get("risks")
    if risks_sec and risks_sec.findings and "[low confidence" not in risks_sec.findings[0].text:
        findings.append(Finding(
            text=f"Top risk on record: {risks_sec.findings[0].text}",
            evidence_ids=risks_sec.findings[0].evidence_ids,
            kind="synthesis",
        ))
    elif risks_sec and risks_sec.findings:
        findings.append(Finding(
            text=(
                "No sufficiently reliable risk factor to headline — every entry on record is a "
                "single, unrecurring mention with no clear risk vocabulary. See What Could Go "
                "Wrong for the full (caveated) list."
            ),
            kind="synthesis",
        ))

    findings.append(Finding(
        text=(
            "Atlas does not issue a buy/sell recommendation and has no market price data — "
            "this is an evidence briefing, not a rating. See Valuation."
        ),
        kind="synthesis",
    ))

    notes = []
    if len(findings) <= 1:
        notes.append("Insufficient data across sections to produce a decision-relevant summary.")

    return ReportSection(
        key="the_call",
        title="The Call",
        findings=findings,
        notes=notes,
    )
