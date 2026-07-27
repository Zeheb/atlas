"""Rule-based fact extraction from SEBI Regulation 30 acquisition and incorporation filings.

Three structural document types are recognised:

  Type A — External acquisition
    SEBI Reg 30 Annexure A with row "Name of the target entity, details in brief".
    Full fact extraction: target name, consideration type, enterprise value, stake %, completion date.
    Annexure B press release (if present) is captured in excerpts but not parsed for facts.

  Type B — Subsidiary incorporation
    SEBI Reg 30 Annexure A with row "Name of the entity, date & country of incorporation".
    Limited extraction: entity name(s), stake % (always 100%), consideration type (subscription),
    subscription cost only when explicitly stated.

  Type C — Completion / update notice
    No Annexure A. Free-prose update referencing a prior filing.
    Emits a warning; no structured facts are extracted.

Provenance sections:
  "cover_letter"   — cover letter body
  "annexure_a"     — Annexure A table body
  "press_release"  — Annexure B press release (Type A only)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
    _fact,
    _snip,
)
from atlas.analysis.patterns import parse_iso_date, split_reg30_sections
from atlas.knowledge.base import KnowledgeBase

ANALYZER_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Annexure type anchors
# ---------------------------------------------------------------------------

# Distinguishes Type A from Type B by the wording of Annexure A row 1.
# \s+ handles PDF line-wrapping within the row label.
_RE_TYPE_A_ANCHOR = re.compile(r"Name of the target entity", re.IGNORECASE)
_RE_TYPE_B_ANCHOR = re.compile(
    r"Name of the entity,\s+date\s*[&]\s*country\s+of\s+incorporation",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Type A extraction patterns
# ---------------------------------------------------------------------------

# Cover letter: "for acquisition of <NAME> and its subsidiaries"
_RE_COVER_TARGET = re.compile(
    r"(?:acquisition of|acquire)\s+"
    r"([A-Z][^.]{5,120}?)"
    r"(?:\s+and its subsidiaries|\s+in\s+first tranche|\s+[,.]|\s*\()",
    re.IGNORECASE,
)

# Consideration type — match value lines only (line-anchored so the row label
# "whether cash consideration or share swap" doesn't trigger a false match)
_RE_CASH = re.compile(r"^\s*Cash consideration\b", re.IGNORECASE | re.MULTILINE)
_RE_SHARE_SWAP = re.compile(r"^\s*Share\s+swap\b", re.IGNORECASE | re.MULTILINE)

# Enterprise value — require "Enterprise Value" context so USD amounts in the
# target description row don't get picked up first
_RE_EV_USD = re.compile(
    r"Enterprise\s+Value\b[^.]*?USD\s+([\d,.]+)\s*(million|billion)\b",
    re.IGNORECASE | re.DOTALL,
)
# INR crore subscription cost
_RE_EV_INR = re.compile(r"INR\s+([\d.]+)\s*crore\b", re.IGNORECASE)

# Stake percentage
_RE_STAKE = re.compile(r"\b(\d{2,3})\s*%")

# Completion date — \s+ between "completed" and "by" handles line-wrapped PDFs
_RE_COMPLETION = re.compile(
    r"expected to be completed\s+by\s+(\w+ \d+,?\s*\d{4})", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Type B extraction patterns
# ---------------------------------------------------------------------------

# Cover letter pattern for single incorporation:
# "'EntityName' has been incorporated in Country on Date"
_RE_COVER_INC_SINGLE = re.compile(
    r"['‘’]([^'‘’]+?)['‘’]\s+has been incorporated",
    re.IGNORECASE,
)

# Annexure A row 1 structured fields for Type B.
# Name may wrap to the next line in PDF-extracted text; capture one optional
# continuation line unless it starts with a known label or row number.
_RE_INC_NAME = re.compile(
    r"Name:\s*([^\n]+(?:\n(?!Country|Date|Name:|Industry|Brief|purposes?|\d+[.:])[^\n]+)?)",
    re.IGNORECASE,
)
_RE_INC_COUNTRY = re.compile(r"Country of Incorporation:\s*([^\n]+)")
_RE_INC_DATE = re.compile(r"Date of Incorporation:\s*(\w+ \d+,?\s*\d{4})")


# ---------------------------------------------------------------------------
# Type A helpers
# ---------------------------------------------------------------------------


def _extract_type_a(
    cover: str,
    ann_a: str,
    ann_b: str,
    full_text: str,
) -> tuple[list[AnalysisFact], list[str]]:
    facts: list[AnalysisFact] = []
    warnings: list[str] = []

    # --- Target name from cover letter ---
    m = _RE_COVER_TARGET.search(cover)
    if m:
        name = m.group(1).strip().rstrip(",.")
        facts.append(
            _fact(
                FactKind.CAPITAL_ACQ_TARGET_NAME,
                name,
                None,
                "cover_letter",
                cover,
                m.start(1),
            )
        )
    else:
        warnings.append("Could not extract target name from cover letter")

    # --- Consideration type from Annexure A ---
    if _RE_SHARE_SWAP.search(ann_a):
        m2 = _RE_SHARE_SWAP.search(ann_a)
        assert m2 is not None
        facts.append(
            _fact(
                FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE,
                "share_swap",
                None,
                "annexure_a",
                ann_a,
                m2.start(),
            )
        )
    elif _RE_CASH.search(ann_a):
        m2 = _RE_CASH.search(ann_a)
        assert m2 is not None
        facts.append(
            _fact(
                FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE,
                "cash",
                None,
                "annexure_a",
                ann_a,
                m2.start(),
            )
        )
    else:
        warnings.append("Consideration type not found in Annexure A")

    # --- Enterprise value from Annexure A ---
    m_usd = _RE_EV_USD.search(ann_a)
    if m_usd:
        amount_str = m_usd.group(1).replace(",", "")
        scale = m_usd.group(2).lower()
        try:
            amount = float(amount_str)
        except ValueError:
            warnings.append(f"Could not parse enterprise value amount: {amount_str!r}")
        else:
            unit = FactUnit.USD_BILLION if scale == "billion" else FactUnit.USD_MILLION
            facts.append(
                _fact(
                    FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE,
                    amount,
                    unit,
                    "annexure_a",
                    ann_a,
                    m_usd.start(),
                )
            )
    else:
        warnings.append("Enterprise value not found in Annexure A")

    # --- Stake percentage from Annexure A ---
    m_stake = _RE_STAKE.search(ann_a)
    if m_stake:
        facts.append(
            _fact(
                FactKind.CAPITAL_ACQ_STAKE_PCT,
                float(m_stake.group(1)),
                FactUnit.PERCENT,
                "annexure_a",
                ann_a,
                m_stake.start(),
            )
        )
    else:
        warnings.append("Stake percentage not found in Annexure A")

    # --- Expected completion date from Annexure A ---
    m_comp = _RE_COMPLETION.search(ann_a)
    if m_comp:
        iso = parse_iso_date(m_comp.group(1))
        if iso:
            facts.append(
                _fact(
                    FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION,
                    iso,
                    FactUnit.ISO_DATE,
                    "annexure_a",
                    ann_a,
                    m_comp.start(),
                )
            )
        else:
            warnings.append(f"Could not parse completion date: {m_comp.group(1)!r}")
    # Completion date absence is not warned — it legitimately may not appear in all Type A filings

    return facts, warnings


# ---------------------------------------------------------------------------
# Type B helpers
# ---------------------------------------------------------------------------


def _extract_type_b(
    cover: str,
    ann_a: str,
    full_text: str,
) -> tuple[list[AnalysisFact], list[str]]:
    facts: list[AnalysisFact] = []
    warnings: list[str] = []

    # --- Entity name(s) ---
    # First try Annexure A structured "Name: <entity>" rows
    name_matches = list(_RE_INC_NAME.finditer(ann_a))
    if name_matches:
        for m in name_matches:
            name = m.group(1)
            # Collapse any line-break from PDF wrapping into a space
            name = re.sub(r"\s+", " ", name).strip()
            # Strip parenthetical short-forms like '("HyperVault")'
            name = re.sub(r'\s*\([“”"][^)]*\)', "", name).strip()
            if name:
                facts.append(
                    _fact(
                        FactKind.CAPITAL_ACQ_TARGET_NAME,
                        name,
                        None,
                        "annexure_a",
                        ann_a,
                        m.start(1),
                    )
                )
    else:
        # Fall back to cover letter single-incorporation sentence
        m_cov = _RE_COVER_INC_SINGLE.search(cover)
        if m_cov:
            facts.append(
                _fact(
                    FactKind.CAPITAL_ACQ_TARGET_NAME,
                    m_cov.group(1).strip(),
                    None,
                    "cover_letter",
                    cover,
                    m_cov.start(1),
                    confidence="medium",
                )
            )
        else:
            warnings.append("Could not extract incorporated entity name")

    # --- Consideration type (always subscription for incorporations) ---
    facts.append(
        _fact(
            FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE,
            "subscription",
            None,
            "annexure_a",
            ann_a,
            0,
        )
    )

    # --- Subscription cost (only when explicitly stated) ---
    m_inr = _RE_EV_INR.search(ann_a)
    if m_inr:
        try:
            amount = float(m_inr.group(1))
        except ValueError:
            pass
        else:
            facts.append(
                _fact(
                    FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE,
                    amount,
                    FactUnit.CRORE_INR,
                    "annexure_a",
                    ann_a,
                    m_inr.start(),
                )
            )

    # --- Stake percentage (typically 100% for wholly owned) ---
    m_stake = _RE_STAKE.search(ann_a)
    if m_stake:
        facts.append(
            _fact(
                FactKind.CAPITAL_ACQ_STAKE_PCT,
                float(m_stake.group(1)),
                FactUnit.PERCENT,
                "annexure_a",
                ann_a,
                m_stake.start(),
            )
        )
    else:
        warnings.append("Stake percentage not found in Annexure A")

    return facts, warnings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured facts from a SEBI Reg 30 acquisition or incorporation filing."""
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    if entry.kind != "acquisition":
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: kind={entry.kind!r} is not 'acquisition'"
        )

    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: document has no content"
        )

    cover, ann_a, ann_b = split_reg30_sections(content)

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="acquisition",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=datetime.fromisoformat(entry.source_date),
    )

    # Populate excerpts
    if cover.strip():
        result.excerpts["cover_letter"] = cover.strip()
    if ann_a.strip():
        result.excerpts["annexure_a"] = ann_a.strip()
    if ann_b.strip():
        result.excerpts["press_release"] = ann_b.strip()

    # --- Type C: no Annexure A ---
    if not ann_a:
        result.warnings.append(
            "No Annexure A found — this appears to be a completion or update notice; "
            "structured facts cannot be extracted"
        )
        return result

    # --- Detect Type A vs Type B ---
    if _RE_TYPE_A_ANCHOR.search(ann_a):
        facts, warnings = _extract_type_a(cover, ann_a, ann_b, content)
        result.facts.extend(facts)
        result.warnings.extend(warnings)
        # High confidence if we got the three core facts
        core_kinds = {f.kind for f in result.facts}
        if (
            FactKind.CAPITAL_ACQ_TARGET_NAME in core_kinds
            and FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE in core_kinds
            and FactKind.CAPITAL_ACQ_STAKE_PCT in core_kinds
        ):
            result.confidence = "high"
        else:
            result.confidence = "medium"

    elif _RE_TYPE_B_ANCHOR.search(ann_a):
        facts, warnings = _extract_type_b(cover, ann_a, content)
        result.facts.extend(facts)
        result.warnings.extend(warnings)
        if FactKind.CAPITAL_ACQ_TARGET_NAME in {f.kind for f in result.facts}:
            result.confidence = "high"
        else:
            result.confidence = "medium"

    else:
        result.warnings.append(
            "Annexure A found but document type not recognised "
            "(neither external acquisition nor subsidiary incorporation)"
        )
        result.confidence = "low"

    return result
