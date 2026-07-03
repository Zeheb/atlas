"""Shared extraction helpers for the analysis layer.

Only helpers that are already duplicated across two or more analyzers, or that
are clearly required by the next three to five planned analyzers, live here.
Speculative utilities belong in the analyzer that first needs them.

Contents
--------
parse_iso_date          "Month D, YYYY" / "Month DD YYYY" → ISO date string.
                        Month-dict approach — more permissive than strptime
                        (handles no-comma dates and abbreviated month names).

split_reg30_sections    Split a Regulation 30 filing into (cover, annexure_a,
                        annexure_b) by the "Annexure - A / B" heading markers.

fiscal_year_end         Derive the Indian FY end (March 31) from a filing date.

extract_dividend_facts  Pull all four CAPITAL_DIVIDEND_* facts from a cover
                        letter window; shared by financial_results and
                        board_outcome.

parse_indian_int        Strip Indian-format commas and parse an integer.
parse_indian_float      Strip Indian-format commas and parse a float.

fix_ocr_numbers         Recover Indian-format numbers mangled by OCR comma/period
                        confusion; shared by financial_results and
                        investor_presentation.
parse_number            Parse a single numeric token, handling "(123)" negatives
                        and "-" as nil/zero.
extract_n_values        Collect up to n numeric values from a table row window,
                        stopping at the next non-numeric label line.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from atlas.analysis.base import (
    AnalysisFact,
    FactKind,
    FactUnit,
    Provenance,
    _snip,
)

# ---------------------------------------------------------------------------
# parse_iso_date
# ---------------------------------------------------------------------------

_MONTH_ABBR: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_RE_MONTH_D_Y = re.compile(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE)


def parse_iso_date(text: str) -> str | None:
    """Search text for 'Month D(D)(,) YYYY' and return 'YYYY-MM-DD', or None.

    More permissive than strptime: accepts no-comma dates ("November 5 2024")
    and is unaffected by surrounding punctuation.  Only full month names are
    matched (no three-letter abbreviations), which is correct for all SEBI
    filings observed to date.
    """
    m = _RE_MONTH_D_Y.search(text.strip())
    if not m:
        return None
    month_name, day, year = m.group(1).lower(), int(m.group(2)), int(m.group(3))
    month_num = _MONTH_ABBR.get(month_name)
    if month_num is None:
        return None
    return f"{year:04d}-{month_num:02d}-{day:02d}"


# ---------------------------------------------------------------------------
# split_reg30_sections
# ---------------------------------------------------------------------------

_RE_ANNEXURE_A = re.compile(r"Annexure\s*[-–]?\s*A\b\s*\n", re.IGNORECASE)
_RE_ANNEXURE_B = re.compile(r"Annexure\s*[-–]?\s*B\b\s*\n", re.IGNORECASE)


def split_reg30_sections(text: str) -> tuple[str, str, str]:
    """Split a SEBI Reg 30 filing into (cover_letter, annexure_a, annexure_b).

    Matches section headings of the form "Annexure - A\\n" (with optional
    em/en dash and optional spaces), so that inline references like
    "enclosed as Annexure A." do not trigger a split.

    Returns empty strings for sections not present in the document.
    """
    m_a = _RE_ANNEXURE_A.search(text)
    if m_a is None:
        return text, "", ""
    m_b = _RE_ANNEXURE_B.search(text, m_a.end())
    cover = text[: m_a.start()]
    if m_b is None:
        return cover, text[m_a.start():], ""
    return cover, text[m_a.start(): m_b.start()], text[m_b.start():]


# ---------------------------------------------------------------------------
# fiscal_year_end
# ---------------------------------------------------------------------------

def fiscal_year_end(source_date: str) -> str:
    """Return the Indian FY end date (March 31) for the year containing source_date.

    The Indian fiscal year ends on March 31.  Annual reports and any document
    that needs to be pinned to a fiscal year can use this to derive the period
    without parsing the document itself.

    Examples:
      "2024-05-08T..." → "2024-03-31"  (filed after Mar 31 2024)
      "2024-01-15T..." → "2023-03-31"  (filed before Mar 31 2024)
    """
    dt = datetime.fromisoformat(source_date)
    fy = date(dt.year, 3, 31)
    if dt.date() < fy:
        fy = date(dt.year - 1, 3, 31)
    return fy.isoformat()


# ---------------------------------------------------------------------------
# extract_dividend_facts
# ---------------------------------------------------------------------------

# "declared/recommended [second/third/...] [interim/final/special] dividend of INR X"
_RE_DIV_DECLARED = re.compile(
    r"(interim|final|special)\s+dividend\s+of\s+INR\s+([\d.]+)",
    re.IGNORECASE,
)

# Record date — two formulations seen in BSE filings:
# 1. Date precedes the label: "as on October 18, 2024, which is the Record Date"
# 2. Label precedes the date: "Record Date fixed for ... October 18, 2024"
_RE_DIV_RECORD = re.compile(
    r"(\w+ \d+,\s*\d{4})[^.]{0,60}?Record Date"
    r"|Record Date[^.]{0,60}?(\w+ \d+,\s*\d{4})",
    re.IGNORECASE,
)

# Payment date: "paid on Tuesday, November 5, 2024"
_RE_DIV_PAYMENT = re.compile(
    r"paid\s+on\s+(?:\w+,\s+)?(\w+ \d+,\s*\d{4})",
    re.IGNORECASE,
)

_DATE_FMT = "%B %d, %Y"


def extract_dividend_facts(
    cover_text: str,
    period: str | None,
) -> list[AnalysisFact]:
    """Extract CAPITAL_DIVIDEND_* facts from a cover letter window.

    cover_text should already be sliced to the appropriate window (e.g.
    text[:3000]).  The function does not re-slice; callers control the window.

    Returns all dividend facts found.  For final dividends pending AGM approval
    the payment date fact is typically absent (no explicit date in the filing).
    """
    facts: list[AnalysisFact] = []

    for m in _RE_DIV_DECLARED.finditer(cover_text):
        div_type = m.group(1).lower()
        try:
            amount = float(m.group(2))
        except ValueError:
            continue
        prov = Provenance(
            section="cover_letter",
            char_offset=m.start(),
            excerpt=_snip(cover_text, m.start()),
        )
        facts.append(AnalysisFact(
            kind=FactKind.CAPITAL_DIVIDEND_PER_SHARE,
            value=amount,
            unit=FactUnit.RUPEES_PER_SHARE,
            period=period,
            confidence="high",
            provenance=prov,
        ))
        facts.append(AnalysisFact(
            kind=FactKind.CAPITAL_DIVIDEND_TYPE,
            value=div_type,
            unit=None,
            period=period,
            confidence="high",
            provenance=prov,
        ))

    m_rec = _RE_DIV_RECORD.search(cover_text)
    if m_rec:
        raw_date = m_rec.group(1) or m_rec.group(2)
        try:
            raw = re.sub(r"\s+", " ", raw_date)
            rec_date = datetime.strptime(raw, _DATE_FMT).date().isoformat()
            facts.append(AnalysisFact(
                kind=FactKind.CAPITAL_DIVIDEND_RECORD_DATE,
                value=rec_date,
                unit=FactUnit.ISO_DATE,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="cover_letter",
                    char_offset=m_rec.start(),
                    excerpt=_snip(cover_text, m_rec.start()),
                ),
            ))
        except ValueError:
            pass

    m_pay = _RE_DIV_PAYMENT.search(cover_text)
    if m_pay:
        try:
            raw = re.sub(r"\s+", " ", m_pay.group(1))
            pay_date = datetime.strptime(raw, _DATE_FMT).date().isoformat()
            facts.append(AnalysisFact(
                kind=FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE,
                value=pay_date,
                unit=FactUnit.ISO_DATE,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="cover_letter",
                    char_offset=m_pay.start(),
                    excerpt=_snip(cover_text, m_pay.start()),
                ),
            ))
        except ValueError:
            pass

    return facts


# ---------------------------------------------------------------------------
# parse_indian_int / parse_indian_float
# ---------------------------------------------------------------------------

def parse_indian_int(s: str) -> int | None:
    """Parse an integer from Indian-format text by stripping all commas.

    "4,09,63,855" → 40963855.  Also handles Western comma-grouping and
    surrounding whitespace.  Returns None if the result is not a valid integer.
    """
    try:
        return int(s.replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def parse_indian_float(s: str) -> float | None:
    """Parse a float from Indian-format text by stripping all commas.

    "1,26,872.50" → 126872.5.  Returns None on parse failure.
    """
    try:
        return float(s.replace(",", "").replace(" ", ""))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# fix_ocr_numbers / parse_number / extract_n_values
# ---------------------------------------------------------------------------

_MAX_VALUE_SCAN = 1500

# Matches: (123) for negatives, - for nil, or Indian-format numbers like 1,26,872
_RE_NUM_TOKEN = re.compile(
    r"\([\d,]+(?:\.\d+)?\)"   # (123) = negative
    r"|(?<!\w)-(?!\w)"        # standalone dash = nil/zero
    r"|[\d,]+(?:\.\d+)?"      # positive number with optional decimal
)

# OCR artifact patterns: some PDFs replace comma thousands-separators with
# periods, producing "58.216.04" (two periods) or "34.228 34" (period+space).
# Indian lakh-crore numbers use two separators: "1,10,960.11" → "1.10.960.11".
# Sometimes only one separator is corrupted, mixing period and comma:
#   2,16,840.35 → 2.16,840.35 (first comma → period, second stays)
#   2,27,296.20 → 2,27.296.20 (second comma → period, first stays)
_RE_OCR_MIX_PERIOD_COMMA = re.compile(
    # First separator corrupted: X.XX,XXX.XX
    r"(?<!\d)(\d{1,2})\.(\d{2}),(\d{3})\.(\d{2})(?!\d)"
)
_RE_OCR_TRIPLE_PERIOD = re.compile(
    r"(?<!\d)(\d{1,2})\.(\d{2})\.(\d{3})\.(\d{2})(?!\d)"
)
_RE_OCR_DOUBLE_PERIOD = re.compile(
    r"(?<!\d)(\d+)\.(\d{3})\.(\d{2})(?!\d)"
)
_RE_OCR_SPACE_DECIMAL = re.compile(
    r"(?<!\d)(\d+)\.(\d{3}) (\d{2})(?!\d)"
)
# "68.55L.81" is OCR for "68,551.81": the digit "1" was read as "L".
# Match: a digit immediately followed by L and then a digit-or-period.
_RE_OCR_L_AS_1 = re.compile(r"(?<=\d)L(?=[.\d])")


def fix_ocr_numbers(text: str) -> str:
    """Recover Indian-format numbers mangled by OCR (comma → period artifact).

    Handles four manifestations (all seen in Tata Steel BSE filings):
      2,16,840.35 → 2.16,840.35  (first comma only → period)  → restored
      1,10,960.11 → 1.10.960.11  (all commas → periods)       → restored
      58,216.04   → 58.216.04    (one comma → period)          → restored
      34,228.34   → 34.228 34    (period then space fragment)  → restored
    The second-comma-only variant (2,27.296.20) is caught by DOUBLE_PERIOD
    matching the "27.296.20" sub-string.
    """
    text = _RE_OCR_L_AS_1.sub("1", text)
    text = _RE_OCR_MIX_PERIOD_COMMA.sub(r"\1,\2,\3.\4", text)
    text = _RE_OCR_TRIPLE_PERIOD.sub(r"\1,\2,\3.\4", text)
    text = _RE_OCR_DOUBLE_PERIOD.sub(r"\1,\2.\3", text)
    text = _RE_OCR_SPACE_DECIMAL.sub(r"\1,\2.\3", text)
    return text


def parse_number(s: str) -> float | None:
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


def extract_n_values(text: str, after: int, n: int = 6) -> list[float | None]:
    """Collect up to n numeric values starting at text[after:].

    Stops at the first non-numeric, non-blank line encountered after values
    have started accumulating (i.e., the next table label row).

    Applies OCR artifact correction before tokenising, so comma-as-period
    mangling (common in older Tata Steel / BSE PDF extractions) does not
    fragment large numbers into spurious decimals.
    """
    values: list[float | None] = []
    segment = fix_ocr_numbers(text[after: after + _MAX_VALUE_SCAN])
    collecting = False

    for line in segment.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        tokens = _RE_NUM_TOKEN.findall(line)
        if tokens:
            # Require the line to be purely numeric (no leftover text after
            # removing all matched tokens).  Section markers like
            # "(3) Assets held for sale" and headers like "TOTAL - ASSETS"
            # both have residual text and must not trigger collection.
            non_token = _RE_NUM_TOKEN.sub("", line).strip()
            # Strip OCR table-border artefacts: Tesseract reads ruling lines
            # as '|' or ']' glyphs appended to numeric cells, e.g. "20,159.67]"
            # or "19,160.44 |".  These are not content and must not block collection.
            non_token = re.sub(r"[|\[\]_]+", "", non_token).strip()
            if non_token:
                if collecting:
                    break
                continue
            collecting = True
            for t in tokens:
                if len(values) >= n:
                    return values
                v = parse_number(t)
                if v is not None:
                    values.append(v)
        elif collecting:
            # Non-numeric non-blank line after values started = next row label
            break
    return values
