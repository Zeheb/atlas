"""M-P3.3: related-party balance extraction + AGM RPT-resolution tagging.

Only the aggregate BALANCE format (Tata Steel's "Loans to related parties"
notes-to-accounts line) is extracted. TCS's per-counterparty transaction
table is deliberately NOT attempted -- tested directly against the real
wider table text and found to have an open-ended category vocabulary, a
variable value-count per row, and the same counterparty recurring under
different categories in the same period, a genuine collision risk with no
verified category-boundary mechanism. See ADR-0012's M-P3.3 amendment.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.analysis.annual_report import _extract_rpt_balance, _parse_rpt_amount
from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.company.builder import build_profile
from atlas.company.model import AGMResolution, CompanyProfile, GovernanceProfile
from atlas.company.store import CompanyStore


# --- _extract_rpt_balance -------------------------------------------------------
def test_rpt_balance_extracts_real_value() -> None:
    text = "Loans to related parties\nConsidered good - Unsecured\n8,601.65\n4,816.15\n"
    facts = _extract_rpt_balance(text, "2024-03-31")
    amounts = [f for f in facts if f.kind == FactKind.GOVERNANCE_RPT_BALANCE_AMOUNT]
    categories = [f for f in facts if f.kind == FactKind.GOVERNANCE_RPT_CATEGORY]
    assert len(amounts) == 1
    assert amounts[0].value == 8601.65
    assert amounts[0].period == "2024-03-31"
    assert len(categories) == 1
    assert categories[0].value == "Loans to related parties"


def test_rpt_balance_handles_disclosed_nil() -> None:
    # "-" is a disclosed nil, not a missing value -- 0.0 is correct here.
    text = "Loans to related parties\n-\n52.01\n"
    facts = _extract_rpt_balance(text, "2026-03-31")
    amount = next(f for f in facts if f.kind == FactKind.GOVERNANCE_RPT_BALANCE_AMOUNT)
    assert amount.value == 0.0


def test_rpt_balance_absent_when_label_not_found() -> None:
    assert _extract_rpt_balance("no related party mention here", "2025-03-31") == []


def test_rpt_balance_row_identity_uses_rpt_row_section() -> None:
    text = "Loans to related parties\n100\n90\n"
    facts = _extract_rpt_balance(text, "2025-03-31")
    assert all(
        f.provenance is not None and f.provenance.section == "rpt_row_0" for f in facts
    )


def test_parse_rpt_amount() -> None:
    assert _parse_rpt_amount("-") == 0.0
    assert _parse_rpt_amount("4,816.15") == 4816.15


# --- builder: rpt_row_N reconstruction -------------------------------------------
def _result_with_rpt(
    amount: float, category: str, period: str, evidence_id: str = "bse-ar-1"
) -> AnalysisResult:
    prov = Provenance(section="rpt_row_0")
    facts = [
        AnalysisFact(
            kind=FactKind.GOVERNANCE_RPT_BALANCE_AMOUNT,
            value=amount,
            unit=FactUnit.CRORE_INR,
            period=period,
            confidence="high",
            provenance=prov,
        ),
        AnalysisFact(
            kind=FactKind.GOVERNANCE_RPT_CATEGORY,
            value=category,
            unit=None,
            period=period,
            confidence="high",
            provenance=prov,
        ),
    ]
    return AnalysisResult(
        evidence_id=evidence_id,
        kind="annual_report",
        analyzer_version="3.3",
        confidence="high",
        source_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        facts=facts,
    )


def test_related_party_entry_reconstructed_by_builder() -> None:
    result = _result_with_rpt(8601.65, "Loans to related parties", "2024-03-31")
    profile = build_profile("TATASTEEL", [result])
    assert len(profile.governance.related_parties) == 1
    entry = profile.governance.related_parties[0]
    assert entry.period == "2024-03-31"
    assert entry.kind == "balance"
    assert entry.category == "Loans to related parties"
    assert entry.amount == 8601.65
    assert entry.counterparty is None


def test_related_party_entry_skipped_without_period() -> None:
    prov = Provenance(section="rpt_row_0")
    result = AnalysisResult(
        evidence_id="bse-ar-1",
        kind="annual_report",
        analyzer_version="3.3",
        confidence="high",
        source_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        facts=[
            AnalysisFact(
                kind=FactKind.GOVERNANCE_RPT_BALANCE_AMOUNT,
                value=100.0,
                unit=FactUnit.CRORE_INR,
                period=None,
                confidence="high",
                provenance=prov,
            )
        ],
    )
    profile = build_profile("TATASTEEL", [result])
    assert profile.governance.related_parties == []


def test_multiple_rpt_rows_multiple_entries() -> None:
    prov0 = Provenance(section="rpt_row_0")
    prov1 = Provenance(section="rpt_row_1")
    facts = [
        AnalysisFact(
            kind=FactKind.GOVERNANCE_RPT_BALANCE_AMOUNT,
            value=100.0,
            unit=FactUnit.CRORE_INR,
            period="2024-03-31",
            confidence="high",
            provenance=prov0,
        ),
        AnalysisFact(
            kind=FactKind.GOVERNANCE_RPT_CATEGORY,
            value="Loans to related parties",
            unit=None,
            period="2024-03-31",
            confidence="high",
            provenance=prov0,
        ),
        AnalysisFact(
            kind=FactKind.GOVERNANCE_RPT_BALANCE_AMOUNT,
            value=50.0,
            unit=FactUnit.CRORE_INR,
            period="2024-03-31",
            confidence="high",
            provenance=prov1,
        ),
        AnalysisFact(
            kind=FactKind.GOVERNANCE_RPT_CATEGORY,
            value="Advances to related parties",
            unit=None,
            period="2024-03-31",
            confidence="high",
            provenance=prov1,
        ),
    ]
    result = AnalysisResult(
        evidence_id="bse-ar-1",
        kind="annual_report",
        analyzer_version="3.3",
        confidence="high",
        source_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        facts=facts,
    )
    profile = build_profile("TATASTEEL", [result])
    assert len(profile.governance.related_parties) == 2


# --- store round-trip -------------------------------------------------------------
def test_related_party_entry_survives_store_round_trip(tmp_path) -> None:
    result = _result_with_rpt(8601.65, "Loans to related parties", "2024-03-31")
    profile = build_profile("TATASTEEL", [result])
    store = CompanyStore(tmp_path / "TATASTEEL" / "profile.json", "TATASTEEL")
    store.save(profile, [result])
    loaded = store.load()
    assert len(loaded.governance.related_parties) == 1
    entry = loaded.governance.related_parties[0]
    assert entry.amount == 8601.65
    assert entry.category == "Loans to related parties"
    assert entry.kind == "balance"
    assert entry.counterparty is None


def test_empty_related_parties_round_trips(tmp_path) -> None:
    store = CompanyStore(tmp_path / "TATASTEEL" / "profile.json", "TATASTEEL")
    store.save(CompanyProfile(company_id="TATASTEEL"), [])
    assert store.load().governance.related_parties == []


# --- related_party_disclosures query ----------------------------------------------
def test_related_party_disclosures_query_registered_and_dispatchable() -> None:
    from atlas.query.engine import available_queries, run_query

    assert "related_party_disclosures" in available_queries()
    result = _result_with_rpt(8601.65, "Loans to related parties", "2024-03-31")
    profile = build_profile("TATASTEEL", [result])
    out = run_query("related_party_disclosures", profile)
    assert out.query == "related_party_disclosures"
    assert out.sections[0].rows[0][2] == "Loans to related parties"


def test_related_party_disclosures_query_empty_result_honest() -> None:
    from atlas.query.engine import related_party_disclosures

    result = related_party_disclosures(CompanyProfile(company_id="TATASTEEL"))
    assert result.sections[0].rows == []
    assert any("no related-party" in n.lower() for n in result.notes)


# --- rpt_resolutions derived query (real TCS title samples) -----------------------
_REAL_TITLES = [
    "To approve existing as well as new material related party transactions with "
    "identified subsidiaries of Promoter Company and/ or their subsidiaries.",
    "To approve material related party transactions with Tata Capital Limited",
    "To approve material related party transactions with Tejas Networks Limited",
    "To approve material related party transactions with Jaguar Land Rover Limited",
    "To approve material related party transactions with Tata Consultancy Services "
    "Japan, Ltd. (a non-wholly owned subsidiary)",
]


def _profile_with_resolutions(titles: list[str]) -> CompanyProfile:
    profile = CompanyProfile(company_id="TCS")
    profile.governance = GovernanceProfile(
        resolutions=[
            AGMResolution(
                source_date=datetime(2024, 6, 1 + i, tzinfo=timezone.utc),
                period="2024-06-01",
                title=title,
                resolution_type="special",
                outcome="passed",
                pct_for=99.0,
                pct_against=1.0,
                evidence_id=f"bse-agm-{i}",
            )
            for i, title in enumerate(titles)
        ]
    )
    return profile


def test_rpt_resolutions_tags_only_rpt_titles() -> None:
    from atlas.query.engine import rpt_resolutions

    profile = _profile_with_resolutions(
        [*_REAL_TITLES, "To reappoint Mr. X as a Director"]
    )
    result = rpt_resolutions(profile)
    assert len(result.sections[0].rows) == len(_REAL_TITLES)


def test_rpt_resolutions_extracts_counterparty() -> None:
    from atlas.query.engine import rpt_resolutions

    profile = _profile_with_resolutions(
        ["To approve material related party transactions with Tata Capital Limited"]
    )
    result = rpt_resolutions(profile)
    assert result.sections[0].rows[0][2] == "Tata Capital Limited"


def test_rpt_resolutions_tolerates_vague_group_reference() -> None:
    from atlas.query.engine import rpt_resolutions

    profile = _profile_with_resolutions([_REAL_TITLES[0]])
    result = rpt_resolutions(profile)
    assert len(result.sections[0].rows) == 1
    assert "subsidiaries" in result.sections[0].rows[0][2]


def test_rpt_resolutions_query_registered_and_dispatchable() -> None:
    from atlas.query.engine import available_queries, run_query

    assert "rpt_resolutions" in available_queries()
    profile = _profile_with_resolutions(_REAL_TITLES)
    result = run_query("rpt_resolutions", profile)
    assert result.query == "rpt_resolutions"
    assert len(result.sections[0].rows) == len(_REAL_TITLES)


def test_rpt_resolutions_empty_result_honest() -> None:
    from atlas.query.engine import rpt_resolutions

    result = rpt_resolutions(
        _profile_with_resolutions(["To reappoint Mr. X as a Director"])
    )
    assert result.sections[0].rows == []
    assert any("no related-party" in n.lower() for n in result.notes)
