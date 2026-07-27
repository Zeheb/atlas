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

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Literal

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    EntityMention,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.knowledge.base import KnowledgeBase
from atlas.knowledge.entities import EntityKind, EntityResolver

ANALYZER_VERSION = "1.1"

# Named-shareholder emission (M-P1.3, Q24). The XBRL names every shareholder
# holding >1%, in per-holder detail contexts "D_<Axis>_Context<N>". Only the
# UNAMBIGUOUSLY PUBLIC axes are emitted; the promoter table and any axis whose
# ownership class is not certain (notably "OthersIndianShareholders", which
# carries promoter-group entities) are excluded. EntityKind is decided from the
# XBRL ownership category ONLY — never from the holder's name. Under-emit rather
# than misattribute (Phase 1 resolver philosophy).
_TAG_HOLDER_NAME = "NameOfTheShareholder"


def _public_holder_class(axis: str) -> tuple[str, EntityKind] | None:
    """Map an ownership-category axis to (category, EntityKind), or None to skip.

    None means "not an emittable public holder" — either explicitly excluded
    (promoter / OthersIndianShareholders) or an unrecognised axis, both of which
    are skipped rather than guessed.
    """
    if "Promoter" in axis or axis == "OthersIndianShareholders":
        return None
    if "MutualFund" in axis:
        return ("mutual_fund", "organization")
    if "InsuranceCompanies" in axis:
        return ("insurance", "organization")
    if "ForeignPortfolio" in axis:
        return ("fpi", "organization")
    if axis == "OtherInstitutions":
        return ("other_institution", "organization")
    if axis == "OtherNonInstitutions":
        return ("other_non_institution", "organization")
    if "Individual" in axis and "InExcessOfRsTwoLakh" in axis:
        return ("individual_hni", "person")
    return None


def _axis_of(context_id: str) -> str:
    """Strip the "D_" prefix and "_Context<N>" suffix from a detail context."""
    a = re.sub(r"^D_", "", context_id)
    return re.sub(r"_Context\d+$", "", a)


def _extract_named_public_holders(
    fmap: dict[tuple[str, str], str], resolver: EntityResolver
) -> list[EntityMention]:
    """Resolve named >1% PUBLIC shareholders to entity mentions (role = the
    ownership category). De-duplicated within this filing by entity id."""
    mentions: list[EntityMention] = []
    seen: set[str] = set()
    for (tag, ctx), value in fmap.items():
        if tag != _TAG_HOLDER_NAME or not value.strip():
            continue
        cls = _public_holder_class(_axis_of(ctx))
        if cls is None:
            continue
        category, kind = cls
        entity = resolver.resolve(value, kind)
        if entity.entity_id in seen:
            continue
        seen.add(entity.entity_id)
        mentions.append(EntityMention(
            entity=entity,
            role=category,
            affiliation=None,
            provenance=Provenance(section=ctx, char_offset=None, excerpt=value.strip()[:120]),
        ))
    return mentions

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

# BSE changed their XBRL format sometime between the 2025-07 and 2025-10
# filings: percentages switched from a 0–100 scale ("33.19" for 33.19%)
# to a 0–1 decimal scale ("0.3319" for 33.19%).  The schema namespace URL
# is NOT a reliable indicator — the same schema date ("2025-05-31") appears
# in both formats.  Instead we inspect the raw values: if any percentage
# tag in the document exceeds 1.5, the document is in 0–100 scale.
_RE_PCT_VALUE = re.compile(
    r"<[^>]+ShareholdingAsAPercentageOfTotalNumberOfShares[^>]*>([^<]+)<"
)


def _detect_decimal_format(content: str) -> bool:
    """Return True if the XBRL uses the new 0–1 decimal percentage scale.

    Checks all percentage values in the document.  Any value > 1.5 means
    the old 0–100 format is in use; all values ≤ 1.5 means the new 0–1
    format is in use.
    """
    for m in _RE_PCT_VALUE.finditer(content):
        try:
            if float(m.group(1)) > 1.5:
                return False  # old 0–100 format
        except ValueError:
            continue
    return True  # no value exceeded 1.5 → assume new 0–1 format


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


def _pct(fmap: dict[tuple[str, str], str], ctx: str, *, decimal_scale: bool) -> float | None:
    """Return the shareholding percentage (0–100) for a context, or None.

    Args:
        decimal_scale: True for the new BSE schema (≥ 2025-10-31) where values
            are stored as 0–1 decimals; False for the older schema where values
            are already in 0–100 percent form.
    """
    raw = _get(fmap, _TAG_PCT, ctx)
    if raw is None:
        return None
    try:
        val = float(raw)
        return round(val * 100 if decimal_scale else val, 4)
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
    # BSE changed from 0–100 percent to 0–1 decimal scale in Oct 2025.
    decimal_scale = _detect_decimal_format(content)

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
             "Promoter and Promoter Group percentage not found", decimal_scale=decimal_scale)
    _add_pct(result, fmap, FactKind.OWNERSHIP_PUBLIC_PCT, _CTX_PUBLIC, period,
             "Public shareholding percentage not found", decimal_scale=decimal_scale)
    _add_pct(result, fmap, FactKind.OWNERSHIP_FPI_PCT, _CTX_FPI, period,
             "FPI percentage not found", decimal_scale=decimal_scale)
    _add_pct(result, fmap, FactKind.OWNERSHIP_DII_PCT, _CTX_DII, period,
             "DII percentage not found", decimal_scale=decimal_scale)
    _add_pct(result, fmap, FactKind.OWNERSHIP_MF_PCT, _CTX_MF, period,
             "Mutual funds percentage not found", decimal_scale=decimal_scale)
    _add_pct(result, fmap, FactKind.OWNERSHIP_INSURANCE_PCT, _CTX_INSURANCE, period,
             "Insurance companies percentage not found", decimal_scale=decimal_scale)
    _add_pct(result, fmap, FactKind.OWNERSHIP_NRI_PCT, _CTX_NRI, period,
             "NRI percentage not found", decimal_scale=decimal_scale)
    _add_pct(result, fmap, FactKind.OWNERSHIP_RETAIL_PCT, _CTX_RETAIL, period,
             "Retail individual percentage not found", warn_missing=False, decimal_scale=decimal_scale)
    _add_pct(result, fmap, FactKind.OWNERSHIP_HNI_PCT, _CTX_HNI, period,
             "HNI individual percentage not found", warn_missing=False, decimal_scale=decimal_scale)

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
        pledged_pct = _pct(fmap, _CTX_PROMOTER + "_Pledged", decimal_scale=decimal_scale)
        if pledged_pct is None:
            # Try the encumbered percentage tag in the promoter context
            raw = _get(fmap, _TAG_PCT_ENCUMBERED, _CTX_PROMOTER)
            if raw:
                try:
                    val = float(raw)
                    pledged_pct = round(val * 100 if decimal_scale else val, 4)
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

    # Named >1% public shareholders -> resolved entity mentions (M-P1.3, Q24).
    # Per-document resolver, like the transcript path; cross-filing unification
    # is a later refinement.
    result.entities.extend(_extract_named_public_holders(fmap, EntityResolver()))

    return result


def _add_pct(
    result: AnalysisResult,
    fmap: dict[tuple[str, str], str],
    kind: FactKind,
    ctx: str,
    period: str,
    warn_msg: str,
    warn_missing: bool = True,
    *,
    decimal_scale: bool,
) -> None:
    val = _pct(fmap, ctx, decimal_scale=decimal_scale)
    if val is not None:
        f = _ownership_fact(kind, val, FactUnit.PERCENT, ctx, period)
        if f:
            result.facts.append(f)
    elif warn_missing:
        result.warnings.append(warn_msg)
