"""Company profile builder.

Assembles a collection of AnalysisResult objects (from multiple evidence
documents) into a CompanyProfile for a single company.

Dispatch table
--------------
financial_results      → FinancialTimeSeries + DividendEvents + SegmentTimeSeries
earnings_transcript    → supplements FinancialTimeSeries (TCV, margins)
brsr                   → ESGTimeSeries
shareholding_pattern   → OwnershipTimeSeries
buyback                → CapitalEventLedger.buybacks
acquisition            → CapitalEventLedger.acquisitions
board_outcome          → CapitalEventLedger (dividends | acquisitions | investments)
credit_rating_report   → CreditHistory

Other kinds (annual_report, investor_presentation, agm_notice) are currently
ignored — they do not populate structured time-series in V1.

Processing order
----------------
financial_results results are processed with regular dict.update() so that a
revised filing correctly overwrites an earlier one for the same period.
earnings_transcript results use setdefault() so that authoritative XBRL data
from financial_results is never overwritten by spoken transcript numbers.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit
from atlas.company.model import (
    AcquisitionEvent,
    BuybackEvent,
    CapitalEventLedger,
    CompanyProfile,
    CreditHistory,
    CreditRatingEntry,
    DividendEvent,
    ESGSnapshot,
    ESGTimeSeries,
    FinancialSnapshot,
    FinancialTimeSeries,
    InvestmentEvent,
    OwnershipSnapshot,
    OwnershipTimeSeries,
    SegmentEntry,
    SegmentTimeSeries,
)

# ---------------------------------------------------------------------------
# FactKind classification helpers
# ---------------------------------------------------------------------------

_FINANCIAL_SNAPSHOT_KINDS: frozenset[FactKind] = frozenset(
    k for k in FactKind if k.value.startswith("financial_")
)

_ESG_KINDS: frozenset[FactKind] = frozenset(
    k for k in FactKind if k.value.startswith("esg_")
)

_OWNERSHIP_KINDS: frozenset[FactKind] = frozenset(
    k for k in FactKind if k.value.startswith("ownership_")
)


def _basis_from_section(section: str) -> str | None:
    """Infer "consolidated" or "standalone" from provenance.section prefix.

    Balance sheet and cash flow sections in financial_results use unprefixed
    names ("balance_sheet", "cash_flow_statement") because the annual filing
    presents only a single consolidated BS/CF.  These default to "consolidated".
    """
    if section.startswith("consolidated"):
        return "consolidated"
    if section.startswith("standalone"):
        return "standalone"
    if section in ("balance_sheet", "cash_flow_statement"):
        return "consolidated"
    return None


# ---------------------------------------------------------------------------
# Per-kind ingestion helpers
# ---------------------------------------------------------------------------


def _ingest_financial_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    period_type = "quarterly"
    for f in result.facts:
        if f.kind == FactKind.REPORT_PERIOD_TYPE and f.value:
            period_type = str(f.value)
            break

    # Group numeric facts by (period, basis)
    snaps: dict[tuple[str, str], dict[FactKind, float]] = defaultdict(dict)
    for fact in result.facts:
        if fact.kind not in _FINANCIAL_SNAPSHOT_KINDS:
            continue
        if fact.period is None or not isinstance(fact.value, (int, float)):
            continue
        section = fact.provenance.section if fact.provenance else ""
        basis = _basis_from_section(section)
        if basis is None:
            continue
        snaps[(fact.period, basis)][fact.kind] = float(fact.value)

    existing = {(s.period, s.basis): s for s in profile.financial.snapshots}
    for (period, basis), facts in snaps.items():
        if (period, basis) in existing:
            existing[(period, basis)].facts.update(facts)
            if result.evidence_id not in existing[(period, basis)].sources:
                existing[(period, basis)].sources.append(result.evidence_id)
        else:
            snap = FinancialSnapshot(
                period=period,
                period_type=period_type,
                basis=basis,
                facts=facts,
                sources=[result.evidence_id],
            )
            profile.financial.snapshots.append(snap)
            existing[(period, basis)] = snap

    _ingest_dividend_facts(result, profile)
    _ingest_segment_facts(result, profile)


def _ingest_transcript_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    period_type = "quarterly"
    for f in result.facts:
        if f.kind == FactKind.REPORT_PERIOD_TYPE and f.value:
            period_type = str(f.value)
            break

    snaps: dict[str, dict[FactKind, float]] = defaultdict(dict)
    for fact in result.facts:
        if fact.kind not in _FINANCIAL_SNAPSHOT_KINDS:
            continue
        if fact.period is None or not isinstance(fact.value, (int, float)):
            continue
        snaps[fact.period][fact.kind] = float(fact.value)

    existing = {(s.period, s.basis): s for s in profile.financial.snapshots}
    for period, facts in snaps.items():
        key = (period, "consolidated")
        if key in existing:
            # Supplement only — do not overwrite authoritative XBRL data
            for fk, fv in facts.items():
                existing[key].facts.setdefault(fk, fv)
            if result.evidence_id not in existing[key].sources:
                existing[key].sources.append(result.evidence_id)
        else:
            snap = FinancialSnapshot(
                period=period,
                period_type=period_type,
                basis="consolidated",
                facts=facts,
                sources=[result.evidence_id],
            )
            profile.financial.snapshots.append(snap)
            existing[key] = snap


def _ingest_brsr_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    snaps: dict[str, dict[FactKind, float]] = defaultdict(dict)
    for fact in result.facts:
        if fact.kind not in _ESG_KINDS:
            continue
        if fact.period is None or not isinstance(fact.value, (int, float)):
            continue
        snaps[fact.period][fact.kind] = float(fact.value)

    existing = {s.period: s for s in profile.esg.snapshots}
    for period, facts in snaps.items():
        if period in existing:
            existing[period].facts.update(facts)
            if result.evidence_id not in existing[period].sources:
                existing[period].sources.append(result.evidence_id)
        else:
            snap = ESGSnapshot(
                period=period,
                facts=facts,
                sources=[result.evidence_id],
            )
            profile.esg.snapshots.append(snap)
            existing[period] = snap


def _ingest_shp_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    snaps: dict[str, dict[FactKind, float]] = defaultdict(dict)
    for fact in result.facts:
        if fact.kind not in _OWNERSHIP_KINDS:
            continue
        if fact.period is None or not isinstance(fact.value, (int, float)):
            continue
        snaps[fact.period][fact.kind] = float(fact.value)

    existing = {s.period: s for s in profile.ownership.snapshots}
    for period, facts in snaps.items():
        if period in existing:
            existing[period].facts.update(facts)
        else:
            snap = OwnershipSnapshot(
                period=period,
                facts=facts,
                evidence_id=result.evidence_id,
            )
            profile.ownership.snapshots.append(snap)
            existing[period] = snap


def _ingest_credit_rating_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    agency = next(
        (str(f.value) for f in result.facts if f.kind == FactKind.CREDIT_AGENCY),
        "",
    )

    instrument_facts = [f for f in result.facts if f.kind == FactKind.CREDIT_INSTRUMENT]
    if not instrument_facts:
        return

    for inst_fact in instrument_facts:
        inst_name = str(inst_fact.value)
        inst_sec = inst_fact.provenance.section if inst_fact.provenance else ""
        is_esg = (inst_name == "ESG")

        def _match(f: AnalysisFact, s: str = inst_sec, esg: bool = is_esg) -> bool:
            sec = f.provenance.section if f.provenance else ""
            if esg:
                return sec in ("esg", "document")
            return sec == s

        rating = next(
            (str(f.value) for f in result.facts if f.kind == FactKind.CREDIT_RATING and _match(f)),
            None,
        )
        outlook = next(
            (str(f.value) for f in result.facts if f.kind == FactKind.CREDIT_OUTLOOK and _match(f)),
            None,
        )
        action = next(
            (str(f.value) for f in result.facts if f.kind == FactKind.CREDIT_ACTION and _match(f)),
            None,
        )
        amount_fact = next(
            (f for f in result.facts if f.kind == FactKind.CREDIT_AMOUNT and _match(f)),
            None,
        )
        amount = (
            float(amount_fact.value)
            if amount_fact and isinstance(amount_fact.value, (int, float))
            else None
        )

        profile.credit_history.entries.append(CreditRatingEntry(
            source_date=result.source_date,
            agency=agency,
            instrument=inst_name,
            rating=rating,
            outlook=outlook,
            action=action,
            amount=amount,
            evidence_id=result.evidence_id,
        ))


def _ingest_dividend_facts(result: AnalysisResult, profile: CompanyProfile) -> None:
    type_by_offset: dict[int | None, str] = {}
    for fact in result.facts:
        if fact.kind == FactKind.CAPITAL_DIVIDEND_TYPE:
            off = fact.provenance.char_offset if fact.provenance else None
            type_by_offset[off] = str(fact.value)

    record_date = next(
        (str(f.value) for f in result.facts if f.kind == FactKind.CAPITAL_DIVIDEND_RECORD_DATE),
        None,
    )
    payment_date = next(
        (str(f.value) for f in result.facts if f.kind == FactKind.CAPITAL_DIVIDEND_PAYMENT_DATE),
        None,
    )

    for fact in result.facts:
        if fact.kind != FactKind.CAPITAL_DIVIDEND_PER_SHARE:
            continue
        if not isinstance(fact.value, (int, float)):
            continue
        off = fact.provenance.char_offset if fact.provenance else None
        profile.capital_events.dividends.append(DividendEvent(
            source_date=result.source_date,
            per_share=float(fact.value),
            dividend_type=type_by_offset.get(off, ""),
            record_date=record_date,
            payment_date=payment_date,
            evidence_id=result.evidence_id,
        ))


def _ingest_acquisition_facts(result: AnalysisResult, profile: CompanyProfile) -> None:
    consideration = next(
        (str(f.value) for f in result.facts if f.kind == FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE),
        None,
    )
    stake = next(
        (float(f.value) for f in result.facts
         if f.kind == FactKind.CAPITAL_ACQ_STAKE_PCT and isinstance(f.value, (int, float))),
        None,
    )
    expected = next(
        (str(f.value) for f in result.facts if f.kind == FactKind.CAPITAL_ACQ_EXPECTED_COMPLETION),
        None,
    )
    ev_fact = next(
        (f for f in result.facts if f.kind == FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE),
        None,
    )
    ev_value = float(ev_fact.value) if ev_fact and isinstance(ev_fact.value, (int, float)) else None
    ev_unit = ev_fact.unit if ev_fact else None

    for fact in result.facts:
        if fact.kind != FactKind.CAPITAL_ACQ_TARGET_NAME:
            continue
        profile.capital_events.acquisitions.append(AcquisitionEvent(
            source_date=result.source_date,
            target_name=str(fact.value),
            consideration_type=consideration,
            enterprise_value=ev_value,
            enterprise_value_unit=ev_unit,
            stake_pct=stake,
            expected_completion=expected,
            evidence_id=result.evidence_id,
        ))


def _ingest_buyback_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    first: dict[FactKind, AnalysisFact] = {}
    for fact in result.facts:
        first.setdefault(fact.kind, fact)

    def _fval(k: FactKind) -> float | None:
        f = first.get(k)
        return float(f.value) if f and isinstance(f.value, (int, float)) else None

    shares_offered = _fval(FactKind.CAPITAL_BUYBACK_SHARES_OFFERED)
    shares_bought = _fval(FactKind.CAPITAL_BUYBACK_SHARES_BOUGHT)
    record_fact = first.get(FactKind.CAPITAL_BUYBACK_RECORD_DATE)

    if shares_bought is not None:
        sub_type = "extinguishment"
    elif shares_offered is not None:
        sub_type = "announcement"
    elif record_fact is not None:
        sub_type = "schedule"
    else:
        sub_type = "unknown"

    profile.capital_events.buybacks.append(BuybackEvent(
        source_date=result.source_date,
        sub_type=sub_type,
        amount=_fval(FactKind.CAPITAL_BUYBACK_AMOUNT),
        price_per_share=_fval(FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE),
        shares_offered=int(shares_offered) if shares_offered is not None else None,
        shares_bought=int(shares_bought) if shares_bought is not None else None,
        record_date=str(record_fact.value) if record_fact else None,
        evidence_id=result.evidence_id,
    ))


def _ingest_board_outcome_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    kinds = {f.kind for f in result.facts}

    if FactKind.CAPITAL_DIVIDEND_PER_SHARE in kinds:
        _ingest_dividend_facts(result, profile)

    if FactKind.CAPITAL_ACQ_TARGET_NAME in kinds:
        _ingest_acquisition_facts(result, profile)

    if FactKind.CAPITAL_INVEST_TARGET_NAME in kinds:
        amount_fact = next(
            (f for f in result.facts if f.kind == FactKind.CAPITAL_INVEST_AMOUNT),
            None,
        )
        amount = float(amount_fact.value) if amount_fact and isinstance(amount_fact.value, (int, float)) else None
        amount_unit = amount_fact.unit if amount_fact else None
        for fact in result.facts:
            if fact.kind == FactKind.CAPITAL_INVEST_TARGET_NAME:
                profile.capital_events.investments.append(InvestmentEvent(
                    source_date=result.source_date,
                    target_name=str(fact.value),
                    amount=amount,
                    amount_unit=amount_unit,
                    evidence_id=result.evidence_id,
                ))


def _ingest_segment_facts(result: AnalysisResult, profile: CompanyProfile) -> None:
    # Map char_offset → segment name (SEGMENT_NAME and SEGMENT_REVENUE share the offset)
    name_by_offset: dict[int, str] = {}
    all_names: list[str] = []
    for fact in result.facts:
        if fact.kind == FactKind.SEGMENT_NAME and fact.period:
            name = str(fact.value)
            all_names.append(name)
            if fact.provenance and fact.provenance.char_offset is not None:
                name_by_offset[fact.provenance.char_offset] = name

    if not all_names:
        return

    rev_by_period_name: dict[tuple[str, str], float] = {}
    for fact in result.facts:
        if fact.kind != FactKind.SEGMENT_REVENUE or not fact.period:
            continue
        if not isinstance(fact.value, (int, float)):
            continue
        off = fact.provenance.char_offset if fact.provenance else None
        name = name_by_offset.get(off) if off is not None else None
        if name:
            rev_by_period_name[(fact.period, name)] = float(fact.value)

    ebit_by_period_name: dict[tuple[str, str], float] = {}
    for fact in result.facts:
        if fact.kind != FactKind.SEGMENT_EBIT or not fact.period:
            continue
        if not isinstance(fact.value, (int, float)):
            continue
        # SEGMENT_EBIT excerpt starts with the segment name text
        excerpt = (fact.provenance.excerpt or "").strip() if fact.provenance else ""
        name = next((n for n in all_names if excerpt.startswith(n)), None)
        if name:
            ebit_by_period_name[(fact.period, name)] = float(fact.value)

    existing = {(e.period, e.name): e for e in profile.segments.entries}
    all_keys = set(rev_by_period_name) | set(ebit_by_period_name)
    for period, name in all_keys:
        if (period, name) in existing:
            e = existing[(period, name)]
            if (period, name) in rev_by_period_name:
                e.revenue = rev_by_period_name[(period, name)]
            if (period, name) in ebit_by_period_name:
                e.ebit = ebit_by_period_name[(period, name)]
        else:
            entry = SegmentEntry(
                period=period,
                name=name,
                revenue=rev_by_period_name.get((period, name)),
                ebit=ebit_by_period_name.get((period, name)),
                evidence_id=result.evidence_id,
            )
            profile.segments.entries.append(entry)
            existing[(period, name)] = entry


# ---------------------------------------------------------------------------
# Finalise — sort all collections
# ---------------------------------------------------------------------------


def _finalize_profile(profile: CompanyProfile) -> None:
    profile.financial.snapshots.sort(key=lambda s: (s.period, s.basis))
    profile.esg.snapshots.sort(key=lambda s: s.period)
    profile.ownership.snapshots.sort(key=lambda s: s.period)
    profile.segments.entries.sort(key=lambda e: (e.period, e.name))
    profile.credit_history.entries.sort(key=lambda e: e.source_date)
    profile.capital_events.dividends.sort(key=lambda e: e.source_date)
    profile.capital_events.buybacks.sort(key=lambda e: e.source_date)
    profile.capital_events.acquisitions.sort(key=lambda e: e.source_date)
    profile.capital_events.investments.sort(key=lambda e: e.source_date)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_DISPATCH = {
    "financial_results": _ingest_financial_result,
    "earnings_transcript": _ingest_transcript_result,
    "brsr": _ingest_brsr_result,
    "shareholding_pattern": _ingest_shp_result,
    "credit_rating_report": _ingest_credit_rating_result,
    "buyback": _ingest_buyback_result,
    "acquisition": _ingest_acquisition_facts,
    "board_outcome": _ingest_board_outcome_result,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_profile(
    company_id: str,
    results: Sequence[AnalysisResult],
) -> CompanyProfile:
    """Build a CompanyProfile by assembling AnalysisResult objects.

    results may be in any order and may mix evidence kinds.  Each result is
    dispatched to the appropriate ingestion function based on result.kind.
    Financial results are processed before transcripts (sorted by kind priority)
    so that XBRL data takes precedence over spoken transcript numbers.

    Unknown kinds (annual_report, investor_presentation, agm_notice) are silently
    skipped — they do not populate structured time-series in V1.
    """
    profile = CompanyProfile(company_id=company_id)

    # Two-pass: authoritative structured data first, supplementary second
    priority = {"earnings_transcript": 2}
    ordered = sorted(
        results,
        key=lambda r: (priority.get(r.kind, 1), r.source_date),
    )

    for result in ordered:
        fn = _DISPATCH.get(result.kind)
        if fn is not None:
            fn(result, profile)

    _finalize_profile(profile)
    return profile
