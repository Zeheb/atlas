"""Orchestrator: calls every section builder in order, then renders.

Section order matters for two reasons: (1) it's the order a reader
encounters them — The Call first because "does this deserve another hour"
is the question every genre of investment memo answers on page one, not
after ten sections of data — and (2) The Call/Open Questions/Evidence
Appendix are built from the OTHER sections' output, so they must run last
regardless of where they render.

No company-specific branching anywhere in this file — the same fixed
section list runs for every ticker; a section that finds nothing for a
given company says so (via ReportSection.notes) rather than being skipped,
so a reader always sees the full shape of what Atlas checked.
"""

from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.research.model import ReportData, ReportSection
from atlas.research.render import render_markdown
from atlas.research.sections import (
    balance_sheet,
    business_quality,
    catalysts,
    competitive_position,
    esg_governance,
    evidence_appendix,
    management_credibility,
    open_questions,
    risks,
    the_call,
    valuation,
    what_changed,
)

# Rendered order, after The Call: What Changed leads (the one question
# every memo genre answers first), then business/management/balance-sheet
# quality questions, then valuation's honest gap, then risk and forward
# catalysts, then the lower-priority sections (Open Questions, Competitive
# Position — currently inert across 3 different-sector companies, ESG) and
# the Appendix last.
_BODY_BUILDERS = (
    what_changed,
    business_quality,
    management_credibility,
    balance_sheet,
    valuation,
    risks,
    catalysts,
    competitive_position,
    esg_governance,
)


def _build_sections(
    profile: CompanyProfile,
    repo: Repository | None,
    ticker: str,
    peer_profiles: dict[str, CompanyProfile] | None,
) -> list[ReportSection]:
    body: list[ReportSection] = []
    for module in _BODY_BUILDERS:
        if module is competitive_position:
            body.append(
                module.build(profile, repo, ticker, peer_profiles=peer_profiles)
            )
        else:
            body.append(module.build(profile, repo, ticker))

    open_q = open_questions.build(profile, repo, ticker, other_sections=body)
    appendix = evidence_appendix.build(
        profile, repo, ticker, other_sections=body + [open_q]
    )
    the_call_sec = the_call.build(profile, repo, ticker, other_sections=body + [open_q])

    return [the_call_sec, *body, open_q, appendix]


def generate_report(
    ticker: str,
    profile: CompanyProfile,
    repo: Repository | None = None,
    peer_profiles: dict[str, CompanyProfile] | None = None,
) -> ReportData:
    """Assemble a complete Atlas Research report for one company.

    Pure function of profile (+ optional repo for citations, + optional
    peer_profiles for Competitive Position) — no I/O here; callers own
    loading the profile and repository and writing the rendered output.
    """
    sections = _build_sections(profile, repo, ticker, peer_profiles)
    return ReportData(
        ticker=ticker,
        title=f"{ticker} — Investment Research Briefing",
        sections=sections,
    )


def generate_report_markdown(
    ticker: str,
    profile: CompanyProfile,
    repo: Repository | None = None,
    peer_profiles: dict[str, CompanyProfile] | None = None,
) -> str:
    """Convenience wrapper: generate_report() + render_markdown() in one call."""
    report = generate_report(ticker, profile, repo, peer_profiles)
    return render_markdown(report, repo=repo, profile=profile)
