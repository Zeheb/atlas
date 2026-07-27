"""Appendix of Evidence — every document cited anywhere in this report,
deduplicated, in one bibliography.

The Zotero idea applied directly: capture each source once, render it once,
regardless of how many sections cited it. Built last, from every other
section's Finding.evidence_ids — never a second, independent evidence scan.
"""

from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.citation import build_citation
from atlas.company.model import CompanyProfile
from atlas.research.citations import Finding
from atlas.research.model import ReportSection


def build(
    profile: CompanyProfile,
    repo: Repository | None,
    ticker: str,
    other_sections: list[ReportSection] | None = None,
) -> ReportSection:
    seen: dict[str, None] = {}
    for sec in other_sections or []:
        for f in sec.findings:
            for eid in f.evidence_ids:
                seen.setdefault(eid, None)

    findings: list[Finding] = []
    notes = []
    if not seen:
        notes.append("No evidence was cited in this report.")
    elif repo is None:
        notes.append(
            f"{len(seen)} distinct evidence_id(s) cited; repository not available to resolve citations."
        )
    else:
        for eid in seen:
            entry = repo.get(eid)
            if entry is None:
                continue
            citation = build_citation(entry, ticker, profile)
            findings.append(
                Finding(text=citation.citation_full.replace("\n", " — "), kind="fact")
            )
        findings.sort(key=lambda f: f.text)

    return ReportSection(
        key="evidence_appendix",
        title="Appendix of Evidence",
        findings=findings,
        notes=notes,
    )
