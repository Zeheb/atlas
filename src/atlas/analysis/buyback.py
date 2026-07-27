"""Rule-based fact extraction from SEBI Reg 30 buyback filings.

Four document sub-types are recognised by scanning cover letter signals:

  Announcement       — "Public Announcement for Buyback" with terms in the cover letter.
                       Extracts: total amount, price per share, max shares offered.

  Post-announcement  — "Post Buyback Public Announcement".
                       Extracts: total amount, price per share, max shares, record date.

  Extinguishment     — "Completion of extinguishment" notice.
                       Extracts: shares actually bought back and extinguished.

  Schedule           — Schedule of activities / timeline update letter.
                       Extracts: record date.

If none of the above signals are found, the document is classified as an
opaque filing (e.g. a cover letter that merely encloses a newspaper announcement
with no terms in the letter itself). A warning is emitted and no facts are extracted.

Number format notes
-------------------
Indian-format numbers like "4,09,63,855" are parsed by stripping all commas,
which is equivalent to removing grouping separators regardless of locale.
The Indian Rupee sign (₹, U+20B9) is used directly in regex patterns; it
appears reliably in text extracted from 2023-era TCS PDFs.
"""

from __future__ import annotations

import re
from datetime import datetime

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    _fact,
)
from atlas.analysis.patterns import parse_indian_float, parse_indian_int, parse_iso_date
from atlas.knowledge.base import KnowledgeBase

ANALYZER_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Cover letter window — most key facts appear in the first 3 000 chars
# ---------------------------------------------------------------------------

_COVER_WINDOW = 3_000

# ---------------------------------------------------------------------------
# Document sub-type detection
# ---------------------------------------------------------------------------

_RE_IS_EXTINGUISHMENT = re.compile(
    r"extinguishment\s+of.*?equity\s+shares",
    re.IGNORECASE | re.DOTALL,
)
_RE_IS_POST_ANNOUNCEMENT = re.compile(
    r"Post\s+Buyback\s+Public\s+Announcement",
    re.IGNORECASE,
)
_RE_IS_ANNOUNCEMENT = re.compile(
    r"Public\s+Announcement\s+for\s+Buyback",
    re.IGNORECASE,
)
_RE_IS_SCHEDULE = re.compile(
    r"Schedule\s+of\s+(?:A|a)ctivities|record\s+date\s+for\s+this\s+purpose",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Extraction patterns
# ---------------------------------------------------------------------------

# Max shares targeted: "buyback up to 4,09,63,855 ... equity shares"
# Also matches "buyback of 4,09,63,855 ... equity shares" (post-announcement phrasing)
_RE_SHARES_OFFERED = re.compile(
    r"buyback\s+(?:up\s+to\s+|of\s+)([\d,]+)"
    r"[\s\S]{0,200}?"
    r"(?:fully\s+paid[- ]up\s+)?equity\s+shares",
    re.IGNORECASE,
)

# Price per share: "at ₹4,150 (Rupees...) per equity share"
# or: "at a price of ₹4,150 ... per Equity Share"
# Parenthetical after the number is optional.
_RE_PRICE = re.compile(
    r"at\s+(?:a\s+price\s+of\s+)?₹\s*([\d,]+)"
    r"(?:\s+\([^)]{0,80}\))?"
    r"\s+per\s+(?:equity\s+)?share",
    re.IGNORECASE,
)

# Total amount: "aggregate amount/consideration not exceeding ₹17,000 crore"
_RE_AMOUNT = re.compile(
    r"not\s+exceeding\s+₹\s*([\d,]+)\s*crore",
    re.IGNORECASE,
)

# Record date — two formulations:
# 1. "Record Date  (i.e. Saturday, November 25, 2023)"
_RE_RECORD_DATE_IE = re.compile(
    r"Record\s+Date[\s\S]{0,40}?\(i\.e\.[\s\S]{0,40}?(\w+ \d+,?\s*\d{4})\)",
    re.IGNORECASE,
)
# 2. "record date for this purpose is November 28, 2020"
_RE_RECORD_DATE_IS = re.compile(
    r"record\s+date\s+for\s+this\s+purpose\s+is\s+(\w+\s+\d+,?\s*\d{4})",
    re.IGNORECASE,
)

# Shares extinguished:
# From subject: "extinguishment of a total of 4,09,63,855 Equity Shares"
_RE_SHARES_EXT_SUBJECT = re.compile(
    r"extinguishment\s+of\s+(?:a\s+total\s+of\s+)?([\d,]+)\s+Equity\s+Shares",
    re.IGNORECASE,
)
# From table: "Total Number of Equity Shares Extinguished/ Destroyed (A + B)  4,09,63,855"
_RE_SHARES_EXT_TABLE = re.compile(
    r"Total\s+Number\s+of\s+Equity\s+Shares\s+Extinguished[^\d]*([\d,]+)",
    re.IGNORECASE | re.DOTALL,
)
# From CDSL confirmation: "bought back 40963855 Equity Shares"
_RE_SHARES_BOUGHT_BACK = re.compile(
    r"has\s+bought\s+back\s+([\d,]+)\s+Equity\s+Shares",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Sub-type extraction helpers
# ---------------------------------------------------------------------------


def _extract_terms(cover: str) -> tuple[list[AnalysisFact], list[str]]:
    """Extract amount, price per share, and max shares from a cover letter."""
    facts: list[AnalysisFact] = []
    warnings: list[str] = []

    m = _RE_SHARES_OFFERED.search(cover)
    if m:
        n = parse_indian_int(m.group(1))
        if n is not None:
            facts.append(
                _fact(
                    FactKind.CAPITAL_BUYBACK_SHARES_OFFERED,
                    n,
                    FactUnit.COUNT,
                    "cover_letter",
                    cover,
                    m.start(1),
                )
            )
        else:
            warnings.append(f"Could not parse shares offered: {m.group(1)!r}")
    else:
        warnings.append("Max shares offered not found in cover letter")

    m = _RE_PRICE.search(cover)
    if m:
        v = parse_indian_float(m.group(1))
        if v is not None:
            facts.append(
                _fact(
                    FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE,
                    v,
                    FactUnit.RUPEES_PER_SHARE,
                    "cover_letter",
                    cover,
                    m.start(1),
                )
            )
        else:
            warnings.append(f"Could not parse price per share: {m.group(1)!r}")
    else:
        warnings.append("Price per share not found in cover letter")

    m = _RE_AMOUNT.search(cover)
    if m:
        v = parse_indian_float(m.group(1))
        if v is not None:
            facts.append(
                _fact(
                    FactKind.CAPITAL_BUYBACK_AMOUNT,
                    v,
                    FactUnit.CRORE_INR,
                    "cover_letter",
                    cover,
                    m.start(1),
                )
            )
        else:
            warnings.append(f"Could not parse total buyback amount: {m.group(1)!r}")
    else:
        warnings.append("Total buyback amount not found in cover letter")

    return facts, warnings


def _extract_record_date(text: str) -> tuple[AnalysisFact | None, str | None]:
    """Try both record-date formulations; return (fact, warning) pair."""
    for pat, section in [
        (_RE_RECORD_DATE_IE, "cover_letter"),
        (_RE_RECORD_DATE_IS, "cover_letter"),
    ]:
        m = pat.search(text)
        if m:
            iso = parse_iso_date(m.group(1))
            if iso:
                return (
                    _fact(
                        FactKind.CAPITAL_BUYBACK_RECORD_DATE,
                        iso,
                        FactUnit.ISO_DATE,
                        section,
                        text,
                        m.start(1),
                    ),
                    None,
                )
            return None, f"Could not parse record date: {m.group(1)!r}"
    return None, "Record date not found"


def _extract_shares_bought(text: str) -> tuple[AnalysisFact | None, str | None]:
    """Extract shares extinguished from an extinguishment notice."""
    # Try table total first (most authoritative)
    for pat in (_RE_SHARES_EXT_TABLE, _RE_SHARES_EXT_SUBJECT, _RE_SHARES_BOUGHT_BACK):
        m = pat.search(text)
        if m:
            n = parse_indian_int(m.group(1))
            if n is not None:
                return (
                    _fact(
                        FactKind.CAPITAL_BUYBACK_SHARES_BOUGHT,
                        n,
                        FactUnit.COUNT,
                        "cover_letter",
                        text,
                        m.start(1),
                    ),
                    None,
                )
    return None, "Shares extinguished count not found"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured facts from a SEBI Reg 30 buyback filing."""
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    if entry.kind != "buyback":
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: "
            f"kind={entry.kind!r} is not 'buyback'"
        )

    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: document has no content"
        )

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="buyback",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=datetime.fromisoformat(entry.source_date),
    )
    result.excerpts["cover_letter"] = content[:_COVER_WINDOW].strip()

    cover = content[:_COVER_WINDOW]

    # --- Detect sub-type and dispatch ---
    if _RE_IS_EXTINGUISHMENT.search(cover):
        # Extinguishment / completion notice
        fact, warn = _extract_shares_bought(content)
        if fact:
            result.facts.append(fact)
            result.confidence = "high"
        else:
            if warn:
                result.warnings.append(warn)
            result.confidence = "medium"

    elif _RE_IS_POST_ANNOUNCEMENT.search(cover):
        # Post-buyback public announcement — has terms + record date
        term_facts, term_warnings = _extract_terms(cover)
        result.facts.extend(term_facts)
        result.warnings.extend(term_warnings)

        rec_fact, rec_warn = _extract_record_date(cover)
        if rec_fact:
            result.facts.append(rec_fact)
        else:
            if rec_warn:
                result.warnings.append(rec_warn)

        core_kinds = {f.kind for f in result.facts}
        if (
            FactKind.CAPITAL_BUYBACK_AMOUNT in core_kinds
            and FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE in core_kinds
        ):
            result.confidence = "high"
        else:
            result.confidence = "medium"

    elif _RE_IS_ANNOUNCEMENT.search(cover):
        # Public announcement — terms should be in the cover letter
        term_facts, term_warnings = _extract_terms(cover)
        result.facts.extend(term_facts)
        result.warnings.extend(term_warnings)

        core_kinds = {f.kind for f in result.facts}
        if (
            FactKind.CAPITAL_BUYBACK_AMOUNT in core_kinds
            and FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE in core_kinds
        ):
            result.confidence = "high"
        elif result.facts:
            result.confidence = "medium"
        else:
            result.warnings.append(
                "Buyback terms not found in cover letter — "
                "the announcement may be enclosed as a newspaper attachment "
                "whose text is not reliably extractable"
            )

    elif _RE_IS_SCHEDULE.search(cover):
        # Schedule of activities / record date update
        rec_fact, rec_warn = _extract_record_date(content)
        if rec_fact:
            result.facts.append(rec_fact)
            result.confidence = "high"
        else:
            if rec_warn:
                result.warnings.append(rec_warn)
            result.confidence = "medium"

    else:
        result.warnings.append(
            "Document sub-type not recognised — "
            "could not identify as announcement, post-announcement, "
            "extinguishment notice, or schedule update"
        )

    return result
