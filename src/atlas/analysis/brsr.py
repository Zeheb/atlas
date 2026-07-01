"""Rule-based fact extraction from BRSR filings (Business Responsibility &
Sustainability Report).

Filed annually under SEBI LODR Regulation 34(2)(f). BRSR Core indicators have
KPMG Reasonable Assurance from FY2024 onwards (EY Assurance for FY2023).

All ESG facts are unique to BRSR within Atlas — no other document type provides
these as structured, audited, annually-comparable figures. See the design audit
in the session notes for the full cross-reference justification.

Fact groups extracted
---------------------
GHG emissions     — Scope 1, 2 (market-based), and 3 totals; unit=TCO2E
Energy            — total consumption in MJ; renewable fraction %
Water             — total consumed in KL
Waste             — total generated in MT; recovery rate %
Workforce         — headcount; female %; female wage %; voluntary attrition %
Safety            — LTIFR (per million person-hours)
Climate targets   — SBTi Scope 1+2 and Scope 3 reduction commitments

Period convention
-----------------
Yearly metrics:   period = Indian fiscal year end "YYYY-03-31"
SBTi commitments: period = target year fiscal year end ("2030-03-31" for
                  Scope 1+2; "2034-03-31" for Scope 3). These are policy
                  facts, not annual measurements, and change only if TCS
                  revises its SBTi commitment.

Number format
-------------
Amounts use Indian comma notation (e.g., "5,73,872" = 573,872). The parser
strips all commas before float conversion; both Indian and international
notation are handled identically.

Waste total note
----------------
Total waste is computed by summing the 8 BRSR waste categories (A–H). If the
sum exceeds 50,000 MT — which occurs in FY2023 due to an anomalous
construction-waste entry in the PDF — the total is suppressed and a warning
is added instead. The recovery percentage is extracted independently via
narrative text and remains available for all years.
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
# Shared helpers
# ---------------------------------------------------------------------------

def _parse_num(text: str) -> float | None:
    """Parse a comma-formatted number (Indian or international) to float."""
    cleaned = re.sub(r"[,\s]", "", text.strip())
    if not cleaned or cleaned in ("-", "NA", "NIL", "Nil", "na"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _first_number_line(text: str, max_chars: int = 600) -> float | None:
    """Return the first standalone-number line within max_chars of text.

    A standalone-number line is one consisting only of digits, commas, spaces,
    and at most one decimal point. Both Indian-format (1,88,47,60,270) and
    international (1,884,760,270) numbers are matched.
    """
    window = text[:max_chars]
    for line in window.split("\n"):
        line = line.strip()
        if line and re.match(r"^[\d][\d,. ]*$", line):
            return _parse_num(line)
    return None


def _pf(
    kind: FactKind,
    value: str | float | int | None,
    unit: FactUnit | None,
    period: str | None,
    section: str,
    offset: int,
    excerpt: str = "",
    confidence: str = "high",
) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence=confidence,  # type: ignore[arg-type]
        provenance=Provenance(
            section=section,
            char_offset=offset,
            excerpt=excerpt[:120] if excerpt else None,
        ),
    )


# ---------------------------------------------------------------------------
# Fiscal period
# ---------------------------------------------------------------------------

_RE_PERIOD_FULL = re.compile(
    r"(?:period\s+from\s+)?1\s+April\s+(\d{4})\s+to\s+31\s+March\s+(\d{4})",
    re.I,
)

_RE_FY_LABEL = re.compile(r"\bFY\s*(\d{4})[-–](\d{2})\b")


def _fiscal_period(content: str, source_date: datetime) -> str:
    """Return fiscal year end as 'YYYY-03-31'."""
    m = _RE_PERIOD_FULL.search(content)
    if m:
        return f"{m.group(2)}-03-31"
    m = _RE_FY_LABEL.search(content[:5000])
    if m:
        # "FY 2025-26" → start=2025, end_year=2026
        return f"{int(m.group(1)) + 1}-03-31"
    # Fallback: BRSR filed April–June after the March year-end
    return (
        f"{source_date.year}-03-31"
        if source_date.month >= 4
        else f"{source_date.year - 1}-03-31"
    )


# ---------------------------------------------------------------------------
# GHG emissions
# ---------------------------------------------------------------------------

_RE_SCOPE1 = re.compile(r"Total Scope 1 emissions", re.I)
_RE_SCOPE2 = re.compile(r"Total Scope 2 emissions", re.I)
_RE_SCOPE3 = re.compile(r"Total Scope 3 emissions", re.I)


def _extract_ghg(content: str, period: str, result: AnalysisResult) -> None:
    for label, re_pat, kind, section_name in [
        ("Scope 1", _RE_SCOPE1, FactKind.ESG_GHG_SCOPE1, "ghg_scope1"),
        ("Scope 2", _RE_SCOPE2, FactKind.ESG_GHG_SCOPE2, "ghg_scope2"),
        ("Scope 3", _RE_SCOPE3, FactKind.ESG_GHG_SCOPE3, "ghg_scope3"),
    ]:
        m = re_pat.search(content)
        if not m:
            result.warnings.append(f"GHG {label}: label not found")
            continue
        value = _first_number_line(content[m.start():])
        if value is None:
            result.warnings.append(f"GHG {label}: could not parse value")
            continue
        excerpt = f"{label}: {value:,.1f} tCO2e"
        result.facts.append(_pf(kind, value, FactUnit.TCO2E, period, section_name, m.start(), excerpt))
        result.excerpts[section_name] = content[m.start():m.start() + 200]


# ---------------------------------------------------------------------------
# Energy
# ---------------------------------------------------------------------------

_RE_ENERGY_RENEWABLE = re.compile(
    r"Total\s+energy\s+consumed\s+from\s+renewable\s+sources\s*\(A\+B\+C\)",
    re.I,
)
_RE_ENERGY_NONRENEWABLE = re.compile(
    r"Total\s+energy\s+consumed\s+from\s+non-renewable\s+sources\s*\(D\+E\+F\)",
    re.I,
)
_RE_ENERGY_TOTAL = re.compile(
    r"Total energy consumed\s*\(A\+B\+C\+D\+E\+F\)",
    re.I,
)


def _extract_energy(content: str, period: str, result: AnalysisResult) -> None:
    total: float | None = None
    renewable: float | None = None

    m_total = _RE_ENERGY_TOTAL.search(content)
    if m_total:
        total = _first_number_line(content[m_total.start():])

    m_ren = _RE_ENERGY_RENEWABLE.search(content)
    if m_ren:
        renewable = _first_number_line(content[m_ren.start():])

    if total is None and renewable is not None:
        # FY23 format: no total line — compute from renewable + non-renewable
        m_non = _RE_ENERGY_NONRENEWABLE.search(content)
        if m_non:
            non_renewable = _first_number_line(content[m_non.start():])
            if non_renewable is not None:
                total = renewable + non_renewable

    if total is not None:
        result.facts.append(_pf(
            FactKind.ESG_ENERGY_TOTAL_MJ, total, FactUnit.MEGAJOULE, period,
            "energy_total", m_total.start() if m_total else (m_ren.start() if m_ren else 0),
            f"Total energy: {total:,.0f} MJ",
        ))
    else:
        result.warnings.append("energy: could not extract total energy consumption")

    if total is not None and renewable is not None and total > 0:
        pct = round(renewable / total * 100, 1)
        result.facts.append(_pf(
            FactKind.ESG_ENERGY_RENEWABLE_PCT, pct, FactUnit.PERCENT, period,
            "energy_renewable", m_ren.start() if m_ren else 0,
            f"Renewable: {pct}% of total",
        ))
    elif renewable is None:
        result.warnings.append("energy: could not extract renewable energy value")


# ---------------------------------------------------------------------------
# Water
# ---------------------------------------------------------------------------

_RE_WATER = re.compile(r"Total volume of water consumption", re.I)


def _extract_water(content: str, period: str, result: AnalysisResult) -> None:
    m = _RE_WATER.search(content)
    if not m:
        result.warnings.append("water: 'Total volume of water consumption' not found")
        return
    value = _first_number_line(content[m.start():])
    if value is None:
        result.warnings.append("water: could not parse total water consumed")
        return
    result.facts.append(_pf(
        FactKind.ESG_WATER_CONSUMED_KL, value, FactUnit.KILOLITRE, period,
        "water_consumed", m.start(), f"Water: {value:,.0f} KL",
    ))
    result.excerpts["water_consumed"] = content[m.start():m.start() + 200]


# ---------------------------------------------------------------------------
# Waste
# ---------------------------------------------------------------------------

_RE_WASTE_HEADER = re.compile(r"Total Waste generated", re.I)
_RE_WASTE_RECOVERY = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*%[^.]*?waste generated is recovered",
    re.I,
)
# Matches each BRSR waste category row (A through H).
# G and H have multi-line descriptions, so we allow one optional non-digit
# continuation line between the category letter and the numeric value.
_RE_WASTE_CATEGORY = re.compile(
    r"\([A-H]\)[^\n]*\n(?:[^\d\n][^\n]*\n)?([\d][\d,. ]*)",
)

_WASTE_ANOMALY_THRESHOLD_MT = 50_000.0


def _extract_waste(content: str, period: str, result: AnalysisResult) -> None:
    # Total waste: sum of categories A–H
    m_hdr = _RE_WASTE_HEADER.search(content)
    if m_hdr:
        section = content[m_hdr.start(): m_hdr.start() + 4500]
        total = 0.0
        cat_count = 0
        for cat_m in _RE_WASTE_CATEGORY.finditer(section):
            val = _parse_num(cat_m.group(1))
            if val is not None:
                total += val
                cat_count += 1
        if cat_count >= 4:
            if total > _WASTE_ANOMALY_THRESHOLD_MT:
                result.warnings.append(
                    f"waste total anomalous ({total:,.0f} MT, exceeds "
                    f"{_WASTE_ANOMALY_THRESHOLD_MT:,.0f} MT threshold); "
                    "ESG_WASTE_GENERATED_MT suppressed"
                )
            else:
                result.facts.append(_pf(
                    FactKind.ESG_WASTE_GENERATED_MT, round(total, 1), FactUnit.METRIC_TONNE,
                    period, "waste_generated", m_hdr.start(),
                    f"Waste: {total:,.1f} MT (sum of {cat_count} categories)",
                ))
        else:
            result.warnings.append(
                f"waste: only {cat_count} categories found; total not reliable"
            )
    else:
        result.warnings.append("waste: 'Total Waste generated' not found")

    # Recovery percentage (independent of total — extracted from narrative)
    m_rec = _RE_WASTE_RECOVERY.search(content)
    if m_rec:
        pct = float(m_rec.group(1))
        result.facts.append(_pf(
            FactKind.ESG_WASTE_RECOVERY_PCT, pct, FactUnit.PERCENT, period,
            "waste_recovery", m_rec.start(),
            f"Waste recovery: {pct}%",
        ))
    else:
        result.warnings.append("waste: recovery % narrative not found")


# ---------------------------------------------------------------------------
# Workforce
# ---------------------------------------------------------------------------

_RE_HEADCOUNT = re.compile(r"Total employees\s*\(D\s*\+\s*E\)", re.I)
_RE_FEMALE_WAGE = re.compile(
    r"Gross wages paid to female as % of total wages\s*\*?\s*\n([\d.]+)",
    re.I,
)
_RE_TURNOVER_LABEL = re.compile(r"Turnover rate for permanent employees", re.I)
_RE_PERM_EMPLOYEES = re.compile(r"Permanent Employees?\s*\n", re.I)


def _extract_workforce(content: str, period: str, result: AnalysisResult) -> None:
    # Headcount and female %
    m = _RE_HEADCOUNT.search(content)
    if m:
        # Line layout: Total, Male_Count, Male_Pct, Female_Count, Female_Pct
        nums = []
        for line in content[m.start():m.start() + 300].split("\n")[1:]:
            v = _parse_num(line.strip())
            if v is not None:
                nums.append(v)
            if len(nums) == 5:
                break
        if nums:
            headcount = int(nums[0])
            result.facts.append(_pf(
                FactKind.ESG_WORKFORCE_HEADCOUNT, headcount, FactUnit.COUNT, period,
                "workforce_headcount", m.start(), f"Headcount: {headcount:,}",
            ))
        if len(nums) >= 5:
            female_pct = round(nums[4], 1)
            result.facts.append(_pf(
                FactKind.ESG_WORKFORCE_FEMALE_PCT, female_pct, FactUnit.PERCENT, period,
                "workforce_female_pct", m.start(), f"Female: {female_pct}%",
            ))
    else:
        result.warnings.append("workforce: 'Total employees (D + E)' not found")

    # Female wage %
    m = _RE_FEMALE_WAGE.search(content)
    if m:
        pct = float(m.group(1))
        result.facts.append(_pf(
            FactKind.ESG_WORKFORCE_FEMALE_WAGE_PCT, pct, FactUnit.PERCENT, period,
            "workforce_female_wage", m.start(), f"Female wage: {pct}% of total",
        ))
    else:
        result.warnings.append("workforce: female wage % not found")

    # Attrition (voluntary turnover rate for permanent employees — Total %)
    m_label = _RE_TURNOVER_LABEL.search(content)
    if m_label:
        # Search window includes 800 chars BEFORE the label (FY26 puts the table
        # before the label due to PDF extraction ordering) and 600 chars AFTER.
        start = max(0, m_label.start() - 800)
        window = content[start: m_label.end() + 600]
        m_perm = _RE_PERM_EMPLOYEES.search(window)
        if m_perm:
            attrition_nums: list[float] = []
            for line in window[m_perm.end():].split("\n"):
                stripped = line.strip().rstrip("%").strip()
                v = _parse_num(stripped)
                if v is not None and 0.0 < v < 100.0:
                    attrition_nums.append(v)
                if len(attrition_nums) == 3:
                    break
            if len(attrition_nums) >= 3:
                total_pct = round(attrition_nums[2], 1)
                result.facts.append(_pf(
                    FactKind.ESG_WORKFORCE_ATTRITION_PCT, total_pct, FactUnit.PERCENT, period,
                    "workforce_attrition", m_label.start(),
                    f"Voluntary attrition: {total_pct}%",
                ))
            else:
                result.warnings.append(
                    f"attrition: found {len(attrition_nums)} numbers, need 3"
                )
        else:
            result.warnings.append("attrition: 'Permanent Employees' row not found")
    else:
        result.warnings.append("attrition: 'Turnover rate for permanent employees' not found")


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

_RE_LTIFR = re.compile(
    r"Lost Time Injury Frequency Rate\s*\(LTIFR\).{0,120}?\nEmployees\n([\d.]+)",
    re.I | re.DOTALL,
)


def _extract_safety(content: str, period: str, result: AnalysisResult) -> None:
    m = _RE_LTIFR.search(content)
    if m:
        value = float(m.group(1))
        result.facts.append(_pf(
            FactKind.ESG_SAFETY_LTIFR, value, None, period,
            "safety_ltifr", m.start(),
            f"LTIFR: {value} per million person-hours",
        ))
    else:
        result.warnings.append("safety: LTIFR not found")


# ---------------------------------------------------------------------------
# SBTi climate commitments
# ---------------------------------------------------------------------------

_RE_SBTI_SCOPE12 = re.compile(
    r"reduce absolute\s+Scope 1 and 2 GHG emissions\s+(\d+)\s*%\s+by\s+FY\s*(\d{4})",
    re.I,
)
_RE_SBTI_SCOPE3 = re.compile(
    r"reduce absolute\s+Scope 3 emissions\s+(\d+)\s*%\s+by\s+FY\s*(\d{4})",
    re.I,
)


def _extract_sbti(content: str, result: AnalysisResult) -> None:
    for re_pat, kind, label in [
        (_RE_SBTI_SCOPE12, FactKind.ESG_CLIMATE_SBTI_SCOPE12_REDUCTION_PCT, "Scope1+2"),
        (_RE_SBTI_SCOPE3, FactKind.ESG_CLIMATE_SBTI_SCOPE3_REDUCTION_PCT, "Scope3"),
    ]:
        m = re_pat.search(content)
        if m:
            pct = float(m.group(1))
            target_year = int(m.group(2))
            target_period = f"{target_year}-03-31"
            result.facts.append(_pf(
                kind, pct, FactUnit.PERCENT, target_period,
                "sbti_commitment", m.start(),
                f"SBTi {label}: {pct:.0f}% reduction by FY{target_year}",
            ))
        else:
            result.warnings.append(f"SBTi: {label} commitment not found")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract ESG facts from one BRSR filing.

    Raises ValueError for missing evidence or wrong document kind.
    """
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(f"evidence_id {evidence_id!r} not found in KnowledgeBase")
    if entry.kind != "brsr":
        raise ValueError(
            f"evidence_id {evidence_id!r} has kind {entry.kind!r}; expected 'brsr'"
        )

    content = kb.get_content(evidence_id) or ""

    source_date = (
        datetime.fromisoformat(entry.source_date)
        if isinstance(entry.source_date, str)
        else entry.source_date
    )

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="brsr",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=source_date,
    )

    if not content.strip():
        result.warnings.append("document content is empty")
        return result

    period = _fiscal_period(content, source_date)
    result.excerpts["fiscal_period"] = period

    _extract_ghg(content, period, result)
    _extract_energy(content, period, result)
    _extract_water(content, period, result)
    _extract_waste(content, period, result)
    _extract_workforce(content, period, result)
    _extract_safety(content, period, result)
    _extract_sbti(content, result)

    # Confidence: require at minimum Scope 1, Scope 2, and headcount
    primary_kinds = {
        FactKind.ESG_GHG_SCOPE1,
        FactKind.ESG_GHG_SCOPE2,
        FactKind.ESG_WORKFORCE_HEADCOUNT,
    }
    extracted = {f.kind for f in result.facts}
    if primary_kinds <= extracted:
        full_kinds = {
            FactKind.ESG_GHG_SCOPE3,
            FactKind.ESG_ENERGY_TOTAL_MJ,
            FactKind.ESG_WATER_CONSUMED_KL,
            FactKind.ESG_SAFETY_LTIFR,
        }
        result.confidence = "high" if (full_kinds <= extracted) else "medium"
    elif primary_kinds & extracted:
        result.confidence = "medium"
    # else stays "low"

    return result
