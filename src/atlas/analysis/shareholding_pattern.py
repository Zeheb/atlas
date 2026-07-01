"""Rule-based fact extraction from BSE XBRL shareholding pattern filings.

BSE XBRL format notes
---------------------
Filings are standard XBRL instance documents served at:
  https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/{XbrlFile}

Facts are flat XML elements with a contextRef attribute.  Context IDs encode
the shareholder category (e.g. "ShareholdingOfPromoterAndPromoterGroup_ContextI",
"MutualFundsOrUTI_ContextI").  Category summary contexts end in "_ContextI";
duration variants for quarterly-change data are prefixed "D_".

All share-count facts use tag "NumberOfFullyPaidUpEquityShares".
All percentage facts use tag "ShareholdingAsAPercentageOfTotalNumberOfShares".
Percentages are stored on a 0–1 scale in the XBRL (0.7177 = 71.77%); this
analyzer multiplies by 100 before storing so FactUnit.PERCENT means 0–100
throughout Atlas.

Context IDs may carry a BSE schema version suffix (e.g. the namespace URI
contains "2025-10-31") but the context IDs themselves are stable across schema
versions; the extractor keys only on context IDs, not namespace URIs.

Quarter-over-quarter comparisons arise naturally from the existing model:
all OWNERSHIP_* facts carry period = quarter_end_date (ISO "YYYY-MM-DD").
A consumer groups by kind + period to reconstruct the time series without
any company-layer aggregation.

Promoter pledging
-----------------
The boolean "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged" is
extracted from the MainI context.  When false (most large caps), pledged_pct
is emitted as 0.  When true, pledged shares and percentages are read from the
promoter pledging sub-context; a warning is emitted if those values are absent.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Literal

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
# XBRL context IDs for the categories we extract
# These IDs are stable across BSE schema versions.
# ---------------------------------------------------------------------------

_CTX_TOTAL = "ShareholdingPattern_ContextI"
_CTX_PROMOTER = "ShareholdingOfPromoterAndPromoterGroup_ContextI"
_CTX_PUBLIC = "PublicShareholding_ContextI"
_CTX_FPI = "InstitutionsForeign_ContextI"               # FPI Cat-I + Cat-II combined
_CTX_DII = "InstitutionsDomestic_ContextI"
_CTX_MF = "MutualFundsOrUTI_ContextI"
_CTX_INSURANCE = "InsuranceCompanies_ContextI"
_CTX_NRI = "NonResidentIndians_ContextI"
_CTX_RETAIL = (
    "ResidentIndividualShareholdersHolding"
    "NominalShareCapitalUpToRsTwoLakh_ContextI"
)
_CTX_HNI = (
    "ResidentIndividualShareholdersHolding"
    "NominalShareCapitalInExcessOfRsTwoLakh_ContextI"
)
_CTX_MAIN_I = "MainI"

# Pledge-related tag in MainI context
_TAG_PLEDGED_BOOL = "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledged"
# When pledging exists: use promoter sub-context for pledge amounts
_TAG_SHARES_ENCUMBERED = "NumberOfSharesEncumbered"
_TAG_PCT_ENCUMBERED = "PercentageOfSharesEncumberedToTotalSharesHeldByPromoter"

_TAG_SHARES = "NumberOfFullyPaidUpEquityShares"
_TAG_PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
_TAG_DATE = "DateOfReport"


# ---------------------------------------------------------------------------
# XBRL parsing helpers
# ---------------------------------------------------------------------------

def _build_fact_map(root: ET.Element) -> dict[tuple[str, str], str]:
    """Return {(local_tag, context_id): text_value} for all fact elements.

    Tags with a namespace prefix are stripped to their local name so the
    caller is insulated from namespace URI changes across schema versions.
    """
    fmap: dict[tuple[str, str], str] = {}
    for elem in root.iter():
        ctx = elem.get("contextRef")
        if ctx is None:
            continue
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if elem.text:
            fmap[(tag, ctx)] = elem.text.strip()
    return fmap


def _get(fmap: dict[tuple[str, str], str], tag: str, ctx: str) -> str | None:
    return fmap.get((tag, ctx))


def _pct(fmap: dict[tuple[str, str], str], ctx: str) -> float | None:
    """Return the shareholding percentage (0–100) for a context, or None."""
    raw = _get(fmap, _TAG_PCT, ctx)
    if raw is None:
        return None
    try:
        return round(float(raw) * 100, 4)
    except ValueError:
        return None


def _shares(fmap: dict[tuple[str, str], str], ctx: str) -> int | None:
    raw = _get(fmap, _TAG_SHARES, ctx)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _ownership_fact(
    kind: FactKind,
    value: float | int | None,
    unit: FactUnit,
    ctx_id: str,
    period: str,
    confidence: Literal["high", "medium", "low"] = "high",
) -> AnalysisFact | None:
    """Construct one ownership fact; returns None if value is None."""
    if value is None:
        return None
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence=confidence,
        provenance=Provenance(
            section=ctx_id,
            char_offset=None,
            excerpt=None,
        ),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
    """Extract structured ownership facts from a BSE XBRL shareholding pattern.

    Raises ValueError for missing, wrong-kind, or empty-content documents.
    """
    entry = kb.get(evidence_id)
    if entry is None:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: not in knowledge base"
        )
    if entry.kind != "shareholding_pattern":
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: "
            f"kind={entry.kind!r} is not 'shareholding_pattern'"
        )

    content = kb.get_content(evidence_id)
    if not content:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: document has no content"
        )

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(
            f"cannot analyze evidence_id={evidence_id!r}: XML parse error: {exc}"
        ) from exc

    fmap = _build_fact_map(root)

    result = AnalysisResult(
        evidence_id=evidence_id,
        kind="shareholding_pattern",
        analyzer_version=ANALYZER_VERSION,
        confidence="low",
        source_date=datetime.fromisoformat(entry.source_date),
    )

    # --- Quarter-end date (becomes AnalysisFact.period for all facts) ---
    period = _get(fmap, _TAG_DATE, _CTX_MAIN_I)
    if period is None:
        result.warnings.append("DateOfReport not found in MainI context")
        period = entry.source_date[:10]  # fall back to filing date

    # --- Total outstanding shares ---
    total_shares = _shares(fmap, _CTX_TOTAL)
    if total_shares is not None:
        f = _ownership_fact(
            FactKind.OWNERSHIP_TOTAL_SHARES, total_shares,
            FactUnit.COUNT, _CTX_TOTAL, period,
        )
        if f:
            result.facts.append(f)
    else:
        result.warnings.append("Total shares not found in ShareholdingPattern_ContextI")

    # --- Category percentages ---
    _add_pct(result, fmap, FactKind.OWNERSHIP_PROMOTER_PCT, _CTX_PROMOTER, period,
             "Promoter and Promoter Group percentage not found")
    _add_pct(result, fmap, FactKind.OWNERSHIP_PUBLIC_PCT, _CTX_PUBLIC, period,
             "Public shareholding percentage not found")
    _add_pct(result, fmap, FactKind.OWNERSHIP_FPI_PCT, _CTX_FPI, period,
             "FPI percentage not found")
    _add_pct(result, fmap, FactKind.OWNERSHIP_DII_PCT, _CTX_DII, period,
             "DII percentage not found")
    _add_pct(result, fmap, FactKind.OWNERSHIP_MF_PCT, _CTX_MF, period,
             "Mutual funds percentage not found")
    _add_pct(result, fmap, FactKind.OWNERSHIP_INSURANCE_PCT, _CTX_INSURANCE, period,
             "Insurance companies percentage not found")
    _add_pct(result, fmap, FactKind.OWNERSHIP_NRI_PCT, _CTX_NRI, period,
             "NRI percentage not found")
    _add_pct(result, fmap, FactKind.OWNERSHIP_RETAIL_PCT, _CTX_RETAIL, period,
             "Retail individual percentage not found", warn_missing=False)
    _add_pct(result, fmap, FactKind.OWNERSHIP_HNI_PCT, _CTX_HNI, period,
             "HNI individual percentage not found", warn_missing=False)

    # --- Promoter pledging ---
    pledged_raw = _get(fmap, _TAG_PLEDGED_BOOL, _CTX_MAIN_I)
    if pledged_raw is None:
        result.warnings.append("Promoter pledge flag not found")
    elif pledged_raw.lower() == "false":
        pledged_fact = _ownership_fact(
            FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT, 0.0,
            FactUnit.PERCENT, _CTX_PROMOTER, period,
        )
        if pledged_fact:
            result.facts.append(pledged_fact)
    else:
        # Pledges exist — try to extract actual percentage
        pledged_pct = _pct(fmap, _CTX_PROMOTER + "_Pledged")
        if pledged_pct is None:
            # Try the encumbered percentage tag in the promoter context
            raw = _get(fmap, _TAG_PCT_ENCUMBERED, _CTX_PROMOTER)
            if raw:
                try:
                    pledged_pct = round(float(raw) * 100, 4)
                except ValueError:
                    pass
        if pledged_pct is not None:
            pledged_fact = _ownership_fact(
                FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT, pledged_pct,
                FactUnit.PERCENT, _CTX_PROMOTER, period,
            )
            if pledged_fact:
                result.facts.append(pledged_fact)
        else:
            result.warnings.append(
                "Promoter pledging flagged as true but pledge percentage could not be extracted"
            )

    # --- Result-level confidence ---
    extracted_kinds = {f.kind for f in result.facts}
    core_kinds = {
        FactKind.OWNERSHIP_TOTAL_SHARES,
        FactKind.OWNERSHIP_PROMOTER_PCT,
        FactKind.OWNERSHIP_PUBLIC_PCT,
        FactKind.OWNERSHIP_FPI_PCT,
        FactKind.OWNERSHIP_DII_PCT,
    }
    if core_kinds.issubset(extracted_kinds):
        result.confidence = "high"
    elif FactKind.OWNERSHIP_TOTAL_SHARES in extracted_kinds and FactKind.OWNERSHIP_PROMOTER_PCT in extracted_kinds:
        result.confidence = "medium"

    return result


def _add_pct(
    result: AnalysisResult,
    fmap: dict[tuple[str, str], str],
    kind: FactKind,
    ctx: str,
    period: str,
    warn_msg: str,
    warn_missing: bool = True,
) -> None:
    val = _pct(fmap, ctx)
    if val is not None:
        f = _ownership_fact(kind, val, FactUnit.PERCENT, ctx, period)
        if f:
            result.facts.append(f)
    elif warn_missing:
        result.warnings.append(warn_msg)
