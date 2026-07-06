"""ReportData -> Markdown. The only module in atlas.research that emits
Markdown syntax — every section builder returns structured data, never a
string, so this is the single place output format changes if a second
format (e.g. eventual PDF) is added later.
"""
from __future__ import annotations

from atlas.acquisition.repository import Repository
from atlas.company.model import CompanyProfile
from atlas.query.engine import TableSection
from atlas.research.citations import Finding, _citations_for
from atlas.research.model import ReportData, ReportSection


def _markdown_safe_cell(value: object) -> str:
    """Collapse embedded newlines/whitespace and escape "|" so a cell value
    can never corrupt Markdown table syntax.

    Found necessary during validation: engine.capital_allocation()'s
    acquisition rows carry target names straight from extracted PDF text,
    which sometimes embeds a literal newline (a multi-line company name
    split across a PDF layout) — unlike summary()/drilldown(), which
    already sanitize this defensively (see engine.py's _oneline()),
    capital_allocation() doesn't, and an embedded newline inside a Markdown
    table cell breaks every row after it, not just the one cell.
    """
    text = " ".join(str(value).split())
    return text.replace("|", "\\|")


def _render_table(table: TableSection) -> list[str]:
    lines = [f"**{table.heading}**", ""]
    lines.append("| " + " | ".join(table.columns) + " |")
    lines.append("|" + "|".join(["---"] * len(table.columns)) + "|")
    for row in table.rows:
        lines.append("| " + " | ".join(_markdown_safe_cell(c) for c in row) + " |")
    lines.append("")
    return lines


def _render_finding(
    finding: Finding, ticker: str, repo: Repository | None, profile: CompanyProfile | None,
) -> list[str]:
    tag = "_[synthesis]_ " if finding.kind == "synthesis" else ""
    lines = [f"- {tag}{finding.text}"]

    if repo is not None and finding.evidence_ids:
        citations = _citations_for(finding, ticker, repo, profile)
        if citations:
            if len(citations) == 1:
                lines.append(f"  - Source: {citations[0].citation_standard}")
            else:
                lines.append("  - Supporting evidence: " + "; ".join(c.citation_standard for c in citations))
    return lines


def _render_section(
    section: ReportSection, ticker: str, repo: Repository | None, profile: CompanyProfile | None,
) -> list[str]:
    lines = [f"## {section.title}", ""]

    for table in section.tables:
        lines.extend(_render_table(table))

    for finding in section.findings:
        lines.extend(_render_finding(finding, ticker, repo, profile))
    if section.findings:
        lines.append("")

    for note in section.notes:
        lines.append(f"> {note}")
    if section.notes:
        lines.append("")

    if section.is_empty():
        lines.append("_No evidence available for this section._")
        lines.append("")

    return lines


def render_markdown(report: ReportData, repo: Repository | None = None, profile: CompanyProfile | None = None) -> str:
    """Render a complete ReportData as a Markdown document.

    repo/profile are optional and only needed to resolve human-readable
    citations — without them, findings render with no Source line rather
    than a raw evidence_id (never expose the internal identifier to a reader).
    """
    lines = [f"# {report.title}", ""]
    for section in report.sections:
        lines.extend(_render_section(section, report.ticker, repo, profile))
    return "\n".join(lines).rstrip() + "\n"
