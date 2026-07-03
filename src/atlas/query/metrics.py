"""Metric registry — the single source of truth mapping every numeric
FactKind (plus derived.py's on-demand computations) to a stable, queryable
key.

Why this exists
----------------
Every query before this module was a bespoke function reading specific
FactKinds by hand (see engine.py's revenue(), leverage(), ownership()).
That doesn't scale: a fact only becomes queryable once someone writes a
dedicated function for it, and an audit of the ontology found ~70 of 114
FactKinds extracted and assembled into CompanyProfile with no query access
at all — an entire sector's defining metrics (banking ratios: NIM, NPA,
CASA, CAR) and an entire domain (all 14 ESG facts) had zero surface area,
despite full extraction pipelines already populating them.

This registry is purely declarative — it does not read CompanyProfile
itself. engine.py's timeline()/compare()/screen() functions consume it to
provide generic access to *any* registered metric, so registering a metric
here is the only step needed to make it queryable, comparable across
periods, and screenable across companies.

Scope note
----------
AUDIT_OPINION, AUDIT_FIRM, EXCEPTIONAL_DESCRIPTION, and EXCEPTIONAL_AMOUNT
are extracted by financial_results.py but never routed into CompanyProfile
by builder.py at all — they're discarded before reaching any container this
registry could read. Fixing that is a builder-ingestion change, not a
query-engine one; deliberately out of scope here (see project retrospective).
GOVERNANCE_DIRECTOR is reserved (no analyzer produces it yet). Categorical/
textual FactKinds (SEGMENT_NAME, RISK_FACTOR, STRATEGY_*, CREDIT_*,
GOVERNANCE_RESOLUTION_*, CAPITAL_ACQ_TARGET_NAME, etc.) are intentionally
excluded — this registry is for *numeric* time-series metrics; the existing
topic-specific queries (risks, strategy, ratings, capital, acquisitions)
already serve textual/categorical facts well and are untouched.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from atlas.analysis.base import FactKind, FactUnit
from atlas.company import derived
from atlas.company.model import CompanyProfile, FinancialSnapshot

Domain = str  # "financial" | "esg" | "ownership"


@dataclass(frozen=True)
class MetricSpec:
    """One queryable metric.

    Exactly one of fact_kind / derive_fn is set. fact_kind metrics read
    directly from a snapshot's facts dict; derive_fn metrics are computed
    on demand from derived.py (financial domain only — the derived module
    only operates on FinancialSnapshot).

    higher_is_better: directional hint for screen()'s default sort and any
    future "flag" styling. None where the direction is context-dependent
    (e.g. promoter ownership — desirable to a control-premium thesis,
    undesirable to a free-float thesis) rather than universally good/bad.
    """

    key: str
    label: str
    domain: Domain
    unit: FactUnit | None
    fact_kind: FactKind | None = None
    derive_fn: Callable[[FinancialSnapshot], float | None] | None = None
    higher_is_better: bool | None = None


def _fk(key: str, label: str, kind: FactKind, unit: FactUnit | None, better: bool | None = None) -> MetricSpec:
    return MetricSpec(key=key, label=label, domain="financial", unit=unit, fact_kind=kind, higher_is_better=better)


def _esg(key: str, label: str, kind: FactKind, unit: FactUnit | None, better: bool | None = None) -> MetricSpec:
    return MetricSpec(key=key, label=label, domain="esg", unit=unit, fact_kind=kind, higher_is_better=better)


def _own(key: str, label: str, kind: FactKind, better: bool | None = None) -> MetricSpec:
    return MetricSpec(key=key, label=label, domain="ownership", unit=FactUnit.PERCENT, fact_kind=kind, higher_is_better=better)


def _derived(key: str, label: str, fn: Callable[[FinancialSnapshot], float | None], unit: FactUnit | None, better: bool | None = None) -> MetricSpec:
    return MetricSpec(key=key, label=label, domain="financial", unit=unit, derive_fn=fn, higher_is_better=better)


_SPECS: list[MetricSpec] = [
    # -- Financial: P&L (raw FactKinds) ----------------------------------
    _fk("revenue", "Revenue", FactKind.FINANCIAL_REVENUE, FactUnit.CRORE_INR, True),
    _fk("other_income", "Other Income", FactKind.FINANCIAL_OTHER_INCOME, FactUnit.CRORE_INR, None),
    _fk("total_income", "Total Income", FactKind.FINANCIAL_TOTAL_INCOME, FactUnit.CRORE_INR, True),
    _fk("employee_cost", "Employee Cost", FactKind.FINANCIAL_EMPLOYEE_COST, FactUnit.CRORE_INR, False),
    _fk("equipment_software_cost", "Equipment & Software Cost", FactKind.FINANCIAL_EQUIPMENT_SOFTWARE_COST, FactUnit.CRORE_INR, False),
    _fk("finance_cost", "Finance Cost", FactKind.FINANCIAL_FINANCE_COST, FactUnit.CRORE_INR, False),
    _fk("depreciation", "Depreciation", FactKind.FINANCIAL_DEPRECIATION, FactUnit.CRORE_INR, None),
    _fk("other_expenses", "Other Expenses", FactKind.FINANCIAL_OTHER_EXPENSES, FactUnit.CRORE_INR, False),
    _fk("total_expenses", "Total Expenses", FactKind.FINANCIAL_TOTAL_EXPENSES, FactUnit.CRORE_INR, False),
    _fk("profit_before_exceptional", "Profit Before Exceptional Items", FactKind.FINANCIAL_PROFIT_BEFORE_EXCEPTIONAL, FactUnit.CRORE_INR, True),
    _fk("profit_before_tax", "Profit Before Tax", FactKind.FINANCIAL_PROFIT_BEFORE_TAX, FactUnit.CRORE_INR, True),
    _fk("current_tax", "Current Tax", FactKind.FINANCIAL_CURRENT_TAX, FactUnit.CRORE_INR, None),
    _fk("deferred_tax", "Deferred Tax", FactKind.FINANCIAL_DEFERRED_TAX, FactUnit.CRORE_INR, None),
    _fk("total_tax", "Total Tax", FactKind.FINANCIAL_TOTAL_TAX, FactUnit.CRORE_INR, None),
    _fk("pat", "Profit After Tax", FactKind.FINANCIAL_PAT, FactUnit.CRORE_INR, True),
    _fk("eps_basic", "EPS (Basic)", FactKind.FINANCIAL_EPS_BASIC, FactUnit.RUPEES, True),
    _fk("eps_diluted", "EPS (Diluted)", FactKind.FINANCIAL_EPS_DILUTED, FactUnit.RUPEES, True),

    # -- Financial: transcript / investor-deck metrics --------------------
    _fk("tcv", "Total Contract Value (TCV)", FactKind.FINANCIAL_TCV, FactUnit.USD_BILLION, True),
    _fk("operating_margin", "Operating Margin", FactKind.FINANCIAL_OPERATING_MARGIN, FactUnit.PERCENT, True),
    _fk("net_margin", "Net Margin", FactKind.FINANCIAL_NET_MARGIN, FactUnit.PERCENT, True),
    _fk("roe", "Return on Equity (ROE)", FactKind.FINANCIAL_ROE, FactUnit.PERCENT, True),
    _fk("fcf", "Free Cash Flow (management-defined)", FactKind.FINANCIAL_FCF, FactUnit.CRORE_INR, True),

    # -- Financial: balance sheet / cash flow ------------------------------
    _fk("cash", "Cash & Equivalents", FactKind.FINANCIAL_CASH_AND_EQUIVALENTS, FactUnit.CRORE_INR, True),
    _fk("total_debt", "Total Debt", FactKind.FINANCIAL_TOTAL_DEBT, FactUnit.CRORE_INR, False),
    _fk("total_equity", "Total Equity", FactKind.FINANCIAL_TOTAL_EQUITY, FactUnit.CRORE_INR, True),
    _fk("operating_cash_flow", "Operating Cash Flow", FactKind.FINANCIAL_OPERATING_CASH_FLOW, FactUnit.CRORE_INR, True),
    _fk("capex", "Capital Expenditure", FactKind.FINANCIAL_CAPEX, FactUnit.CRORE_INR, None),

    # -- Financial: banking / NBFC ratios ----------------------------------
    _fk("nii", "Net Interest Income", FactKind.FINANCIAL_NET_INTEREST_INCOME, FactUnit.CRORE_INR, True),
    _fk("nim", "Net Interest Margin", FactKind.FINANCIAL_NET_INTEREST_MARGIN, FactUnit.PERCENT, True),
    _fk("gross_npa_ratio", "Gross NPA Ratio", FactKind.FINANCIAL_GROSS_NPA_RATIO, FactUnit.PERCENT, False),
    _fk("net_npa_ratio", "Net NPA Ratio", FactKind.FINANCIAL_NET_NPA_RATIO, FactUnit.PERCENT, False),
    _fk("provision_coverage_ratio", "Provision Coverage Ratio", FactKind.FINANCIAL_PROVISION_COVERAGE_RATIO, FactUnit.PERCENT, True),
    _fk("credit_cost", "Credit Cost", FactKind.FINANCIAL_CREDIT_COST, FactUnit.PERCENT, False),
    _fk("casa_ratio", "CASA Ratio", FactKind.FINANCIAL_CASA_RATIO, FactUnit.PERCENT, True),
    _fk("capital_adequacy_ratio", "Capital Adequacy Ratio (CRAR)", FactKind.FINANCIAL_CAPITAL_ADEQUACY_RATIO, FactUnit.PERCENT, True),
    _fk("slippage_ratio", "Slippage Ratio", FactKind.FINANCIAL_SLIPPAGE_RATIO, FactUnit.PERCENT, False),

    # -- Financial: physical operating volume ------------------------------
    _fk("production_volume", "Production Volume", FactKind.FINANCIAL_PRODUCTION_VOLUME, FactUnit.MILLION_TONNES, True),
    _fk("delivery_volume", "Delivery Volume", FactKind.FINANCIAL_DELIVERY_VOLUME, FactUnit.MILLION_TONNES, True),

    # -- Financial: derived (computed on demand from derived.py) ----------
    _derived("net_debt", "Net Debt (debt - cash)", derived.net_debt, FactUnit.CRORE_INR, False),
    _derived("ebit", "EBIT", derived.ebit, FactUnit.CRORE_INR, True),
    _derived("ebitda", "EBITDA", derived.ebitda, FactUnit.CRORE_INR, True),
    _derived("ebit_margin", "EBIT Margin", derived.ebit_margin_pct, FactUnit.PERCENT, True),
    _derived("ebitda_margin", "EBITDA Margin", derived.ebitda_margin_pct, FactUnit.PERCENT, True),
    _derived("pat_margin", "PAT Margin", derived.pat_margin_pct, FactUnit.PERCENT, True),
    _derived("capex_intensity", "Capex Intensity (capex / revenue)", derived.capex_intensity_pct, FactUnit.PERCENT, None),
    _derived("fcf_gaap", "Free Cash Flow (GAAP: OCF - capex)", derived.fcf_gaap, FactUnit.CRORE_INR, True),
    _derived("employee_cost_pct", "Employee Cost % of Revenue", derived.employee_cost_pct, FactUnit.PERCENT, False),

    # -- ESG ----------------------------------------------------------------
    _esg("ghg_scope1", "GHG Scope 1 Emissions", FactKind.ESG_GHG_SCOPE1, FactUnit.TCO2E, False),
    _esg("ghg_scope2", "GHG Scope 2 Emissions", FactKind.ESG_GHG_SCOPE2, FactUnit.TCO2E, False),
    _esg("ghg_scope3", "GHG Scope 3 Emissions", FactKind.ESG_GHG_SCOPE3, FactUnit.TCO2E, False),
    _esg("energy_total", "Total Energy Consumption", FactKind.ESG_ENERGY_TOTAL_MJ, FactUnit.MEGAJOULE, None),
    _esg("energy_renewable_pct", "Renewable Energy %", FactKind.ESG_ENERGY_RENEWABLE_PCT, FactUnit.PERCENT, True),
    _esg("water_consumed", "Water Consumed", FactKind.ESG_WATER_CONSUMED_KL, FactUnit.KILOLITRE, False),
    _esg("waste_generated", "Waste Generated", FactKind.ESG_WASTE_GENERATED_MT, FactUnit.METRIC_TONNE, False),
    _esg("waste_recovery_pct", "Waste Recovery %", FactKind.ESG_WASTE_RECOVERY_PCT, FactUnit.PERCENT, True),
    _esg("workforce_headcount", "Workforce Headcount", FactKind.ESG_WORKFORCE_HEADCOUNT, FactUnit.COUNT, None),
    _esg("workforce_female_pct", "Female Workforce %", FactKind.ESG_WORKFORCE_FEMALE_PCT, FactUnit.PERCENT, True),
    _esg("workforce_female_wage_pct", "Female Wage Share %", FactKind.ESG_WORKFORCE_FEMALE_WAGE_PCT, FactUnit.PERCENT, True),
    _esg("workforce_attrition_pct", "Voluntary Attrition %", FactKind.ESG_WORKFORCE_ATTRITION_PCT, FactUnit.PERCENT, False),
    _esg("safety_ltifr", "Lost Time Injury Frequency Rate", FactKind.ESG_SAFETY_LTIFR, None, False),
    _esg("sbti_scope12_target", "SBTi Scope 1+2 Reduction Target %", FactKind.ESG_CLIMATE_SBTI_SCOPE12_REDUCTION_PCT, FactUnit.PERCENT, True),
    _esg("sbti_scope3_target", "SBTi Scope 3 Reduction Target %", FactKind.ESG_CLIMATE_SBTI_SCOPE3_REDUCTION_PCT, FactUnit.PERCENT, True),
    _esg("csr_spend", "CSR Spend", FactKind.ESG_CSR_SPEND, FactUnit.CRORE_INR, None),

    # -- Ownership ------------------------------------------------------------
    MetricSpec("total_shares", "Total Shares Outstanding", "ownership", FactUnit.COUNT, FactKind.OWNERSHIP_TOTAL_SHARES, higher_is_better=None),
    _own("promoter_pct", "Promoter Holding %", FactKind.OWNERSHIP_PROMOTER_PCT, None),
    _own("promoter_pledged_pct", "Promoter Pledged %", FactKind.OWNERSHIP_PROMOTER_PLEDGED_PCT, False),
    _own("fpi_pct", "FPI Holding %", FactKind.OWNERSHIP_FPI_PCT, None),
    _own("dii_pct", "DII Holding %", FactKind.OWNERSHIP_DII_PCT, None),
    _own("mf_pct", "Mutual Fund Holding %", FactKind.OWNERSHIP_MF_PCT, None),
    _own("insurance_pct", "Insurance Holding %", FactKind.OWNERSHIP_INSURANCE_PCT, None),
    _own("public_pct", "Public Holding %", FactKind.OWNERSHIP_PUBLIC_PCT, None),
    _own("retail_pct", "Retail Holding %", FactKind.OWNERSHIP_RETAIL_PCT, None),
    _own("hni_pct", "HNI Holding %", FactKind.OWNERSHIP_HNI_PCT, None),
    _own("nri_pct", "NRI Holding %", FactKind.OWNERSHIP_NRI_PCT, None),
]

METRICS: dict[str, MetricSpec] = {spec.key: spec for spec in _SPECS}


def get_metric(key: str) -> MetricSpec:
    spec = METRICS.get(key)
    if spec is None:
        raise ValueError(f"Unknown metric {key!r}. Run 'atlas metrics' to list all {len(METRICS)} available.")
    return spec


def metrics_by_domain() -> dict[Domain, list[MetricSpec]]:
    out: dict[Domain, list[MetricSpec]] = {"financial": [], "esg": [], "ownership": []}
    for spec in METRICS.values():
        out[spec.domain].append(spec)
    for domain_specs in out.values():
        domain_specs.sort(key=lambda s: s.key)
    return out


# ---------------------------------------------------------------------------
# Reading values for a MetricSpec — shared by engine.py (single-company
# timeline/compare) and screen.py (cross-company). Lives here, not in
# engine.py, so screen.py doesn't need to import from engine.py at all —
# both are independent consumers of this registry.
# ---------------------------------------------------------------------------


def domain_snapshots(profile: CompanyProfile, domain: Domain) -> list:
    """The snapshot list a metric's domain reads from, in one place.

    financial/esg/ownership snapshots are structurally different (only
    FinancialSnapshot has basis/period_type) — callers that need to filter
    by those must check spec.domain == "financial" themselves.
    """
    if domain == "financial":
        return profile.financial.snapshots
    if domain == "esg":
        return profile.esg.snapshots
    if domain == "ownership":
        return profile.ownership.snapshots
    raise ValueError(f"Unknown metric domain {domain!r}")


def snapshot_value(spec: MetricSpec, snap: object) -> float | None:
    """The metric's value for one snapshot, or None if not present."""
    if spec.derive_fn is not None:
        return spec.derive_fn(snap)  # type: ignore[arg-type]
    value = snap.facts.get(spec.fact_kind)  # type: ignore[attr-defined]
    return float(value) if value is not None else None


def format_value(value: float, unit: FactUnit | None) -> str:
    """Render one metric value with its natural unit, for table display."""
    if unit is None:
        return f"{value:,.2f}"
    if unit == FactUnit.CRORE_INR:
        return f"{value:,.0f} cr"
    if unit == FactUnit.PERCENT:
        return f"{value:.2f}%"
    if unit == FactUnit.USD_BILLION:
        return f"${value:,.2f}B"
    if unit == FactUnit.USD_MILLION:
        return f"${value:,.1f}M"
    if unit == FactUnit.COUNT:
        return f"{value:,.0f}"
    if unit == FactUnit.RUPEES:
        return f"Rs {value:,.2f}"
    if unit == FactUnit.RUPEES_PER_SHARE:
        return f"Rs {value:,.2f}/share"
    if unit == FactUnit.TCO2E:
        return f"{value:,.0f} tCO2e"
    if unit == FactUnit.MEGAJOULE:
        return f"{value:,.0f} MJ"
    if unit == FactUnit.KILOLITRE:
        return f"{value:,.0f} KL"
    if unit == FactUnit.METRIC_TONNE:
        return f"{value:,.0f} MT"
    if unit == FactUnit.MILLION_TONNES:
        return f"{value:,.2f} Mt"
    return f"{value:,.2f}"
