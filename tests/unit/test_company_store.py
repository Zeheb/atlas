"""Unit tests for atlas.company.store (CompanyStore).

All fixtures are synthetic — no real PDFs or KB access.
Tests are parameterised over every domain (financial, ESG, ownership, segments,
credit_history, capital_events, strategy, governance) to verify full roundtrip
fidelity through JSON serialisation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.company.builder import BUILDER_VERSION, build_profile
from atlas.company.model import (
    AGMResolution,
    AcquisitionEvent,
    BuybackEvent,
    CSATEntry,
    CapitalEventLedger,
    CompanyProfile,
    CreditHistory,
    CreditRatingEntry,
    DividendEvent,
    ESGSnapshot,
    ESGTimeSeries,
    FinancialSnapshot,
    FinancialTimeSeries,
    GovernanceProfile,
    InvestmentEvent,
    OwnershipSnapshot,
    OwnershipTimeSeries,
    SegmentEntry,
    SegmentTimeSeries,
    StrategyEntry,
    StrategyProfile,
)
from atlas.company.store import STORE_VERSION, CompanyStore, StaleResultError

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_DT = datetime(2024, 10, 10, tzinfo=timezone.utc)
_DT2 = datetime(2025, 1, 15, tzinfo=timezone.utc)


def _fact(
    kind: FactKind,
    value: object,
    unit: FactUnit | None = None,
    period: str | None = None,
    section: str = "consolidated_pl_table",
    char_offset: int | None = None,
) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence="high",
        provenance=Provenance(section=section, char_offset=char_offset),
    )


def _result(
    kind: str,
    facts: list[AnalysisFact],
    evidence_id: str = "ev-001",
    source_date: datetime = _DT,
    analyzer_version: str = "1.0",
) -> AnalysisResult:
    return AnalysisResult(
        evidence_id=evidence_id,
        kind=kind,
        analyzer_version=analyzer_version,
        confidence="high",
        source_date=source_date,
        facts=facts,
    )


def _financial_result(
    period: str = "2024-09-30",
    revenue: float = 60000.0,
    pat: float = 12000.0,
    evidence_id: str = "fr-001",
    source_date: datetime = _DT,
) -> AnalysisResult:
    facts = [
        _fact(
            FactKind.REPORT_PERIOD_END,
            period,
            FactUnit.ISO_DATE,
            section="cover_letter",
        ),
        _fact(FactKind.REPORT_PERIOD_TYPE, "quarterly", section="cover_letter"),
        _fact(FactKind.FINANCIAL_REVENUE, revenue, FactUnit.CRORE_INR, period=period),
        _fact(FactKind.FINANCIAL_PAT, pat, FactUnit.CRORE_INR, period=period),
    ]
    return _result(
        "financial_results", facts, evidence_id=evidence_id, source_date=source_date
    )


def _esg_result(
    period: str = "2024-03-31",
    evidence_id: str = "brsr-001",
) -> AnalysisResult:
    facts = [
        _fact(
            FactKind.ESG_GHG_SCOPE1,
            5000.0,
            FactUnit.TCO2E,
            period=period,
            section="emissions",
        ),
        _fact(
            FactKind.ESG_WORKFORCE_HEADCOUNT,
            600000,
            FactUnit.COUNT,
            period=period,
            section="workforce",
        ),
    ]
    return _result("brsr", facts, evidence_id=evidence_id)


def _shp_result(evidence_id: str = "shp-001") -> AnalysisResult:
    facts = [
        _fact(
            FactKind.OWNERSHIP_PROMOTER_PCT,
            71.8,
            FactUnit.PERCENT,
            period="2024-09-30",
            section="promoter",
        ),
        _fact(
            FactKind.OWNERSHIP_PUBLIC_PCT,
            28.2,
            FactUnit.PERCENT,
            period="2024-09-30",
            section="public",
        ),
    ]
    return _result("shareholding_pattern", facts, evidence_id=evidence_id)


def _credit_result(evidence_id: str = "cr-001") -> AnalysisResult:
    facts = [
        _fact(FactKind.CREDIT_AGENCY, "NSE Sustainability", section="document"),
        _fact(FactKind.CREDIT_INSTRUMENT, "ESG", section="esg"),
        _fact(FactKind.CREDIT_RATING, "73", section="esg"),
    ]
    return _result("credit_rating_report", facts, evidence_id=evidence_id)


def _buyback_result(evidence_id: str = "bb-001") -> AnalysisResult:
    facts = [
        _fact(
            FactKind.CAPITAL_BUYBACK_AMOUNT,
            17000.0,
            FactUnit.CRORE_INR,
            section="buyback",
        ),
        _fact(
            FactKind.CAPITAL_BUYBACK_PRICE_PER_SHARE,
            4150.0,
            FactUnit.RUPEES_PER_SHARE,
            section="buyback",
        ),
        _fact(FactKind.CAPITAL_BUYBACK_SHARES_OFFERED, 40000000, section="buyback"),
    ]
    return _result("buyback", facts, evidence_id=evidence_id)


def _investor_presentation_result(evidence_id: str = "ip-001") -> AnalysisResult:
    facts = [
        _fact(FactKind.STRATEGY_PRIORITY, "Cloud leadership", section="strategy"),
        _fact(
            FactKind.STRATEGY_CSAT,
            78.5,
            FactUnit.PERCENT,
            period="2024-09-30",
            section="customer",
        ),
        _fact(
            FactKind.FINANCIAL_ROE,
            52.0,
            FactUnit.PERCENT,
            period="2025-03-31",
            section="financial_highlights",
        ),
    ]
    return _result("investor_presentation", facts, evidence_id=evidence_id)


def _agm_result(evidence_id: str = "agm-001") -> AnalysisResult:
    facts = [
        _fact(
            FactKind.GOVERNANCE_RESOLUTION_TITLE,
            "Re-appoint auditor",
            period="2024-08-14",
            section="resolution_1",
        ),
        _fact(
            FactKind.GOVERNANCE_RESOLUTION_TYPE,
            "ordinary",
            period="2024-08-14",
            section="resolution_1",
        ),
        _fact(
            FactKind.GOVERNANCE_VOTE_PCT_FOR,
            99.12,
            FactUnit.PERCENT,
            period="2024-08-14",
            section="resolution_1",
        ),
    ]
    return _result("agm_notice", facts, evidence_id=evidence_id)


@pytest.fixture
def store(tmp_path: Path) -> CompanyStore:
    return CompanyStore(tmp_path / "TCS.json", "TCS")


def _profile_as_json(profile: CompanyProfile) -> dict:
    """Round-trip a profile through JSON for equality comparison."""
    from atlas.company.store import _serialize_profile

    return _serialize_profile(profile)


# ---------------------------------------------------------------------------
# exists() / save() basics
# ---------------------------------------------------------------------------


def test_exists_false_before_save(store: CompanyStore) -> None:
    assert not store.exists()


def test_exists_true_after_save(store: CompanyStore) -> None:
    profile = build_profile("TCS", [])
    store.save(profile)
    assert store.exists()


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "TCS.json"
    s = CompanyStore(deep, "TCS")
    s.save(build_profile("TCS", []))
    assert deep.exists()


def test_save_raises_on_company_id_mismatch(store: CompanyStore) -> None:
    profile = build_profile("INFOSYS", [])
    with pytest.raises(ValueError, match="company_id"):
        store.save(profile)


# ---------------------------------------------------------------------------
# JSON envelope structure
# ---------------------------------------------------------------------------


def test_json_contains_store_version(store: CompanyStore) -> None:
    store.save(build_profile("TCS", []))
    raw = json.loads(store._path.read_text())
    assert raw["store_version"] == STORE_VERSION


def test_json_contains_builder_version(store: CompanyStore) -> None:
    store.save(build_profile("TCS", []))
    raw = json.loads(store._path.read_text())
    assert raw["builder_version"] == BUILDER_VERSION


def test_json_contains_company_id(store: CompanyStore) -> None:
    store.save(build_profile("TCS", []))
    raw = json.loads(store._path.read_text())
    assert raw["company_id"] == "TCS"


def test_json_contains_built_at(store: CompanyStore) -> None:
    store.save(build_profile("TCS", []))
    raw = json.loads(store._path.read_text())
    assert "built_at" in raw
    datetime.fromisoformat(raw["built_at"])  # must be valid ISO string


def test_json_contains_ingested_results_metadata(store: CompanyStore) -> None:
    r = _financial_result()
    profile = build_profile("TCS", [r])
    store.save(profile, [r])
    raw = json.loads(store._path.read_text())
    assert len(raw["ingested_results"]) == 1
    rec = raw["ingested_results"][0]
    assert rec["evidence_id"] == r.evidence_id
    assert rec["kind"] == r.kind
    assert rec["analyzer_version"] == r.analyzer_version
    assert "source_date" in rec
    assert "analyzed_at" in rec


# ---------------------------------------------------------------------------
# Roundtrip — FinancialTimeSeries
# ---------------------------------------------------------------------------


def test_roundtrip_empty_profile(store: CompanyStore) -> None:
    profile = build_profile("TCS", [])
    store.save(profile)
    loaded = store.load()
    assert loaded.company_id == "TCS"
    assert loaded.financial.snapshots == []
    assert loaded.esg.snapshots == []


def test_roundtrip_financial_snapshot(store: CompanyStore) -> None:
    profile = build_profile("TCS", [_financial_result()])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.financial.snapshots) == 1
    snap = loaded.financial.snapshots[0]
    assert snap.period == "2024-09-30"
    assert snap.period_type == "quarterly"
    assert snap.basis == "consolidated"
    assert snap.facts[FactKind.FINANCIAL_REVENUE] == pytest.approx(60000.0)
    assert snap.facts[FactKind.FINANCIAL_PAT] == pytest.approx(12000.0)
    assert "fr-001" in snap.sources


def test_roundtrip_financial_facts_keys_are_factkind(store: CompanyStore) -> None:
    profile = build_profile("TCS", [_financial_result()])
    store.save(profile)
    loaded = store.load()
    snap = loaded.financial.snapshots[0]
    for key in snap.facts:
        assert isinstance(key, FactKind)


# ---------------------------------------------------------------------------
# Roundtrip — ESGTimeSeries
# ---------------------------------------------------------------------------


def test_roundtrip_esg_snapshot(store: CompanyStore) -> None:
    profile = build_profile("TCS", [_esg_result()])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.esg.snapshots) == 1
    snap = loaded.esg.snapshots[0]
    assert snap.period == "2024-03-31"
    assert snap.facts[FactKind.ESG_GHG_SCOPE1] == pytest.approx(5000.0)
    assert snap.facts[FactKind.ESG_WORKFORCE_HEADCOUNT] == pytest.approx(600000.0)


# ---------------------------------------------------------------------------
# Roundtrip — OwnershipTimeSeries
# ---------------------------------------------------------------------------


def test_roundtrip_ownership_snapshot_sources_is_list(store: CompanyStore) -> None:
    profile = build_profile("TCS", [_shp_result()])
    store.save(profile)
    loaded = store.load()
    snap = loaded.ownership.snapshots[0]
    assert isinstance(snap.sources, list)
    assert "shp-001" in snap.sources


def test_roundtrip_ownership_facts(store: CompanyStore) -> None:
    profile = build_profile("TCS", [_shp_result()])
    store.save(profile)
    loaded = store.load()
    snap = loaded.ownership.snapshots[0]
    assert snap.facts[FactKind.OWNERSHIP_PROMOTER_PCT] == pytest.approx(71.8)


# ---------------------------------------------------------------------------
# Roundtrip — CreditHistory (split lists)
# ---------------------------------------------------------------------------


def test_roundtrip_credit_esg_in_esg_ratings(store: CompanyStore) -> None:
    profile = build_profile("TCS", [_credit_result()])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.credit_history.esg_ratings) == 1
    entry = loaded.credit_history.esg_ratings[0]
    assert entry.instrument == "ESG"
    assert entry.rating == "73"
    assert entry.agency == "NSE Sustainability"
    assert entry.evidence_id == "cr-001"


def test_roundtrip_credit_debt_ratings_empty_for_esg_filing(
    store: CompanyStore,
) -> None:
    profile = build_profile("TCS", [_credit_result()])
    store.save(profile)
    loaded = store.load()
    assert loaded.credit_history.debt_ratings == []


# ---------------------------------------------------------------------------
# Roundtrip — CapitalEventLedger
# ---------------------------------------------------------------------------


def test_roundtrip_buyback_event(store: CompanyStore) -> None:
    profile = build_profile("TCS", [_buyback_result()])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.capital_events.buybacks) == 1
    bb = loaded.capital_events.buybacks[0]
    assert bb.sub_type == "announcement"
    assert bb.amount == pytest.approx(17000.0)
    assert bb.price_per_share == pytest.approx(4150.0)
    assert bb.shares_offered == 40000000
    assert bb.evidence_id == "bb-001"
    assert isinstance(bb.source_date, datetime)


def test_roundtrip_dividend_event(store: CompanyStore) -> None:
    facts = [
        _fact(
            FactKind.CAPITAL_DIVIDEND_PER_SHARE,
            10.0,
            FactUnit.RUPEES_PER_SHARE,
            section="consolidated_pl_table",
            char_offset=100,
        ),
        _fact(
            FactKind.CAPITAL_DIVIDEND_TYPE,
            "interim",
            section="consolidated_pl_table",
            char_offset=100,
        ),
    ]
    r = _result("financial_results", facts, evidence_id="div-001")
    profile = build_profile("TCS", [r])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.capital_events.dividends) >= 1
    div = loaded.capital_events.dividends[0]
    assert div.per_share == pytest.approx(10.0)
    assert div.dividend_type == "interim"
    assert div.evidence_id == "div-001"


def test_roundtrip_acquisition_event_with_unit(store: CompanyStore) -> None:
    facts = [
        _fact(FactKind.CAPITAL_ACQ_TARGET_NAME, "Acme Corp", section="acquisition"),
        _fact(
            FactKind.CAPITAL_ACQ_ENTERPRISE_VALUE,
            500.0,
            FactUnit.USD_MILLION,
            section="acquisition",
        ),
        _fact(FactKind.CAPITAL_ACQ_CONSIDERATION_TYPE, "cash", section="acquisition"),
    ]
    r = _result("acquisition", facts, evidence_id="acq-001")
    profile = build_profile("TCS", [r])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.capital_events.acquisitions) == 1
    acq = loaded.capital_events.acquisitions[0]
    assert acq.target_name == "Acme Corp"
    assert acq.enterprise_value == pytest.approx(500.0)
    assert acq.enterprise_value_unit == FactUnit.USD_MILLION
    assert acq.consideration_type == "cash"


def test_roundtrip_investment_event_with_unit(store: CompanyStore) -> None:
    facts = [
        _fact(
            FactKind.CAPITAL_INVEST_TARGET_NAME, "TCS Subsidiary", section="investments"
        ),
        _fact(
            FactKind.CAPITAL_INVEST_AMOUNT,
            250.0,
            FactUnit.CRORE_INR,
            section="investments",
        ),
    ]
    r = _result("board_outcome", facts, evidence_id="bo-001")
    profile = build_profile("TCS", [r])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.capital_events.investments) == 1
    inv = loaded.capital_events.investments[0]
    assert inv.target_name == "TCS Subsidiary"
    assert inv.amount == pytest.approx(250.0)
    assert inv.amount_unit == FactUnit.CRORE_INR


# ---------------------------------------------------------------------------
# Roundtrip — StrategyProfile
# ---------------------------------------------------------------------------


def test_roundtrip_strategy_entries(store: CompanyStore) -> None:
    profile = build_profile("TCS", [_investor_presentation_result()])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.strategy.entries) == 1
    entry = loaded.strategy.entries[0]
    assert entry.kind == "priority"
    assert entry.text == "Cloud leadership"
    assert isinstance(entry.source_date, datetime)
    assert entry.evidence_id == "ip-001"


def test_roundtrip_strategy_csat(store: CompanyStore) -> None:
    profile = build_profile("TCS", [_investor_presentation_result()])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.strategy.csat) == 1
    c = loaded.strategy.csat[0]
    assert c.period == "2024-09-30"
    assert c.score == pytest.approx(78.5)


# ---------------------------------------------------------------------------
# Roundtrip — GovernanceProfile
# ---------------------------------------------------------------------------


def test_roundtrip_agm_resolutions(store: CompanyStore) -> None:
    profile = build_profile("TCS", [_agm_result()])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.governance.resolutions) == 1
    res = loaded.governance.resolutions[0]
    assert res.title == "Re-appoint auditor"
    assert res.resolution_type == "ordinary"
    assert res.pct_for == pytest.approx(99.12)
    assert res.period == "2024-08-14"
    assert isinstance(res.source_date, datetime)


# ---------------------------------------------------------------------------
# Segments roundtrip
# ---------------------------------------------------------------------------


def test_roundtrip_segment_entries(store: CompanyStore) -> None:
    facts = [
        _fact(
            FactKind.SEGMENT_NAME,
            "BFSI",
            period="2024-09-30",
            section="segment_table",
            char_offset=0,
        ),
        _fact(
            FactKind.SEGMENT_REVENUE,
            20000.0,
            FactUnit.CRORE_INR,
            period="2024-09-30",
            section="segment_table",
            char_offset=0,
        ),
    ]
    r = _result("financial_results", facts, evidence_id="fr-seg-001")
    profile = build_profile("TCS", [r])
    store.save(profile)
    loaded = store.load()
    assert len(loaded.segments.entries) >= 1
    entry = next(e for e in loaded.segments.entries if e.name == "BFSI")
    assert entry.period == "2024-09-30"
    assert entry.revenue == pytest.approx(20000.0)


# ---------------------------------------------------------------------------
# get_ingested_ids()
# ---------------------------------------------------------------------------


def test_get_ingested_ids_empty_before_save(store: CompanyStore) -> None:
    assert store.get_ingested_ids() == set()


def test_get_ingested_ids_after_save(store: CompanyStore) -> None:
    r1 = _financial_result(evidence_id="fr-001")
    r2 = _esg_result(evidence_id="brsr-002")
    profile = build_profile("TCS", [r1, r2])
    store.save(profile, [r1, r2])
    ids = store.get_ingested_ids()
    assert ids == {"fr-001", "brsr-002"}


def test_get_ingested_ids_empty_results_passed(store: CompanyStore) -> None:
    store.save(build_profile("TCS", []))
    assert store.get_ingested_ids() == set()


# ---------------------------------------------------------------------------
# merge() — basic incremental update
# ---------------------------------------------------------------------------


def test_merge_creates_store_when_not_exists(store: CompanyStore) -> None:
    assert not store.exists()
    profile = store.merge(_financial_result())
    assert store.exists()
    assert len(profile.financial.snapshots) == 1


def test_merge_adds_new_snapshot(store: CompanyStore) -> None:
    r1 = _financial_result(period="2024-09-30", evidence_id="fr-001")
    initial = build_profile("TCS", [r1])
    store.save(initial, [r1])

    r2 = _financial_result(period="2024-12-31", revenue=62000.0, evidence_id="fr-002")
    profile = store.merge(r2)
    assert len(profile.financial.snapshots) == 2
    assert profile.financial.snapshots[1].period == "2024-12-31"
    assert profile.financial.snapshots[1].facts[
        FactKind.FINANCIAL_REVENUE
    ] == pytest.approx(62000.0)


def test_merge_is_idempotent(store: CompanyStore) -> None:
    r1 = _financial_result(evidence_id="fr-001")
    initial = build_profile("TCS", [r1])
    store.save(initial, [r1])

    profile1 = store.merge(r1)
    profile2 = store.merge(r1)
    assert len(profile1.financial.snapshots) == len(profile2.financial.snapshots) == 1


def test_merge_idempotent_does_not_duplicate_evidence(store: CompanyStore) -> None:
    r1 = _financial_result(evidence_id="fr-001")
    store.save(build_profile("TCS", [r1]), [r1])
    store.merge(r1)
    assert store.get_ingested_ids() == {"fr-001"}


def test_merge_raises_stale_result_error(store: CompanyStore) -> None:
    r1 = _financial_result(evidence_id="fr-001")
    store.save(build_profile("TCS", [r1]), [r1])

    r1_new = _result(
        "financial_results",
        [
            _fact(
                FactKind.FINANCIAL_REVENUE,
                99999.0,
                FactUnit.CRORE_INR,
                period="2024-09-30",
            )
        ],
        evidence_id="fr-001",
        analyzer_version="2.0",
    )
    with pytest.raises(StaleResultError, match="fr-001"):
        store.merge(r1_new)


def test_merge_persists_updated_ids(store: CompanyStore) -> None:
    r1 = _financial_result(evidence_id="fr-001")
    store.save(build_profile("TCS", [r1]), [r1])

    r2 = _esg_result(evidence_id="brsr-002")
    store.merge(r2)
    assert store.get_ingested_ids() == {"fr-001", "brsr-002"}


def test_merge_sorted_after_update(store: CompanyStore) -> None:
    r1 = _financial_result(period="2024-12-31", evidence_id="fr-002", source_date=_DT2)
    store.save(build_profile("TCS", [r1]), [r1])

    r2 = _financial_result(period="2024-09-30", evidence_id="fr-001", source_date=_DT)
    profile = store.merge(r2)
    periods = [s.period for s in profile.financial.snapshots]
    assert periods == sorted(periods)


def test_merge_esg_result_populates_esg_snapshots(store: CompanyStore) -> None:
    store.save(build_profile("TCS", []), [])
    profile = store.merge(_esg_result(evidence_id="brsr-001"))
    assert len(profile.esg.snapshots) == 1
    assert profile.esg.snapshots[0].facts[FactKind.ESG_GHG_SCOPE1] == pytest.approx(
        5000.0
    )


def test_merge_strategy_result_populates_strategy_profile(store: CompanyStore) -> None:
    store.save(build_profile("TCS", []), [])
    profile = store.merge(_investor_presentation_result(evidence_id="ip-001"))
    assert len(profile.strategy.entries) == 1
    assert profile.strategy.entries[0].kind == "priority"


def test_merge_unknown_kind_is_silently_skipped(store: CompanyStore) -> None:
    store.save(build_profile("TCS", []), [])
    r = _result("annual_report", [], evidence_id="ar-001")
    profile = store.merge(r)
    assert profile.financial.snapshots == []
    assert "ar-001" in store.get_ingested_ids()


# ---------------------------------------------------------------------------
# merge() == build_profile() equivalence
# ---------------------------------------------------------------------------


def test_merge_matches_rebuild_from_scratch_financial(
    store: CompanyStore, tmp_path: Path
) -> None:
    """Incrementally merging R2 must produce the same profile as rebuilding from [R1, R2]."""
    r1 = _financial_result(
        period="2024-09-30", revenue=60000.0, pat=12000.0, evidence_id="fr-001"
    )
    r2 = _financial_result(
        period="2024-12-31",
        revenue=63000.0,
        pat=13500.0,
        evidence_id="fr-002",
        source_date=_DT2,
    )

    # Incremental path
    initial = build_profile("TCS", [r1])
    store.save(initial, [r1])
    merged = store.merge(r2)

    # Rebuild path
    rebuilt = build_profile("TCS", [r1, r2])

    assert _profile_as_json(merged) == _profile_as_json(rebuilt)


def test_merge_matches_rebuild_supplement_does_not_overwrite(
    store: CompanyStore,
) -> None:
    """A priority-2 (transcript) merged after priority-1 (financial_results) must
    not overwrite XBRL facts — consistent with batch build_profile() behaviour."""
    r_fin = _financial_result(
        period="2024-09-30", revenue=60000.0, evidence_id="fr-001"
    )
    r_tx = _result(
        "earnings_transcript",
        [
            _fact(
                FactKind.FINANCIAL_REVENUE,
                59000.0,
                FactUnit.CRORE_INR,
                period="2024-09-30",
            )
        ],
        evidence_id="tx-001",
        source_date=_DT2,
    )

    # Incremental
    store.save(build_profile("TCS", [r_fin]), [r_fin])
    merged = store.merge(r_tx)

    # Rebuild
    rebuilt = build_profile("TCS", [r_fin, r_tx])

    assert _profile_as_json(merged) == _profile_as_json(rebuilt)
    # XBRL value must win
    rev = merged.financial.snapshots[0].facts[FactKind.FINANCIAL_REVENUE]
    assert rev == pytest.approx(60000.0)


def test_merge_matches_rebuild_multi_domain(store: CompanyStore) -> None:
    """Merging ESG and SHP results into a financial profile matches rebuild."""
    r1 = _financial_result(evidence_id="fr-001")
    r2 = _esg_result(evidence_id="brsr-001")

    initial = build_profile("TCS", [r1])
    store.save(initial, [r1])
    store.merge(r2)
    merged = store.load()

    rebuilt = build_profile("TCS", [r1, r2])

    assert _profile_as_json(merged) == _profile_as_json(rebuilt)


# ---------------------------------------------------------------------------
# load() error handling
# ---------------------------------------------------------------------------


def test_load_raises_file_not_found(store: CompanyStore) -> None:
    with pytest.raises(FileNotFoundError):
        store.load()


def test_load_raises_on_unsupported_store_version(store: CompanyStore) -> None:
    store.save(build_profile("TCS", []))
    raw = json.loads(store._path.read_text())
    raw["store_version"] = "99"
    store._path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="store_version"):
        store.load()
