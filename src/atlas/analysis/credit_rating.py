"""Rule-based fact extraction from credit rating and ESG rating disclosures.

Two document formats are handled:

1. ESG rating cover letters (SEBI Reg-30 disclosures)
   Short (~2 kB) cover letters filed with exchanges when a rating agency
   (CRISIL ESG, NSE Sustainability, etc.) publishes or updates a company's
   ESG score.  There is no attached rationale PDF.

   Example sentence:
     "NSE Sustainability has reaffirmed the overall Environmental, Social
      and Governance (ESG) Rating of 73 under the category 'Leader'."

2. Debt credit rating rationale PDFs (CRISIL, ICRA, CARE, India Ratings, Acuite)
   Longer PDFs with a structured instrument table near the top and a narrative
   rationale body.  Multiple instruments may appear in a single document.

   Instrument table row example (CRISIL):
     Long-term Bank Facilities | Rs. 1,000 Crore | CRISIL AAA | Reaffirmed | Stable

   Instrument table row example (ICRA):
     Non-Convertible Debentures | [ICRA]AAA(Stable) | Assigned | INR 2,000 Crore

Fact vocabulary
---------------
CREDIT_AGENCY      one per document; the rating agency name
CREDIT_INSTRUMENT  one per instrument row; type or "ESG"
CREDIT_RATING      one per instrument row; the rating symbol or ESG score
CREDIT_ACTION      one per instrument row; assigned/reaffirmed/upgraded/downgraded/withdrawn
CREDIT_OUTLOOK     one per instrument row; stable/positive/negative/watch/leader/leadership
                   absent for short-term instruments
CREDIT_AMOUNT      one per instrument row; rated ceiling in crore INR
                   absent for ESG / unsolicited ratings

Multi-instrument documents
--------------------------
Per-instrument facts are linked via provenance.section (set to the normalised
instrument type string).  CREDIT_AGENCY uses section = "document".

Confidence
----------
"high"   -- agency + rating + action all extracted
"medium" -- agency + rating extracted but action missing
"low"    -- only agency or only rating found; or nothing useful found
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
# Known agency patterns (case-insensitive; more specific patterns first)
# ---------------------------------------------------------------------------

_AGENCY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # International agencies must appear before generic patterns to avoid
    # "CARE" in surrounding text grabbing priority over "Moody's".
    (re.compile(r"moody['’‘]?s\s+ratings?", re.I), "Moody's"),
    (re.compile(r"moody['’‘]?s", re.I), "Moody's"),
    (re.compile(r"s\s*&\s*p\s+global\s+ratings?", re.I), "S&P Global Ratings"),
    (re.compile(r"s\s*&\s*p\s+global", re.I), "S&P Global"),
    (re.compile(r"\bfitch\b", re.I), "Fitch"),
    (re.compile(r"crisil\s+esg\s+ratings?\s*&?\s*analytics", re.I), "CRISIL ESG"),
    (
        re.compile(r"nse\s+sustainability\s+ratings?\s*&?\s*analytics", re.I),
        "NSE Sustainability",
    ),
    (re.compile(r"\bcrisil\b", re.I), "CRISIL"),
    (re.compile(r"\bicra\b", re.I), "ICRA"),
    (re.compile(r"\bcare\s+ratings?\b", re.I), "CARE Ratings"),
    (re.compile(r"\bcare\b", re.I), "CARE"),
    (re.compile(r"\bindia\s+ratings?\b", re.I), "India Ratings"),
    (re.compile(r"\bacuit[e\xe9]\b", re.I), "Acuite"),
    (re.compile(r"\bbrickwork\b", re.I), "Brickwork"),
    (re.compile(r"\binfomerics\b", re.I), "Infomerics"),
]

# ---------------------------------------------------------------------------
# Rating action keywords
# ---------------------------------------------------------------------------

_ACTION_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bdowngrad", re.I), "downgraded"),
    (re.compile(r"\bupgrad", re.I), "upgraded"),
    (re.compile(r"\bwithdraw", re.I), "withdrawn"),
    (re.compile(r"\breaffirm", re.I), "reaffirmed"),
    (
        re.compile(r"\baffirm", re.I),
        "reaffirmed",
    ),  # S&P uses "affirmed", not "reaffirmed"
    (re.compile(r"\bassign", re.I), "assigned"),
    (re.compile(r"\brevise", re.I), "revised"),  # CARE revision-table disclosures
    (re.compile(r"\bremain", re.I), "reaffirmed"),  # S&P "remains"
    (re.compile(r"\bchange", re.I), "revised"),  # S&P "changed"
]

# ---------------------------------------------------------------------------
# ESG extraction
# ---------------------------------------------------------------------------

# Matches "Rating of 73" or "Rating of 'CRISIL ESG 74'" in ESG cover letters.
# Does NOT require "ESG" as a prefix — real cover letters embed the acronym in
# parentheses: "Environmental, Social and Governance (ESG) Rating of 73", which
# places a closing paren between "ESG" and "Rating" and breaks an ESG-prefix match.
_RE_ESG_SCORE = re.compile(
    r"[Rr]ating\s+of\s+['\"‘’“”]?" r"(CRISIL\s+ESG\s+\d+|\d+)" r"['\"‘’“”]?",
    re.I,
)

# Matches "under the category 'Leader'" or "category 'Leadership'"
_RE_ESG_CATEGORY = re.compile(
    r"category\s+['\"‘’“”]?" r"([A-Za-z][A-Za-z\s\-]{0,30}?)" r"['\"‘’“”]?\s*[,.]",
    re.I,
)

# ---------------------------------------------------------------------------
# Debt rating extraction
# ---------------------------------------------------------------------------

# Matches agency-prefixed rating symbols extracted from a SINGLE TABLE LINE.
# Uses no word-boundary assertion because "[ICRA]" starts with a bracket (non-\w)
# which would fail \b. Single-letter ratings (C, D) are only matched when
# accompanied by an agency prefix to avoid spurious matches in words like
# "Debentures" (D) or "Commercial" (C).
# Moody's long-term scale: Aaa Aa1..Aa3 A1..A3 Baa1..Baa3 Ba1..Ba3 B1..B3 Caa1..Caa3 Ca C
_RE_DEBT_RATING = re.compile(
    r"(?:"
    # Agency-prefixed long-term and short-term ratings (Indian agencies)
    r"\[?(?:CRISIL|ICRA|CARE|IND)\]?\s*"
    r"(?:AAA|AA[+-]?|A[+-](?!\d)|BBB[+-]?|BB[+-]?|B[+-]?|C|D|A[1-4]\+?)"
    r"(?:\s*\([^)]{1,30}\))?"
    # Moody's scale (word-boundary safe; must be whole token)
    r"|(?<!\w)(?:Aaa|Aa[123]|A[123]|Baa[123]|Ba[123]|B[123]|Caa[123]|Ca)(?!\w)"
    # Standalone multi-character ratings without agency prefix (word-boundary safe)
    r"|(?<!\w)(?:AAA|AA[+-]?|A[+-](?!\d)|BBB[+-]?|BB[+-]?|A[1-4]\+?)(?!\w)" r")",
    re.I,
)

# Outlook words (standalone or embedded in "(Stable)")
_RE_OUTLOOK = re.compile(
    r"\b(Stable|Positive|Negative|Watch\s*Positive|Watch\s*Negative|Rating\s*Watch)\b",
    re.I,
)

# Instrument type labels (PDF text may run words together with spaces or hyphens)
_INSTRUMENT_LABELS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"long.?term\s+bank\s+facilit", re.I), "Long-term Bank Facilities"),
    (re.compile(r"short.?term\s+bank\s+facilit", re.I), "Short-term Bank Facilities"),
    (re.compile(r"non.?convertible\s+debenture", re.I), "Non-Convertible Debentures"),
    (re.compile(r"commercial\s+paper", re.I), "Commercial Paper"),
    (re.compile(r"cash\s+credit", re.I), "Cash Credit"),
    (re.compile(r"term\s+loan", re.I), "Term Loan"),
    (re.compile(r"fund.?based\s+limit", re.I), "Fund-Based Limits"),
    (re.compile(r"non.?fund.?based\s+limit", re.I), "Non-Fund-Based Limits"),
    (re.compile(r"letter\s+of\s+credit", re.I), "Letter of Credit"),
    (re.compile(r"bank\s+guarantee", re.I), "Bank Guarantee"),
]

# Rated amount: "Rs. 1,000 Crore", "INR 2,000 Crore", "Rs.500 Cr", number-first OK
_RE_AMOUNT = re.compile(
    r"(?:Rs\.?\s*|INR\s*|₹\s*)([0-9][0-9,]*(?:\.\d+)?)\s*(?:Crore|Cr\.?)\b"
    r"|([0-9][0-9,]{2,}(?:\.\d+)?)\s*(?:Crore|Cr\.?)\b",
    re.I,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _section_key(label: str) -> str:
    return re.sub(r"\W+", "_", label.lower()).strip("_")


def _extract_agency(text: str) -> tuple[str | None, int]:
    for pat, name in _AGENCY_PATTERNS:
        m = pat.search(text)
        if m:
            return name, m.start()
    return None, -1


def _extract_action(text: str) -> tuple[str | None, int]:
    earliest: tuple[str, int] | None = None
    for pat, action in _ACTION_MAP:
        m = pat.search(text)
        if m and (earliest is None or m.start() < earliest[1]):
            earliest = (action, m.start())
    if earliest:
        return earliest[0], earliest[1]
    return None, -1


def _parse_amount(m: re.Match[str]) -> float | None:
    raw = (m.group(1) or m.group(2) or "").replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# ESG path
# ---------------------------------------------------------------------------


def _parse_esg_cover_letter(
    text: str, period: str
) -> tuple[list[AnalysisFact], dict[str, str], list[str]]:
    """Extract facts from an ESG rating cover letter.

    Returns (facts, excerpts, warnings) — pure function, no side effects.
    """
    facts: list[AnalysisFact] = []
    excerpts: dict[str, str] = {}
    warnings: list[str] = []

    m_score = _RE_ESG_SCORE.search(text)
    if m_score:
        raw_score = m_score.group(1).strip()
        facts.append(
            AnalysisFact(
                kind=FactKind.CREDIT_INSTRUMENT,
                value="ESG",
                unit=None,
                period=period,
                confidence="high",
                provenance=Provenance(section="document", char_offset=m_score.start()),
            )
        )
        facts.append(
            AnalysisFact(
                kind=FactKind.CREDIT_RATING,
                value=raw_score,
                unit=None,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="esg",
                    char_offset=m_score.start(),
                    excerpt=text[max(0, m_score.start() - 20) : m_score.end() + 20]
                    .replace("\n", " ")
                    .strip(),
                ),
            )
        )
    else:
        warnings.append("ESG score not found in document")

    m_cat = _RE_ESG_CATEGORY.search(text)
    if m_cat:
        category = m_cat.group(1).strip().lower()
        facts.append(
            AnalysisFact(
                kind=FactKind.CREDIT_OUTLOOK,
                value=category,
                unit=None,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="esg",
                    char_offset=m_cat.start(),
                    excerpt=text[max(0, m_cat.start() - 10) : m_cat.end() + 10]
                    .replace("\n", " ")
                    .strip(),
                ),
            )
        )

    action, act_off = _extract_action(text)
    if action:
        facts.append(
            AnalysisFact(
                kind=FactKind.CREDIT_ACTION,
                value=action,
                unit=None,
                period=period,
                confidence="high",
                provenance=Provenance(section="document", char_offset=act_off),
            )
        )
    else:
        warnings.append("Rating action not found")

    return facts, excerpts, warnings


# ---------------------------------------------------------------------------
# Debt rating path
# ---------------------------------------------------------------------------


def _parse_debt_rationale(
    text: str, period: str
) -> tuple[list[AnalysisFact], dict[str, str], list[str]]:
    """Extract per-instrument facts from a credit rating rationale PDF.

    Rating, outlook, and amount are extracted from the INSTRUMENT LINE ONLY
    to prevent adjacent table rows from contaminating each other's values.
    Action is extracted from a small three-line window because some PDFs place
    the action word on a separate header or sub-header line.

    Returns (facts, excerpts, warnings) — pure function, no side effects.
    """
    facts: list[AnalysisFact] = []
    excerpts: dict[str, str] = {}
    warnings: list[str] = []

    lines = text.splitlines()
    instruments_found: list[str] = []

    for i, line in enumerate(lines):
        instrument_label: str | None = None
        for pat, label in _INSTRUMENT_LABELS:
            if pat.search(line):
                instrument_label = label
                break
        if instrument_label is None:
            continue

        section = _section_key(instrument_label)
        char_off = text.find(line)

        # Rating: from this line only (prevents cross-row contamination)
        m_rating = _RE_DEBT_RATING.search(line)
        rating_val = m_rating.group(0).strip() if m_rating else None

        # Outlook: embedded in rating symbol "AAA(Stable)" first, then standalone
        outlook_val: str | None = None
        if rating_val:
            m_emb = re.search(r"\(([^)]+)\)", rating_val)
            if m_emb:
                outlook_val = m_emb.group(1).strip().lower()
        if outlook_val is None:
            m_out = _RE_OUTLOOK.search(line)
            if m_out:
                outlook_val = m_out.group(1).strip().lower()

        # Amount: from this line only
        m_amt = _RE_AMOUNT.search(line)
        amount_val = _parse_amount(m_amt) if m_amt else None

        # Action: small window (i-1 to i+2) — action word sometimes in header
        ctx = " ".join(lines[max(0, i - 1) : i + 3])
        action_val, _ = _extract_action(ctx)

        facts.append(
            AnalysisFact(
                kind=FactKind.CREDIT_INSTRUMENT,
                value=instrument_label,
                unit=None,
                period=period,
                confidence="high",
                provenance=Provenance(section=section, char_offset=char_off),
            )
        )
        instruments_found.append(instrument_label)

        if rating_val:
            facts.append(
                AnalysisFact(
                    kind=FactKind.CREDIT_RATING,
                    value=rating_val,
                    unit=None,
                    period=period,
                    confidence="high",
                    provenance=Provenance(
                        section=section,
                        char_offset=char_off,
                        excerpt=line[:120],
                    ),
                )
            )

        if outlook_val:
            facts.append(
                AnalysisFact(
                    kind=FactKind.CREDIT_OUTLOOK,
                    value=outlook_val,
                    unit=None,
                    period=period,
                    confidence="high",
                    provenance=Provenance(section=section, char_offset=char_off),
                )
            )

        if amount_val is not None:
            facts.append(
                AnalysisFact(
                    kind=FactKind.CREDIT_AMOUNT,
                    value=amount_val,
                    unit=FactUnit.CRORE_INR,
                    period=period,
                    confidence="high",
                    provenance=Provenance(section=section, char_offset=char_off),
                )
            )

        if action_val:
            facts.append(
                AnalysisFact(
                    kind=FactKind.CREDIT_ACTION,
                    value=action_val,
                    unit=None,
                    period=period,
                    confidence="high",
                    provenance=Provenance(section=section, char_offset=char_off),
                )
            )

    if not instruments_found:
        warnings.append(
            "No instrument table rows found — may be a cover letter or unsupported format"
        )

    _collect_rationale_excerpts(text, excerpts)

    return facts, excerpts, warnings


# ---------------------------------------------------------------------------
# Narrative issuer-rating cover letter path
# ---------------------------------------------------------------------------

# Matches the key sentence in BSE cover letters that disclose a rating action:
#   "S&P Global Ratings affirmed its issuer credit ratings on Tata Steel at 'BBB' with a Stable Outlook"
#   "Moody's upgraded the issuer rating of Tata Steel from 'Baa3 (Stable)' to 'Baa2 (Stable)'"
#   "The issuer credit rating remains 'BBB Stable Outlook'"
_RE_ISSUER_SENTENCE = re.compile(
    r"(?:issuer\s+(?:credit\s+)?rating|credit\s+rating)"
    r".{0,200}"
    r"(?:at|to|remains?)\s+[''\"'‘’“”]?"
    r"([A-Za-z][A-Za-z0-9+\-]*(?:\s*\([^)]{1,30}\))?)"
    r"[''\"'‘’“”]?",
    re.I | re.DOTALL,
)

# After "from X to Y" — captures the NEW (post-action) rating for upgrades/downgrades
_RE_ISSUER_FROM_TO = re.compile(
    r"from\s+[''\"'‘’“”]?[A-Za-z0-9+\-]+(?:\s*\([^)]+\))?[''\"'‘’“”]?"
    r"\s+to\s+[''\"'‘’“”]?"
    r"([A-Za-z][A-Za-z0-9+\-]*(?:\s*\([^)]{1,30}\))?)"
    r"[''\"'‘’“”]?",
    re.I,
)


# ---------------------------------------------------------------------------
# Revision-table path (CARE / India Ratings BSE disclosure format)
# ---------------------------------------------------------------------------

# BSE disclosures for Indian agency downgrades/upgrades use a table:
#   Name | Agency | Type of Credit Rating | Existing | Revised
# The "Revised" cell holds the new rating.  PDF extraction often wraps each
# cell across lines, so we match "Revised" followed by the first rating-like
# token within the next 200 chars.
# Quote chars seen in BSE PDFs (U+0027, U+0022, U+2018, U+2019, U+201C, U+201D).
# Expressed as bytes to avoid encoding issues in the source file.
_QUOTES = b"\x27\x22\xe2\x80\x98\xe2\x80\x99\xe2\x80\x9c\xe2\x80\x9d".decode("utf-8")

_RE_REVISION_CELL = re.compile(
    r"\bRevised\b.{0,400}?"
    r"["
    + re.escape(_QUOTES)
    + r"][A-Za-z][A-Za-z0-9+-]{0,5}["
    + re.escape(_QUOTES)
    + r"]"
    r".{0,200}?"
    r"["
    + re.escape(_QUOTES)
    + r"]([A-Za-z][A-Za-z0-9+-]{0,5})["
    + re.escape(_QUOTES)
    + r"]",
    re.I | re.DOTALL,
)


def _parse_revision_table(
    text: str, period: str
) -> tuple[list[AnalysisFact], list[str]]:
    """Extract facts from the CARE/India Ratings 'Existing → Revised' BSE table.

    Returns (facts, warnings).
    """
    facts: list[AnalysisFact] = []
    warnings: list[str] = []

    m = _RE_REVISION_CELL.search(text[:3000])
    if m is None:
        return facts, warnings

    raw_rating = m.group(1).strip()
    if not _RE_DEBT_RATING.search(raw_rating):
        return facts, warnings

    action_val, act_off = _extract_action(text[:2000])

    # Outlook: search AFTER the revised rating (m.end()), not from m.start().
    # Searching from m.start() would find the Existing column's outlook first.
    window = text[m.end() : m.end() + 120]
    m_out = _RE_OUTLOOK.search(window)
    outlook_val = m_out.group(1).strip().lower() if m_out else None

    facts.append(
        AnalysisFact(
            kind=FactKind.CREDIT_INSTRUMENT,
            value="Long-term",
            unit=None,
            period=period,
            confidence="medium",
            provenance=Provenance(section="revision_table", char_offset=m.start()),
        )
    )
    facts.append(
        AnalysisFact(
            kind=FactKind.CREDIT_RATING,
            value=raw_rating,
            unit=None,
            period=period,
            confidence="medium",
            provenance=Provenance(
                section="revision_table",
                char_offset=m.start(),
                excerpt=window[:80].replace("\n", " ").strip(),
            ),
        )
    )
    if outlook_val:
        facts.append(
            AnalysisFact(
                kind=FactKind.CREDIT_OUTLOOK,
                value=outlook_val,
                unit=None,
                period=period,
                confidence="medium",
                provenance=Provenance(section="revision_table", char_offset=m.start()),
            )
        )
    if action_val:
        facts.append(
            AnalysisFact(
                kind=FactKind.CREDIT_ACTION,
                value=action_val,
                unit=None,
                period=period,
                confidence="medium",
                provenance=Provenance(section="revision_table", char_offset=act_off),
            )
        )

    return facts, warnings


def _parse_narrative_issuer_rating(
    text: str, period: str
) -> tuple[list[AnalysisFact], list[str]]:
    """Extract facts from short BSE cover letters disclosing international agency ratings.

    Handles patterns like:
      - "S&P affirmed its issuer credit ratings on Tata Steel at 'BBB' with a Stable Outlook"
      - "Moody's upgraded the issuer rating from 'Baa3 (Stable)' to 'Baa2 (Stable)'"
      - "The issuer credit rating remains 'BBB Stable Outlook'"

    Returns (facts, warnings).
    """
    facts: list[AnalysisFact] = []
    warnings: list[str] = []

    # Try "from X to Y" pattern first — gives the new (post-action) rating
    m_from_to = _RE_ISSUER_FROM_TO.search(text[:2000])
    if m_from_to:
        raw_rating = m_from_to.group(1).strip()
    else:
        m_at = _RE_ISSUER_SENTENCE.search(text[:2000])
        raw_rating = m_at.group(1).strip() if m_at else None

    if raw_rating is None:
        warnings.append("Narrative issuer rating sentence not found")
        return facts, warnings

    # Validate: must look like a rating symbol
    if not _RE_DEBT_RATING.search(raw_rating):
        warnings.append(
            f"Narrative rating candidate {raw_rating!r} did not match known patterns"
        )
        return facts, warnings

    # Outlook: embedded "Baa2 (Stable)" or standalone keyword
    m_emb = re.search(r"\(([^)]+)\)", raw_rating)
    outlook_val: str | None = None
    if m_emb:
        outlook_val = m_emb.group(1).strip().lower()
    else:
        m_out = _RE_OUTLOOK.search(text[:2000])
        if m_out:
            outlook_val = m_out.group(1).strip().lower()

    # Clean the rating: strip embedded outlook
    clean_rating = re.sub(r"\s*\([^)]+\)", "", raw_rating).strip()

    action_val, act_off = _extract_action(text[:2000])

    facts.append(
        AnalysisFact(
            kind=FactKind.CREDIT_INSTRUMENT,
            value="Issuer",
            unit=None,
            period=period,
            confidence="high",
            provenance=Provenance(section="narrative_cover", char_offset=0),
        )
    )
    excerpt_match = m_from_to or m_at
    facts.append(
        AnalysisFact(
            kind=FactKind.CREDIT_RATING,
            value=clean_rating,
            unit=None,
            period=period,
            confidence="high",
            provenance=Provenance(
                section="narrative_cover",
                char_offset=0,
                excerpt=excerpt_match.group(0)[:120] if excerpt_match else None,
            ),
        )
    )
    if outlook_val:
        facts.append(
            AnalysisFact(
                kind=FactKind.CREDIT_OUTLOOK,
                value=outlook_val,
                unit=None,
                period=period,
                confidence="high",
                provenance=Provenance(section="narrative_cover", char_offset=0),
            )
        )
    if action_val:
        facts.append(
            AnalysisFact(
                kind=FactKind.CREDIT_ACTION,
                value=action_val,
                unit=None,
                period=period,
                confidence="high",
                provenance=Provenance(section="narrative_cover", char_offset=act_off),
            )
        )

    return facts, warnings


def _collect_rationale_excerpts(text: str, excerpts: dict[str, str]) -> None:
    _capture_excerpt(
        excerpts, text, r"key\s+(?:rating\s+)?(?:strengths?|drivers?)", "key_strengths"
    )
    _capture_excerpt(
        excerpts,
        text,
        r"key\s+(?:rating\s+)?(?:concerns?|weaknesses?|risks?)",
        "key_concerns",
    )
    _capture_excerpt(excerpts, text, r"liquidity\s*[:\-]", "liquidity")


def _capture_excerpt(
    excerpts: dict[str, str],
    text: str,
    header_pattern: str,
    key: str,
    window: int = 2000,
) -> None:
    m = re.search(header_pattern, text, re.I)
    if m:
        excerpts[key] = text[m.start() : m.start() + window].strip()


# ---------------------------------------------------------------------------
# Document type detection
# ---------------------------------------------------------------------------

_RE_ESG_SIGNAL = re.compile(
    r"\bESG\s+[Rr]ating|Environmental,?\s+Social\s+and\s+Governance\s+\(?ESG\)?",
    re.I,
)

_RE_DEBT_SIGNAL = re.compile(
    r"(?:long.?term|short.?term|non.?convertible|commercial\s+paper|bank\s+facilit|term\s+loan)",
    re.I,
)


def _is_esg(text: str) -> bool:
    return bool(_RE_ESG_SIGNAL.search(text)) and not bool(_RE_DEBT_SIGNAL.search(text))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured credit/ESG rating facts from a rating disclosure.

    Raises ValueError for missing, wrong-kind, or empty-content documents.
    """
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    if entry.kind != "credit_rating_report":
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: "
            f"kind={entry.kind!r} is not 'credit_rating_report'"
        )

    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: document has no content"
        )

    period = entry.source_date[:10]

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="credit_rating_report",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=datetime.fromisoformat(entry.source_date),
    )

    result.excerpts["cover_letter"] = content[:5000]

    agency, agency_off = _extract_agency(content)
    if agency:
        result.facts.append(
            AnalysisFact(
                kind=FactKind.CREDIT_AGENCY,
                value=agency,
                unit=None,
                period=period,
                confidence="high",
                provenance=Provenance(section="document", char_offset=agency_off),
            )
        )
    else:
        result.warnings.append("Rating agency not identified")

    if _is_esg(content):
        facts, excerpts, warnings = _parse_esg_cover_letter(content, period)
    else:
        facts, excerpts, warnings = _parse_debt_rationale(content, period)
        # If no CREDIT_RATING was extracted, try two fallback paths in order:
        # 1. Revision-table: CARE/India Ratings BSE disclosure table with
        #    "Existing | Revised" columns (often the only rating source).
        # 2. Narrative: S&P/Moody's/Fitch cover letters with a sentence like
        #    "affirmed at 'BBB'" or "upgraded from Baa3 to Baa2".
        if FactKind.CREDIT_RATING not in {f.kind for f in facts}:
            revision_facts, revision_warnings = _parse_revision_table(content, period)
            if revision_facts:
                facts = [
                    f for f in facts if f.kind != FactKind.CREDIT_INSTRUMENT
                ] + revision_facts
                warnings = [w for w in warnings if "No instrument table rows" not in w]
                warnings.extend(revision_warnings)
            else:
                narrative_facts, narrative_warnings = _parse_narrative_issuer_rating(
                    content, period
                )
                if narrative_facts:
                    facts = [
                        f for f in facts if f.kind != FactKind.CREDIT_INSTRUMENT
                    ] + narrative_facts
                    warnings = [
                        w for w in warnings if "No instrument table rows" not in w
                    ]
                    warnings.extend(narrative_warnings)
                else:
                    warnings.extend(revision_warnings)
                    warnings.extend(narrative_warnings)

    result.facts.extend(facts)
    result.excerpts.update(excerpts)
    result.warnings.extend(warnings)

    # Result-level confidence
    extracted_kinds = {f.kind for f in result.facts}
    has_agency = FactKind.CREDIT_AGENCY in extracted_kinds
    has_rating = FactKind.CREDIT_RATING in extracted_kinds
    has_action = FactKind.CREDIT_ACTION in extracted_kinds

    if has_agency and has_rating and has_action:
        result.confidence = "high"
    elif has_agency and has_rating:
        result.confidence = "medium"
    elif has_agency or has_rating:
        result.confidence = "low"

    return result
