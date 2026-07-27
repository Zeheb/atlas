"""M-P3.2: cash-tax-paid, intangible assets, gross block, auditor history.

Notes to accounts is the source SECTION these facts are drawn from, not an
independent target (verified against the frozen roadmap before implementing).
Contingent liabilities is evidence-deferred (narrative prose in the corpus,
no clean aggregate found even with a targeted search) -- explicitly not
attempted here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.analysis.annual_report import _extract_gross_block
from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.analysis.financial_results import (
    _extract_balance_sheet_facts,
    _extract_cashflow_facts,
)
from atlas.company.builder import build_profile
from atlas.company.model import CompanyProfile
from atlas.company.store import CompanyStore


# --- cash-tax-paid extraction ---------------------------------------------------
def test_cash_tax_paid_tcs_phrasing() -> None:
    text = "CASH FLOWS FROM OPERATING\nTaxes paid (net of refunds)\n(8,712)\n(5,793)\n"
    facts = _extract_cashflow_facts(text, "2026-03-31")
    tax = [f for f in facts if f.kind == FactKind.FINANCIAL_CASH_TAX_PAID]
    assert len(tax) == 1
    assert tax[0].value == 8712.0  # absolute value of the outflow


def test_cash_tax_paid_tata_steel_phrasing() -> None:
    text = "CASH FLOWS FROM OPERATING\nIncome taxes paid\n(1,818.78)\n(2,000.00)\n"
    facts = _extract_cashflow_facts(text, "2020-03-31")
    tax = [f for f in facts if f.kind == FactKind.FINANCIAL_CASH_TAX_PAID]
    assert len(tax) == 1
    assert tax[0].value == 1818.78


def test_cash_tax_paid_absent_when_no_cf_region() -> None:
    assert _extract_cashflow_facts("no cash flow statement here", "2026-03-31") == []


# --- intangible assets extraction (direct layout only) --------------------------
def test_intangible_assets_direct_layout() -> None:
    text = (
        "\nASSETS\nNon-current assets\nOther intangible assets\n413\n510\n"
        "Financial assets\nInvestments\n289\n281\n"
        "Cash and cash equivalents\n1000\n900\n"
    )
    facts = _extract_balance_sheet_facts(text, "2026-03-31")
    intang = [f for f in facts if f.kind == FactKind.FINANCIAL_INTANGIBLE_ASSETS]
    assert len(intang) == 1
    assert intang[0].value == 413.0


def test_intangible_assets_excludes_under_development() -> None:
    text = "\nASSETS\nIntangible assets under development\n50\n40\nCash and cash equivalents\n1000\n900\n"
    facts = _extract_balance_sheet_facts(text, "2026-03-31")
    assert [f for f in facts if f.kind == FactKind.FINANCIAL_INTANGIBLE_ASSETS] == []


def test_intangible_assets_absent_in_deferred_layout_documented_limitation() -> None:
    # Deferred layout: labels all appear together, values elsewhere -- no
    # verified positional anchor for the non-current-assets block, so this
    # must stay absent (under-emit), not guessed.
    text = (
        "\nASSETS\nNon-current assets\nGoodwill\nIntangible assets\n"
        "Current assets\n(a) Inventories\n(b) Financial assets\n(i) Investments\n"
        "(ii) Trade receivables\n(iii) Cash and cash equivalents\n"
        "(iv) Other balances with banks\n(v) Loans\n"  # more labels before any number -> genuinely deferred
        "100\n50\n30\n20\n10\n1\n"
    )
    facts = _extract_balance_sheet_facts(text, "2026-03-31")
    assert [f for f in facts if f.kind == FactKind.FINANCIAL_INTANGIBLE_ASSETS] == []


# --- gross block extraction (TCS highlights-table format only) ------------------
def test_gross_block_highlights_table() -> None:
    text = "Gross block of property, \nplant and equipment\n37,277\n33,853\n30,300\n"
    fact = _extract_gross_block(text, "2025-03-31")
    assert fact is not None
    assert fact.kind == FactKind.FINANCIAL_GROSS_BLOCK
    assert fact.value == 37277.0  # most-recent (first) column only


def test_gross_block_absent_when_label_not_found() -> None:
    assert _extract_gross_block("no gross block mention here", "2025-03-31") is None


def test_gross_block_absent_for_movement_schedule_format() -> None:
    # Tata Steel's PP&E movement-schedule wording ("Gross block as at DATE")
    # deliberately does NOT match -- see the module comment: tested directly
    # and found to produce a wrong Total when guessed positionally.
    text = "Gross block as at 01.04.2015\n441.17\n726.20\n41,614.38\n"
    assert _extract_gross_block(text, "2016-03-31") is None


def test_gross_block_rejects_zero_or_negative() -> None:
    text = "Gross block of property, \nplant and equipment\n0\n"
    assert _extract_gross_block(text, "2025-03-31") is None


# --- auditor history: builder wiring (AUDIT_FIRM/AUDIT_OPINION already extracted) --
def _result_with_audit(
    firm: str | None, opinion: str | None, evidence_id: str = "bse-fr-1"
) -> AnalysisResult:
    facts: list[AnalysisFact] = []
    if firm is not None:
        facts.append(
            AnalysisFact(
                kind=FactKind.AUDIT_FIRM,
                value=firm,
                unit=None,
                period=None,
                confidence="high",
                provenance=None,
            )
        )
    if opinion is not None:
        facts.append(
            AnalysisFact(
                kind=FactKind.AUDIT_OPINION,
                value=opinion,
                unit=None,
                period=None,
                confidence="high",
                provenance=None,
            )
        )
    return AnalysisResult(
        evidence_id=evidence_id,
        kind="financial_results",
        analyzer_version="1.2",
        confidence="high",
        source_date=datetime(2026, 4, 9, tzinfo=timezone.utc),
        facts=facts,
    )


def test_auditor_history_ingested_from_existing_facts() -> None:
    profile = build_profile(
        "TCS", [_result_with_audit("B S R & Co. LLP", "unmodified")]
    )
    assert len(profile.governance.auditor_history) == 1
    entry = profile.governance.auditor_history[0]
    assert entry.firm == "B S R & Co. LLP"
    assert entry.opinion == "unmodified"
    assert entry.source_date.year == 2026


def test_auditor_history_uses_result_source_date_not_fact_period() -> None:
    # AUDIT_FIRM/AUDIT_OPINION carry period=None -- source_date must come
    # from the AnalysisResult, not the fact.
    profile = build_profile("TCS", [_result_with_audit("Deloitte LLP", None)])
    assert (
        profile.governance.auditor_history[0]
        .source_date.isoformat()
        .startswith("2026-04-09")
    )


def test_auditor_history_skipped_when_neither_fact_present() -> None:
    profile = build_profile("TCS", [_result_with_audit(None, None)])
    assert profile.governance.auditor_history == []


def test_auditor_history_multiple_filings_multiple_entries() -> None:
    r1 = _result_with_audit("B S R & Co. LLP", "unmodified", "bse-fr-1")
    r2 = _result_with_audit("B S R & Co. LLP", "unmodified", "bse-fr-2")
    profile = build_profile("TCS", [r1, r2])
    assert len(profile.governance.auditor_history) == 2


# --- store round-trip -------------------------------------------------------------
def test_auditor_history_survives_store_round_trip(tmp_path) -> None:
    profile = build_profile(
        "TCS", [_result_with_audit("B S R & Co. LLP", "unmodified")]
    )
    store = CompanyStore(tmp_path / "TCS" / "profile.json", "TCS")
    store.save(profile, [_result_with_audit("B S R & Co. LLP", "unmodified")])
    loaded = store.load()
    assert len(loaded.governance.auditor_history) == 1
    assert loaded.governance.auditor_history[0].firm == "B S R & Co. LLP"


def test_empty_auditor_history_round_trips(tmp_path) -> None:
    store = CompanyStore(tmp_path / "TCS" / "profile.json", "TCS")
    store.save(CompanyProfile(company_id="TCS"), [])
    assert store.load().governance.auditor_history == []


def test_gross_block_survives_store_round_trip(tmp_path) -> None:
    result = AnalysisResult(
        evidence_id="bse-ar-1",
        kind="annual_report",
        analyzer_version="3.2",
        confidence="high",
        source_date=datetime(2025, 6, 1, tzinfo=timezone.utc),
        facts=[
            AnalysisFact(
                kind=FactKind.FINANCIAL_GROSS_BLOCK,
                value=37277.0,
                unit=FactUnit.CRORE_INR,
                period="2025-03-31",
                confidence="high",
                provenance=Provenance(section="financial_highlights"),
            )
        ],
    )
    profile = build_profile("TCS", [result])
    store = CompanyStore(tmp_path / "TCS" / "profile.json", "TCS")
    store.save(profile, [result])
    loaded = store.load()
    snap = next(s for s in loaded.financial.snapshots if s.period == "2025-03-31")
    assert snap.facts[FactKind.FINANCIAL_GROSS_BLOCK] == 37277.0


# --- query registration ------------------------------------------------------------
def test_auditor_history_query_registered_and_dispatchable() -> None:
    from atlas.query.engine import available_queries, run_query

    assert "auditor_history" in available_queries()
    profile = build_profile(
        "TCS", [_result_with_audit("B S R & Co. LLP", "unmodified")]
    )
    result = run_query("auditor_history", profile)
    assert result.query == "auditor_history"
    assert result.sections[0].rows[0][1] == "B S R & Co. LLP"


def test_auditor_history_query_empty_result_honest() -> None:
    from atlas.query.engine import auditor_history

    result = auditor_history(CompanyProfile(company_id="TCS"))
    assert result.sections[0].rows == []
    assert any("no auditor" in n.lower() for n in result.notes)


def test_new_metrics_registered() -> None:
    from atlas.query.metrics import get_metric

    for key in ("cash_tax_paid", "intangible_assets", "gross_block"):
        spec = get_metric(key)
        assert spec.fact_kind is not None
