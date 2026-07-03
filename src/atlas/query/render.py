"""Text table renderer for QueryResult objects.

Produces a plain-text output suitable for terminal display.
Tests should inspect QueryResult.sections directly — this module is for CLI use only.
"""
from __future__ import annotations

from atlas.query.engine import QueryResult, TableSection


def _render_section(section: TableSection) -> list[str]:
    if not section.rows:
        return []

    lines: list[str] = []
    lines.append(f"\n{section.heading}")
    lines.append("-" * len(section.heading))

    all_rows = [section.columns] + section.rows
    col_widths = [
        max(len(str(row[i])) for row in all_rows)
        for i in range(len(section.columns))
    ]

    def _pad_row(row: list[str]) -> str:
        return "  ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row))

    lines.append(_pad_row(section.columns))
    lines.append("  ".join("-" * w for w in col_widths))
    for row in section.rows:
        lines.append(_pad_row(row))

    return lines


def render_result(result: QueryResult) -> str:
    """Format a QueryResult as a plain-text table string."""
    lines: list[str] = []

    header = f"{result.title}  [{result.company_id}]"
    lines.append(header)
    lines.append("=" * len(header))

    if result.is_empty():
        lines.append("(no data)")
    else:
        for section in result.sections:
            lines.extend(_render_section(section))

    if result.notes:
        lines.append("\nNotes:")
        for note in result.notes:
            lines.append(f"  * {note}")

    return "\n".join(lines)
