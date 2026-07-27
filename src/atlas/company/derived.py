"""Derived financial metrics computed from FinancialSnapshot facts.

All functions return None when any required input fact is absent (which means
the data was not extracted, not that the value is zero).

Primary vs. Derived policy (mirroring the Analysis layer):
- These metrics are intentionally absent from AnalysisFact — they can be
  exactly computed from XBRL-sourced primary facts.
- Company-defined metrics (FCF, ROE) are primary facts in the Analysis layer
  and therefore NOT re-derived here.
"""

from __future__ import annotations

from atlas.analysis.base import FactKind
from atlas.company.model import FinancialSnapshot


def net_debt(snap: FinancialSnapshot) -> float | None:
    """Total debt minus cash and cash equivalents (CRORE_INR).

    Positive = net debtor; negative = net cash position.
    """
    debt = snap.facts.get(FactKind.FINANCIAL_TOTAL_DEBT)
    cash = snap.facts.get(FactKind.FINANCIAL_CASH_AND_EQUIVALENTS)
    if debt is None or cash is None:
        return None
    return debt - cash


def net_cash(snap: FinancialSnapshot) -> float | None:
    """Cash minus total debt (CRORE_INR).  Positive = net cash company."""
    v = net_debt(snap)
    return None if v is None else -v


def ebit(snap: FinancialSnapshot) -> float | None:
    """Earnings before interest and tax (CRORE_INR).

    Derived as PROFIT_BEFORE_EXCEPTIONAL + FINANCE_COST because the Ind AS
    P&L already deducts finance costs before the PROFIT_BEFORE_EXCEPTIONAL
    line.  Exceptional items are excluded to reflect recurring operating profit.
    """
    pbe = snap.facts.get(FactKind.FINANCIAL_PROFIT_BEFORE_EXCEPTIONAL)
    fin = snap.facts.get(FactKind.FINANCIAL_FINANCE_COST)
    if pbe is None or fin is None:
        return None
    return pbe + fin


def ebitda(snap: FinancialSnapshot) -> float | None:
    """EBIT plus depreciation and amortisation (CRORE_INR)."""
    e = ebit(snap)
    dep = snap.facts.get(FactKind.FINANCIAL_DEPRECIATION)
    if e is None or dep is None:
        return None
    return e + dep


def ebit_margin_pct(snap: FinancialSnapshot) -> float | None:
    """EBIT as a percentage of revenue."""
    e = ebit(snap)
    rev = snap.facts.get(FactKind.FINANCIAL_REVENUE)
    if e is None or not rev:
        return None
    return e / rev * 100


def ebitda_margin_pct(snap: FinancialSnapshot) -> float | None:
    """EBITDA as a percentage of revenue."""
    e = ebitda(snap)
    rev = snap.facts.get(FactKind.FINANCIAL_REVENUE)
    if e is None or not rev:
        return None
    return e / rev * 100


def pat_margin_pct(snap: FinancialSnapshot) -> float | None:
    """Profit after tax as a percentage of revenue."""
    pat = snap.facts.get(FactKind.FINANCIAL_PAT)
    rev = snap.facts.get(FactKind.FINANCIAL_REVENUE)
    if pat is None or not rev:
        return None
    return pat / rev * 100


def capex_intensity_pct(snap: FinancialSnapshot) -> float | None:
    """Capital expenditure (PP&E purchases) as a percentage of revenue."""
    capex = snap.facts.get(FactKind.FINANCIAL_CAPEX)
    rev = snap.facts.get(FactKind.FINANCIAL_REVENUE)
    if capex is None or not rev:
        return None
    return capex / rev * 100


def fcf_gaap(snap: FinancialSnapshot) -> float | None:
    """GAAP free cash flow: operating cash flow minus capex (CRORE_INR).

    Distinct from FINANCIAL_FCF (management-defined, includes acquisition
    outflows).  Use this for cross-company comparisons.
    """
    ocf = snap.facts.get(FactKind.FINANCIAL_OPERATING_CASH_FLOW)
    capex = snap.facts.get(FactKind.FINANCIAL_CAPEX)
    if ocf is None or capex is None:
        return None
    return ocf - capex


def employee_cost_pct(snap: FinancialSnapshot) -> float | None:
    """Employee benefit expenses as a percentage of revenue."""
    emp = snap.facts.get(FactKind.FINANCIAL_EMPLOYEE_COST)
    rev = snap.facts.get(FactKind.FINANCIAL_REVENUE)
    if emp is None or not rev:
        return None
    return emp / rev * 100


def cost_of_debt(
    snap: FinancialSnapshot, prior_debt: float | None = None
) -> float | None:
    """Finance cost as a percentage of debt — the effective borrowing rate.

    Average-debt convention: when the prior period's total debt is supplied
    (``prior_debt``), the denominator is the average of opening and closing
    debt, which is the correct base for a period *flow* (finance cost) divided
    by a period-end *stock* (debt). With no prior period available — the common
    case in this stateless single-snapshot module, and how the query registry
    calls it — the denominator falls back to period-end debt.

    Returns None when finance cost or debt is absent, or when the debt base is
    zero (an effectively debt-free company has no meaningful cost of debt, and
    the ratio would divide by zero).

    Most meaningful on annual snapshots, where finance cost is a full-year flow.
    """
    fin = snap.facts.get(FactKind.FINANCIAL_FINANCE_COST)
    debt = snap.facts.get(FactKind.FINANCIAL_TOTAL_DEBT)
    if fin is None or debt is None:
        return None
    base = (debt + prior_debt) / 2 if prior_debt is not None else debt
    if not base:
        return None
    return fin / base * 100


def interest_coverage(snap: FinancialSnapshot) -> float | None:
    """EBIT divided by finance cost — how many times operating profit covers
    interest (a ratio in 'times', not a percentage).

    Higher is safer. Returns None when EBIT is not derivable or finance cost is
    absent or zero (a company with no interest expense has no finite coverage
    ratio, which None reports honestly rather than as a fabricated infinity).
    """
    e = ebit(snap)
    fin = snap.facts.get(FactKind.FINANCIAL_FINANCE_COST)
    if e is None or not fin:
        return None
    return e / fin
