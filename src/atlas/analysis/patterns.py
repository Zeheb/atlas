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
