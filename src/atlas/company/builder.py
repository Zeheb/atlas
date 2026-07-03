"""Company profile builder.

Assembles a collection of AnalysisResult objects (from multiple evidence
documents) into a CompanyProfile for a single company.

Dispatch table
--------------
financial_results      → FinancialTimeSeries + DividendEvents + SegmentTimeSeries
earnings_transcript    → supplements FinancialTimeSeries (TCV, margins)
investor_presentation  → supplements FinancialTimeSeries (ROE, FCF) + StrategyProfile
brsr                   → ESGTimeSeries
shareholding_pattern   → OwnershipTimeSeries
buyback                → CapitalEventLedger.buybacks
acquisition            → CapitalEventLedger.acquisitions
board_outcome          → CapitalEventLedger (dividends | acquisitions | investments)
credit_rating_report   → CreditHistory (debt_ratings or esg_ratings)
agm_notice             → GovernanceProfile.resolutions

annual_report          → ESGTimeSeries (CSR spend) + GovernanceProfile.audit_kams

Processing order
----------------
financial_results results are processed with regular dict.update() so that a
revised filing correctly overwrites an earlier one for the same period.

earnings_transcript and investor_presentation results use setdefault() so that
authoritative XBRL data from financial_results is never overwritten by spoken
or presentation numbers.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from atlas.analysis.base import AnalysisFact, AnalysisResult, FactKind, FactUnit
from atlas.company.model import (
    AGMResolution,
    AcquisitionEvent,
    BuybackEvent,
    CSATEntry,
    CapitalEventLedger,
    CompanyProfile,
    CreditHistory,
    CreditRatingEntry,
    DirectorChange,
    DividendEvent,
    ESGSnapshot,
    ESGTimeSeries,
    FinancialSnapshot,
    FinancialTimeSeries,
    FundraisingEvent,
    GovernanceProfile,
    InvestmentEvent,
    OwnershipSnapshot,
    OwnershipTimeSeries,
    RiskEntry,
    SegmentEntry,
    SegmentTimeSeries,
    StrategyEntry,
    StrategyProfile,
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

# Bump when builder logic changes in a way that would produce different output
# from the same AnalysisResult inputs.  CompanyStore records this to detect
# profiles built with an older algorithm.
BUILDER_VERSION = "1.0"

_STRATEGY_KIND_TO_KEY: dict[FactKind, str] = {
    FactKind.STRATEGY_PRIORITY: "priority",
    FactKind.STRATEGY_ASPIRATION: "aspiration",
    FactKind.STRATEGY_GUIDANCE: "guidance",
}


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


def _ingest_investor_presentation_result(
    result: AnalysisResult, profile: CompanyProfile
) -> None:
    # 1. Textual strategy facts → StrategyProfile.entries
    for fact in result.facts:
        key = _STRATEGY_KIND_TO_KEY.get(fact.kind)
        if key and isinstance(fact.value, str) and fact.value:
            profile.strategy.entries.append(StrategyEntry(
                source_date=result.source_date,
                kind=key,
                text=fact.value,
                evidence_id=result.evidence_id,
            ))
        elif (
            fact.kind == FactKind.STRATEGY_CSAT
            and isinstance(fact.value, (int, float))
            and fact.period
        ):
            profile.strategy.csat.append(CSATEntry(
                period=fact.period,
                score=float(fact.value),
                evidence_id=result.evidence_id,
            ))

    # 2. Numeric financial facts (ROE, FCF) → FinancialTimeSeries (supplement only)
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
            for fk, fv in facts.items():
                existing[key].facts.setdefault(fk, fv)
            if result.evidence_id not in existing[key].sources:
                existing[key].sources.append(result.evidence_id)
        else:
            snap = FinancialSnapshot(
                period=period,
                period_type="annual",   # ROE and FCF are annual management metrics
                basis="consolidated",
                facts=facts,
                sources=[result.evidence_id],
            )
            profile.financial.snapshots.append(snap)
            existing[key] = snap


_ANNUAL_REPORT_AUTHORITATIVE_ESG: frozenset[FactKind] = frozenset({
    FactKind.ESG_CSR_SPEND,
})


def _ingest_annual_report_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    """Ingest an annual_report AnalysisResult into the CompanyProfile.

    ESG_CSR_SPEND is authoritative (update) — the mandatory s.135 disclosure
    is the canonical source.  Workforce ESG facts (attrition) are supplementary
    (setdefault) because BRSR data is more detailed and verified.
    AUDIT_KAM_TITLE facts go to GovernanceProfile.audit_kams (deduped).
    """
    auth_snaps: dict[str, dict[FactKind, float]] = defaultdict(dict)
    supp_snaps: dict[str, dict[FactKind, float]] = defaultdict(dict)

    for fact in result.facts:
        if fact.kind not in _ESG_KINDS:
            continue
        if fact.period is None or not isinstance(fact.value, (int, float)):
            continue
        if fact.kind in _ANNUAL_REPORT_AUTHORITATIVE_ESG:
            auth_snaps[fact.period][fact.kind] = float(fact.value)
        else:
            supp_snaps[fact.period][fact.kind] = float(fact.value)

    existing = {s.period: s for s in profile.esg.snapshots}

    for period, facts in auth_snaps.items():
        if period in existing:
            existing[period].facts.update(facts)
            if result.evidence_id not in existing[period].sources:
                existing[period].sources.append(result.evidence_id)
        else:
            snap = ESGSnapshot(period=period, facts=facts, sources=[result.evidence_id])
            profile.esg.snapshots.append(snap)
            existing[period] = snap

    for period, facts in supp_snaps.items():
        if period in existing:
            for fk, fv in facts.items():
                existing[period].facts.setdefault(fk, fv)
            if result.evidence_id not in existing[period].sources:
                existing[period].sources.append(result.evidence_id)
        else:
            snap = ESGSnapshot(period=period, facts=facts, sources=[result.evidence_id])
            profile.esg.snapshots.append(snap)
            existing[period] = snap

    for fact in result.facts:
        if fact.kind == FactKind.AUDIT_KAM_TITLE and isinstance(fact.value, str):
            title = fact.value
            if title not in profile.governance.audit_kams:
                profile.governance.audit_kams.append(title)

    for fact in result.facts:
        if fact.kind == FactKind.RISK_FACTOR and isinstance(fact.value, str) and fact.period:
            profile.governance.risk_factors.append(RiskEntry(
                period=fact.period,
                text=fact.value,
                evidence_id=result.evidence_id,
            ))


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
            if result.evidence_id not in existing[period].sources:
                existing[period].sources.append(result.evidence_id)
        else:
            snap = OwnershipSnapshot(
                period=period,
                facts=facts,
                sources=[result.evidence_id],
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

        entry = CreditRatingEntry(
            source_date=result.source_date,
            agency=agency,
            instrument=inst_name,
            rating=rating,
            outlook=outlook,
            action=action,
            amount=amount,
            evidence_id=result.evidence_id,
        )
        if is_esg:
            profile.credit_history.esg_ratings.append(entry)
        else:
            profile.credit_history.debt_ratings.append(entry)


def _ingest_agm_notice_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    # Group resolution facts by provenance.section ("resolution_N")
    by_section: dict[str, dict[FactKind, AnalysisFact]] = defaultdict(dict)
    for fact in result.facts:
        sec = fact.provenance.section if fact.provenance else ""
        if sec.startswith("resolution_"):
            by_section[sec].setdefault(fact.kind, fact)

    for _sec, facts in sorted(by_section.items()):
        title_fact = facts.get(FactKind.GOVERNANCE_RESOLUTION_TITLE)
        if title_fact is None:
            continue

        res_type_fact = facts.get(FactKind.GOVERNANCE_RESOLUTION_TYPE)
        outcome_fact = facts.get(FactKind.GOVERNANCE_RESOLUTION_OUTCOME)
        pct_for_fact = facts.get(FactKind.GOVERNANCE_VOTE_PCT_FOR)
        pct_against_fact = facts.get(FactKind.GOVERNANCE_VOTE_PCT_AGAINST)

        profile.governance.resolutions.append(AGMResolution(
            source_date=result.source_date,
            period=title_fact.period,
            title=str(title_fact.value),
            resolution_type=str(res_type_fact.value) if res_type_fact else "",
            outcome=str(outcome_fact.value) if outcome_fact else None,
            pct_for=(
                float(pct_for_fact.value)
                if pct_for_fact and isinstance(pct_for_fact.value, (int, float))
                else None
            ),
            pct_against=(
                float(pct_against_fact.value)
                if pct_against_fact and isinstance(pct_against_fact.value, (int, float))
                else None
            ),
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


def _ingest_board_outcome_buyback(result: AnalysisResult, profile: CompanyProfile) -> None:
    """Create a BuybackEvent(sub_type='announcement') from board_outcome buyback facts."""
    first: dict[FactKind, AnalysisFact] = {}
    for fact in result.facts:
        if fact.kind in (FactKind.CAPITAL_BUYBACK_AMOUNT, FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE):
            first.setdefault(fact.kind, fact)
    amount_fact = first.get(FactKind.CAPITAL_BUYBACK_AMOUNT)
    price_fact = first.get(FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE)
    profile.capital_events.buybacks.append(BuybackEvent(
        source_date=result.source_date,
        sub_type="announcement",
        amount=float(amount_fact.value) if amount_fact and isinstance(amount_fact.value, (int, float)) else None,
        price_per_share=float(price_fact.value) if price_fact and isinstance(price_fact.value, (int, float)) else None,
        evidence_id=result.evidence_id,
    ))


def _ingest_fundraise_facts(result: AnalysisResult, profile: CompanyProfile) -> None:
    """Create one FundraisingEvent per fundraise type detected in the result."""
    # Amount is shared across all detected types (a board typically approves one ceiling)
    amount_fact = next(
        (f for f in result.facts if f.kind == FactKind.CAPITAL_FUNDRAISE_AMOUNT),
        None,
    )
    amount = (
        float(amount_fact.value)
        if amount_fact and isinstance(amount_fact.value, (int, float))
        else None
    )
    seen_types: set[str] = set()
    for fact in result.facts:
        if fact.kind == FactKind.CAPITAL_FUNDRAISE_TYPE:
            ftype = str(fact.value)
            if ftype in seen_types:
                continue
            seen_types.add(ftype)
            profile.capital_events.fundraises.append(FundraisingEvent(
                source_date=result.source_date,
                fundraise_type=ftype,
                amount=amount,
                evidence_id=result.evidence_id,
            ))


def _ingest_director_changes(result: AnalysisResult, profile: CompanyProfile) -> None:
    """Assemble DirectorChange objects from director_change_N section-grouped facts."""
    by_section: dict[str, dict[FactKind, AnalysisFact]] = defaultdict(dict)
    for fact in result.facts:
        sec = fact.provenance.section if fact.provenance else ""
        if sec.startswith("director_change_"):
            by_section[sec].setdefault(fact.kind, fact)

    for _sec, facts in sorted(by_section.items()):
        name_fact = facts.get(FactKind.GOVERNANCE_DIRECTOR)
        type_fact = facts.get(FactKind.GOVERNANCE_DIRECTOR_CHANGE_TYPE)
        if name_fact is None or type_fact is None:
            continue
        role_fact = facts.get(FactKind.GOVERNANCE_DIRECTOR_CHANGE_ROLE)
        profile.governance.director_changes.append(DirectorChange(
            source_date=result.source_date,
            change_type=str(type_fact.value),
            name=str(name_fact.value),
            role=str(role_fact.value) if role_fact else None,
            evidence_id=result.evidence_id,
        ))


def _ingest_board_outcome_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    kinds = {f.kind for f in result.facts}

    if FactKind.CAPITAL_DIVIDEND_PER_SHARE in kinds:
        _ingest_dividend_facts(result, profile)

    if FactKind.CAPITAL_BUYBACK_AMOUNT in kinds:
        _ingest_board_outcome_buyback(result, profile)

    if FactKind.CAPITAL_FUNDRAISE_TYPE in kinds:
        _ingest_fundraise_facts(result, profile)

    if FactKind.GOVERNANCE_DIRECTOR in kinds:
        _ingest_director_changes(result, profile)

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
    profile.credit_history.debt_ratings.sort(key=lambda e: e.source_date)
    profile.credit_history.esg_ratings.sort(key=lambda e: e.source_date)
    profile.capital_events.dividends.sort(key=lambda e: e.source_date)
    profile.capital_events.buybacks.sort(key=lambda e: e.source_date)
    profile.capital_events.acquisitions.sort(key=lambda e: e.source_date)
    profile.capital_events.investments.sort(key=lambda e: e.source_date)
    profile.capital_events.fundraises.sort(key=lambda e: e.source_date)
    profile.strategy.entries.sort(key=lambda e: e.source_date)
    profile.strategy.csat.sort(key=lambda e: e.period)
    profile.governance.resolutions.sort(key=lambda r: (r.period or "", r.title))
    profile.governance.director_changes.sort(key=lambda d: d.source_date)
    profile.governance.risk_factors.sort(key=lambda r: r.period)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_DISPATCH = {
    "financial_results":      _ingest_financial_result,
    "earnings_transcript":    _ingest_transcript_result,
    "investor_presentation":  _ingest_investor_presentation_result,
    "brsr":                   _ingest_brsr_result,
    "shareholding_pattern":   _ingest_shp_result,
    "credit_rating_report":   _ingest_credit_rating_result,
    "buyback":                _ingest_buyback_result,
    "acquisition":            _ingest_acquisition_facts,
    "board_outcome":          _ingest_board_outcome_result,
    "agm_notice":             _ingest_agm_notice_result,
    "annual_report":          _ingest_annual_report_result,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def merge_result(result: AnalysisResult, profile: CompanyProfile) -> None:
    """Apply one AnalysisResult to an existing CompanyProfile in place.

    This is the incremental primitive used by CompanyStore.  Callers do not
    need to worry about processing order — the same update semantics apply
    as in build_profile():

    - financial_results:       dict.update() — overwrites existing facts
    - earnings_transcript:     setdefault()  — supplements without overwriting
    - investor_presentation:   setdefault()  — supplements without overwriting

    Unknown kinds are silently skipped.
    All collections are re-sorted after ingestion.
    """
    fn = _DISPATCH.get(result.kind)
    if fn is not None:
        fn(result, profile)
    _finalize_profile(profile)


def build_profile(
    company_id: str,
    results: Sequence[AnalysisResult],
) -> CompanyProfile:
    """Build a CompanyProfile by assembling AnalysisResult objects.

    results may be in any order and may mix evidence kinds.  Each result is
    dispatched to the appropriate ingestion function based on result.kind.

    Processing order:
    - financial_results and authoritative structured data are processed first
      (priority=1) so that XBRL data takes precedence.
    - earnings_transcript and investor_presentation (priority=2) supplement
      only — they never overwrite facts already present from XBRL sources.

    Unknown kinds are silently skipped.
    """
    profile = CompanyProfile(company_id=company_id)

    # Two-pass: authoritative structured data first, supplementary second
    priority = {"earnings_transcript": 2, "investor_presentation": 2}
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
