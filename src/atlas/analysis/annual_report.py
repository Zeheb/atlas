"""Rule-based structured extraction from parsed annual report text.

Sections are detected by keyword patterns. All text fields are verbatim
excerpts — not paraphrases. If a section header is absent from the
extracted text the corresponding field is None or empty.

Year-on-year comparison requires two evidence IDs from the same company;
the caller selects them using Repository.list_evidence() and passes them here.
The analysis layer only reads from KnowledgeBase — it never touches the
acquisition layer or raw files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from atlas.knowledge.base import KnowledgeBase

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Characters extracted after a detected section header.
_SECTION_CHARS = 4_000

# Minimum following content to accept a header match as a real section
# (not a table-of-contents reference, which has only a page number after it).
_MIN_SECTION_CONTENT = 200

# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


@dataclass
class AnnualReportSummary:
    """Structured text extractions from one annual report.

    `business_overview`, `management_commentary`, and `capital_allocation`
    are verbatim excerpts. `segments` and `major_risks` are lists parsed
    from section text. `year_on_year_changes` lists detected metric shifts
    vs. `previous_evidence_id`; empty when no previous report is supplied.
    """

    evidence_id: str
    title: str
    source_date: str
    char_count: int

    business_overview: str | None
    management_commentary: str | None
    capital_allocation: str | None

    segments: list[str]
    major_risks: list[str]
    year_on_year_changes: list[str]

    extracted_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Section header patterns
# (re.MULTILINE makes ^ / $ match at line boundaries, not just string edges)
# ---------------------------------------------------------------------------

_RE_BUSINESS_OVERVIEW = re.compile(
    r"^(?:Business Overview|About TCS|Company Overview|Our Business)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_RE_MANAGEMENT = re.compile(
    r"(?:"
    r"^Letter from the\n?Chairman"
    r"|^Chairman['’]?s?\s+(?:Letter|Message|Statement|Review)"
    r"|^Directors['’]?\s+Report"
    r"|^Management Discussion and Analysis"
    r"|^CEO['’]?s?\s+(?:Letter|Message)"
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

# Used to find the segment growth paragraph (e.g. "Among the Business Segments, X grew Y%...")
_RE_SEGMENT_PARAGRAPH = re.compile(
    r"(?i)Among the Business Segments?[,\s]+(.*?)(?=\n\n|\. Among|\. The company)",
    re.DOTALL,
)

# Captures segment name before "grew X%"
_RE_SEGMENT_ENTRY = re.compile(
    r"([\w,\s&]+?)\s+grew\s+[\d.]+%",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Financial metric patterns for year-on-year comparison
# ---------------------------------------------------------------------------

_RE_REVENUE = re.compile(
    r"(?:total\s+)?(?:revenues?\s+of|income\s+from\s+operations)\s*"
    r"(?:[₹\?]|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)\s*(?:crore|cr\.?)",
    re.IGNORECASE,
)

_RE_NET_INCOME = re.compile(
    r"(?:net\s+(?:income|profit)|profit\s+after\s+tax|pat)\s*"
    r"(?:of|was|stood\s+at)?\s*"
    r"(?:[₹\?]|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)\s*(?:crore|cr\.?)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def summarize(
    evidence_id: str,
    kb: KnowledgeBase,
    *,
    previous_evidence_id: str | None = None,
) -> AnnualReportSummary:
    """Extract a structured summary from a parsed annual report.

    Raises:
        KeyError: evidence_id is not recorded in the knowledge base.
        ValueError: the document failed to parse or yielded no text.
    """
    doc = kb.get(evidence_id)
    if doc is None:
        raise KeyError(evidence_id)
    if doc.status != "ok" or not doc.char_count:
        raise ValueError(
            f"{evidence_id}: cannot summarize — "
            f"status={doc.status!r}, char_count={doc.char_count}"
        )

    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(f"{evidence_id}: content unavailable")

    yoy: list[str] = []
    if previous_evidence_id is not None:
        prev_content = kb.get_content(previous_evidence_id)
        if prev_content:
            yoy = _compare(content, prev_content)

    return AnnualReportSummary(
        evidence_id=evidence_id,
        title=doc.title,
        source_date=doc.source_date,
        char_count=doc.char_count,
        business_overview=_extract_section(content, _RE_BUSINESS_OVERVIEW),
        management_commentary=_extract_section(content, _RE_MANAGEMENT),
        capital_allocation=_extract_section(content, _RE_CAPITAL_ALLOCATION),
        segments=_extract_segments(content),
        major_risks=_extract_risks(content),
        year_on_year_changes=yoy,
    )


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _extract_section(text: str, pattern: re.Pattern[str]) -> str | None:
    """Return text after the first pattern match that has substantial content.

    Skips table-of-contents references (followed only by a page number) by
    requiring at least _MIN_SECTION_CONTENT chars of following text.
    """
    for m in pattern.finditer(text):
        start = m.end()
        excerpt = text[start : start + _SECTION_CHARS].strip()
        if len(excerpt) >= _MIN_SECTION_CONTENT:
            return excerpt
    return None


def _extract_list_items(text: str) -> list[str]:
    """Parse bullet-point or numbered items from text."""
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

    # Fall back: look for a section header then parse list items.
    section = _extract_section(text, re.compile(
        r"^(?:Business\s+Segments?|Service\s+Lines?|Industry\s+Verticals?|Reportable\s+Segments?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ))
    return _extract_list_items(section) if section else []


def _extract_risks(text: str) -> list[str]:
    """Extract risk factor names from the risk section."""
    section = _extract_section(text, _RE_RISKS)
    if not section:
        return []
    items = _extract_list_items(section)
    if items:
        return items[:10]
    # If no bullet/numbered list found, look for short title-like lines.
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


def _extract_number(text: str, pattern: re.Pattern[str]) -> float | None:
    """Return the first number matched by pattern, or None."""
    m = pattern.search(text)
    if m is None:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _compare(current: str, previous: str) -> list[str]:
    """Produce a list of detected metric changes between two report texts."""
    changes: list[str] = []

    curr_rev = _extract_number(current, _RE_REVENUE)
    prev_rev = _extract_number(previous, _RE_REVENUE)
    if curr_rev is not None and prev_rev is not None and prev_rev != 0:
        pct = (curr_rev - prev_rev) / prev_rev * 100
        verb = "grew" if pct >= 0 else "declined"
        changes.append(
            f"Revenue {verb} {abs(pct):.1f}% YoY "
            f"(current ₹{curr_rev:,.0f} cr, prior ₹{prev_rev:,.0f} cr)"
        )

    curr_ni = _extract_number(current, _RE_NET_INCOME)
    prev_ni = _extract_number(previous, _RE_NET_INCOME)
    if curr_ni is not None and prev_ni is not None and prev_ni != 0:
        pct = (curr_ni - prev_ni) / prev_ni * 100
        verb = "grew" if pct >= 0 else "declined"
        changes.append(
            f"Net income {verb} {abs(pct):.1f}% YoY "
            f"(current ₹{curr_ni:,.0f} cr, prior ₹{prev_ni:,.0f} cr)"
        )

    return changes
