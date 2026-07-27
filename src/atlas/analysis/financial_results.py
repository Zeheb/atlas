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
from atlas.analysis.patterns import (
    extract_dividend_facts,
    extract_n_values,
    fix_ocr_numbers,
    parse_number,
)
from atlas.knowledge.base import KnowledgeBase

ANALYZER_VERSION = "1.1"

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

# Dynamic segment-name detection: any line in the segment table that looks
# like a company segment rather than a header, total, or footnote.
# Matches title-case (or ALLCAPS) lines that contain letters and common
# punctuation but are not numeric, not "Total …" / "Less" / "Add" / "Less:" etc.
_SEGMENT_NAME_LINE = re.compile(
    r"^([A-Z][A-Za-z ,&/()\-]{2,80})\s*$",
    re.MULTILINE,
)

# Lines to exclude from segment-name candidates.
_SEGMENT_EXCLUDE = re.compile(
    r"^(?:Total|Less|Add|Unallocable|Eliminat|Reconcil|Corporate|SEGMENT|Revenue|Result|Note|Refer)",
    re.IGNORECASE,
)


def _is_segment_candidate(name: str) -> bool:
    """Return True if the line looks like a segment name, not a header/total."""
    stripped = name.strip()
    if not stripped:
        return False
    if _SEGMENT_EXCLUDE.match(stripped):
        return False
    # Reject all-caps lines (they're usually section headers like "SEGMENT REVENUE")
    if stripped == stripped.upper() and stripped.replace(" ", "").isalpha():
        return False
    return True

# ---------------------------------------------------------------------------
# Number parsing — shared with investor_presentation.py; see patterns.py
# ---------------------------------------------------------------------------

_extract_n_values = extract_n_values
_parse_number = parse_number
_fix_ocr_numbers = fix_ocr_numbers


# ---------------------------------------------------------------------------
# Filing type and period detection
# ---------------------------------------------------------------------------

_RE_QUARTER_PERIOD = re.compile(
    # Matches "quarter ended …", "quarter and six-month period ended …",
    # "quarter and half year ended …", and standalone "half year ended …".
    r"(?:quarter|half[- ]?year)(?:[^.\n]{0,60}?)ended\s+(\w+ \d+,\s*\d{4})",
    re.IGNORECASE,
)
_RE_YEAR_PERIOD = re.compile(
    r"\byear\s+ended\s+(\w+ \d+,\s*\d{4})",
    re.IGNORECASE,
)
_DATE_FMT = "%B %d, %Y"


def _detect_filing(text: str) -> tuple[str, str | None]:
    """Return (period_type, period_end_iso) from the cover letter (first 3000 chars).

    Handles three filing shapes:
    - "quarter and half year ended Sep 30" → quarterly
    - "quarter ended Mar 31" + "financial year ended Mar 31" (same date) → annual
      (Tata Steel style: Q4 and annual results bundled in one document)
    - "year ended Mar 31" only (no quarter prefix) → annual (TCS style)
    """
    cover = text[:3000]

    quarter_date = None
    m = _RE_QUARTER_PERIOD.search(cover)
    if m:
        try:
            quarter_date = datetime.strptime(
                re.sub(r"\s+", " ", m.group(1)), _DATE_FMT
            ).date()
        except ValueError:
            pass

    annual_date = None
    for m in re.finditer(_RE_YEAR_PERIOD, cover):
        # Skip "half year ended" — "half " immediately precedes "year"
        pre = cover[max(0, m.start() - 5): m.start()]
        if pre.lower().endswith("half ") or pre.lower().endswith("half-"):
            continue
        try:
            annual_date = datetime.strptime(
                re.sub(r"\s+", " ", m.group(1)), _DATE_FMT
            ).date()
            break
        except ValueError:
            pass

    # When both match the SAME date this is a Q4 annual filing (e.g. Tata Steel
    # May filing that says "quarter ended Mar 31" AND "year ended Mar 31").
    # Prefer "annual" so that col-3 (full-year) data is extracted.
    if annual_date and (quarter_date is None or quarter_date == annual_date):
        return "annual", annual_date.isoformat()
    if quarter_date:
        return "quarterly", quarter_date.isoformat()
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

_RE_CONSOLIDATED_LABEL = re.compile(
    r"Consolidated\s+(?:\w+\s+)?(?:Statement|Results|Financial)",
    re.IGNORECASE,
)
_RE_STANDALONE_LABEL = re.compile(
    r"Standalone\s+(?:\w+\s+)?(?:Statement|Results|Financial)",
    re.IGNORECASE,
)
_LABEL_LOOKBACK = 600  # chars to scan before "Revenue from operations"


def _detect_basis(text: str, rev_offset: int) -> str | None:
    """Return 'consolidated' or 'standalone' by looking for a statement label
    in the 600 chars before *rev_offset*.  Returns None when ambiguous."""
    window = text[max(0, rev_offset - _LABEL_LOOKBACK): rev_offset]
    has_con = bool(_RE_CONSOLIDATED_LABEL.search(window))
    has_sa = bool(_RE_STANDALONE_LABEL.search(window))
    if has_con and not has_sa:
        return "consolidated"
    if has_sa and not has_con:
        return "standalone"
    return None  # Ambiguous; caller falls back to positional heuristic


def _find_pl_regions(text: str) -> dict[str, tuple[int, int]]:
    """Locate consolidated and standalone P&L regions by Revenue from operations anchor.

    Returns a dict with keys "consolidated" and/or "standalone", each mapping
    to (revenue_offset, region_end_offset).

    Detects basis from section headers in the surrounding text (Tata Steel has
    standalone BEFORE consolidated; TCS has consolidated BEFORE standalone).
    When detection is ambiguous, falls back to position order.
    """
    offsets = [m.start() for m in re.finditer(r"Revenue from operations", text)]
    if not offsets:
        return {}

    # Collect (basis, start) pairs for the first two P&L occurrences.
    # Skip occurrences that are too far from their section headers
    # (segment table entries, ratio disclosures, etc.).
    pl_offsets: list[tuple[str | None, int]] = []
    for off in offsets[:6]:  # scan up to 6 occurrences
        basis = _detect_basis(text, off)
        pl_offsets.append((basis, off))
        if len([b for b, _ in pl_offsets if b in ("consolidated", "standalone")]) >= 2:
            break

    # Pair up detected regions
    con_start = sa_start = None
    for basis, off in pl_offsets:
        if basis == "consolidated" and con_start is None:
            con_start = off
        elif basis == "standalone" and sa_start is None:
            sa_start = off

    # Fall back to positional order when label detection fails
    if con_start is None and sa_start is None and len(pl_offsets) >= 1:
        con_start = pl_offsets[0][1]
        if len(pl_offsets) >= 2:
            sa_start = pl_offsets[1][1]
    elif con_start is None and sa_start is not None and len(pl_offsets) >= 2:
        # Only standalone detected; use the other occurrence as consolidated
        for _, off in pl_offsets:
            if off != sa_start:
                con_start = off
                break

    regions: dict[str, tuple[int, int]] = {}
    if con_start is not None:
        con_end = sa_start if (sa_start and sa_start > con_start) else _region_end(text, con_start)
        regions["consolidated"] = (con_start, con_end)
    if sa_start is not None:
        sa_end = con_start if (con_start and con_start > sa_start) else _region_end(text, sa_start)
        regions["standalone"] = (sa_start, sa_end)
    return regions


def _region_end(text: str, from_offset: int) -> int:
    """Find the end of a P&L region (before balance sheet ASSETS block)."""
    m = re.search(r"\nASSETS\b", text[from_offset:])
    return from_offset + (m.start() if m else min(8000, len(text) - from_offset))


def _detect_n_cols(text: str, rev_offset: int) -> int:
    """Count columns by extracting values from the Revenue row.

    Scans forward from rev_offset trying each 'Revenue from operations'
    occurrence until one yields substantial values (> 50).  This skips the
    label sections in old 'labels-then-values' PDFs where only row numbers
    appear immediately after the row label.
    """
    for m in re.compile(r"Revenue from operations").finditer(text, rev_offset):
        values = _extract_n_values(text, m.end(), n=8)
        if values and any(abs(v or 0) > 50 for v in values):
            return max(len(values), 1)
        if values:
            # Has values but all small — keep scanning
            continue
    return 6


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
        # Old "labels-then-values" PDFs (e.g. Tata Steel FY20) repeat the
        # row label in a label section (no values follow) and again in a
        # separate value section.  Try every match in the region; prefer the
        # first one that yields at least one value > 50 crore.
        chosen_m = None
        chosen_values: list[float | None] = []
        for m in pat.finditer(region):
            candidate = _extract_n_values(text, rev_offset + m.end(), n=6)
            if candidate and any(abs(v or 0) > 50 for v in candidate):
                chosen_m, chosen_values = m, candidate
                break
            if chosen_m is None:
                chosen_m, chosen_values = m, candidate  # keep first as fallback

        if chosen_m is None:
            continue
        if not chosen_values:
            continue
        idx = col_idx if col_idx < len(chosen_values) else 0
        val = chosen_values[idx]
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
                char_offset=rev_offset + chosen_m.start(),
                excerpt=_snip(region, chosen_m.start()),
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
_RE_BS_EL_TOTAL = re.compile(r"TOTAL\s*-\s*EQUITY AND LIABILITIES", re.IGNORECASE)


def _extract_bs_deferred_equity_debt(
    bs_text: str, period: str, bs_start: int
) -> list[AnalysisFact]:
    """Extract equity and debt from the 'deferred' BS layout (Tata Steel style).

    In the deferred layout all E&L labels appear first, then all values are
    written together after "TOTAL - EQUITY AND LIABILITIES".  The structure
    follows IndAS Schedule III:

        [0] Equity share capital
        [1] Other equity
        [2] Equity attributable to shareholders (= [0]+[1], consolidated only)
        [3] Non-controlling interests (consolidated only)
        [4] Sub-total Total equity (= [2]+[3] consolidated, or [0]+[1] standalone)
        [5] NCL Borrowings   ← first NCL item
        ... (N more NCL items)
        [5+N] Sub-total NCL  (≈ sum of NCL items — used to locate current Borrowings)
        [6+N] CL Borrowings  ← first CL item
        ...

    Sub-totals are found algebraically (a value that equals the sum of the
    preceding N items).  This avoids relying on label positions that shift
    between companies and years.
    """
    m = _RE_BS_EL_TOTAL.search(bs_text)
    if m is None:
        return []

    vals = _extract_n_values(bs_text, m.end(), n=35)
    if len(vals) < 3:
        return []

    # --- Locate equity sub-total index algebraically ---
    # Primary check: vals[2] ≈ vals[0] + vals[1]  (equity attributable, consolidated)
    equity_idx: int | None = None
    if len(vals) >= 3 and abs(vals[2] - (vals[0] + vals[1])) < max(5.0, 0.001 * abs(vals[2])):
        equity_idx = 2
        # Consolidated: check for a further sub-total at index 4
        if len(vals) >= 5 and abs(vals[4] - (vals[2] + vals[3])) < max(5.0, 0.001 * abs(vals[4])):
            equity_idx = 4
    else:
        # Standalone: no equity-attributable row; sub-total at index 2
        equity_idx = 2

    if equity_idx >= len(vals):
        return []

    facts: list[AnalysisFact] = [
        AnalysisFact(
            kind=FactKind.FINANCIAL_TOTAL_EQUITY,
            value=vals[equity_idx],
            unit=FactUnit.CRORE_INR,
            period=period,
            confidence="medium",
            provenance=Provenance(section="balance_sheet", char_offset=bs_start + m.start()),
        )
    ]

    # --- NCL Borrowings = first value after equity sub-total ---
    ncl_borr_idx = equity_idx + 1
    if ncl_borr_idx >= len(vals) or vals[ncl_borr_idx] <= 0:
        return facts
    total_debt = vals[ncl_borr_idx]

    # --- Find NCL sub-total to locate CL Borrowings ---
    # Try windows of 1–14 NCL items; the sub-total value ≈ sum of window.
    for ncl_n in range(1, 15):
        end_idx = ncl_borr_idx + ncl_n
        if end_idx >= len(vals):
            break
        ncl_sum = sum(vals[ncl_borr_idx:end_idx])
        if abs(vals[end_idx] - ncl_sum) < max(10.0, 0.001 * abs(vals[end_idx])):
            cl_borr_idx = end_idx + 1
            if cl_borr_idx < len(vals) and vals[cl_borr_idx] > 0:
                total_debt += vals[cl_borr_idx]
            break

    if total_debt > 0:
        facts.append(AnalysisFact(
            kind=FactKind.FINANCIAL_TOTAL_DEBT,
            value=total_debt,
            unit=FactUnit.CRORE_INR,
            period=period,
            confidence="medium",
            provenance=Provenance(section="balance_sheet"),
        ))

    return facts
_RE_BS_BORROWINGS = re.compile(r"^\s*(?:Long.term\s+)?[Bb]orrowings\b", re.MULTILINE)

# Working-capital items (M-P3.1, ADR-0012).
_RE_BS_INVENTORIES = re.compile(r"^\s*Inventories\b", re.MULTILINE | re.IGNORECASE)
_RE_BS_TRADE_RECEIVABLES = re.compile(r"Trade receivables\b", re.IGNORECASE)
# "Billed"/"Unbilled" sub-lines: only some filings (IT-services, long-duration
# contracts) split Trade Receivables this way -- see FINANCIAL_UNBILLED_REVENUE.
_RE_BS_BILLED = re.compile(r"^\s*Billed\b", re.MULTILINE | re.IGNORECASE)
_RE_BS_UNBILLED = re.compile(r"^\s*Unbilled\b", re.MULTILINE | re.IGNORECASE)
# Schedule III's mandatory MSMED-Act payables split. Wording verified against
# real BSE filings (not assumed): "Total outstanding dues of micro and small
# enterprises" / "...creditors other than micro and small enterprises".
_RE_BS_PAYABLES_MSME = re.compile(
    r"[Tt]otal\s+outstanding\s+dues\s+of\s+micro\s+and\s+small\s+enterprises",
)
_RE_BS_PAYABLES_OTHER = re.compile(
    r"[Tt]otal\s+outstanding\s+dues\s+of\s+creditors\s+other\s+than\s+micro\s+and\s+small\s+enterprises",
)

# Intangible assets (M-P3.2, ADR-0012). Non-current-assets line, no "current"
# homonym to disambiguate (unlike receivables/inventories), so a plain
# document-wide search is sufficient -- unlike those, no _last_match_before
# anchor is needed. Direct-layout only (verified clean at TCS): the
# deferred-layout non-current-assets block has no verified positional anchor
# equivalent to Cash's fixed Schedule III position among current assets, so
# guessing one would risk exactly the misattribution this codebase avoids —
# under-emit rather than speculate; deferred-layout intangibles are absent,
# not zero, not wrong.
_RE_BS_INTANGIBLE = re.compile(r"^\s*(?:Other )?[Ii]ntangible assets\b(?! under development)", re.MULTILINE)


def _last_match_before(pattern: "re.Pattern[str]", text: str, before: int) -> "re.Match[str] | None":
    """The LAST match of *pattern* strictly before offset *before*, or None.

    Current-assets lines (Inventories, Trade receivables) can appear twice in
    a filing that also reports a non-current/long-duration variant (verified:
    TCS's financial_results filings show a non-current "Trade receivables /
    Billed / Unbilled" block for long-duration contracts, ahead of the
    current-assets one). Cash and cash equivalents is reliably a current-
    assets-only, single-occurrence line (IndAS Schedule III), so anchoring to
    the match immediately preceding it selects the current-assets occurrence
    -- the same anchor-to-Cash discipline the deferred layout already uses
    positionally.
    """
    last: "re.Match[str] | None" = None
    for m in pattern.finditer(text, 0, before):
        last = m
    return last


def _positive(value: float | None) -> float | None:
    """Plausibility floor for working-capital values: a balance-sheet asset
    or liability magnitude is never zero or negative for a going concern.
    Returns None (drop, do not emit) rather than a downgraded-confidence
    fact -- under-emit rather than misattribute, matching the convention
    every other extractor in this codebase already follows."""
    if value is None or value <= 0:
        return None
    return value


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
        # Two balance-sheet layouts exist:
        #   "direct" (TCS style): each label row is immediately followed by
        #     its values → vals[0] is Cash.
        #   "deferred" (Tata Steel style): all current-asset labels appear
        #     first, then all values in the same order.  IndAS Schedule III
        #     always places Cash 4th among current assets (after Inventories,
        #     Investments, Trade receivables) → vals[3] is Cash.
        # Detection: if the text immediately after the Cash label starts with a
        # digit or negative-paren, it is direct format; otherwise deferred.
        remainder = bs_text[m.end():m.end() + 12].lstrip()
        is_direct = bool(remainder) and (
            remainder[0].isdigit()
            or (remainder[0] == "(" and len(remainder) > 1 and remainder[1].isdigit())
        )
        vals = _extract_n_values(bs_text, m.end(), n=6)
        cash_idx = 0 if is_direct else 3
        if vals and len(vals) > cash_idx:
            facts.append(AnalysisFact(
                kind=FactKind.FINANCIAL_CASH_AND_EQUIVALENTS,
                value=vals[cash_idx],
                unit=FactUnit.CRORE_INR,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="balance_sheet",
                    char_offset=bs_start + m.start(),
                    excerpt=_snip(bs_text, m.start()),
                ),
            ))

    # 2 & 3. Equity + Debt: two paths depending on layout.
    if not is_direct:
        # Deferred layout: extract equity and debt algebraically from the
        # E&L values block anchored at "TOTAL - EQUITY AND LIABILITIES".
        facts.extend(_extract_bs_deferred_equity_debt(bs_text, period, bs_start))
    else:
        # Direct layout (TCS style): labels are immediately followed by values.
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

    # 4, 5, 6. Working-capital items: Inventories, Trade receivables (billed-
    # only), Unbilled revenue (M-P3.1, ADR-0012). Cash's own regex match (m,
    # still in scope from step 1) anchors the current-assets region for the
    # direct-layout path.
    cash_m = _RE_BS_CASH.search(bs_text)
    if cash_m:
        if not is_direct:
            # Deferred layout: reuse the SAME positionally-indexed vals[]
            # already computed for Cash above -- Inventories and Trade
            # receivables are already-computed byproducts (IndAS Schedule III
            # order: Inventories, Investments, Trade receivables, Cash), not a
            # new extraction. No Billed/Unbilled split is disclosed in this
            # layout in any verified filing -- vals[2] is the whole figure.
            vals = _extract_n_values(bs_text, cash_m.end(), n=6)
            if vals and len(vals) > 0 and (v := _positive(vals[0])) is not None:
                facts.append(AnalysisFact(
                    kind=FactKind.FINANCIAL_INVENTORIES, value=v, unit=FactUnit.CRORE_INR,
                    period=period, confidence="high",
                    provenance=Provenance(section="balance_sheet", char_offset=bs_start + cash_m.start()),
                ))
            if vals and len(vals) > 2 and (v := _positive(vals[2])) is not None:
                facts.append(AnalysisFact(
                    kind=FactKind.FINANCIAL_TRADE_RECEIVABLES, value=v, unit=FactUnit.CRORE_INR,
                    period=period, confidence="high",
                    provenance=Provenance(section="balance_sheet", char_offset=bs_start + cash_m.start()),
                ))
        else:
            # Direct layout: each label has its own regex, anchored to the
            # occurrence closest to (immediately preceding) Cash, which
            # selects the current-assets block over any non-current homonym
            # (verified: TCS reports a separate non-current Trade receivables
            # / Billed / Unbilled block for long-duration contracts).
            inv_m = _last_match_before(_RE_BS_INVENTORIES, bs_text, cash_m.start())
            if inv_m:
                vals = _extract_n_values(bs_text, inv_m.end(), n=2)
                if vals and (v := _positive(vals[0])) is not None:
                    facts.append(AnalysisFact(
                        kind=FactKind.FINANCIAL_INVENTORIES, value=v, unit=FactUnit.CRORE_INR,
                        period=period, confidence="high",
                        provenance=Provenance(section="balance_sheet", char_offset=bs_start + inv_m.start()),
                    ))

            tr_m = _last_match_before(_RE_BS_TRADE_RECEIVABLES, bs_text, cash_m.start())
            if tr_m:
                # Billed-only: if a Billed sub-line immediately follows this
                # Trade receivables label, extract from there. Otherwise the
                # label itself carries a single (unsplit) value.
                billed_m = _RE_BS_BILLED.search(bs_text, tr_m.end(), tr_m.end() + 50)
                anchor = billed_m if billed_m else tr_m
                vals = _extract_n_values(bs_text, anchor.end(), n=2)
                if vals and (v := _positive(vals[0])) is not None:
                    facts.append(AnalysisFact(
                        kind=FactKind.FINANCIAL_TRADE_RECEIVABLES, value=v, unit=FactUnit.CRORE_INR,
                        period=period, confidence="high",
                        provenance=Provenance(section="balance_sheet", char_offset=bs_start + anchor.start()),
                    ))
                if billed_m:
                    unbilled_m = _RE_BS_UNBILLED.search(bs_text, billed_m.end(), billed_m.end() + 200)
                    if unbilled_m:
                        vals = _extract_n_values(bs_text, unbilled_m.end(), n=2)
                        if vals and (v := _positive(vals[0])) is not None:
                            facts.append(AnalysisFact(
                                kind=FactKind.FINANCIAL_UNBILLED_REVENUE, value=v, unit=FactUnit.CRORE_INR,
                                period=period, confidence="high",
                                provenance=Provenance(section="balance_sheet", char_offset=bs_start + unbilled_m.start()),
                            ))

    # 6b. Intangible assets (M-P3.2). Direct layout only -- see
    # _RE_BS_INTANGIBLE's docstring comment for why deferred layout is
    # deliberately not attempted. Not anchored to cash_m: intangibles has no
    # "current" homonym requiring disambiguation, so a plain search suffices.
    if is_direct:
        intangible_m = _RE_BS_INTANGIBLE.search(bs_text)
        if intangible_m:
            vals = _extract_n_values(bs_text, intangible_m.end(), n=2)
            if vals and (v := _positive(vals[0])) is not None:
                facts.append(AnalysisFact(
                    kind=FactKind.FINANCIAL_INTANGIBLE_ASSETS, value=v, unit=FactUnit.CRORE_INR,
                    period=period, confidence="high",
                    provenance=Provenance(section="balance_sheet", char_offset=bs_start + intangible_m.start()),
                ))

    # 7. Trade payables: Schedule III's mandatory MSME + non-MSME split,
    # summed -- the same iterate-and-sum shape already used for debt above.
    # Layout-independent: the split is a fixed statutory disclosure, not
    # subject to the direct/deferred current-assets ordering convention.
    # Under-emit: only emit when BOTH sub-lines are found -- a partial sum
    # would misstate the total (never misattribute a half-total as the whole).
    msme_m = _RE_BS_PAYABLES_MSME.search(bs_text)
    other_m = _RE_BS_PAYABLES_OTHER.search(bs_text)
    if msme_m and other_m:
        msme_vals = _extract_n_values(bs_text, msme_m.end(), n=2)
        other_vals = _extract_n_values(bs_text, other_m.end(), n=2)
        if msme_vals and other_vals:
            total_payables = msme_vals[0] + other_vals[0]
            if (v := _positive(total_payables)) is not None:
                facts.append(AnalysisFact(
                    kind=FactKind.FINANCIAL_TRADE_PAYABLES, value=v, unit=FactUnit.CRORE_INR,
                    period=period, confidence="high",
                    provenance=Provenance(section="balance_sheet", char_offset=bs_start + msme_m.start()),
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
# Two observed phrasings: "Taxes paid (net of refunds)" (TCS) and "Income
# taxes paid" (Tata Steel, no parenthetical) -- verified against real filings.
_RE_CF_TAX_PAID = re.compile(r"(?:Income )?[Tt]axes? paid(?: \(net of refunds\))?", re.IGNORECASE)


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
    """Extract FINANCIAL_OPERATING_CASH_FLOW, FINANCIAL_CAPEX, and
    FINANCIAL_CASH_TAX_PAID from the cash flow statement in an annual filing.

    FINANCIAL_CAPEX is the absolute value of "Payment for purchase of
    property, plant and equipment" (PP&E only; intangibles excluded).
    FINANCIAL_CASH_TAX_PAID is the absolute value of "Taxes paid (net of
    refunds)" (M-P3.2, ADR-0012) — the cash-basis counterpart to the P&L's
    book-basis FINANCIAL_TOTAL_TAX/FINANCIAL_CURRENT_TAX.
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

    # 3. Taxes paid, cash basis (M-P3.2)
    m = _RE_CF_TAX_PAID.search(cf_text)
    if m:
        vals = _extract_n_values(cf_text, m.end(), n=2)
        if vals and (v := _positive(abs(vals[0]))) is not None:
            facts.append(AnalysisFact(
                kind=FactKind.FINANCIAL_CASH_TAX_PAID,
                value=v,
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
    for name_m in _SEGMENT_NAME_LINE.finditer(region):
        seg_name = name_m.group(1).strip()
        if not _is_segment_candidate(seg_name):
            continue
        values = _extract_n_values(region, name_m.end(), n=6)
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
    for name_m in _SEGMENT_NAME_LINE.finditer(region):
        seg_name = name_m.group(1).strip()
        if not _is_segment_candidate(seg_name):
            continue
        values = _extract_n_values(region, name_m.end(), n=6)
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
# Banking-format detection and extraction
# ---------------------------------------------------------------------------

# Banks file under Banking Regulation Act format — no "Revenue from operations".
# Key identifiers in the P&L: Interest Earned / Net Interest Income, or
# OCR-corrupted equivalents (e.g. "lnt€resU" from scanned SBI PDFs).
_RE_BANKING_ANCHOR = re.compile(
    # Clean text: standard banking P&L labels
    r"Interest\s+Earned"
    r"|Net\s+Interest\s+Income"
    r"|Net\s+Profit\s+for\s+the\s+(?:quarter|year|half)"
    # OCR-corrupted variants: I→l, e→€, other confusions
    r"|[Il]nt[€e]re[s$]t\s+[Ee]arned"
    r"|[Il]nt[€e]re[s$]t\s+[Ii]ncome"
    r"|[Il]nt[€e]re[s$].{0,4}[Dd]iscount",  # "Interest/discount on advances"
    re.IGNORECASE,
)

# Net Profit row label in banking P&L — several phrasings observed across years and OCR engines.
#
# Statutory row (Banking Regulation Act layout):
#   "NET PROFIT/ (LOSS) FROM ORDINARY ACTIVITIES AFTER TAX"   (2025, space in AFTER TAX)
#   "NET PROFIT! (LOSS) FROM ORDINARY ACTIVITIES AFTERTAX"    (2024, ! not /, no space)
#
# Abbreviated cover-letter phrasing (also appears in subsidiary notes — these matches
# are ignored by _extract_n_values because the surrounding prose lines are not purely
# numeric, so they produce no facts even when accidentally matched):
#   "Net Profit for the quarter after tax"
_RE_BANK_PAT = re.compile(
    # Abbreviated form
    r"Net\s+Profit\s+(?:for\s+the\s+(?:period|quarter|year|half|Q\d)|after\s+tax)"
    # Statutory form: NET PROFIT <any punctuation/space up to 80 chars> ORDINARY ACTIVITIES AFTERTAX
    r"|NET\s+PROFIT[^\n]{0,80}ORDINARY\s+ACTIVITIES\s+AFTER\s*TAX",
    re.IGNORECASE,
)


_RE_BANK_ENTITY = re.compile(
    r"\b(?:Bank|BANK|Banking|BANKING)\b",
)


def _is_banking_filing(text: str) -> bool:
    """Return True if the document uses the Banking Regulation Act P&L format.

    Two-stage check:
    1. Direct: "Interest Earned" / "Net Interest Income" present (clean PDFs).
    2. Cover letter: entity identifies itself as a Bank and no "Revenue from
       operations" is present (catches OCR-corrupted banking PDFs).
    """
    no_rev = not bool(re.search(r"Revenue from operations", text[:15000], re.IGNORECASE))
    if not no_rev:
        return False

    # Fast path: readable banking P&L labels present
    if _RE_BANKING_ANCHOR.search(text[:15000]):
        return True

    # Fallback: company name in cover letter contains "Bank" or "Banking"
    # and no manufacturing P&L anchor found — assume Banking Regulation Act format.
    cover = text[:2000]
    return bool(_RE_BANK_ENTITY.search(cover))


def _extract_banking_facts(
    text: str, period_end: str, period_type: str
) -> list[AnalysisFact]:
    """Extract Net Profit from the OCR-corrupted banking-format P&L.

    Banks (Banking Regulation Act) don't use IndAS Schedule III: they have no
    "Revenue from operations" row.  We locate the Net Profit figure directly,
    using the same _extract_n_values column logic, and emit FINANCIAL_PAT.
    All other line items are left for future banking-specific analyzer work.
    """
    facts: list[AnalysisFact] = []
    m = _RE_BANK_PAT.search(text)
    if m is None:
        return facts

    col_idx = _primary_col(period_type, 6)
    vals = _extract_n_values(text, m.end(), n=8)
    if vals and len(vals) > col_idx and vals[col_idx] is not None:
        facts.append(AnalysisFact(
            kind=FactKind.FINANCIAL_PAT,
            value=vals[col_idx],
            unit=FactUnit.CRORE_INR,
            period=period_end,
            confidence="medium",
            provenance=Provenance(
                section="consolidated_pl_table",
                char_offset=m.start(),
                excerpt=_snip(text, m.start()),
            ),
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
        # Check if this is a banking-format filing (no "Revenue from operations")
        if _is_banking_filing(content):
            warnings.append(
                "Banking-format filing detected (Banking Regulation Act layout): "
                "'Revenue from operations' absent; extracting Net Profit only"
            )
            bank_facts = _extract_banking_facts(content, period_end, period_type)
            facts.extend(bank_facts)
            facts.extend(extract_dividend_facts(content, period_end))
            return AnalysisResult(
                evidence_id=evidence_id,
                kind=doc.kind,
                analyzer_version=ANALYZER_VERSION,
                confidence="medium" if bank_facts else "low",
                source_date=datetime.fromisoformat(doc.source_date),
                warnings=warnings,
                facts=facts,
                excerpts=excerpts,
            )
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
