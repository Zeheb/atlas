"""Atlas Research — deterministic report generation from CompanyProfile.

Public API: generate_report() assembles a full evidence-first investment
briefing (see docs/architecture/research_engine.md for the design). Finding/
render_finding/render_report are re-exported unchanged from citations.py for
backward compatibility with existing callers.
"""

from __future__ import annotations

from atlas.research.citations import Finding, render_finding, render_report
from atlas.research.report import generate_report

__all__ = [
    "Finding",
    "render_finding",
    "render_report",
    "generate_report",
]
