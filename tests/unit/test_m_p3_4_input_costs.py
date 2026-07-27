"""M-P3.4: input-cost line items (cost of materials, purchases of
stock-in-trade, changes in inventories) -- reuses the existing generic
_PL_ROWS/_extract_pl_facts mechanism, no new extraction function.

Manufacturer-specific: absent for service companies (TCS) by business model,
same conditional-firing pattern already accepted for FINANCIAL_TCV/
FINANCIAL_UNBILLED_REVENUE (ADR-0012).

FINANCIAL_CHANGE_IN_INVENTORIES is the one FactKind in this ontology accepted
as genuinely negative -- an inventory drawdown is a real disclosed value, not
an extraction error. This mechanism has no positivity floor for ANY FactKind
that passes through it (unlike the dedicated M-P3.1/M-P3.2 balance-sheet/
cash-flow extractions, which use `_positive()`) -- see ADR-0012's M-P3.4
amendment.
"""

from __future__ import annotations

from atlas.analysis.base import FactKind
from atlas.analysis.financial_results import _extract_pl_facts
from atlas.company.builder import build_profile
from atlas.company.store import CompanyStore


def _region(text: str) -> tuple[str, int, int]:
    return text, 0, len(text)


# --- extraction: real Tata Steel wording -------------------------------------
def test_cost_of_materials_real_wording() -> None:
    text = "Revenue from operations\n34,679.54\nCost of materials consumed\n11,764.27\n10,833.48\n"
    region, start, end = _region(text)
    facts = _extract_pl_facts(region, start, end, "2025-09-30", 0, "consolidated")
    f = [x for x in facts if x.kind == FactKind.FINANCIAL_COST_OF_MATERIALS]
    assert len(f) == 1
    assert f[0].value == 11764.27


def test_cost_of_materials_ocr_typo_wording() -> None:
    # "matenals" is a real OCR typo verified in a Tata Steel filing.
    text = "Revenue from operations\n34,679.54\nCost of matenals consumed\n11,764.27\n10,833.48\n"
    region, start, end = _region(text)
    facts = _extract_pl_facts(region, start, end, "2025-09-30", 0, "consolidated")
    f = [x for x in facts if x.kind == FactKind.FINANCIAL_COST_OF_MATERIALS]
    assert len(f) == 1
    assert f[0].value == 11764.27


def test_purchases_stock_in_trade() -> None:
    text = "Revenue from operations\n34,679.54\nPurchases of stock-in-trade\n1,196.83\n988.33\n"
    region, start, end = _region(text)
    facts = _extract_pl_facts(region, start, end, "2025-09-30", 0, "consolidated")
    f = [x for x in facts if x.kind == FactKind.FINANCIAL_PURCHASES_STOCK_IN_TRADE]
    assert len(f) == 1
    assert f[0].value == 1196.83


def test_change_in_inventories_positive() -> None:
    text = "Revenue from operations\n34,679.54\nChanges in inventories of finished and semi-finished goods\n559.40\n106.61\n"
    region, start, end = _region(text)
    facts = _extract_pl_facts(region, start, end, "2025-09-30", 0, "consolidated")
    f = [x for x in facts if x.kind == FactKind.FINANCIAL_CHANGE_IN_INVENTORIES]
    assert len(f) == 1
    assert f[0].value == 559.40


def test_change_in_inventories_negative_not_floored() -> None:
    # A real disclosed drawdown -- must NOT be dropped or clamped to positive.
    text = "Revenue from operations\n34,679.54\nChanges in inventories of finished and semi-finished goods\n(851.30)\n106.61\n"
    region, start, end = _region(text)
    facts = _extract_pl_facts(region, start, end, "2025-09-30", 0, "consolidated")
    f = [x for x in facts if x.kind == FactKind.FINANCIAL_CHANGE_IN_INVENTORIES]
    assert len(f) == 1
    assert f[0].value == -851.30


def test_absent_for_service_company_pl() -> None:
    # TCS-style P&L: no input-cost lines at all -- confirmed absent, not a bug.
    text = (
        "Revenue from operations\n34,679.54\n"
        "Other income\n610.13\n"
        "Employee benefit expenses\n1,995.90\n"
    )
    region, start, end = _region(text)
    facts = _extract_pl_facts(region, start, end, "2025-09-30", 0, "consolidated")
    kinds = {f.kind for f in facts}
    assert FactKind.FINANCIAL_COST_OF_MATERIALS not in kinds
    assert FactKind.FINANCIAL_PURCHASES_STOCK_IN_TRADE not in kinds
    assert FactKind.FINANCIAL_CHANGE_IN_INVENTORIES not in kinds


# --- builder: routes via existing _FINANCIAL_SNAPSHOT_KINDS, no new code ------
def test_input_cost_facts_route_into_financial_snapshot() -> None:
    from datetime import datetime, timezone

    from atlas.analysis.base import AnalysisFact, AnalysisResult, FactUnit, Provenance

    result = AnalysisResult(
        evidence_id="bse-fr-1",
        kind="financial_results",
        analyzer_version="1.1",
        confidence="high",
        source_date=datetime(2025, 10, 1, tzinfo=timezone.utc),
        facts=[
            AnalysisFact(
                kind=FactKind.FINANCIAL_COST_OF_MATERIALS,
                value=11764.27,
                unit=FactUnit.CRORE_INR,
                period="2025-09-30",
                confidence="high",
                provenance=Provenance(section="consolidated_pl_table"),
            ),
            AnalysisFact(
                kind=FactKind.FINANCIAL_CHANGE_IN_INVENTORIES,
                value=-851.30,
                unit=FactUnit.CRORE_INR,
                period="2025-09-30",
                confidence="high",
                provenance=Provenance(section="consolidated_pl_table"),
            ),
        ],
    )
    profile = build_profile("TATASTEEL", [result])
    snap = next(s for s in profile.financial.snapshots if s.period == "2025-09-30")
    assert snap.facts[FactKind.FINANCIAL_COST_OF_MATERIALS] == 11764.27
    assert snap.facts[FactKind.FINANCIAL_CHANGE_IN_INVENTORIES] == -851.30


# --- store round-trip (negative value must survive) --------------------------
def test_change_in_inventories_negative_survives_store_round_trip(tmp_path) -> None:
    from datetime import datetime, timezone

    from atlas.analysis.base import AnalysisFact, AnalysisResult, FactUnit, Provenance

    result = AnalysisResult(
        evidence_id="bse-fr-1",
        kind="financial_results",
        analyzer_version="1.1",
        confidence="high",
        source_date=datetime(2025, 10, 1, tzinfo=timezone.utc),
        facts=[
            AnalysisFact(
                kind=FactKind.FINANCIAL_CHANGE_IN_INVENTORIES,
                value=-851.30,
                unit=FactUnit.CRORE_INR,
                period="2025-09-30",
                confidence="high",
                provenance=Provenance(section="consolidated_pl_table"),
            )
        ],
    )
    profile = build_profile("TATASTEEL", [result])
    store = CompanyStore(tmp_path / "TATASTEEL" / "profile.json", "TATASTEEL")
    store.save(profile, [result])
    loaded = store.load()
    snap = next(s for s in loaded.financial.snapshots if s.period == "2025-09-30")
    assert snap.facts[FactKind.FINANCIAL_CHANGE_IN_INVENTORIES] == -851.30


# --- metrics registration -----------------------------------------------------
def test_new_metrics_registered() -> None:
    from atlas.query.metrics import get_metric

    for key in (
        "cost_of_materials",
        "purchases_stock_in_trade",
        "change_in_inventories",
    ):
        spec = get_metric(key)
        assert spec.fact_kind is not None
