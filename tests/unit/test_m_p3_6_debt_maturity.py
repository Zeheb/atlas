"""M-P3.6: borrowings maturity schedule (6 disclosed buckets), from the AR
notes-to-accounts "Maturity profile of borrowings" table.

Positional extraction, not per-bucket label regex: the exact wording varies
across real filing years for the identical 6-bucket structure (FY2016: "In
one year or less or on demand" / FY2026: "Not later than one year or on
demand"). Extraction anchors once on the stable heading phrase and walks
forward collecting exactly 12 numeric tokens (6 buckets x 2 comparative
columns), which also naturally excludes the Total/adjustment/Net
reconciliation rows that follow.

Manufacturer-specific: absent at TCS (near-zero-debt) and SBIN (bank; a
different disclosure format), same conditional-firing pattern already
accepted for FINANCIAL_TCV/FINANCIAL_GROSS_BLOCK (ADR-0012).

Does NOT reconcile to FINANCIAL_TOTAL_DEBT -- see ADR-0012's M-P3.6
amendment for the verified real-number reconciliation (bucket sum matches
the note's own pre-adjustment gross Total; FINANCIAL_TOTAL_DEBT matches the
post-adjustment Net figure, which nets out "Capitalisation of transaction
costs").
"""
from __future__ import annotations

from atlas.analysis.annual_report import _extract_debt_maturity
from atlas.analysis.base import FactKind
from atlas.company.builder import build_profile
from atlas.company.store import CompanyStore

_REAL_TABLE_FY2026 = (
    "(viii)\tMaturity profile of borrowings including current maturities is as below:\n"
    "(I crore)\n"
    "As at \nMarch 31, 2026\nAs at \nMarch 31, 2025\n"
    "Not later than one year or on demand\n14,039.18\n8,643.10\n"
    "Later than one year but not two years\n5,394.81\n4,856.00\n"
    "Later than two years but not three years\n3,956.50\n5,929.00\n"
    "Later than three years but not four years\n9,046.25\n3,567.00\n"
    "Later than four years but not five years\n7,523.22\n9,063.25\n"
    "More than five years \n24,797.32\n27,685.25\n"
    "64,757.28\n59,743.60\n"
    "Less: Capitalisation of transaction costs \n53.10\n62.18\n"
    "64,704.18\n59,681.42\n"
    "(ix)\t Some of the Company's major financing arrangements include financial covenants"
)

_REAL_TABLE_FY2016 = (
    "The maturity profile of borrowings (including current maturities of long-term borrowings) is as follows:\n"
    "(` crore)\n"
    "As at \n31st March, 2016\n As at \n31st March, 2015\n"
    "In one year or less or on demand\n17,937.18\n15,084.01\n"
    "Between one-two years\n1,794.35\n2,983.14\n"
    "Between two-three years\n2,565.49\n 2,215.88\n"
    "Between three-four years\n12,690.65\n 2,436.15\n"
    "Between four-five years\n10,196.69\n9,135.85\n"
    "More than five years\n41,512.95\n49,249.02\n"
    "86,697.31\n81,104.05\n"
    "Less: Unearned interest on Finance lease obligation\n(493.53)\n(402.76)\n"
    "86,203.78\n80,701.29\n"
)

_ALL_BUCKET_KINDS = [
    FactKind.FINANCIAL_DEBT_MATURITY_WITHIN_1Y,
    FactKind.FINANCIAL_DEBT_MATURITY_1_TO_2Y,
    FactKind.FINANCIAL_DEBT_MATURITY_2_TO_3Y,
    FactKind.FINANCIAL_DEBT_MATURITY_3_TO_4Y,
    FactKind.FINANCIAL_DEBT_MATURITY_4_TO_5Y,
    FactKind.FINANCIAL_DEBT_MATURITY_BEYOND_5Y,
]


# --- extraction: real Tata Steel wording, two differently-worded years ------
def test_debt_maturity_fy2026_wording() -> None:
    facts = _extract_debt_maturity(_REAL_TABLE_FY2026, "2026-03-31")
    values = {f.kind: f.value for f in facts}
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_WITHIN_1Y] == 14039.18
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_1_TO_2Y] == 5394.81
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_2_TO_3Y] == 3956.50
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_3_TO_4Y] == 9046.25
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_4_TO_5Y] == 7523.22
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_BEYOND_5Y] == 24797.32


def test_debt_maturity_fy2016_different_wording() -> None:
    # Same 6-bucket structure, completely different bucket-label wording --
    # confirms extraction is positional, not label-regex-dependent.
    facts = _extract_debt_maturity(_REAL_TABLE_FY2016, "2016-03-31")
    values = {f.kind: f.value for f in facts}
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_WITHIN_1Y] == 17937.18
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_1_TO_2Y] == 1794.35
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_2_TO_3Y] == 2565.49
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_3_TO_4Y] == 12690.65
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_4_TO_5Y] == 10196.69
    assert values[FactKind.FINANCIAL_DEBT_MATURITY_BEYOND_5Y] == 41512.95


def test_debt_maturity_does_not_extract_reconciliation_rows() -> None:
    # Total, transaction-cost adjustment, and Net rows must NOT surface as
    # any of the 6 bucket FactKinds -- stopping at exactly 12 values excludes them.
    facts = _extract_debt_maturity(_REAL_TABLE_FY2026, "2026-03-31")
    values = {f.value for f in facts}
    assert 64757.28 not in values  # Total
    assert 53.10 not in values     # transaction-cost adjustment
    assert 64704.18 not in values  # Net


def test_debt_maturity_absent_when_heading_not_found() -> None:
    assert _extract_debt_maturity("no borrowings mention here", "2025-03-31") == []


def test_debt_maturity_absent_when_fewer_than_12_values() -> None:
    truncated = "Maturity profile of borrowings\nNot later than one year\n100\n90\n"
    assert _extract_debt_maturity(truncated, "2025-03-31") == []


def test_debt_maturity_drops_zero_bucket() -> None:
    text = (
        "Maturity profile of borrowings\n"
        "Not later than one year\n0\n0\n"
        "1-2 years\n100\n90\n"
        "2-3 years\n50\n40\n"
        "3-4 years\n30\n20\n"
        "4-5 years\n10\n5\n"
        "More than 5 years\n200\n150\n"
    )
    facts = _extract_debt_maturity(text, "2025-03-31")
    kinds = {f.kind for f in facts}
    assert FactKind.FINANCIAL_DEBT_MATURITY_WITHIN_1Y not in kinds
    assert FactKind.FINANCIAL_DEBT_MATURITY_1_TO_2Y in kinds


# --- confirmed absent for non-manufacturers ----------------------------------
def test_debt_maturity_absent_for_service_company_boilerplate() -> None:
    # TCS-style text: no borrowings-maturity table at all.
    text = "Revenue from operations\n34,679.54\nEmployee benefit expenses\n1,995.90\n"
    assert _extract_debt_maturity(text, "2025-03-31") == []


# --- builder: routes via existing _FINANCIAL_SNAPSHOT_KINDS, no new code ----
def test_debt_maturity_facts_route_into_financial_snapshot() -> None:
    result_facts = _extract_debt_maturity(_REAL_TABLE_FY2026, "2026-03-31")
    from datetime import datetime, timezone
    from atlas.analysis.base import AnalysisResult

    result = AnalysisResult(
        evidence_id="bse-ar-1", kind="annual_report", analyzer_version="3.4",
        confidence="high", source_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        facts=result_facts,
    )
    profile = build_profile("TATASTEEL", [result])
    snap = next(s for s in profile.financial.snapshots if s.period == "2026-03-31")
    assert snap.facts[FactKind.FINANCIAL_DEBT_MATURITY_WITHIN_1Y] == 14039.18
    assert snap.facts[FactKind.FINANCIAL_DEBT_MATURITY_BEYOND_5Y] == 24797.32


# --- store round-trip ---------------------------------------------------------
def test_debt_maturity_survives_store_round_trip(tmp_path) -> None:
    from datetime import datetime, timezone
    from atlas.analysis.base import AnalysisResult

    result_facts = _extract_debt_maturity(_REAL_TABLE_FY2026, "2026-03-31")
    result = AnalysisResult(
        evidence_id="bse-ar-1", kind="annual_report", analyzer_version="3.4",
        confidence="high", source_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        facts=result_facts,
    )
    profile = build_profile("TATASTEEL", [result])
    store = CompanyStore(tmp_path / "TATASTEEL" / "profile.json", "TATASTEEL")
    store.save(profile, [result])
    loaded = store.load()
    snap = next(s for s in loaded.financial.snapshots if s.period == "2026-03-31")
    assert snap.facts[FactKind.FINANCIAL_DEBT_MATURITY_WITHIN_1Y] == 14039.18


# --- metrics registration -------------------------------------------------------
def test_new_metrics_registered() -> None:
    from atlas.query.metrics import get_metric
    for key in (
        "debt_maturity_within_1y", "debt_maturity_1_to_2y", "debt_maturity_2_to_3y",
        "debt_maturity_3_to_4y", "debt_maturity_4_to_5y", "debt_maturity_beyond_5y",
    ):
        spec = get_metric(key)
        assert spec.fact_kind is not None


# --- reconciliation finding (documented, not enforced at runtime) -------------
def test_bucket_sum_matches_disclosed_gross_total_not_net() -> None:
    """Real-number reconciliation check (M-P3.6 requirement #6). The 6 buckets
    sum to the note's own pre-adjustment gross Total (64,757.28) -- confirming
    positional extraction is arithmetically sound -- NOT the post-adjustment
    Net figure (64,704.18) that FINANCIAL_TOTAL_DEBT reconciles to instead
    (verified separately against real financial_results extraction; see
    ADR-0012's M-P3.6 amendment). This difference (53.10, the disclosed
    "Capitalisation of transaction costs" deduction) is expected, not a bug.
    """
    facts = _extract_debt_maturity(_REAL_TABLE_FY2026, "2026-03-31")
    bucket_sum = sum(f.value for f in facts)
    assert round(bucket_sum, 2) == 64757.28
    assert round(bucket_sum, 2) != 64704.18
