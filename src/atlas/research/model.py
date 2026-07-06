"""Structured, render-agnostic report data.

ReportSection carries everything a section wants to say, but never a
Markdown (or any other) string — that translation belongs entirely to
render.py. A section builder that finds itself formatting text should
reach for one of these three shapes instead:

  findings   narrative bullets, each optionally backed by evidence_ids
             (rendered as prose + a citation line)
  tables     reuses query.engine.TableSection as-is — already a clean,
             renderer-agnostic heading/columns/rows shape; no reason to
             invent a second one
  notes      uncited, short methodology/absence notes ("no data found for
             X"), rendered plainly, no citation line expected
"""
from __future__ import annotations

from dataclasses import dataclass, field

from atlas.query.engine import TableSection
from atlas.research.citations import Finding


@dataclass
class ReportSection:
    key: str
    title: str
    findings: list[Finding] = field(default_factory=list)
    tables: list[TableSection] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.findings and not any(t.rows for t in self.tables) and not self.notes


@dataclass
class ReportData:
    ticker: str
    title: str
    sections: list[ReportSection] = field(default_factory=list)

    def section(self, key: str) -> ReportSection | None:
        for s in self.sections:
            if s.key == key:
                return s
        return None
