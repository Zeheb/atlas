"""Rule-based fact extraction from parsed annual report text.

Extracts durable structured facts and verbatim excerpts from an annual
report document.  Does not compare across documents.

Section detection uses a two-level TOC-skip strategy:

1. If the first non-blank content after a header match is a bare page number
   *and* the item following that page number is *also* followed by a page
   number (i.e., the ``text → num → text → num`` TOC pattern), the match is
   skipped as a table-of-contents entry.

2. If the first non-blank content is a bare page number but the content
   *after* that page number is prose (not another ``text/num`` pair), the
   match is a running page header inside the section body and is accepted,
   using the prose content that follows the page number.

This handles the common Indian PDF structure where section names appear both
in the TOC and as running headers on every body page.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    EntityMention,
    FactKind,
    FactUnit,
    Provenance,
    _snip,
)
from atlas.analysis.patterns import extract_n_values, fiscal_year_end
from atlas.knowledge.base import KnowledgeBase
from atlas.knowledge.entities import EntityResolver

ANALYZER_VERSION = "3.3"

# Director identity (M-P1.4, narrowed): only CLEAN "Name (DIN 12345678)"
# adjacencies. The name is 2-4 Title-case tokens immediately before the DIN
# (an honorific like "Dr" allowed as a lead token); the DIN is exactly 8
# digits (leading zeros preserved). Age and tenure are deliberately NOT
# extracted — the AR corporate-governance section presents them as category-
# level aggregates or dissociated OCR columns that cannot be bound to a named
# director, so binding them would misattribute (see the M-P1.4 execution note
# in the Atlas Evaluation Matrix). Under-emit rather than misattribute.
_RE_DIRECTOR_DIN = re.compile(
    r"((?:Dr|Mr|Ms|Mrs|Shri|Smt)?\.?\s*"
    r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z.]+){1,3})"
    r"\s*\(\s*DIN[:\s]*(\d{8})\s*\)"
)


# Gross block of property, plant and equipment (M-P3.2, ADR-0012), from the
# AR's 10-year financial-highlights table -- a single labeled row, most-recent
# year first, verified clean at TCS. The label wraps mid-phrase across a line
# break ("property, \nplant and equipment"), hence \s+ between the two halves.
#
# Deliberately NOT extracted from Tata Steel's PP&E movement/reconciliation
# schedule (opening/closing "Gross block as at [date]" rows with a per-
# asset-class column breakdown and a final "Total" column): tested directly
# against real text and found unreliable -- two consecutive unlabeled rows
# concatenate with no detectable boundary between them, and a "last value
# before the next row label" heuristic returned the WRONG total (a value from
# the second row, not the first row's own Total). Under-emit rather than ship
# a heuristic already shown to produce a wrong number: absent for
# movement-schedule-only filings, not zero, not guessed.
_RE_GROSS_BLOCK = re.compile(r"Gross block of property,\s*plant and equipment", re.IGNORECASE)


def _extract_gross_block(content: str, period: str) -> AnalysisFact | None:
    m = _RE_GROSS_BLOCK.search(content)
    if m is None:
        return None
    vals = extract_n_values(content, m.end(), n=1)
    if not vals or vals[0] is None or vals[0] <= 0:
        return None
    return AnalysisFact(
        kind=FactKind.FINANCIAL_GROSS_BLOCK,
        value=vals[0],
        unit=FactUnit.CRORE_INR,
        period=period,
        confidence="high",
        provenance=Provenance(
            section="financial_highlights",
            char_offset=m.start(),
            excerpt=_snip(content, m.start()),
        ),
    )


# Related-party aggregate balance (M-P3.3, ADR-0012), from the notes-to-
# accounts "Loans to related parties" line -- verified across 9/25 real Tata
# Steel filings, real varying multi-year values, single clean label + a
# 2-value comparative pair.
#
# Deliberately NOT the per-counterparty transaction table (TCS's "related
# party transactions are as follows" note): that table has an open-ended,
# not-fully-observed category vocabulary, a variable value-count per row (some
# rows carry one value, not two), and the same counterparty recurs under
# different categories in the same period -- a real collision risk without a
# category scanner this milestone does not build. Deferred, not guessed.
#
# A dedicated regex, NOT `extract_n_values`: this table's own nil-convention
# writes a disclosed zero as a bare "-", which `extract_n_values` either
# silently skips (misattributing the next real number to the wrong period) or
# treats as a stop condition once collection has started -- tested directly
# and confirmed wrong before writing this. The label appears twice per filing
# (non-current, then current); only the first (non-current) occurrence is
# read, matching the "always read the first/current column" convention
# already established for FINANCIAL_CASH_AND_EQUIVALENTS -- summing the two
# sections was not attempted, since that would guess a semantic (is a
# combined current+non-current total meaningful here?) this pass did not verify.
_RE_RPT_BALANCE = re.compile(
    r"Loans to related parties\n(?:Considered good - Unsecured\n)?([\d,]+(?:\.\d+)?|-)\n([\d,]+(?:\.\d+)?|-)"
)


def _parse_rpt_amount(token: str) -> float:
    """"-" is a disclosed nil, not a missing value -- 0.0 is the correct
    figure here (the company genuinely reports zero), not an extraction gap."""
    return 0.0 if token.strip() == "-" else float(token.replace(",", ""))


def _extract_rpt_balance(content: str, period: str) -> list[AnalysisFact]:
    m = _RE_RPT_BALANCE.search(content)
    if m is None:
        return []
    amount = _parse_rpt_amount(m.group(1))
    prov = Provenance(section="rpt_row_0", char_offset=m.start(), excerpt=_snip(content, m.start()))
    return [
        AnalysisFact(
            kind=FactKind.GOVERNANCE_RPT_BALANCE_AMOUNT,
            value=amount, unit=FactUnit.CRORE_INR, period=period,
            confidence="high", provenance=prov,
        ),
        AnalysisFact(
            kind=FactKind.GOVERNANCE_RPT_CATEGORY,
            value="Loans to related parties", unit=None, period=period,
            confidence="high", provenance=prov,
        ),
    ]


def _extract_directors(content: str, resolver: EntityResolver) -> list[EntityMention]:
    """Resolve directors named with a clean adjacent DIN. One EntityMention per
    distinct (entity, DIN); role="director", identifier=DIN. No age/tenure."""
    mentions: list[EntityMention] = []
    seen: set[tuple[str, str]] = set()
    for m in _RE_DIRECTOR_DIN.finditer(content):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        name = re.sub(r"^(?:Dr|Mr|Ms|Mrs|Shri|Smt)\.?\s+", "", name)
        din = m.group(2)
        entity = resolver.resolve(name, "person")
        key = (entity.entity_id, din)
        if key in seen:
            continue
        seen.add(key)
        mentions.append(EntityMention(
            entity=entity,
            role="director",
            affiliation=None,
            identifier=din,
            provenance=Provenance("corporate_governance", m.start(), _snip(content, m.start())),
        ))
    return mentions

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_SECTION_CHARS = 80_000   # chars to capture from a section header onward
_MIN_SECTION_CONTENT = 200

# ---------------------------------------------------------------------------
# Section header patterns
#
# Both ASCII apostrophe (U+0027) and Unicode right single quotation mark
# (U+2019) are accepted.  TCS PDFs consistently use U+2019, which breaks
# naïve ASCII-only patterns.
# ---------------------------------------------------------------------------

_APO = r"[’']"

_RE_BOARDS_REPORT = re.compile(rf"Board{_APO}s\s+Report", re.IGNORECASE)
_RE_DIRS_REPORT = re.compile(rf"Directors{_APO}\s+Report", re.IGNORECASE)
_RE_MDA = re.compile(r"Management\s+Discussion\s+and\s+Analysis", re.IGNORECASE)
_RE_AUDITOR_CONSOL = re.compile(
    # Standard: "Independent Auditors' Report" (IndAS manufacturing/services)
    # Banking: "Statutory Central Auditors' Report" / "Report of the Auditors" (Banking Regulation Act)
    rf"(?:Independent|Statutory(?:\s+Central)?)\s+Auditor{_APO}s?\s+Report"
    r"|Report\s+of\s+the\s+(?:Statutory\s+)?(?:Central\s+)?Auditors?",
    re.IGNORECASE,
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

# ---------------------------------------------------------------------------
# Fact extraction patterns
# ---------------------------------------------------------------------------

# Mandatory CSR disclosure (Companies Act s.135 annual table in Board's Report).
# Backtick (`) appears as a rupee-symbol OCR artefact in older filings.
# \x07 (BEL) is a stray control character seen in some PDF extractions.
# Banking format: "Total CSR Expenditure" in summary highlight box (no "(a)" label).
_RE_CSR_SPEND = re.compile(
    r"\(a\)\s+(?:\x07\s*)?Amount\s+spent\s+on\s+CSR\s+Projects?"
    r"[^:]*?:\s*(?:₹|Rs\.?|[`₹H])\s*([\d,]+(?:\.\d+)?)\s*(?:crore|Cr\.?)"
    r"|(?:₹|Rs\.?|[`₹HI])\s*([\d,]+(?:\.\d+)?)\s*(?:crore|Cr\.?)\s*\|?\s*Total\s+CSR\s+Expenditure"
    r"|Total\s+CSR\s+Expenditure\s*\|?\s*(?:₹|Rs\.?|[`₹HI])\s*([\d,]+(?:\.\d+)?)\s*(?:crore|Cr\.?)",
    re.IGNORECASE | re.DOTALL,
)

# KAM entry title: a capitalised line immediately followed by "See Note".
_RE_KAM_ENTRY = re.compile(r"^([^\n]{20,300})\nSee\s+Note", re.MULTILINE)

# KAM section header within the auditor's report.
# FY2026/FY2025 write "Key Audit Matters"; FY2024 writes "Key Audit Matter(s)".
_RE_KAM_HEADER = re.compile(
    r"Key\s+Audit\s+Matter(?:s|\(s\))?\s*\n", re.IGNORECASE
)

# Voluntary LTM attrition rate, typically in MDA workforce discussion.
_RE_ATTRITION = re.compile(
    r"(?:voluntary\s+)?(?:LTM\s+)?(?:IT\s+services?\s+)?attrition"
    r"(?:\s+in\s+IT\s+[Ss]ervices?)?"
    r"[^%\n]{0,80}?([\d]+\.[\d]+)\s*%",
    re.IGNORECASE,
)

_RE_BARE_PAGE_NUM = re.compile(r"^\d{1,3}$")

# Validator for the auditor's report: confirm the section body is genuine
# report text (not a TOC listing).  FY2025/FY2024 TOC layouts differ from
# FY2026, so the two-level page-number check alone is insufficient.
_RE_AUDITOR_BODY = re.compile(
    r"To the Members|Report on the Audit|Basis for Opinion",
    re.IGNORECASE,
)
_VALIDATOR_CHARS = 2_000

# ---------------------------------------------------------------------------
# Section finding
# ---------------------------------------------------------------------------


def _find_section(
    content: str,
    patterns: list[re.Pattern[str]],
    min_content: int = _MIN_SECTION_CONTENT,
    validator: re.Pattern[str] | None = None,
) -> tuple[str, int] | None:
    """Return ``(section_text, header_char_offset)`` for the first real match.

    Tries each pattern in order, returning the first qualifying hit.
    Applies the two-level TOC-skip strategy described in the module docstring.

    If *validator* is given, the candidate excerpt must contain a match for
    that pattern within its first ``_VALIDATOR_CHARS`` characters.  This lets
    callers rule out TOC entries whose text content passes the length check but
    lacks distinguishing prose (e.g. the auditor's report "To the Members"
    opening that is absent from a TOC line).
    """
    for pat in patterns:
        for m in pat.finditer(content):
            after = content[m.end(): m.end() + _SECTION_CHARS + 500]
            non_blank = [ln.strip() for ln in after.split("\n") if ln.strip()]
            if not non_blank:
                continue

            if _RE_BARE_PAGE_NUM.match(non_blank[0]):
                # First non-blank is a bare page number.
                rest = non_blank[1:]
                if not rest:
                    continue
                # TOC test: if the item after the page number is *itself*
                # followed by another page number → classic TOC pattern → skip.
                if len(rest) >= 2 and _RE_BARE_PAGE_NUM.match(rest[1]):
                    continue
                # Running header in the section body: use the prose that follows.
                body = "\n".join(rest)
                if len(body) >= min_content:
                    excerpt = body[:_SECTION_CHARS]
                    if validator and not validator.search(excerpt[:_VALIDATOR_CHARS]):
                        continue
                    return excerpt, m.start()
                continue

            # First non-blank is prose — genuine section content.
            body = "\n".join(non_blank)
            if len(body) >= min_content:
                excerpt = after.strip()[:_SECTION_CHARS]
                if validator and not validator.search(excerpt[:_VALIDATOR_CHARS]):
                    continue
                return excerpt, m.start()

    return None


# ---------------------------------------------------------------------------
# List and risk helpers (stable extraction core)
# ---------------------------------------------------------------------------


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


def _extract_risks(content: str) -> list[str]:
    """Extract risk factor names from the MDA/risk section."""
    result = _find_section(content, [_RE_RISKS])
    if not result:
        return []
    section_text = result[0]
    items = _extract_list_items(section_text)
    if items:
        return items[:10]
    headings: list[str] = []
    for line in section_text.split("\n"):
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
# Fact extractors
# ---------------------------------------------------------------------------


def _extract_csr_spend(
    content: str,
) -> tuple[float | None, int | None, str | None]:
    """Return ``(amount_crore, char_offset, excerpt)`` for the mandatory CSR table."""
    m = _RE_CSR_SPEND.search(content)
    if not m:
        return None, None, None
    # The pattern has three alternating capture groups (main / banking-pre / banking-post).
    raw_group = m.group(1) or m.group(2) or m.group(3)
    if not raw_group:
        return None, None, None
    raw = raw_group.replace(",", "")
    try:
        amount = float(raw)
    except ValueError:
        return None, None, None
    return amount, m.start(), _snip(content, m.start())


def _extract_kam_titles(
    content: str,
    auditor_header_offset: int,
) -> list[tuple[str, int]]:
    """Return ``[(title, char_offset)]`` for KAM entries in the consolidated auditor's report.

    Searches within ``_SECTION_CHARS`` bytes of ``auditor_header_offset``.
    KAM titles are lines that immediately precede "See Note" in the KAM section.
    """
    section_text = content[auditor_header_offset: auditor_header_offset + _SECTION_CHARS]
    kam_m = _RE_KAM_HEADER.search(section_text)
    if not kam_m:
        return []
    kam_body = section_text[kam_m.end():]
    results: list[tuple[str, int]] = []
    for entry_m in _RE_KAM_ENTRY.finditer(kam_body):
        title = entry_m.group(1).strip()
        if title and not title[0].islower():
            abs_offset = auditor_header_offset + kam_m.end() + entry_m.start()
            results.append((title, abs_offset))
    return results


def _extract_attrition(
    content: str,
) -> tuple[float | None, int | None, str | None]:
    """Return ``(attrition_pct, char_offset, excerpt)`` for the LTM attrition rate."""
    m = _RE_ATTRITION.search(content)
    if not m:
        return None, None, None
    try:
        pct = float(m.group(1))
    except ValueError:
        return None, None, None
    return pct, m.start(), _snip(content, m.start())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured facts from a parsed annual report document.

    Fact kinds produced:

    * ``ESG_CSR_SPEND`` — mandatory s.135 CSR expenditure from Board's/Directors' Report
    * ``AUDIT_KAM_TITLE`` — Key Audit Matter titles from the consolidated auditor's report
    * ``ESG_WORKFORCE_ATTRITION_PCT`` — voluntary LTM attrition from MDA (supplementary)
    * ``RISK_FACTOR`` — major risk factors from the MDA risk section

    Excerpts stored:

    * ``boards_report`` — first qualifying Board's/Directors' Report section text
    * ``mda`` — Management Discussion and Analysis section text
    * ``key_audit_matters`` — consolidated auditor's report section text

    Raises ``KeyError`` when ``evidence_id`` is not in the knowledge base.
    Raises ``ValueError`` when the document failed to parse or has no content.
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

    # ------------------------------------------------------------------ #
    # 1. Board's / Directors' Report — excerpt + CSR mandatory spend       #
    # ------------------------------------------------------------------ #
    boards_result = _find_section(content, [_RE_BOARDS_REPORT, _RE_DIRS_REPORT])
    if boards_result:
        excerpts["boards_report"] = boards_result[0]
    else:
        warnings.append("Board's/Directors' Report section not found")

    csr_amount, csr_offset, csr_snip = _extract_csr_spend(content)
    if csr_amount is not None:
        facts.append(
            AnalysisFact(
                kind=FactKind.ESG_CSR_SPEND,
                value=csr_amount,
                unit=FactUnit.CRORE_INR,
                period=period,
                confidence="high",
                provenance=Provenance(
                    section="boards_report_csr",
                    char_offset=csr_offset,
                    excerpt=csr_snip,
                ),
            )
        )
    else:
        warnings.append("CSR mandatory disclosure not found")

    # ------------------------------------------------------------------ #
    # 2. MDA — excerpt + attrition + risk factors                          #
    # ------------------------------------------------------------------ #
    mda_result = _find_section(content, [_RE_MDA])
    if mda_result:
        excerpts["mda"] = mda_result[0]
    else:
        warnings.append("MDA section not found")

    attrition, attr_offset, attr_snip = _extract_attrition(content)
    if attrition is not None:
        facts.append(
            AnalysisFact(
                kind=FactKind.ESG_WORKFORCE_ATTRITION_PCT,
                value=attrition,
                unit=FactUnit.PERCENT,
                period=period,
                confidence="medium",
                provenance=Provenance(
                    section="mda_attrition",
                    char_offset=attr_offset,
                    excerpt=attr_snip,
                ),
            )
        )

    major_risks = _extract_risks(content)
    risk_result = _find_section(content, [_RE_RISKS])
    risk_offset = risk_result[1] if risk_result else None
    risk_snip = _snip(content, risk_offset) if risk_offset is not None else None
    risk_conf: Literal["high", "medium", "low"] = "medium" if risk_result else "low"
    for risk in major_risks:
        facts.append(
            AnalysisFact(
                kind=FactKind.RISK_FACTOR,
                value=risk,
                unit=None,
                period=period,
                confidence=risk_conf,
                provenance=Provenance(
                    section="mda_risk",
                    char_offset=risk_offset,
                    excerpt=risk_snip,
                ),
            )
        )
    if not major_risks:
        warnings.append("Risk factors not found")

    # ------------------------------------------------------------------ #
    # 2b. Gross block of property, plant and equipment (M-P3.2)            #
    # ------------------------------------------------------------------ #
    gross_block_fact = _extract_gross_block(content, period)
    if gross_block_fact is not None:
        facts.append(gross_block_fact)

    facts.extend(_extract_rpt_balance(content, period))

    # ------------------------------------------------------------------ #
    # 3. Consolidated auditor's report — KAM titles                        #
    # ------------------------------------------------------------------ #
    auditor_result = _find_section(
        content, [_RE_AUDITOR_CONSOL], validator=_RE_AUDITOR_BODY
    )
    if auditor_result:
        excerpts["key_audit_matters"] = auditor_result[0]
        auditor_offset = auditor_result[1]
        kam_entries = _extract_kam_titles(content, auditor_offset)
        for title, kam_offset in kam_entries:
            facts.append(
                AnalysisFact(
                    kind=FactKind.AUDIT_KAM_TITLE,
                    value=title,
                    unit=None,
                    period=period,
                    confidence="high",
                    provenance=Provenance(
                        section="auditor_report_kam",
                        char_offset=kam_offset,
                        excerpt=_snip(content, kam_offset),
                    ),
                )
            )
        if not kam_entries:
            warnings.append("No KAM entries found in auditor's report")
    else:
        warnings.append("Consolidated auditor's report not found")

    # ------------------------------------------------------------------ #
    # Result-level confidence                                              #
    # ------------------------------------------------------------------ #
    has_csr = csr_amount is not None
    has_kams = any(f.kind == FactKind.AUDIT_KAM_TITLE for f in facts)
    excerpt_count = len(excerpts)

    if has_csr and has_kams and excerpt_count >= 2:
        result_confidence: Literal["high", "medium", "low"] = "high"
    elif has_csr or has_kams:
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
        entities=_extract_directors(content, EntityResolver()),
    )


def summarize(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Backward-compatible alias for ``analyze()``."""
    return analyze(evidence_id, kb)
