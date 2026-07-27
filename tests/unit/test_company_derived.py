"""Derived financial metrics (company/derived.py).

Focused unit tests for cost_of_debt and interest_coverage (M-P0.1). The other
derived functions are exercised via test_query_metrics.py and the company
builder/integration suites; these two are new and get direct coverage of their
convention and None-guard behavior.
"""

from __future__ import annotations

from atlas.analysis.base import FactKind
from atlas.company import derived
from atlas.company.model import FinancialSnapshot


def _snap(**facts: float) -> FinancialSnapshot:
    kmap = {
        "finance_cost": FactKind.FINANCIAL_FINANCE_COST,
        "debt": FactKind.FINANCIAL_TOTAL_DEBT,
        "pbe": FactKind.FINANCIAL_PROFIT_BEFORE_EXCEPTIONAL,
    }
    return FinancialSnapshot(
        period="2026-03-31",
        period_type="annual",
        basis="consolidated",
        facts={kmap[k]: v for k, v in facts.items()},
        sources=[],
    )


# --- cost_of_debt -------------------------------------------------------------
def test_cost_of_debt_point_in_time() -> None:
    # finance_cost 80 / debt 1000 = 8.0%
    assert derived.cost_of_debt(_snap(finance_cost=80.0, debt=1000.0)) == 8.0


def test_cost_of_debt_average_debt_convention() -> None:
    # avg of prior 600 and current 1000 = 800; 80 / 800 = 10.0%
    got = derived.cost_of_debt(_snap(finance_cost=80.0, debt=1000.0), prior_debt=600.0)
    assert got == 10.0


def test_cost_of_debt_none_when_debt_zero() -> None:
    assert derived.cost_of_debt(_snap(finance_cost=80.0, debt=0.0)) is None


def test_cost_of_debt_none_when_input_absent() -> None:
    assert derived.cost_of_debt(_snap(finance_cost=80.0)) is None
    assert derived.cost_of_debt(_snap(debt=1000.0)) is None


# --- interest_coverage --------------------------------------------------------
def test_interest_coverage_ratio() -> None:
    # ebit = pbe + finance_cost = 920 + 80 = 1000; coverage = 1000 / 80 = 12.5x
    assert derived.interest_coverage(_snap(pbe=920.0, finance_cost=80.0)) == 12.5


def test_interest_coverage_none_when_finance_cost_zero() -> None:
    assert derived.interest_coverage(_snap(pbe=920.0, finance_cost=0.0)) is None


def test_interest_coverage_none_when_ebit_not_derivable() -> None:
    # ebit needs both pbe and finance_cost; missing pbe -> None
    assert derived.interest_coverage(_snap(finance_cost=80.0)) is None
