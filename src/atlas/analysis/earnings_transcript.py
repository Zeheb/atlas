"""Rule-based fact extraction from earnings call transcripts.

Earnings call transcripts are SEBI Reg-30 disclosures filed after quarterly
Board of Directors meetings. The PDF contains:

  1. Cover letter — Reg-30 filing header, addresses to NSE/BSE, ~1 page.
  2. Transcript body:
       Moderator introduction
       Nehal Shah (IR Head) — participant introductions + disclaimer
       K Krithivasan (CEO) — five key messages (revenue growth, TCV, clients)
       Samir Seksaria (CFO) — quarterly + annual P&L, margins, cash flow
       Aarthi Subramanian (COO) — operational highlights (when present)
       [CHRO] — headcount / talent commentary (when present)
       Q&A — analyst questions and management answers

Fact vocabulary
---------------
FINANCIAL_REVENUE           Quarterly revenue (CRORE_INR or USD_BILLION)
                            Annual revenue is also emitted for Q4 calls.
FINANCIAL_TCV               Total Contract Value; USD_BILLION; quarterly only.
                            Not in XBRL — uniquely available from transcript.
FINANCIAL_OPERATING_MARGIN  Operating margin %; PERCENT.
FINANCIAL_NET_MARGIN        Net income margin %; PERCENT.
REPORT_PERIOD_END           Quarter / fiscal-year end date; unit=ISO_DATE.
REPORT_PERIOD_TYPE          "quarterly" | "annual"; unit=None.

Period convention
-----------------
All facts carry period = the quarter-end date (e.g. "2026-03-31").
For Q4 calls that report full-year metrics, annual facts are emitted with the
same period date but REPORT_PERIOD_TYPE = "annual".

CFO section structure
---------------------
Q4 transcripts report both quarterly and annual figures.  The order varies:
  FY26+ style: quarterly first ("In the fourth quarter..."), then annual
               ("Coming to the full year FY26...").
  FY25 style:  annual first ("I will start with the full year's numbers..."),
               then quarterly ("Coming to Q4...").

Both are handled by detecting which boundary marker appears first in the
CFO section and splitting accordingly.

Excerpts
--------
ceo_commentary   CEO opening remarks (first substantive block)
cfo_commentary   CFO financial section
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
# Period extraction
# ---------------------------------------------------------------------------

_RE_PERIOD = re.compile(
    r"(?:quarter|half)(?:[^.]{0,120}?)ended\s+([A-Z][a-z]+\s+\d{1,2},?\s*\d{4})",
    re.I,
)

_RE_IS_ANNUAL = re.compile(
    r"quarter\s+and\s+(?:year|full\s+year|annual|year\s+period)",
    re.I,
)

_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _parse_period_date(date_str: str) -> str | None:
    """Parse 'March 31, 2026' or 'March 31 2026' → '2026-03-31'."""
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})", date_str.strip())
    if not m:
        return None
    month = _MONTH_MAP.get(m.group(1).lower())
    if not month:
        return None
    return f"{m.group(3)}-{month}-{m.group(2).zfill(2)}"


# ---------------------------------------------------------------------------
# Revenue patterns (tolerant of varying phrasing across transcript vintages)
# ---------------------------------------------------------------------------

# "our revenue was ₹70,698 crore" (FY26) or "reaching ₹64,479" (FY25, no 'crore')
_RE_REVENUE_INR = re.compile(
    r"₹\s*([\d,]+)(?:\s*(?:crore|cr\.?))?\b",
    re.I,
)

# "revenue was $7.621 billion" or "our dollar revenues were at 7.47 billion"
_RE_REVENUE_USD = re.compile(
    r"revenue\s+was\s+\$([\d.]+)\s*billion"
    r"|dollar\s+revenues?\s+(?:were|was)\s+(?:at\s+)\$?([\d.]+)\s*billion",
    re.I,
)

# ---------------------------------------------------------------------------
# Margin patterns — verb-based to avoid digit confusion from context words
# ---------------------------------------------------------------------------

# "operating margin stood at 25.3%" / "operating margin was 25%"
# / "operating margin was at 24.3%" (FY25 annual phrasing uses "was at")
_RE_OP_MARGIN = re.compile(
    r"operating\s+margin\s+(?:stood\s+at|was\s+(?:at\s+)?|of)\s*([\d]+\.?\d*)\s*%",
    re.I,
)

# "Net margins for Q4 were 19.4%" / "Net margins in Q4 were 19%"
# / "Net margins for FY26 were 19.8%" / "net income margin was 19.6%"
# Uses [^\n]{0,40}? (lazy, no newline) to skip over context words that may
# contain digits (e.g. "Q4", "FY26", "FY '25") without digit-stopping issues.
_RE_NET_MARGIN = re.compile(
    r"(?:net\s+(?:income\s+)?margin|net\s+margins)"
    r"[^\n]{0,40}?"
    r"(?:were|was|stood\s+at)\s+"
    r"([\d]+\.?\d*)\s*%",
    re.I,
)

# ---------------------------------------------------------------------------
# TCV pattern
# ---------------------------------------------------------------------------

# "TCV of $12 billion" or "$10 billion in TCV"
_RE_TCV = re.compile(
    r"TCV\s+(?:of\s+)?\$([\d.]+)\s*billion"
    r"|\$([\d.]+)\s*billion\s+in\s+TCV",
    re.I,
)

# ---------------------------------------------------------------------------
# CFO section split boundaries
# Handles both FY26 (quarterly-first) and FY25 (annual-first) ordering.
# ---------------------------------------------------------------------------

# Marks the start of the ANNUAL commentary block
_RE_ANNUAL_BOUNDARY = re.compile(
    r"coming\s+to\s+(?:the\s+)?full\s+year"
    r"|for\s+fy\s*'?\d{2,4}[,.]"   # "For FY26," or "For FY '25,"
    r"|full\s+year\s+fy",
    re.I,
)

# Marks the start of the QUARTERLY commentary block (in annual-first transcripts)
_RE_QUARTERLY_BOUNDARY = re.compile(
    r"coming\s+to\s+Q\d"
    r"|coming\s+to\s+the\s+(?:fourth|third|second|first)\s+quarter",
    re.I,
)


def _split_cfo_sections(cfo_text: str) -> tuple[str, str]:
    """Return (quarterly_text, annual_text) by detecting the section order.

    If neither boundary is found, the entire text is treated as quarterly
    (appropriate for Q1/Q2/Q3 mid-year calls).
    """
    m_ann = _RE_ANNUAL_BOUNDARY.search(cfo_text)
    m_qtr = _RE_QUARTERLY_BOUNDARY.search(cfo_text)

    if m_ann and m_qtr:
        # Both markers present; determine which comes first
        if m_ann.start() < m_qtr.start():
            # Annual section first (unusual), quarterly follows
            return cfo_text[m_qtr.start():], cfo_text[:m_qtr.start()]
        else:
            # Quarterly section first (FY26 style), annual follows
            return cfo_text[:m_ann.start()], cfo_text[m_ann.start():]
    elif m_ann:
        # Only annual boundary found: FY26 style (quarterly first)
        return cfo_text[:m_ann.start()], cfo_text[m_ann.start():]
    elif m_qtr:
        # Only quarterly boundary found: FY25 style (annual first)
        # Text before "Coming to Q4" is the annual section
        return cfo_text[m_qtr.start():], cfo_text[:m_qtr.start()]
    else:
        # No split boundary — mid-year call (Q1/Q2/Q3)
        return cfo_text, ""


# ---------------------------------------------------------------------------
# Speaker / section extraction helpers
# ---------------------------------------------------------------------------

# Regex to detect any speaker tag in a transcript: "Firstname Lastname:" or
# "Name (Title):" at the start of a line.  Used to bound speaker sections.
_RE_ANY_SPEAKER = re.compile(r"^[A-Z][A-Za-z .]{2,50}:\s", re.MULTILINE)

# Role phrases used to identify the CFO speaker dynamically.
_RE_CFO_ROLE = re.compile(
    r"Chief\s+Financial\s+Officer|CFO",
    re.IGNORECASE,
)

# Role phrases used to identify the CEO speaker dynamically.
_RE_CEO_ROLE = re.compile(
    r"Chief\s+Executive\s+Officer|CEO|Managing\s+Director|MD\b",
    re.IGNORECASE,
)


def _detect_speaker_tag(text: str, role_re: re.Pattern) -> str | None:
    """Return the speaker tag (e.g. 'Koushik Chatterjee:') for a given role.

    Searches the first 4000 chars (moderator introductions) for the role
    mention, then scans backwards for the person's name.  Handles:
    - Full names: "Koushik Chatterjee"
    - Initial + surname: "K Krithivasan", "T V Narendran"
    Returns None if the role is not found.
    """
    preamble = text[:4000]
    m_role = role_re.search(preamble)
    if not m_role:
        return None
    # Scan backwards to find the preceding name on the same or previous line.
    segment = preamble[: m_role.start()]
    # Matches "K Krithivasan", "T V Narendran", "Samir Seksaria", etc.
    # Leading "Mr." / "Ms." / "Dr." are excluded via the non-greedy word boundary.
    name_m = re.search(
        r"(?<!\w)"  # not preceded by a word char (excludes partial matches)
        r"([A-Z][a-z]*(?:\.[A-Z]\.?)*"  # first name or initial(s)
        r"(?:\s+[A-Z][a-z]*(?:\.[A-Z]\.?)*)+)"  # surname(s)
        r"\s*[,\-]?\s*$",
        segment,
    )
    if name_m:
        name = name_m.group(1).strip()
        # Strip honorifics
        name = re.sub(r"^(?:Mr|Ms|Dr|Mrs|Prof)\.?\s+", "", name)
        return name + ":"
    return None


def _all_speaker_offsets(text: str) -> list[int]:
    """Return sorted list of offsets where any speaker turn begins."""
    return sorted(m.start() for m in _RE_ANY_SPEAKER.finditer(text))


def _extract_speaker_section(text: str, tag: str, next_tag_re: re.Pattern | None = None) -> tuple[str, int]:
    """Return (section_text, start_offset) for the speaker identified by *tag*.

    Skips the first occurrence (the greeting) and uses the second as the start
    of substantive commentary.  If *next_tag_re* is provided, ends at the first
    match of that pattern after start; otherwise uses the next generic speaker
    turn or a 8000-char cap.
    """
    first = text.find(tag)
    if first < 0:
        return "", 0
    second = text.find(tag, first + len(tag))
    start = second if second >= 0 else first
    if next_tag_re:
        m = next_tag_re.search(text, start + len(tag))
        end = m.start() if m else start + 8000
    else:
        offsets = [o for o in _all_speaker_offsets(text) if o > start + len(tag)]
        end = offsets[0] if offsets else start + 8000
    return text[start:end], start


def _extract_cfo_section(text: str) -> tuple[str, int]:
    """Return (cfo_text, start_offset) for the CFO's substantive commentary.

    Tries to detect the CFO speaker dynamically from the moderator introduction.
    Falls back to returning ("", 0) if no CFO turn is found; the caller will
    then fall back to searching the full transcript.
    """
    tag = _detect_speaker_tag(text, _RE_CFO_ROLE)
    if tag:
        return _extract_speaker_section(text, tag)
    return "", 0


def _extract_ceo_section(text: str) -> str:
    """Return CEO's substantive commentary, or "" if not detected."""
    tag = _detect_speaker_tag(text, _RE_CEO_ROLE)
    if tag:
        section, _ = _extract_speaker_section(text, tag)
        return section
    return ""


# ---------------------------------------------------------------------------
# Fact construction helper
# ---------------------------------------------------------------------------

def _period_fact(
    kind: FactKind,
    value: str | float | int | None,
    unit: FactUnit | None,
    period: str,
    section: str,
    char_offset: int,
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
            char_offset=char_offset,
            excerpt=excerpt[:120] if excerpt else None,
        ),
    )


def _parse_inr(s: str) -> float:
    return float(s.replace(",", ""))


def _usd_from_match(m: re.Match) -> float | None:
    raw = m.group(1) or m.group(2)
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured facts from an earnings call transcript PDF.

    Raises ValueError for missing, wrong-kind, or empty-content documents.
    """
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    if entry.kind != "earnings_transcript":
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: "
            f"kind={entry.kind!r} is not 'earnings_transcript'"
        )

    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: document has no content"
        )

    content = content.replace("ﬁ", "fi").replace("ﬂ", "fl")

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="earnings_transcript",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=datetime.fromisoformat(entry.source_date),
    )

    # ------------------------------------------------------------------
    # 1. Period detection (from cover letter, first 3000 chars)
    # ------------------------------------------------------------------
    period: str | None = None
    is_annual = False

    m_period = _RE_PERIOD.search(content[:3000])
    if m_period:
        period = _parse_period_date(m_period.group(1))
        is_annual = bool(_RE_IS_ANNUAL.search(content[:3000]))

    if period is None:
        result.warnings.append("Could not extract quarter-end date from cover letter")
        result.confidence = "low"
        return result

    result.facts.append(_period_fact(
        FactKind.REPORT_PERIOD_END, period, FactUnit.ISO_DATE,
        period, "cover_letter", m_period.start(),
    ))
    result.facts.append(_period_fact(
        FactKind.REPORT_PERIOD_TYPE, "quarterly", None,
        period, "cover_letter", m_period.start(),
    ))
    if is_annual:
        result.facts.append(_period_fact(
            FactKind.REPORT_PERIOD_TYPE, "annual", None,
            period, "cover_letter", m_period.start(),
        ))

    # ------------------------------------------------------------------
    # 2. Extract speaker sections
    # ------------------------------------------------------------------
    cfo_text, cfo_start = _extract_cfo_section(content)
    ceo_text = _extract_ceo_section(content)

    if ceo_text:
        result.excerpts["ceo_commentary"] = ceo_text[:6000].strip()
    if cfo_text:
        result.excerpts["cfo_commentary"] = cfo_text[:8000].strip()

    # Split CFO text into quarterly and annual sections.
    # The boundary patterns only work reliably within the CFO commentary;
    # when no CFO section was found, search the whole transcript unsplit.
    if cfo_text:
        quarterly_cfo, annual_cfo = _split_cfo_sections(cfo_text)
    else:
        # Fallback: speaker not identified — treat whole transcript as the
        # quarterly search text. The first revenue/margin match is usually
        # the most-recently-reported (quarterly) figure.
        quarterly_cfo, annual_cfo = content, ""

    # ------------------------------------------------------------------
    # 3. Revenue
    # ------------------------------------------------------------------
    m_inr = _RE_REVENUE_INR.search(quarterly_cfo)
    if m_inr:
        result.facts.append(_period_fact(
            FactKind.FINANCIAL_REVENUE, _parse_inr(m_inr.group(1)), FactUnit.CRORE_INR,
            period, "quarterly", cfo_start + m_inr.start(),
            excerpt=m_inr.group(0),
        ))

    m_usd = _RE_REVENUE_USD.search(quarterly_cfo)
    if m_usd:
        usd_val = _usd_from_match(m_usd)
        if usd_val is not None:
            result.facts.append(_period_fact(
                FactKind.FINANCIAL_REVENUE, usd_val, FactUnit.USD_BILLION,
                period, "quarterly", cfo_start + m_usd.start(),
                excerpt=m_usd.group(0),
            ))

    if is_annual and annual_cfo:
        m_annual_inr = _RE_REVENUE_INR.search(annual_cfo)
        if m_annual_inr:
            result.facts.append(_period_fact(
                FactKind.FINANCIAL_REVENUE, _parse_inr(m_annual_inr.group(1)), FactUnit.CRORE_INR,
                period, "annual", cfo_start + m_annual_inr.start(),
                excerpt=m_annual_inr.group(0),
            ))

    # ------------------------------------------------------------------
    # 4. Operating margin
    # ------------------------------------------------------------------
    m_op = _RE_OP_MARGIN.search(quarterly_cfo)
    if m_op:
        result.facts.append(_period_fact(
            FactKind.FINANCIAL_OPERATING_MARGIN, float(m_op.group(1)), FactUnit.PERCENT,
            period, "quarterly", cfo_start + m_op.start(),
            excerpt=m_op.group(0),
        ))

    if is_annual and annual_cfo:
        m_annual_op = _RE_OP_MARGIN.search(annual_cfo)
        if m_annual_op:
            result.facts.append(_period_fact(
                FactKind.FINANCIAL_OPERATING_MARGIN, float(m_annual_op.group(1)), FactUnit.PERCENT,
                period, "annual", cfo_start + m_annual_op.start(),
                excerpt=m_annual_op.group(0),
            ))

    # ------------------------------------------------------------------
    # 5. Net margin
    # ------------------------------------------------------------------
    m_net = _RE_NET_MARGIN.search(quarterly_cfo)
    if m_net:
        result.facts.append(_period_fact(
            FactKind.FINANCIAL_NET_MARGIN, float(m_net.group(1)), FactUnit.PERCENT,
            period, "quarterly", cfo_start + m_net.start(),
            excerpt=m_net.group(0),
        ))

    if is_annual and annual_cfo:
        m_annual_net = _RE_NET_MARGIN.search(annual_cfo)
        if m_annual_net:
            result.facts.append(_period_fact(
                FactKind.FINANCIAL_NET_MARGIN, float(m_annual_net.group(1)), FactUnit.PERCENT,
                period, "annual", cfo_start + m_annual_net.start(),
                excerpt=m_annual_net.group(0),
            ))

    # ------------------------------------------------------------------
    # 6. TCV (search full transcript — stated by CEO, not CFO)
    # ------------------------------------------------------------------
    # TCV is always expressed as a specific dollar figure by management and
    # never by analysts, so searching the full content is safe.
    m_tcv = _RE_TCV.search(content)
    if m_tcv:
        tcv_raw = m_tcv.group(1) or m_tcv.group(2)
        result.facts.append(_period_fact(
            FactKind.FINANCIAL_TCV, float(tcv_raw), FactUnit.USD_BILLION,
            period, "quarterly", 0,
            excerpt=m_tcv.group(0),
        ))
    # ------------------------------------------------------------------
    # 7. Result-level confidence
    # ------------------------------------------------------------------
    # TCV is IT-sector specific (not universal) so is excluded from the core set.
    extracted = {f.kind for f in result.facts}
    core = {FactKind.FINANCIAL_REVENUE, FactKind.FINANCIAL_OPERATING_MARGIN}
    if core.issubset(extracted):
        result.confidence = "high"
    elif FactKind.FINANCIAL_REVENUE in extracted:
        result.confidence = "medium"

    return result
