"""Rule-based fact extraction from SEBI Regulation 30 board outcome filings.

Recognised sub-types and extracted facts
-----------------------------------------
Results / Dividend
    Board approved quarterly/annual results and declared or recommended a dividend.
    Extracts CAPITAL_DIVIDEND_* facts from the cover letter on every filing path.

Acquisition (Type A Annexure)
    Board approved an external acquisition; Annexure A has the SEBI target-entity
    table ("Name of the target entity..."). Extracts CAPITAL_ACQ_* facts.

Investment
    Board approved investment into a subsidiary via a Securities Subscription
    Agreement. Annexure A uses the agreement-party table; extracts
    CAPITAL_INVEST_TARGET_NAME and CAPITAL_INVEST_AMOUNT.

Agreement (pure JV / distribution)
    Annexure A uses the agreement-party table but no investment amount is stated;
    no structured facts extracted; full text captured as excerpt.

Buyback announcement
    Board authorised an equity buyback. Cover letter states the aggregate amount
    and price per share. Extracts CAPITAL_BUYBACK_AMOUNT and
    CAPITAL_BUYBACK_PRICE_PER_SHARE.

Fundraising (QIP / Rights / Preferential / NCD)
    Board approved raising capital via equity or debt instruments. Extracts
    CAPITAL_FUNDRAISE_TYPE and CAPITAL_FUNDRAISE_AMOUNT.

Management changes
    Board approved or noted appointment, reappointment, or resignation of a
    director or KMP. Extracts GOVERNANCE_DIRECTOR, GOVERNANCE_DIRECTOR_CHANGE_TYPE,
    and GOVERNANCE_DIRECTOR_CHANGE_ROLE; grouped by section "director_change_N".

Other
    Any board outcome not matching the above; cover letter captured as excerpt
    only with a warning.

Always-on extraction
--------------------
All extractors except the Annexure-based ones (acquisition, investment/agreement)
run unconditionally on the cover letter.  A single board meeting may both declare
a dividend AND announce a management change; all facts will be captured.

Dividend period inference
--------------------------
"quarter/year ended [date]" is parsed from the cover letter. Falls back to the
most recent Indian fiscal year end (March 31) from source_date when a dividend
is declared but no period phrase is found (standalone dividend announcement).
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
from atlas.analysis.patterns import (
    extract_dividend_facts,
    fiscal_year_end,
    parse_iso_date,
    split_reg30_sections,
)
from atlas.knowledge.base import KnowledgeBase

ANALYZER_VERSION = "1.1"

_COVER_WINDOW = 5_000

# ---------------------------------------------------------------------------
# Sub-type anchors (Annexure A structure detection)
# ---------------------------------------------------------------------------

# Acquisition Annexure A: SEBI-mandated target entity table
_RE_TYPE_A_ANCHOR = re.compile(r"Name of the target entity", re.IGNORECASE)

# Agreement / JV Annexure A: party-to-agreement table (different SEBI format)
_RE_AGREEMENT_ANCHOR = re.compile(
    r"Name\(s\)\s+of\s+parties\s+with\s+whom\s+the\s+agreement"
    r"|Purpose\s+of\s+entering\s+into\s+the\s+agreement",
    re.IGNORECASE,
)

# Investment sub-type signals within an Agreement filing
_RE_INVEST_SIGNAL = re.compile(
    r"Securities\s+Subscription\s+Agreement"
    r"|aggregate\s+amount\s+of\s+up\s*to",
    re.IGNORECASE,
)
# "HyperVault AI Data Center Limited, a wholly owned subsidiary of the Company"
# No re.IGNORECASE: [A-Z] must be uppercase so "and HyperVault..." cannot match from "and"
_RE_INVEST_SUBSIDIARY = re.compile(
    r"([A-Z][A-Za-z\s]+\bLimited\b[^,()\n]{0,30}?)"
    r",?\s*a\s+wholly\s+owned\s+subsidiary\s+of\s+the\s+Company",
)
# "Rs 18,000 crore" / "INR 1,000 crore" / "₹ 500 crore"
_RE_INVEST_AMOUNT_INR = re.compile(
    r"(?:Rs|INR|₹)\s*([\d,]+)\s*crore",
    re.IGNORECASE,
)
# "$1 Bn" / "$1.2 billion"
_RE_INVEST_AMOUNT_USD = re.compile(
    r"\$\s*([\d,.]+)\s*(?:Bn\.?|billion)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Period detection
# ---------------------------------------------------------------------------

_RE_PERIOD_QUARTER = re.compile(
    r"quarter(?:\s+and\s+[\w\s-]+period)?\s+ended\s+(\w+ \d+,?\s*\d{4})",
    re.IGNORECASE,
)
_RE_PERIOD_YEAR = re.compile(
    r"year\s+ended\s+(?:on\s+)?(\w+ \d+,?\s*\d{4})",
    re.IGNORECASE,
)
_DATE_FMT = "%B %d, %Y"


def _detect_period(cover: str) -> str | None:
    """Parse 'quarter/year ended [date]' from the cover letter; return ISO date or None."""
    for pat in (_RE_PERIOD_QUARTER, _RE_PERIOD_YEAR):
        m = pat.search(cover)
        if m:
            try:
                raw = re.sub(r"\s+", " ", m.group(1))
                return datetime.strptime(raw, _DATE_FMT).date().isoformat()
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Acquisition Type A extraction
# Mirrors acquisition.py Type A; kept separate to allow independent edge-case
# handling for documents classified as board outcomes vs. standalone filings.
# ---------------------------------------------------------------------------

_RE_COVER_TARGET = re.compile(
    r"(?:acquisition of|acquire)\s+"
    r"([A-Z][^.]{5,120}?)"
    r"(?:\s+and its subsidiaries|\s+in\s+first tranche|\s+[,.]|\s*\()",
    re.IGNORECASE,
)
_RE_CASH = re.compile(r"^\s*Cash consideration\b", re.IGNORECASE | re.MULTILINE)
_RE_SHARE_SWAP = re.compile(r"^\s*Share\s+swap\b", re.IGNORECASE | re.MULTILINE)
_RE_EV_USD = re.compile(
    r"Enterprise\s+Value\b[^.]*?USD\s+([\d,.]+)\s*(million|billion)\b",
    re.IGNORECASE | re.DOTALL,
)
_RE_EV_INR = re.compile(
    r"Enterprise\s+Value\b[^.]*?(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:crore|cr\.?)\b",
    re.IGNORECASE | re.DOTALL,
)
_RE_STAKE = re.compile(r"\b(\d{2,3})\s*%")
_RE_COMPLETION = re.compile(
    r"expected to be completed\s+by\s+(\w+ \d+,?\s*\d{4})", re.IGNORECASE
)


def _extract_acq_type_a(
    cover: str, ann_a: str, ann_b: str,
) -> tuple[list[AnalysisFact], list[str]]:
    """Extract CAPITAL_ACQ_* facts when Annexure A has the target-entity table."""
    facts: list[AnalysisFact] = []
    warnings: list[str] = []

    m = _RE_COVER_TARGET.search(cover)
    if m:
        name = m.group(1).strip().rstrip(",.")
        facts.append(_fact(
            FactKind.CAPITAL_ACQ_TARGET_NAME, name, None,
            "cover_letter", cover, m.start(1),
        ))
    else:
        warnings.append("Could not extract target name from cover letter")

    if _RE_SHARE_SWAP.search(ann_a):
        m2 = _RE_SHARE_SWAP.search(ann_a)
        assert m2 is not None
        facts.append(_fact(
            FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE, "share_swap", None,
            "annexure_a", ann_a, m2.start(),
        ))
    elif _RE_CASH.search(ann_a):
        m2 = _RE_CASH.search(ann_a)
        assert m2 is not None
        facts.append(_fact(
            FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE, "cash", None,
            "annexure_a", ann_a, m2.start(),
        ))
    else:
        warnings.append("Consideration type not found in Annexure A")

    m_usd = _RE_EV_USD.search(ann_a)
    m_inr = _RE_EV_INR.search(ann_a)
    if m_usd:
        amount_str = m_usd.group(1).replace(",", "")
        scale = m_usd.group(2).lower()
        try:
            amount = float(amount_str)
        except ValueError:
            warnings.append(f"Could not parse enterprise value: {amount_str!r}")
        else:
            unit = FactUnit.USD_BILLION if scale == "billion" else FactUnit.USD_MILLION
            facts.append(_fact(
                FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE, amount, unit,
                "annexure_a", ann_a, m_usd.start(),
            ))
    elif m_inr:
        amount_str = m_inr.group(1).replace(",", "")
        try:
            amount = float(amount_str)
        except ValueError:
            warnings.append(f"Could not parse enterprise value: {amount_str!r}")
        else:
            facts.append(_fact(
                FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE, amount, FactUnit.CRORE_INR,
                "annexure_a", ann_a, m_inr.start(),
            ))
    else:
        warnings.append("Enterprise value not found in Annexure A")

    m_stake = _RE_STAKE.search(ann_a)
    if m_stake:
        facts.append(_fact(
            FactKind.CAPITAL_ACQ_STAKE_PCT, float(m_stake.group(1)), FactUnit.PERCENT,
            "annexure_a", ann_a, m_stake.start(),
        ))
    else:
        warnings.append("Stake percentage not found in Annexure A")

    m_comp = _RE_COMPLETION.search(ann_a)
    if m_comp:
        iso = parse_iso_date(m_comp.group(1))
        if iso:
            facts.append(_fact(
                FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION, iso, FactUnit.ISO_DATE,
                "annexure_a", ann_a, m_comp.start(),
            ))
        else:
            warnings.append(f"Could not parse completion date: {m_comp.group(1)!r}")

    return facts, warnings


# ---------------------------------------------------------------------------
# Investment / subsidiary fundraise extraction
# ---------------------------------------------------------------------------

def _extract_investment(
    cover: str, ann_a: str, ann_b: str,
) -> tuple[list[AnalysisFact], list[str]]:
    """Extract CAPITAL_INVEST_* facts when Agreement Annexure contains an investment.

    Returns empty lists when the filing is a pure JV with no stated investment
    amount — the caller falls back to excerpt-only in that case.
    """
    facts: list[AnalysisFact] = []
    warnings: list[str] = []

    full = cover + "\n" + ann_a + "\n" + ann_b
    if not _RE_INVEST_SIGNAL.search(full):
        return facts, warnings  # pure JV/agreement — no investment facts

    # Subsidiary receiving the investment (typically named in cover letter)
    m_sub = _RE_INVEST_SUBSIDIARY.search(cover)
    if m_sub:
        name = re.sub(r"\s+", " ", m_sub.group(1).strip())
        facts.append(_fact(
            FactKind.CAPITAL_INVEST_TARGET_NAME, name, None,
            "cover_letter", cover, m_sub.start(1),
        ))
    else:
        warnings.append("Could not identify subsidiary receiving investment from cover letter")

    # Investment amount: search press release (ann_b) first; fall back to Annexure A
    def _find_inr(texts: list[tuple[str, str]]) -> tuple[re.Match | None, str, str]:
        for text, section in texts:
            m = _RE_INVEST_AMOUNT_INR.search(text)
            if m:
                return m, section, text
        return None, "", ""

    def _find_usd(texts: list[tuple[str, str]]) -> tuple[re.Match | None, str, str]:
        for text, section in texts:
            m = _RE_INVEST_AMOUNT_USD.search(text)
            if m:
                return m, section, text
        return None, "", ""

    _ordered = [
        (ann_b, "press_release"),
        (ann_a, "annexure_a"),
        (cover, "cover_letter"),
    ]
    m_inr, inr_section, inr_text = _find_inr(_ordered)
    if m_inr:
        raw = m_inr.group(1).replace(",", "")
        try:
            amount = float(raw)
        except ValueError:
            warnings.append(f"Could not parse INR investment amount: {m_inr.group(1)!r}")
        else:
            facts.append(_fact(
                FactKind.CAPITAL_INVEST_AMOUNT, amount, FactUnit.CRORE_INR,
                inr_section, inr_text, m_inr.start(),
            ))
    else:
        m_usd, usd_section, usd_text = _find_usd(_ordered)
        if m_usd:
            raw = m_usd.group(1).replace(",", "")
            try:
                amount = float(raw)
            except ValueError:
                warnings.append(f"Could not parse USD investment amount: {m_usd.group(1)!r}")
            else:
                facts.append(_fact(
                    FactKind.CAPITAL_INVEST_AMOUNT, amount, FactUnit.USD_BILLION,
                    usd_section, usd_text, m_usd.start(),
                ))
        else:
            warnings.append("Investment amount not found in document")

    return facts, warnings


# ---------------------------------------------------------------------------
# Buyback announcement extraction
# ---------------------------------------------------------------------------

_RE_BUYBACK_SIGNAL = re.compile(
    r"buyback\s+of\s+equity\s+shares"
    r"|approved\s+(?:the\s+)?(?:proposal\s+(?:for\s+)?)?buyback\b",
    re.IGNORECASE,
)
_RE_BUYBACK_AMOUNT = re.compile(
    r"(?:aggregate\s+)?(?:amount\s+)?(?:not\s+exceeding|not\s+more\s+than|up\s+to|of\s+(?:INR|Rs\.?|₹))?"
    r"\s*(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:crore|cr\.?)\b",
    re.IGNORECASE,
)
_RE_BUYBACK_PRICE = re.compile(
    r"price\s+(?:not\s+exceeding|of)\s+(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*per\s+(?:equity\s+)?share",
    re.IGNORECASE,
)


def _extract_buyback(cover: str) -> tuple[list[AnalysisFact], list[str]]:
    """Extract CAPITAL_BUYBACK_* facts from a buyback announcement in the cover letter."""
    facts: list[AnalysisFact] = []
    warnings: list[str] = []

    if not _RE_BUYBACK_SIGNAL.search(cover):
        return facts, warnings

    m_amt = _RE_BUYBACK_AMOUNT.search(cover)
    if m_amt:
        raw = m_amt.group(1).replace(",", "")
        try:
            amount = float(raw)
        except ValueError:
            warnings.append(f"Could not parse buyback amount: {m_amt.group(1)!r}")
        else:
            facts.append(_fact(
                FactKind.CAPITAL_BUYBACK_AMOUNT, amount, FactUnit.CRORE_INR,
                "cover_letter", cover, m_amt.start(),
            ))
    else:
        warnings.append("Buyback amount not found in cover letter")

    m_price = _RE_BUYBACK_PRICE.search(cover)
    if m_price:
        raw = m_price.group(1).replace(",", "")
        try:
            price = float(raw)
        except ValueError:
            warnings.append(f"Could not parse buyback price: {m_price.group(1)!r}")
        else:
            facts.append(_fact(
                FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE, price, FactUnit.RUPEES_PER_SHARE,
                "cover_letter", cover, m_price.start(),
            ))

    return facts, warnings


# ---------------------------------------------------------------------------
# Fundraising detection (QIP / Rights Issue / Preferential Allotment / NCD)
# ---------------------------------------------------------------------------

_FUNDRAISE_SIGNALS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Qualified\s+Institutional\s+Placement|(?<!\w)QIP(?!\w)", re.IGNORECASE), "QIP"),
    (re.compile(r"rights?\s+issue\b", re.IGNORECASE), "rights_issue"),
    (re.compile(r"preferential\s+(?:allotment|issue)\b", re.IGNORECASE), "preferential_allotment"),
    (re.compile(r"Non[-–]?Convertible\s+Debentures?|(?<!\w)NCDs?(?!\w)", re.IGNORECASE), "NCD"),
]

_RE_FUNDRAISE_AMOUNT = re.compile(
    r"(?:not\s+exceeding|not\s+more\s+than|up\s+to"
    r"|aggregate(?:\s+amount)?(?:\s+of)?(?:\s+not\s+exceeding)?)"
    r"\s+(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:crore|cr\.?)\b",
    re.IGNORECASE,
)


def _extract_fundraising(cover: str) -> tuple[list[AnalysisFact], list[str]]:
    """Extract CAPITAL_FUNDRAISE_* facts from equity/debt capital raise announcements."""
    facts: list[AnalysisFact] = []
    warnings: list[str] = []

    detected: list[tuple[str, int]] = []
    for pattern, kind in _FUNDRAISE_SIGNALS:
        m = pattern.search(cover)
        if m:
            detected.append((kind, m.start()))

    if not detected:
        return facts, warnings

    m_amount = _RE_FUNDRAISE_AMOUNT.search(cover)
    amount: float | None = None
    amount_pos = 0
    if m_amount:
        raw = m_amount.group(1).replace(",", "")
        try:
            amount = float(raw)
            amount_pos = m_amount.start()
        except ValueError:
            warnings.append(f"Could not parse fundraise amount: {m_amount.group(1)!r}")

    for kind, offset in detected:
        facts.append(_fact(
            FactKind.CAPITAL_FUNDRAISE_TYPE, kind, None,
            "cover_letter", cover, offset,
        ))
        if amount is not None:
            facts.append(_fact(
                FactKind.CAPITAL_FUNDRAISE_AMOUNT, amount, FactUnit.CRORE_INR,
                "cover_letter", cover, amount_pos,
            ))

    return facts, warnings


# ---------------------------------------------------------------------------
# Management change detection (director / KMP appointments and resignations)
# ---------------------------------------------------------------------------

# Step 1: anchor — "appointment/resignation of " (case-insensitive)
_RE_DIR_CHANGE_ANCHOR = re.compile(
    r"(re-?appointment|appointment|resignation|cessation)\s+of\s+",
    re.IGNORECASE,
)
# Step 2: title-case person name immediately following the anchor (case-sensitive)
_RE_PERSON_NAME = re.compile(
    r"([A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z.]{1,}){1,4})"
)
# Step 3: role after "as" / "from the position of" etc. in the 300 chars after the name
_RE_AS_ROLE = re.compile(
    r"\bas\s+([^.,;\n]{5,120}?)(?=\s*(?:effective|w\.?e\.?f\.?|with\s+effect"
    r"|subject|of\s+the\s+Company|,|\.|$))",
    re.IGNORECASE,
)

_DIR_NAME_STOPWORDS = frozenset({
    "board", "directors", "director", "committee", "company", "trustee",
    "sebi", "stock", "exchange", "income", "supreme", "court", "high",
    "national", "reserve", "bank", "securities", "act", "regulation",
    "annual", "general", "meeting", "executive", "the",
})


def _clean_role(role: str) -> str:
    """Strip trailing noise from extracted role strings."""
    role = role.strip().rstrip(" ,")
    for suffix_re in (
        re.compile(r"\s+(?:effective|w\.?e\.?f\.?|with\s+effect).*$", re.IGNORECASE),
        re.compile(r"\s+of\s+the\s+Company.*$", re.IGNORECASE),
        re.compile(r",?\s+subject\s+to.*$", re.IGNORECASE),
    ):
        role = suffix_re.sub("", role).strip()
    return role


def _extract_management_changes(cover: str) -> tuple[list[AnalysisFact], list[str]]:
    """Extract GOVERNANCE_DIRECTOR* facts for director/KMP changes.

    Facts for each person are grouped under section "director_change_N" so the
    builder can assemble DirectorChange objects per person.
    """
    facts: list[AnalysisFact] = []
    warnings: list[str] = []
    seen_names: set[str] = set()
    counter = 0

    for m_anchor in _RE_DIR_CHANGE_ANCHOR.finditer(cover):
        change_type_raw = m_anchor.group(1).lower()

        # Look for title-case person name immediately after the anchor
        window_start = m_anchor.end()
        window = cover[window_start:window_start + 200]
        m_name = _RE_PERSON_NAME.match(window)
        if m_name is None:
            continue

        name = m_name.group(1).strip()
        parts = name.split()
        if len(parts) < 2 or parts[0].lower() in _DIR_NAME_STOPWORDS:
            continue

        name_key = name.lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        # Normalise change type
        cr = change_type_raw.replace("-", "").replace(" ", "")
        if "reappointment" in cr:
            change_type = "reappointment"
        elif "appointment" in cr:
            change_type = "appointment"
        else:
            change_type = "resignation"

        section = f"director_change_{counter}"
        counter += 1

        name_pos = window_start + m_name.start(1)
        facts.append(_fact(
            FactKind.GOVERNANCE_DIRECTOR, name, None,
            section, cover, name_pos,
        ))
        facts.append(_fact(
            FactKind.GOVERNANCE_DIRECTOR_CHANGE_TYPE, change_type, None,
            section, cover, m_anchor.start(1),
        ))

        # Look for role ("as [role]") in the 300 chars after the name.
        # Normalise internal whitespace so multi-line role strings are captured.
        role_window_start = window_start + m_name.end()
        role_window = re.sub(r"\s+", " ", cover[role_window_start:role_window_start + 300])
        m_role = _RE_AS_ROLE.search(role_window)
        if m_role:
            role = _clean_role(m_role.group(1))
            if role:
                role_pos = role_window_start + m_role.start(1)
                facts.append(_fact(
                    FactKind.GOVERNANCE_DIRECTOR_CHANGE_ROLE, role, None,
                    section, cover, role_pos,
                ))

    return facts, warnings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured facts from a SEBI Reg 30 board outcome filing."""
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    if entry.kind != "board_outcome":
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: "
            f"kind={entry.kind!r} is not 'board_outcome'"
        )

    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: document has no content"
        )

    cover, ann_a, ann_b = split_reg30_sections(content)

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="board_outcome",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=datetime.fromisoformat(entry.source_date),
    )

    if cover.strip():
        result.excerpts["cover_letter"] = cover.strip()[:_COVER_WINDOW]
    if ann_a.strip():
        result.excerpts["annexure_a"] = ann_a.strip()
    if ann_b.strip():
        result.excerpts["press_release"] = ann_b.strip()

    cover_scan = cover or content[:_COVER_WINDOW]

    # --- Always-on cover-letter extractors ---

    period = _detect_period(cover_scan[:_COVER_WINDOW])
    div_facts = extract_dividend_facts(cover_scan[:_COVER_WINDOW], period)
    if period is None and div_facts:
        period = fiscal_year_end(entry.source_date)
        for f in div_facts:
            f.period = period
    result.facts.extend(div_facts)

    bb_facts, bb_warnings = _extract_buyback(cover_scan[:_COVER_WINDOW])
    result.facts.extend(bb_facts)
    result.warnings.extend(bb_warnings)

    fundraise_facts, fundraise_warnings = _extract_fundraising(cover_scan[:_COVER_WINDOW])
    result.facts.extend(fundraise_facts)
    result.warnings.extend(fundraise_warnings)

    mgmt_facts, mgmt_warnings = _extract_management_changes(cover_scan[:_COVER_WINDOW])
    result.facts.extend(mgmt_facts)
    result.warnings.extend(mgmt_warnings)

    # --- Annexure-based routing ---

    acq_detected = False
    if ann_a and _RE_TYPE_A_ANCHOR.search(ann_a):
        acq_facts, acq_warnings = _extract_acq_type_a(cover, ann_a, ann_b)
        result.facts.extend(acq_facts)
        result.warnings.extend(acq_warnings)
        acq_detected = True

    elif ann_a and _RE_AGREEMENT_ANCHOR.search(ann_a):
        inv_facts, inv_warnings = _extract_investment(cover, ann_a, ann_b)
        if inv_facts:
            result.facts.extend(inv_facts)
            result.warnings.extend(inv_warnings)
        else:
            result.warnings.append(
                "Annexure A contains a material agreement disclosure (JV/SHA/subscription); "
                "no structured facts extracted — see annexure_a excerpt"
            )

    # --- Confidence scoring ---

    kinds = {f.kind for f in result.facts}

    if acq_detected and (
        FactKind.CAPITAL_ACQ_TARGET_NAME in kinds
        and FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE in kinds
        and FactKind.CAPITAL_ACQ_STAKE_PCT in kinds
    ):
        result.confidence = "high"
    elif FactKind.CAPITAL_DIVIDEND_PER_SHARE in kinds:
        result.confidence = "high"
    elif kinds & {
        FactKind.CAPITAL_ACQ_TARGET_NAME,
        FactKind.CAPITAL_INVEST_TARGET_NAME,
        FactKind.CAPITAL_BUYBACK_AMOUNT,
        FactKind.CAPITAL_FUNDRAISE_TYPE,
        FactKind.GOVERNANCE_DIRECTOR,
    }:
        result.confidence = "medium"
    else:
        if not result.facts:
            result.warnings.append(
                "No structured facts detected; "
                "see cover_letter excerpt for board decisions"
            )

    return result
