"""Rule-based fact extraction from investor presentation filings.

Investor presentation filings cover two distinct sub-types:

  strategy:     Actual slide decks (e.g., TCS Analyst Day 2025). Long documents
                (10,000+ chars) with strategic vision, transformation pillars,
                financial history, and operating metrics.

  ir_activity:  Short administrative filings (1,000-7,000 chars) covering
                analyst/institutional investor meeting schedules (Reg-30) and
                embedded earnings call announcement notices.

Fact vocabulary
---------------
STRATEGY_ASPIRATION     Company-level strategic vision statement; unit=None
STRATEGY_PRIORITY       Transformation pillar (one fact per pillar; unit=None)
STRATEGY_GUIDANCE       Long-term margin target as a range text (e.g. "26-28%"); unit=None
STRATEGY_CSAT           Customer satisfaction score, most recent half-year; unit=PERCENT
SEGMENT_NAME            Service line or practice name (one per fact; unit=None)
SEGMENT_GROWTH_PCT      YoY constant-currency growth rate per service line; unit=PERCENT
FINANCIAL_ROE           Return on equity per fiscal year; unit=PERCENT
FINANCIAL_FCF           Free cash flow after investments per fiscal year; unit=CRORE_INR
REPORT_PERIOD_END       Quarter end date (ir_activity only); unit=ISO_DATE
REPORT_PERIOD_TYPE      "quarterly" (ir_activity only)

Period conventions
------------------
STRATEGY_ASPIRATION, STRATEGY_PRIORITY, STRATEGY_GUIDANCE, SEGMENT_*: period=None
STRATEGY_CSAT: period = half-year end ISO date (e.g. "2025-09-30" for H1 FY26)
FINANCIAL_ROE, FINANCIAL_FCF: period = fiscal year end ISO date ("{YYYY}-03-31")
REPORT_PERIOD_END (ir_activity): ISO date of the quarter being reported

Excerpts
--------
subtype          Detected sub-type string ("strategy" or "ir_activity")
aspiration       Text window around the aspiration statement
margin_levers    Margin Levers slide section (strategy only)
"""
from __future__ import annotations

import re
from datetime import datetime

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.knowledge.base import KnowledgeBase

ANALYZER_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Month name map (shared by both paths)
# ---------------------------------------------------------------------------

_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _parse_date(date_str: str) -> str | None:
    """Parse 'September 30, 2024' or 'September 30 2024' → '2024-09-30'."""
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})", date_str.strip())
    if not m:
        return None
    month = _MONTH_MAP.get(m.group(1).lower())
    if not month:
        return None
    return f"{m.group(3)}-{month}-{m.group(2).zfill(2)}"


def _half_year_period(label: str) -> str | None:
    """Convert 'H1 FY26' → '2025-09-30', 'H2 FY23' → '2023-03-31'.

    Indian fiscal year FY26 = April 2025 – March 2026.
    H1 ends September 30 of (FY year - 1).
    H2 ends March 31 of FY year.
    """
    m = re.match(r"H([12])\s*FY(\d{2})", label.strip())
    if not m:
        return None
    half = int(m.group(1))
    fy_year = 2000 + int(m.group(2))
    if half == 1:
        return f"{fy_year - 1}-09-30"
    return f"{fy_year}-03-31"


# ---------------------------------------------------------------------------
# Sub-type detection
# ---------------------------------------------------------------------------

_RE_STRATEGY_MARKER = re.compile(
    r"Analyst\s+Day|presentation\s+to\s+be\s+made",
    re.I,
)


def _detect_subtype(content: str) -> str:
    """Return 'strategy' for actual slide decks, 'ir_activity' for all others.

    Detection is based on the first 3000 chars (the BSE cover letter).
    Strategy decks carry 'Analyst Day' or 'presentation to be made' in the
    subject line; IR schedule and earnings announcement filings do not.
    """
    if _RE_STRATEGY_MARKER.search(content[:3000]):
        return "strategy"
    return "ir_activity"


# ---------------------------------------------------------------------------
# Shared fact constructor
# ---------------------------------------------------------------------------

def _pf(
    kind: FactKind,
    value: str | float | int | None,
    unit: FactUnit | None,
    period: str | None,
    section: str,
    offset: int,
    excerpt: str = "",
) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence="high",
        provenance=Provenance(
            section=section,
            char_offset=offset,
            excerpt=excerpt[:120] if excerpt else None,
        ),
    )


# ---------------------------------------------------------------------------
# Strategy path — extraction patterns
# ---------------------------------------------------------------------------

_RE_ASPIRATION = re.compile(
    r"We will be the world.s largest\s+AI-led Technology Services company",
    re.I,
)

# Five canonical transformation pillars as they appear in slide deck text.
_PILLAR_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"tcsAI\s+Internal\s+Transformation", re.I), "tcsAI Internal Transformation"),
    (re.compile(r"Redefining\s+all\s+Services", re.I), "Redefining all Services"),
    (re.compile(r"Future.ready\s+Talent\s+Model", re.I), "Future-ready Talent Model"),
    (re.compile(r"Making\s+AI\s+Real\s+for\s+clients", re.I), "Making AI Real for clients"),
    (re.compile(r"AI\s+Ecosystem\s+Play", re.I), "AI Ecosystem Play"),
]

# "Margin Levers" slide: captures the guidance range (e.g. "26-28") before "%".
_RE_MARGIN_LEVERS = re.compile(
    r"Margin\s+Levers\n(.{0,800}?)(\d{2,3}-\d{2,3})\s*%",
    re.DOTALL,
)

# Service line growth: "38.2%\nY-O-Y CC\nAI Services"
_RE_SERVICE_GROWTH = re.compile(
    r"([\d.]+)%\s*\nY-O-Y\s+CC\s*\n([^\n]+)",
)

# ROE bar chart: years listed then percentages (PDF column ordering).
_RE_ROE_BLOCK = re.compile(
    r"Return on Equity\n(.+?)Industry Leading RoE",
    re.DOTALL,
)

# Capital allocation / FCF bar chart.
_RE_FCF_BLOCK = re.compile(
    r"Capital Allocation\n(.+?)Free cashflow after all investments",
    re.DOTALL,
)

_RE_CSAT_MARKER = re.compile(r"Customer Satisfaction Score")
_RE_CSAT_VALUE  = re.compile(r"(\d{2}\.\d{2})%")
_RE_CSAT_PERIOD = re.compile(r"(H[12]\s+FY\d{2})")

_RE_FY_YEAR  = re.compile(r"FY\s+(\d{4})\b")
_RE_ROE_PCT  = re.compile(r"(\d{2,3}\.\d+)%")
# FCF values: 5-digit comma-separated crore amounts (e.g. "30,664").
_RE_FCF_VAL  = re.compile(r"\b(\d{2,3}),(\d{3})\b")


def _extract_strategy_facts(content: str, result: AnalysisResult) -> None:
    """Extract all strategy-path facts from an Analyst Day slide deck."""

    # 1. Strategic aspiration statement
    m = _RE_ASPIRATION.search(content)
    if m:
        value = m.group(0).replace("\n", " ").strip()
        result.facts.append(_pf(
            FactKind.STRATEGY_ASPIRATION, value, None, None,
            "aspiration", m.start(), value,
        ))
        result.excerpts["aspiration"] = content[
            max(0, m.start() - 80) : m.end() + 200
        ]
    else:
        result.warnings.append("Strategic aspiration statement not found")

    # 2. Transformation pillars — one STRATEGY_PRIORITY per unique pillar
    for pattern, canonical in _PILLAR_PATTERNS:
        m = pattern.search(content)
        if m:
            result.facts.append(_pf(
                FactKind.STRATEGY_PRIORITY, canonical, None, None,
                "pillars", m.start(), m.group(0),
            ))

    # 3. Long-term margin guidance from "Margin Levers" slide
    m = _RE_MARGIN_LEVERS.search(content)
    if m:
        guidance = f"{m.group(2)}%"
        result.facts.append(_pf(
            FactKind.STRATEGY_GUIDANCE, guidance, None, None,
            "margin_levers", m.start(), m.group(0)[:80],
        ))
        result.excerpts["margin_levers"] = m.group(0)[:500]

    # 4. Service line growth rates — SEGMENT_NAME + SEGMENT_GROWTH_PCT pairs
    seen_segments: set[str] = set()
    for m in _RE_SERVICE_GROWTH.finditer(content):
        seg_name = m.group(2).strip()
        if seg_name in seen_segments:
            continue
        seen_segments.add(seg_name)
        pct_val = float(m.group(1))
        result.facts.append(_pf(
            FactKind.SEGMENT_NAME, seg_name, None, None,
            "service_growth", m.start(), m.group(0),
        ))
        result.facts.append(_pf(
            FactKind.SEGMENT_GROWTH_PCT, pct_val, FactUnit.PERCENT, None,
            "service_growth", m.start(), m.group(0),
        ))

    # 5. Return on Equity — multi-year from bar chart section
    m_block = _RE_ROE_BLOCK.search(content)
    if m_block:
        block = m_block.group(1)
        years = _RE_FY_YEAR.findall(block)
        pcts  = _RE_ROE_PCT.findall(block)
        for year, pct_str in zip(years, pcts):
            result.facts.append(_pf(
                FactKind.FINANCIAL_ROE, float(pct_str), FactUnit.PERCENT,
                f"{year}-03-31", "roe", m_block.start(), f"FY {year}: {pct_str}%",
            ))
    else:
        result.warnings.append("ROE section not found")

    # 6. Free Cash Flow — multi-year from Capital Allocation section
    m_block = _RE_FCF_BLOCK.search(content)
    if m_block:
        block = m_block.group(1)
        years  = _RE_FY_YEAR.findall(block)
        # Each match is (thousands, hundreds) e.g. ("30", "664") → 30664
        fcf_pairs = _RE_FCF_VAL.findall(block)
        fcf_vals  = [int(a + b) for a, b in fcf_pairs]
        for year, fcf_val in zip(years, fcf_vals):
            result.facts.append(_pf(
                FactKind.FINANCIAL_FCF, fcf_val, FactUnit.CRORE_INR,
                f"{year}-03-31", "fcf", m_block.start(), f"FY {year}: ₹{fcf_val} cr",
            ))
    else:
        result.warnings.append("Capital Allocation / FCF section not found")

    # 7. Customer Satisfaction Score — most recent half-year value
    m_marker = _RE_CSAT_MARKER.search(content)
    if m_marker:
        preceding = content[max(0, m_marker.start() - 1200) : m_marker.start()]
        csat_vals    = _RE_CSAT_VALUE.findall(preceding)
        csat_periods = _RE_CSAT_PERIOD.findall(preceding)
        pairs = list(zip(csat_vals, csat_periods))
        if pairs:
            latest_val, latest_label = pairs[-1]
            period = _half_year_period(latest_label)
            result.facts.append(_pf(
                FactKind.STRATEGY_CSAT, float(latest_val), FactUnit.PERCENT,
                period, "csat", m_marker.start(),
                f"CSAT {latest_val}% {latest_label}",
            ))
    else:
        result.warnings.append("Customer Satisfaction Score section not found")


# ---------------------------------------------------------------------------
# IR activity path — extraction patterns
# ---------------------------------------------------------------------------

_RE_QUARTER_END = re.compile(
    r"Quarter\s+[Ee]nded\s+([A-Z][a-z]+\s+\d{1,2},?\s*\d{4})",
)


def _extract_ir_activity_facts(content: str, result: AnalysisResult) -> None:
    """Extract period facts from an IR activity / earnings announcement filing.

    Content is first normalized (newlines → spaces) so that period dates
    split across lines (a common PDF extraction artefact) are matched.
    """
    normalized = re.sub(r"\s+", " ", content)
    m = _RE_QUARTER_END.search(normalized)
    if m:
        date_str = m.group(1).strip()
        period = _parse_date(date_str)
        if period:
            result.facts.append(_pf(
                FactKind.REPORT_PERIOD_END, period, FactUnit.ISO_DATE,
                period, "earnings_announcement", m.start(), m.group(0),
            ))
            result.facts.append(_pf(
                FactKind.REPORT_PERIOD_TYPE, "quarterly", None,
                period, "earnings_announcement", m.start(), "quarterly",
            ))
        else:
            result.warnings.append(
                f"Could not parse quarter-end date: {date_str!r}"
            )
    else:
        result.warnings.append(
            "Quarter end date not found in IR activity filing"
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured facts from an investor presentation filing.

    Raises ValueError for missing, wrong-kind, or empty-content documents.
    """
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    if entry.kind != "investor_presentation":
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: "
            f"kind={entry.kind!r} is not 'investor_presentation'"
        )

    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: document has no content"
        )

    content = content.replace("ﬁ", "fi").replace("ﬂ", "fl")

    subtype = _detect_subtype(content)

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="investor_presentation",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=datetime.fromisoformat(entry.source_date),
    )
    result.excerpts["subtype"] = subtype

    if subtype == "strategy":
        _extract_strategy_facts(content, result)
        has_aspiration = any(f.kind == FactKind.STRATEGY_ASPIRATION for f in result.facts)
        has_roe        = any(f.kind == FactKind.FINANCIAL_ROE for f in result.facts)
        has_csat       = any(f.kind == FactKind.STRATEGY_CSAT for f in result.facts)
        if has_aspiration and has_roe and has_csat:
            result.confidence = "high"
        elif has_aspiration:
            result.confidence = "medium"
    else:
        _extract_ir_activity_facts(content, result)
        has_period = any(f.kind == FactKind.REPORT_PERIOD_END for f in result.facts)
        result.confidence = "high" if has_period else "medium"

    return result
