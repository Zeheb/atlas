"""Rule-based fact extraction from parsed annual report text.

Extracts durable structured facts and verbatim excerpts from one annual
report document. Does not compare across documents — cross-document
reasoning belongs in a future Facts layer.

Section detection uses a TOC-skip strategy: a pattern match is only
accepted if at least _MIN_SECTION_CONTENT chars of substantive text
follow it, filtering out table-of-contents entries that match the same
header keyword but are followed only by a page number.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
    _snip,
)
from atlas.analysis.patterns import fiscal_year_end
from atlas.knowledge.base import KnowledgeBase

ANALYZER_VERSION = "2.0"

# ---------------------------------------------------------------------------
# Extraction configuration
# ---------------------------------------------------------------------------

_SECTION_CHARS = 4_000      # chars to capture after a section header match
_MIN_SECTION_CONTENT = 200  # minimum chars to accept a match as a real section

# ---------------------------------------------------------------------------
# Section header patterns
# ---------------------------------------------------------------------------

_RE_BUSINESS_OVERVIEW = re.compile(
    r"^(?:Business Overview|About TCS|Company Overview|Our Business)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_RE_MANAGEMENT = re.compile(
    r"(?:"
    r"^Letter from the\n?Chairman"
    r"|^Chairman['']?s?\s+(?:Letter|Message|Statement|Review)"
    r"|^Directors['']?\s+Report"
    r"|^Management Discussion and Analysis"
    r"|^CEO['']?s?\s+(?:Letter|Message)"
    r"|Dear Shareholders?[,.]"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

_RE_CAPITAL_ALLOCATION = re.compile(
    r"(?:"
    r"capital\s+allocation\s+policy"
    r"|^Capital\s+Allocation\s*$"
    r"|^Dividend(?:s)?\s*$"
    r"|recommended\s+a\s+(?:final|interim)\s+dividend"
    r"|buyback\s+program"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

_RE_RISKS = re.compile(
    r"(?:"
    r"^Risk\s+Factors?\s*$"
    r"|^Key\s+Risks?\s*$"
    r"|^Principal\s+Risks?\s*$"
    r"|^Material\s+Risks?\s*$"
    r"|^Risk\s+Management\s*$"
    r"|^Risks\s+and\s+Concerns?\s*$"
    r"|^Enterprise\s+Risk(?:\s+Management)?\s*$"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

_RE_SEGMENT_PARAGRAPH = re.compile(
    r"(?i)Among the Business Segments?[,\s]+(.*?)(?=\n\n|\. Among|\. The company)",
    re.DOTALL,
)

_RE_SEGMENT_ENTRY = re.compile(
    r"([\w,\s&]+?)\s+grew\s+[\d.]+%",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Internal extraction helpers
# (These are the stable extraction core — no output-type dependency.)
# ---------------------------------------------------------------------------


def _find_section(
    text: str, pattern: re.Pattern[str]
) -> tuple[str, int] | None:
    """Return (excerpt, match_char_offset) for the first substantial match.

    Skips TOC entries by requiring at least _MIN_SECTION_CONTENT chars of
    following text. Returns None if no qualifying match is found.
    """
    for m in pattern.finditer(text):
        start = m.end()
        excerpt = text[start : start + _SECTION_CHARS].strip()
        if len(excerpt) >= _MIN_SECTION_CONTENT:
            return excerpt, m.start()
    return None


def _extract_section(text: str, pattern: re.Pattern[str]) -> str | None:
    """Return section text or None. Backward-compatible wrapper around _find_section."""
    result = _find_section(text, pattern)
    return result[0] if result is not None else None


def _extract_list_items(text: str) -> list[str]:
    """Parse bullet-point or numbered items from section text."""
    items: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        m = re.match(
            r"^(?:\d+[\.\)]\s+|[•●▪■\-\*]\s*|[a-zA-Z][\.\)]\s+)(.+)", line
        )
        if m:
            item = m.group(1).strip()
            if 5 <= len(item) <= 200:
                items.append(item)
    return items


def _extract_segments(text: str) -> list[str]:
    """Extract business segment names from the 'Among the Business Segments' paragraph."""
    m = _RE_SEGMENT_PARAGRAPH.search(text)
    if m:
        paragraph = m.group(1)
        segments = [
            entry.group(1).strip().rstrip(",")
            for entry in _RE_SEGMENT_ENTRY.finditer(paragraph)
        ]
        if segments:
            return segments

    section = _extract_section(
        text,
        re.compile(
            r"^(?:Business\s+Segments?|Service\s+Lines?|Industry\s+Verticals?|Reportable\s+Segments?)\s*$",
            re.IGNORECASE | re.MULTILINE,
        ),
    )
    return _extract_list_items(section) if section else []


def _extract_risks(text: str) -> list[str]:
    """Extract risk factor names from the risk section."""
    section = _extract_section(text, _RE_RISKS)
    if not section:
        return []
    items = _extract_list_items(section)
    if items:
        return items[:10]
    headings: list[str] = []
    for line in section.split("\n"):
        line = line.strip()
        words = line.split()
        if (
            5 < len(line) < 100
            and len(words) >= 2
            and any(w[0].isupper() for w in words if w[0].isalpha())
        ):
            headings.append(line)
            if len(headings) >= 10:
                break
    return headings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def summarize(
    evidence_id: str,
    kb: KnowledgeBase,
) -> AnalysisResult:
    """Extract structured facts and verbatim excerpts from a parsed annual report.

    Returns AnalysisResult. Raises KeyError if evidence_id is not recorded
    in the knowledge base; raises ValueError if the document failed to parse.
    """
    doc = kb.get(evidence_id)
    if doc is None:
        raise KeyError(evidence_id)
    if doc.status != "ok" or not doc.char_count:
        raise ValueError(
            f"{evidence_id}: cannot analyze — "
            f"status={doc.status!r}, char_count={doc.char_count}"
        )
    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(f"{evidence_id}: content unavailable")

    period = fiscal_year_end(doc.source_date)
    facts: list[AnalysisFact] = []
    excerpts: dict[str, str] = {}
    warnings: list[str] = []

    # --- Business segments ---
    seg_match = _RE_SEGMENT_PARAGRAPH.search(content)
    segment_names = _extract_segments(content)
    seg_offset = seg_match.start() if seg_match is not None else None
    seg_snip = _snip(content, seg_offset) if seg_offset is not None else None

    for name in segment_names:
        facts.append(
            AnalysisFact(
                kind=FactKind.SEGMENT_NAME,
                value=name,
                unit=None,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="segment_paragraph",
                    char_offset=seg_offset,
                    excerpt=seg_snip,
                ),
            )
        )
    if not segment_names:
        warnings.append("No business segments extracted")

    # --- Risk factors ---
    risk_result = _find_section(content, _RE_RISKS)
    major_risks = _extract_risks(content)

    if risk_result is not None:
        _, risk_offset = risk_result
        risk_snip = _snip(content, risk_offset)
        risk_conf: Literal["high", "medium", "low"] = "medium"
    else:
        risk_offset = None
        risk_snip = None
        risk_conf = "low"

    for risk in major_risks:
        facts.append(
            AnalysisFact(
                kind=FactKind.RISK_FACTOR,
                value=risk,
                unit=None,
                period=period,
                confidence=risk_conf,
                provenance=Provenance(
                    section="risk_section",
                    char_offset=risk_offset,
                    excerpt=risk_snip,
                ),
            )
        )
    if not major_risks:
        warnings.append("No risk factors extracted")

    # --- Verbatim excerpts ---
    biz_result = _find_section(content, _RE_BUSINESS_OVERVIEW)
    if biz_result:
        excerpts["business_overview"] = biz_result[0]
    else:
        warnings.append("Business overview section not found")

    mgmt_result = _find_section(content, _RE_MANAGEMENT)
    if mgmt_result:
        excerpts["management_commentary"] = mgmt_result[0]
    else:
        warnings.append("Management commentary not found")

    cap_result = _find_section(content, _RE_CAPITAL_ALLOCATION)
    if cap_result:
        excerpts["capital_allocation"] = cap_result[0]
    else:
        warnings.append("Capital allocation section not found")

    # --- Result-level confidence ---
    key_excerpts = sum(
        1 for k in ("business_overview", "management_commentary") if k in excerpts
    )
    has_segments = len(segment_names) >= 2
    if key_excerpts == 2 and has_segments:
        result_confidence: Literal["high", "medium", "low"] = "high"
    elif key_excerpts >= 1 or has_segments:
        result_confidence = "medium"
    else:
        result_confidence = "low"

    return AnalysisResult(
        evidence_id=evidence_id,
        kind=doc.kind,
        analyzer_version=ANALYZER_VERSION,
        confidence=result_confidence,
        source_date=datetime.fromisoformat(doc.source_date),
        warnings=warnings,
        facts=facts,
        excerpts=excerpts,
    )
