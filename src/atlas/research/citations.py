"""Reusable citation formatting for research reports.

What this module is not
-------------------------
Atlas's query engine is explicitly deterministic and rule-based — no LLM
calls (see engine.py's module docstring). This module does not generate
analytical prose ("management is optimistic because..."); that judgment is
made by whoever writes the report (a human analyst, or an LLM reading the
underlying transcripts), the same way it always has been. What this module
DOES own is turning that judgment's supporting evidence into professional,
consistent citations — the mechanical part that was previously hand-written
prose per report, sometimes as a bare evidence_id, sometimes not at all.

Design
------
A Finding pairs a claim with the evidence_ids that support it. render()
formats a list of Findings as a plain-text/markdown report section: a
single supporting document becomes a "Source:" block (citation_full, with
section/page when the Finding carries provenance); more than one becomes a
"Supporting evidence" bulleted list (citation_standard each) — this is
exactly the grouping behaviour asked for, driven by how many evidence_ids
a Finding actually has, not a fixed style choice.

Every evidence_id must still resolve through the same repo/profile
back-links atlas.citation already uses — no separate index, no duplicated
metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from atlas.acquisition.repository import Repository
from atlas.citation import Citation, build_citation
from atlas.company.model import CompanyProfile

# What kind of statement a Finding is -- and, through CITATION_OBLIGATION
# below, whether it must cite evidence. M2.3 widened this from the original
# "fact" | "synthesis" pair, which had collapsed four genuinely different
# things into one label:
#
#   FACT           a claim read directly off extracted data
#   DERIVED        an interpretive connection across facts ("3 consecutive
#                  quarters of margin improvement"); inherits the ids of what
#                  it derives from
#   CONCLUSION     a synthesized view over completed investigations (M2.3's
#                  thesis layer); closed-world checked against its run
#   EVIDENCE_NOTE  a statement ABOUT the evidence -- that it is thin, absent,
#                  or unreliable. May cite what it examined, or nothing
#   DISCLOSURE     a statement about Atlas's own limits ("Atlas does not issue
#                  a buy/sell recommendation"). Not an evidence claim at all
#
# The distinction is not cosmetic: before it existed, an empty evidence_ids
# meant BOTH "this is a disclosure" and "this claim is ungrounded", and no
# code could tell them apart. That ambiguity is exactly what a provenance
# gate cannot tolerate.
FACT = "fact"
DERIVED = "derived"
CONCLUSION = "conclusion"
EVIDENCE_NOTE = "evidence_note"
DISCLOSURE = "disclosure"

FindingKind = Literal["fact", "derived", "conclusion", "evidence_note", "disclosure"]

# Whether a kind MUST cite, MAY cite, or must NOT cite.
#
# Three levels, not two. FORBIDDEN is the one a binary must-cite/optional
# split would lose, and it catches a real error class: a policy statement
# dressed up as evidence-backed. A disclosure carrying citations is a
# category error, not a bonus.
#
# Declared here and consumed by the thesis completeness gate
# (research/thesis.py). Obligation is DECLARED by kind, never inferred from
# whether citations happen to be present -- inferring is the ambiguity above.
REQUIRED = "required"
OPTIONAL = "optional"
FORBIDDEN = "forbidden"

CITATION_OBLIGATION: dict[str, str] = {
    FACT: REQUIRED,
    DERIVED: REQUIRED,
    CONCLUSION: REQUIRED,
    EVIDENCE_NOTE: OPTIONAL,
    DISCLOSURE: FORBIDDEN,
}

# "synthesis" was the pre-M2.3 label for what are now DERIVED, EVIDENCE_NOTE
# and DISCLOSURE. Accepted as a legacy alias so any caller or persisted
# artifact predating the split still loads; it maps to the most permissive
# obligation, since its real intent cannot be recovered after the fact.
LEGACY_SYNTHESIS = "synthesis"
CITATION_OBLIGATION[LEGACY_SYNTHESIS] = OPTIONAL


def citation_obligation(kind: str) -> str:
    """The citation obligation for *kind*. Unknown kinds are OPTIONAL rather
    than an error: a stricter default would turn an unrecognized label into a
    hard failure at render time, which is the wrong place to discover it.
    """
    return CITATION_OBLIGATION.get(kind, OPTIONAL)


@dataclass(frozen=True)
class Finding:
    """One claim in a research report, plus the evidence backing it.

    Frozen, with ``evidence_ids`` coerced to a tuple (M2.3): this was the last
    mutable dataclass in the research dependency chain, and the mutability was
    not merely stylistic. ``the_call.py`` builds derived findings by passing
    another finding's ``evidence_ids`` straight through, which aliased one
    list across two findings — safe only by the accident that nothing mutated
    it. As a tuple that sharing is structurally safe.

    Callers may still pass a list; ``__post_init__`` coerces it, matching the
    discipline every other frozen type in Atlas uses.

    text:         the claim/statement itself (the analyst's or LLM's
                  judgment — not generated by this module).
    evidence_ids: one or more supporting documents. Order is preserved.
    section:      optional Provenance-style section label for a single-
                  source finding's "Source:" block (e.g. "Business Outlook").
    page:         optional page number; never fabricated — omitted from
                  output whenever not supplied, same as atlas.citation.
    kind:         one of FACT / DERIVED / CONCLUSION / EVIDENCE_NOTE /
                  DISCLOSURE (see the module-level vocabulary above), which
                  determines the citation obligation. Defaults to FACT, so
                  every pre-existing call site is unaffected; "synthesis" is
                  still accepted as a legacy alias.
    """

    text: str
    evidence_ids: tuple[str, ...] = ()
    section: str | None = None
    page: int | None = None
    kind: str = "fact"

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_ids, tuple):
            object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))


def _citations_for(
    finding: Finding,
    ticker: str,
    repo: Repository,
    profile: CompanyProfile | None,
) -> list[Citation]:
    citations = []
    for eid in finding.evidence_ids:
        entry = repo.get(eid)
        if entry is None:
            continue
        section = finding.section if len(finding.evidence_ids) == 1 else None
        page = finding.page if len(finding.evidence_ids) == 1 else None
        citations.append(
            build_citation(entry, ticker, profile, section=section, page=page)
        )
    return citations


def render_finding(
    finding: Finding,
    ticker: str,
    repo: Repository,
    profile: CompanyProfile | None = None,
) -> str:
    """Render one Finding as text + its citation block.

    One supporting document -> "Source:" + citation_full (section/page
    included when the Finding carries them). More than one -> "Supporting
    evidence" + a bulleted citation_standard list, since several
    independent documents corroborating the same claim is a materially
    different (stronger) kind of evidence than a single source, and the
    reader should see that at a glance rather than a flat list of names.
    """
    lines = [finding.text, ""]
    citations = _citations_for(finding, ticker, repo, profile)

    if not citations:
        lines.append("Source: (evidence unavailable)")
    elif len(citations) == 1:
        lines.append("Source:")
        for line in citations[0].citation_full.split("\n"):
            lines.append(line)
    else:
        lines.append("Supporting evidence:")
        for c in citations:
            lines.append(f"  - {c.citation_standard}")

    return "\n".join(lines)


def render_report(
    title: str,
    findings: list[Finding],
    ticker: str,
    repo: Repository,
    profile: CompanyProfile | None = None,
) -> str:
    """A complete plain-text report: a title, then each Finding with its
    citation block, blank-line separated."""
    blocks = [title, "=" * len(title), ""]
    for finding in findings:
        blocks.append(render_finding(finding, ticker, repo, profile))
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"
