"""Rule-based fact extraction from quarterly and annual financial results filings (Reg 33).

Extracts P&L line items, segment revenues, audit details, and declared dividends
from a single filing. Only the PRIMARY reporting period is extracted (the most
recent period in the comparative statement). Prior-period comparatives are
captured in excerpts for reference but not emitted as facts.

Both consolidated and standalone statements are extracted when present.
Provenance.section distinguishes the source table:
  "consolidated_pl_table" — consolidated P&L line items
  "standalone_pl_table"   — standalone P&L line items
  "segment_table"         — segment revenue table
  "cover_letter"          — cover letter / board resolution text
  "auditor_report"        — auditor's report

Column selection heuristic (BSE Reg 33 format):
  Quarterly filings (6 columns): col 0 = current quarter
  Annual filings   (5 columns): col 3 = current full year

Known limitation: there is no explicit `basis` field on AnalysisFact. Consumers
distinguish consolidated vs standalone facts by filtering on
provenance.section.startswith("consolidated_") vs "standalone_".
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
    _snip,
)
from atlas.analysis.patterns import extract_dividend_facts
from atlas.knowledge.base import KnowledgeBase

ANALYZER_VERSION = "1.0"

_MAX_VALUE_SCAN = 800

# ---------------------------------------------------------------------------
# P&L row definitions
# ---------------------------------------------------------------------------

_PL_ROWS: list[tuple[FactKind, re.Pattern[str]]] = [
    (FactKind.FINANCIAL_REVENUE,
     re.compile(r"Revenue from operations")),
    (FactKind.FINANCIAL_OTHER_INCOME,
     re.compile(r"^Other income\b", re.MULTILINE)),
    (FactKind.FINANCIAL_TOTAL_INCOME,
     re.compile(r"TOTAL INCOME")),
    (FactKind.FINANCIAL_EMPLOYEE_COST,
     re.compile(r"Employee benefit expenses")),
    (FactKind.FINANCIAL_EQUIPMENT_SOFTWARE_COST,
     re.compile(r"Cost of equipment and software licences")),
    (FactKind.FINANCIAL_FINANCE_COST,
     re.compile(r"^Finance costs?\b", re.MULTILINE)),
    (FactKind.FINANCIAL_DEPRECIATION,
     re.compile(r"Depreciation and amortisation expense")),
    (FactKind.FINANCIAL_OTHER_EXPENSES,
     re.compile(r"^Other expenses\b", re.MULTILINE)),
    (FactKind.FINANCIAL_TOTAL_EXPENSES,
     re.compile(r"TOTAL EXPENSES")),
    (FactKind.FINANCIAL_PROFIT_BEFORE_EXCEPTIONAL,
     re.compile(r"PROFIT BEFORE EXCEPTIONAL")),
    (FactKind.FINANCIAL_PROFIT_BEFORE_TAX,
     re.compile(r"PROFIT BEFORE TAX")),
    (FactKind.FINANCIAL_CURRENT_TAX,
     re.compile(r"^Current tax\b", re.MULTILINE)),
    (FactKind.FINANCIAL_DEFERRED_TAX,
     re.compile(r"^Deferred tax\b", re.MULTILINE)),
    (FactKind.FINANCIAL_TOTAL_TAX,
     re.compile(r"TOTAL TAX EXPENSE")),
    (FactKind.FINANCIAL_PAT,
     re.compile(r"PROFIT FOR THE (?:PERIOD|YEAR)")),
]

_SEGMENT_NAMES = re.compile(
    r"^("
    r"Banking, Financial Services and Insurance"
    r"|Manufacturing"
    r"|Consumer Business"
    r"|Communication, Media and Technology"
    r"|Life Sciences and Healthcare"
    r"|Others"
    r")\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Number parsing
# ---------------------------------------------------------------------------

# Matches: (123) for negatives, - for nil, or Indian-format numbers like 1,26,872
_RE_NUM_TOKEN = re.compile(
    r"\([\d,]+(?:\.\d+)?\)"   # (123) = negative
    r"|(?<!\w)-(?!\w)"        # standalone dash = nil/zero
    r"|[\d,]+(?:\.\d+)?"      # positive number with optional decimal
)


def _parse_number(s: str) -> float | None:
    s = s.strip()
    if not s or s == "-":
        return 0.0
    if s.startswith("(") and s.endswith(")"):
        inner = s[1:-1].replace(",", "").replace(" ", "")
        try:
            return -float(inner)
        except ValueError:
            return None
    try:
        return float(s.replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def _extract_n_values(text: str, after: int, n: int = 6) -> list[float | None]:
    """Collect up to n numeric values starting at text[after:].

    Stops at the first non-numeric, non-blank line encountered after values
    have started accumulating (i.e., the next P&L label row).
    """
    values: list[float | None] = []
    segment = text[after: after + _MAX_VALUE_SCAN]
    collecting = False

    for line in segment.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        tokens = _RE_NUM_TOKEN.findall(line)
        if tokens:
            collecting = True
            for t in tokens:
                if len(values) >= n:
                    return values
                v = _parse_number(t)
                if v is not None:
                    values.append(v)
        elif collecting:
            # Non-numeric non-blank line after values started = next row label
            break
    return values


# ---------------------------------------------------------------------------
# Filing type and period detection
# ---------------------------------------------------------------------------

_RE_QUARTER_PERIOD = re.compile(
    r"quarter(?:\s+and\s+six[- ]month\s+period)?\s+ended\s+(\w+ \d+,\s*\d{4})",
    re.IGNORECASE,
)
_RE_YEAR_PERIOD = re.compile(
    r"\byear\s+ended\s+(\w+ \d+,\s*\d{4})",
    re.IGNORECASE,
)
_DATE_FMT = "%B %d, %Y"


def _detect_filing(text: str) -> tuple[str, str | None]:
    """Return (period_type, period_end_iso) from the cover letter (first 3000 chars)."""
    cover = text[:3000]
    m = _RE_QUARTER_PERIOD.search(cover)
    if m:
        try:
            raw = re.sub(r"\s+", " ", m.group(1))
            d = datetime.strptime(raw, _DATE_FMT).date()
            return "quarterly", d.isoformat()
        except ValueError:
            pass
    m = _RE_YEAR_PERIOD.search(cover)
    if m:
        try:
            raw = re.sub(r"\s+", " ", m.group(1))
            d = datetime.strptime(raw, _DATE_FMT).date()
            return "annual", d.isoformat()
        except ValueError:
            pass
    return "unknown", None


def _primary_col(period_type: str, n_values: int) -> int:
    """Return the 0-based column index for the primary reporting period.

    BSE Reg 33 layout:
      6-column (quarterly/H1): col 0 = current quarter
      5-column (annual/Q4):    col 3 = current full year, col 0 = current Q4
    """
    if period_type == "annual" and n_values >= 5:
        return 3
    return 0


# ---------------------------------------------------------------------------
# P&L region detection
# ---------------------------------------------------------------------------

def _find_pl_regions(text: str) -> dict[str, tuple[int, int]]:
    """Locate consolidated and standalone P&L regions by Revenue from operations anchor.

    Returns a dict with keys "consolidated" and/or "standalone", each mapping
    to (revenue_offset, region_end_offset).
    """
    offsets = [m.start() for m in re.finditer(r"Revenue from operations", text)]
    regions: dict[str, tuple[int, int]] = {}

    if not offsets:
        return regions

    # Consolidated = first occurrence
    con_start = offsets[0]
    con_end = offsets[1] if len(offsets) >= 2 else _region_end(text, con_start)
    regions["consolidated"] = (con_start, con_end)

    # Standalone = second occurrence (if present)
    if len(offsets) >= 2:
        sa_start = offsets[1]
        sa_end = _region_end(text, sa_start)
        regions["standalone"] = (sa_start, sa_end)

    return regions


def _region_end(text: str, from_offset: int) -> int:
    """Find the end of a P&L region (before balance sheet ASSETS block)."""
    m = re.search(r"\nASSETS\b", text[from_offset:])
    return from_offset + (m.start() if m else min(8000, len(text) - from_offset))


def _detect_n_cols(text: str, rev_offset: int) -> int:
    """Count columns by extracting values from the Revenue row."""
    m = re.compile(r"Revenue from operations").search(text, rev_offset)
    if m is None:
        return 6
    values = _extract_n_values(text, m.end(), n=8)
    return max(len(values), 1)


# ---------------------------------------------------------------------------
# P&L fact extraction
# ---------------------------------------------------------------------------

def _extract_pl_facts(
    text: str,
    rev_offset: int,
    end_offset: int,
    period: str,
    col_idx: int,
    basis: str,
) -> list[AnalysisFact]:
    region = text[rev_offset:end_offset]
    facts: list[AnalysisFact] = []

    for kind, pat in _PL_ROWS:
        m = pat.search(region)
        if m is None:
            continue
        values = _extract_n_values(text, rev_offset + m.end(), n=6)
        if not values:
            continue
        idx = col_idx if col_idx < len(values) else 0
        val = values[idx]
        if val is None:
            continue
        facts.append(AnalysisFact(
            kind=kind,
            value=val,
            unit=FactUnit.CRORE_INR,
            period=period,
            confidence="high",
            provenance=Provenance(
                section=f"{basis}_pl_table",
                char_offset=rev_offset + m.start(),
                excerpt=_snip(region, m.start()),
            ),
        ))
    return facts


# ---------------------------------------------------------------------------
# EPS extraction
# ---------------------------------------------------------------------------

_RE_EPS = re.compile(
    r"Earnings per equity share.*?Basic and diluted",
    re.IGNORECASE | re.DOTALL,
)


def _extract_eps_facts(
    text: str,
    period: str,
    col_idx: int,
    basis: str,
    search_start: int,
    search_end: int,
) -> list[AnalysisFact]:
    region = text[search_start:search_end]
    m = _RE_EPS.search(region)
    if m is None:
        return []
    values = _extract_n_values(text, search_start + m.end(), n=6)
    if not values:
        return []
    idx = col_idx if col_idx < len(values) else 0
    val = values[idx]
    if val is None or val == 0.0:
        return []
    return [AnalysisFact(
        kind=FactKind.FINANCIAL_EPS_BASIC,
        value=val,
        unit=FactUnit.RUPEES,
        period=period,
        confidence="high",
        provenance=Provenance(
            section=f"{basis}_eps_row",
            char_offset=search_start + m.start(),
            excerpt=_snip(region, m.start()),
        ),
    )]


# ---------------------------------------------------------------------------
# Exceptional items
# ---------------------------------------------------------------------------

_RE_EXCEPTIONAL_BLOCK = re.compile(
    r"Exceptional items?\s*\n(.*?)(?=PROFIT BEFORE TAX)",
    re.IGNORECASE | re.DOTALL,
)


def _extract_exceptional_facts(
    text: str,
    period: str,
    col_idx: int,
    basis: str,
    search_start: int,
    search_end: int,
) -> list[AnalysisFact]:
    region = text[search_start:search_end]
    m = _RE_EXCEPTIONAL_BLOCK.search(region)
    if m is None:
        return []

    block = m.group(1)
    block_abs = search_start + m.start(1)
    facts: list[AnalysisFact] = []

    for item_m in re.finditer(r"^(.+)\n", block, re.MULTILINE):
        line = item_m.group(1).strip()
        if not line or not line[0].isupper():
            continue
        values = _extract_n_values(text, block_abs + item_m.end(), n=6)
        if not values:
            continue
        idx = col_idx if col_idx < len(values) else 0
        val = values[idx]
        if val is None or val == 0.0:
            continue
        prov = Provenance(
            section=f"{basis}_pl_table",
            char_offset=block_abs + item_m.start(),
            excerpt=_snip(block, item_m.start()),
        )
        facts.append(AnalysisFact(
            kind=FactKind.EXCEPTIONAL_DESCRIPTION,
            value=line,
            unit=None,
            period=period,
            confidence="medium",
            provenance=prov,
        ))
        facts.append(AnalysisFact(
            kind=FactKind.EXCEPTIONAL_AMOUNT,
            value=val,
            unit=FactUnit.CRORE_INR,
            period=period,
            confidence="medium",
            provenance=prov,
        ))
    return facts


# ---------------------------------------------------------------------------
# Segment revenue
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Balance sheet extraction (annual filings only)
# ---------------------------------------------------------------------------

_RE_BS_CASH = re.compile(r"Cash and cash equivalents\b", re.IGNORECASE)
_RE_BS_EQUITY = re.compile(
    r"Equity attributable to (?:shareholders|owners|equity holders) of (?:the Company|Parent|the parent)",
    re.IGNORECASE,
)
_RE_BS_EQUITY_FALLBACK = re.compile(r"^Total equity\b", re.MULTILINE | re.IGNORECASE)
_RE_BS_BORROWINGS = re.compile(r"^\s*(?:Long.term\s+)?[Bb]orrowings\b", re.MULTILINE)


def _find_bs_region(text: str) -> tuple[int, int] | None:
    """Return (start, end) of the balance sheet block, or None if not found.

    The balance sheet begins with the ASSETS header and ends just before
    the cash flow statement.
    """
    m_start = re.search(r"\nASSETS\b", text)
    if m_start is None:
        return None
    m_end = re.search(r"\bCASH FLOWS FROM OPERATING", text[m_start.start():], re.IGNORECASE)
    end = m_start.start() + (m_end.start() if m_end else min(10_000, len(text) - m_start.start()))
    return m_start.start(), end


def _extract_balance_sheet_facts(text: str, period: str) -> list[AnalysisFact]:
    """Extract FINANCIAL_CASH_AND_EQUIVALENTS, FINANCIAL_TOTAL_EQUITY, and
    FINANCIAL_TOTAL_DEBT from the audited balance sheet in an annual filing.

    Always reads the first (current-year) column.  Emits no fact and no
    warning for FINANCIAL_TOTAL_DEBT when no borrowings row is found —
    the Company layer treats absence as zero for debt-free entities.
    """
    region = _find_bs_region(text)
    if region is None:
        return []
    bs_start, bs_end = region
    bs_text = text[bs_start:bs_end]

    facts: list[AnalysisFact] = []

    # 1. Cash and cash equivalents
    m = _RE_BS_CASH.search(bs_text)
    if m:
        vals = _extract_n_values(bs_text, m.end(), n=2)
        if vals:
            facts.append(AnalysisFact(
                kind=FactKind.FINANCIAL_CASH_AND_EQUIVALENTS,
                value=vals[0],
                unit=FactUnit.CRORE_INR,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="balance_sheet",
                    char_offset=bs_start + m.start(),
                    excerpt=_snip(bs_text, m.start()),
                ),
            ))

    # 2. Total equity (parent shareholders only, excluding non-controlling interests)
    m = _RE_BS_EQUITY.search(bs_text)
    if m is None:
        m = _RE_BS_EQUITY_FALLBACK.search(bs_text)
    if m:
        vals = _extract_n_values(bs_text, m.end(), n=2)
        if vals:
            facts.append(AnalysisFact(
                kind=FactKind.FINANCIAL_TOTAL_EQUITY,
                value=vals[0],
                unit=FactUnit.CRORE_INR,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="balance_sheet",
                    char_offset=bs_start + m.start(),
                    excerpt=_snip(bs_text, m.start()),
                ),
            ))

    # 3. Total debt (borrowings — not emitted if zero / absent)
    total_debt = 0.0
    found_debt = False
    for m in _RE_BS_BORROWINGS.finditer(bs_text):
        vals = _extract_n_values(bs_text, m.end(), n=2)
        if vals and vals[0] != 0.0:
            total_debt += vals[0]
            found_debt = True
    if found_debt:
        facts.append(AnalysisFact(
            kind=FactKind.FINANCIAL_TOTAL_DEBT,
            value=total_debt,
            unit=FactUnit.CRORE_INR,
            period=period,
            confidence="high",
            provenance=Provenance(section="balance_sheet"),
        ))

    return facts


# ---------------------------------------------------------------------------
# Cash flow extraction (annual filings only)
# ---------------------------------------------------------------------------

_RE_CF_OPERATING = re.compile(
    r"Net cash (?:flows? )?(?:generated from|from) operating activities",
    re.IGNORECASE,
)
_RE_CF_CAPEX = re.compile(
    r"Payment(?:s)? (?:including advances )?for (?:purchase of )?property,\s*plant and equipment",
    re.IGNORECASE,
)


def _find_cf_region(text: str) -> tuple[int, int] | None:
    """Return (start, end) of the cash flow statement block, or None."""
    m_start = re.search(r"\bCASH FLOWS FROM OPERATING", text, re.IGNORECASE)
    if m_start is None:
        return None
    # End at balance sheet note or next major section
    m_end = re.search(r"\bNotes? to (?:the )?(?:standalone|consolidated)? (?:Financial|Accounts)",
                       text[m_start.start():], re.IGNORECASE)
    end = m_start.start() + (m_end.start() if m_end else min(12_000, len(text) - m_start.start()))
    return m_start.start(), end


def _extract_cashflow_facts(text: str, period: str) -> list[AnalysisFact]:
    """Extract FINANCIAL_OPERATING_CASH_FLOW and FINANCIAL_CAPEX from the
    cash flow statement in an annual filing.

    FINANCIAL_CAPEX is the absolute value of "Payment for purchase of
    property, plant and equipment" (PP&E only; intangibles excluded).
    """
    region = _find_cf_region(text)
    if region is None:
        return []
    cf_start, cf_end = region
    cf_text = text[cf_start:cf_end]

    facts: list[AnalysisFact] = []

    # 1. Operating cash flow
    m = _RE_CF_OPERATING.search(cf_text)
    if m:
        vals = _extract_n_values(cf_text, m.end(), n=2)
        if vals:
            facts.append(AnalysisFact(
                kind=FactKind.FINANCIAL_OPERATING_CASH_FLOW,
                value=vals[0],
                unit=FactUnit.CRORE_INR,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="cash_flow_statement",
                    char_offset=cf_start + m.start(),
                    excerpt=_snip(cf_text, m.start()),
                ),
            ))

    # 2. Capital expenditure (PP&E purchases — absolute value; outflows are negative)
    m = _RE_CF_CAPEX.search(cf_text)
    if m:
        vals = _extract_n_values(cf_text, m.end(), n=2)
        if vals and vals[0] != 0.0:
            facts.append(AnalysisFact(
                kind=FactKind.FINANCIAL_CAPEX,
                value=abs(vals[0]),
                unit=FactUnit.CRORE_INR,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="cash_flow_statement",
                    char_offset=cf_start + m.start(),
                    excerpt=_snip(cf_text, m.start()),
                ),
            ))

    return facts


# ---------------------------------------------------------------------------
# Segment revenue (existing) + segment EBIT (new)
# ---------------------------------------------------------------------------


def _extract_segment_facts(
    text: str,
    period: str,
    col_idx: int,
    search_start: int,
) -> list[AnalysisFact]:
    """Extract segment name + revenue pairs.

    Works when segment values immediately follow each segment name (quarterly
    format). If all segment names appear before any values (annual PDF layout),
    returns an empty list — the caller adds a warning.
    """
    seg_start = text.find("SEGMENT REVENUE", search_start)
    if seg_start == -1:
        return []
    seg_result = text.find("SEGMENT RESULT", seg_start)
    seg_end = seg_result if seg_result != -1 else seg_start + 3000
    region = text[seg_start:seg_end]

    facts: list[AnalysisFact] = []
    for name_m in _SEGMENT_NAMES.finditer(region):
        seg_name = name_m.group(1).strip()
        values = _extract_n_values(text, seg_start + name_m.end(), n=6)
        if not values:
            # All names listed before values — annual layout, cannot align
            return []
        idx = col_idx if col_idx < len(values) else 0
        val = values[idx]
        if val is None:
            continue
        prov = Provenance(
            section="segment_table",
            char_offset=seg_start + name_m.start(),
            excerpt=_snip(region, name_m.start()),
        )
        facts.append(AnalysisFact(
            kind=FactKind.SEGMENT_NAME,
            value=seg_name,
            unit=None,
            period=period,
            confidence="high",
            provenance=prov,
        ))
        facts.append(AnalysisFact(
            kind=FactKind.SEGMENT_REVENUE,
            value=val,
            unit=FactUnit.CRORE_INR,
            period=period,
            confidence="high",
            provenance=prov,
        ))
    return facts


def _extract_segment_ebit_facts(
    text: str,
    period: str,
    col_idx: int,
    search_start: int,
) -> list[AnalysisFact]:
    """Extract SEGMENT_EBIT from the SEGMENT RESULT section.

    Mirrors _extract_segment_facts — annual PDF layout causes empty return
    (no additional warning; the segment-revenue warning already covers it).
    """
    ebit_start = text.find("SEGMENT RESULT", search_start)
    if ebit_start == -1:
        return []
    m_end = re.search(r"(?:Unallocable expenses|Operating income)", text[ebit_start:], re.IGNORECASE)
    ebit_end = ebit_start + (m_end.start() if m_end else 3000)
    region = text[ebit_start:ebit_end]

    facts: list[AnalysisFact] = []
    for name_m in _SEGMENT_NAMES.finditer(region):
        seg_name = name_m.group(1).strip()
        values = _extract_n_values(text, ebit_start + name_m.end(), n=6)
        if not values:
            return []
        idx = col_idx if col_idx < len(values) else 0
        val = values[idx]
        if val is None:
            continue
        facts.append(AnalysisFact(
            kind=FactKind.SEGMENT_EBIT,
            value=val,
            unit=FactUnit.CRORE_INR,
            period=period,
            confidence="high",
            provenance=Provenance(
                section="segment_table",
                char_offset=ebit_start + name_m.start(),
                excerpt=_snip(region, name_m.start()),
            ),
        ))
    return facts


# ---------------------------------------------------------------------------
# Audit opinion and firm
# ---------------------------------------------------------------------------

_RE_UNMODIFIED = re.compile(r"unmodified\s+(?:audit\s+)?opinion", re.IGNORECASE)
_RE_AUDIT_FIRM = re.compile(
    r"^(B S R.*?LLP|Deloitte.*?LLP|Price Waterhouse.*?LLP|KPMG.*?LLP|Ernst.*?LLP)",
    re.MULTILINE,
)


def _extract_audit_facts(text: str) -> list[AnalysisFact]:
    facts: list[AnalysisFact] = []
    m = _RE_UNMODIFIED.search(text)
    if m:
        facts.append(AnalysisFact(
            kind=FactKind.AUDIT_OPINION,
            value="unmodified",
            unit=None,
            period=None,
            confidence="high",
            provenance=Provenance(
                section="auditor_report",
                char_offset=m.start(),
                excerpt=_snip(text, m.start()),
            ),
        ))
    m = _RE_AUDIT_FIRM.search(text[:5000])
    if m:
        facts.append(AnalysisFact(
            kind=FactKind.AUDIT_FIRM,
            value=m.group(1).strip(),
            unit=None,
            period=None,
            confidence="high",
            provenance=Provenance(
                section="auditor_report",
                char_offset=m.start(),
                excerpt=_snip(text, m.start()),
            ),
        ))
    return facts


# ---------------------------------------------------------------------------
# Report metadata facts
# ---------------------------------------------------------------------------

def _report_meta_facts(period_type: str, period_end: str, text: str) -> list[AnalysisFact]:
    cover_snip = _snip(text)
    facts: list[AnalysisFact] = [
        AnalysisFact(
            kind=FactKind.REPORT_PERIOD_END,
            value=period_end,
            unit=FactUnit.ISO_DATE,
            period=period_end,
            confidence="high",
            provenance=Provenance(section="cover_letter", excerpt=cover_snip),
        ),
        AnalysisFact(
            kind=FactKind.REPORT_PERIOD_TYPE,
            value=period_type,
            unit=None,
            period=period_end,
            confidence="high" if period_type != "unknown" else "low",
            provenance=Provenance(section="cover_letter", excerpt=cover_snip),
        ),
    ]
    txt_lower = text.lower()
    for basis in ("consolidated", "standalone"):
        if basis in txt_lower:
            facts.append(AnalysisFact(
                kind=FactKind.REPORT_BASIS,
                value=basis,
                unit=None,
                period=period_end,
                confidence="high",
                provenance=Provenance(section="cover_letter", excerpt=cover_snip),
            ))
    return facts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured facts from a parsed quarterly or annual financial results filing.

    Raises KeyError if evidence_id is not in the knowledge base.
    Raises ValueError if the document failed to parse or content is unavailable.
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

    facts: list[AnalysisFact] = []
    warnings: list[str] = []
    excerpts: dict[str, str] = {}

    # --- Period and filing type ---
    period_type, period_end = _detect_filing(content)
    if period_end is None:
        warnings.append("Could not detect primary reporting period from cover letter")
        period_end = doc.source_date[:10]
        period_type = "unknown"

    facts.extend(_report_meta_facts(period_type, period_end, content))

    # --- P&L regions ---
    pl_regions = _find_pl_regions(content)

    if not pl_regions:
        warnings.append("No P&L table found — may be a Regulation 23(9) disclosure")
        return AnalysisResult(
            evidence_id=evidence_id,
            kind=doc.kind,
            analyzer_version=ANALYZER_VERSION,
            confidence="low",
            source_date=datetime.fromisoformat(doc.source_date),
            warnings=warnings,
            facts=facts,
            excerpts=excerpts,
        )

    # Detect column count from consolidated table to determine primary column index
    con_rev_off = pl_regions["consolidated"][0]
    n_cols = _detect_n_cols(content, con_rev_off)
    col_idx = _primary_col(period_type, n_cols)

    # --- Consolidated ---
    con_rev, con_end = pl_regions["consolidated"]
    excerpts["consolidated_pl_table"] = content[con_rev: min(con_rev + 3000, con_end)]

    con_pl = _extract_pl_facts(content, con_rev, con_end, period_end, col_idx, "consolidated")
    facts.extend(con_pl)
    if not con_pl:
        warnings.append("No P&L line items extracted from consolidated table")

    facts.extend(_extract_eps_facts(
        content, period_end, col_idx, "consolidated",
        con_rev, con_end + 3000,
    ))
    facts.extend(_extract_exceptional_facts(
        content, period_end, col_idx, "consolidated", con_rev, con_end,
    ))

    seg_facts = _extract_segment_facts(content, period_end, col_idx, con_rev)
    facts.extend(seg_facts)
    if not seg_facts:
        warnings.append(
            "Segment revenue not extracted — annual PDF layout may prevent alignment"
        )

    facts.extend(_extract_segment_ebit_facts(content, period_end, col_idx, con_rev))

    # --- Standalone ---
    if "standalone" in pl_regions:
        sa_rev, sa_end = pl_regions["standalone"]
        excerpts["standalone_pl_table"] = content[sa_rev: min(sa_rev + 2000, sa_end)]

        sa_n_cols = _detect_n_cols(content, sa_rev)
        sa_col = _primary_col(period_type, sa_n_cols)

        sa_pl = _extract_pl_facts(content, sa_rev, sa_end, period_end, sa_col, "standalone")
        facts.extend(sa_pl)

        facts.extend(_extract_eps_facts(
            content, period_end, sa_col, "standalone",
            sa_rev, sa_end + 3000,
        ))

    # --- Balance sheet and cash flow (annual filings only) ---
    if period_type == "annual":
        facts.extend(_extract_balance_sheet_facts(content, period_end))
        facts.extend(_extract_cashflow_facts(content, period_end))

    # --- Dividend (cover letter is authoritative) ---
    div_facts = extract_dividend_facts(content[:3000], period_end)
    facts.extend(div_facts)
    if not div_facts:
        warnings.append("No dividend declaration found in cover letter")

    # --- Audit ---
    audit_facts = _extract_audit_facts(content)
    facts.extend(audit_facts)
    if not audit_facts:
        warnings.append("Audit opinion not detected")

    # --- Result-level confidence ---
    pl_count = sum(1 for f in facts if f.kind.value.startswith("financial_"))
    if pl_count >= 10:
        result_conf: Literal["high", "medium", "low"] = "high"
    elif pl_count >= 5:
        result_conf = "medium"
    else:
        result_conf = "low"

    return AnalysisResult(
        evidence_id=evidence_id,
        kind=doc.kind,
        analyzer_version=ANALYZER_VERSION,
        confidence=result_conf,
        source_date=datetime.fromisoformat(doc.source_date),
        warnings=warnings,
        facts=facts,
        excerpts=excerpts,
    )
