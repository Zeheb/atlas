"""Integration tests for atlas.company against real TCS filings.

Runs the full pipeline: KB parse → analyze → build_profile.
Validates that build_profile correctly assembles facts from multiple real
TCS documents into a coherent CompanyProfile.

Run with: pytest -m integration -v -s
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from atlas.analysis.base import FactKind
from atlas.analysis.registry import analyze
from atlas.company.builder import build_profile
from atlas.company.derived import ebit, pat_margin_pct
from atlas.company.model import CompanyProfile
from atlas.knowledge.base import KnowledgeBase

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

# Annual financial result FY2026
_ANN_ID = "bse-news-e4ffa3fc-e4f0-4da0-89fe-75d2f7b7b956"
# Q2 FY2025 quarterly financial result
_Q2_ID = "bse-news-373a3674-df22-42d5-ac50-1d77941355cd"
# TCS Q4 FY26 SHP
_SHP_ID = "bse-shp-532540-129"
# NSE ESG Dec 2025 credit rating
_CREDIT_ID = "bse-news-f5e7effc-aded-46c5-acad-a9c72a80da77"
# TCS buyback
_BUYBACK_ID = "bse-news-e2b7edf6-e25b-4a08-a7da-cdb7f6e7befa"


@pytest.fixture(scope="module")
def tcs_root(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(
        _TCS_REPO, evidence_ids=[_ANN_ID, _Q2_ID, _SHP_ID, _CREDIT_ID, _BUYBACK_ID]
    )


@pytest.fixture(scope="module")
def kb(tcs_root: Path) -> Generator[KnowledgeBase, None, None]:
    instance = KnowledgeBase(tcs_root)
    from atlas.acquisition.repository import Repository

    repo = Repository(tcs_root)
    for eid in (_ANN_ID, _Q2_ID, _SHP_ID, _CREDIT_ID, _BUYBACK_ID):
        entry = repo.get(eid)
        if entry is not None:
            instance.parse(entry)
    yield instance


@pytest.fixture(scope="module")
def tcs_profile(kb: KnowledgeBase) -> CompanyProfile:
    results = []
    for eid in (_ANN_ID, _Q2_ID, _SHP_ID, _CREDIT_ID, _BUYBACK_ID):
        try:
            results.append(analyze(eid, kb))
        except Exception:  # noqa: BLE001 - one bad document must not break the fixture
            pass
    return build_profile("TCS", results)


# ---------------------------------------------------------------------------
# Financial time-series
# ---------------------------------------------------------------------------


def test_financial_snapshots_exist(tcs_profile: CompanyProfile) -> None:
    assert len(tcs_profile.financial.snapshots) >= 1


def test_financial_annual_snapshot_has_revenue(tcs_profile: CompanyProfile) -> None:
    annual = [s for s in tcs_profile.financial.snapshots if s.period_type == "annual"]
    assert annual, "Expected at least one annual snapshot"
    snap = annual[0]
    revenue = snap.facts.get(FactKind.FINANCIAL_REVENUE)
    assert revenue is not None
    assert (
        revenue > 100_000
    ), f"TCS annual revenue should be > 1 lakh crore; got {revenue}"


def test_financial_snapshots_sorted_asc(tcs_profile: CompanyProfile) -> None:
    periods = [s.period for s in tcs_profile.financial.snapshots]
    assert periods == sorted(periods)


def test_annual_snapshot_has_balance_sheet(tcs_profile: CompanyProfile) -> None:
    annual = next(
        (s for s in tcs_profile.financial.snapshots if s.period_type == "annual"),
        None,
    )
    if annual is None:
        pytest.skip("No annual snapshot available")
    assert FactKind.FINANCIAL_CASH_AND_EQUIVALENTS in annual.facts


def test_annual_snapshot_derived_metrics(tcs_profile: CompanyProfile) -> None:
    annual = next(
        (
            s
            for s in tcs_profile.financial.snapshots
            if s.period_type == "annual" and s.basis == "consolidated"
        ),
        None,
    )
    if annual is None:
        pytest.skip("No consolidated annual snapshot")
    margin = pat_margin_pct(annual)
    if margin is not None:
        assert 10.0 < margin < 40.0, f"TCS PAT margin out of range: {margin:.1f}%"
    e = ebit(annual)
    if e is not None:
        assert e > 0


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


def test_ownership_snapshot_exists(tcs_profile: CompanyProfile) -> None:
    if not tcs_profile.ownership.snapshots:
        pytest.skip("SHP evidence not available")
    snap = tcs_profile.ownership.snapshots[0]
    promoter = snap.facts.get(FactKind.OWNERSHIP_PROMOTER_PCT)
    assert promoter is not None
    assert 70.0 < promoter < 80.0, f"TCS promoter holding out of range: {promoter:.1f}%"


def test_ownership_snapshot_uses_sources_list(tcs_profile: CompanyProfile) -> None:
    if not tcs_profile.ownership.snapshots:
        pytest.skip("SHP evidence not available")
    snap = tcs_profile.ownership.snapshots[0]
    assert isinstance(snap.sources, list)
    assert len(snap.sources) >= 1


# ---------------------------------------------------------------------------
# Credit history — debt_ratings and esg_ratings
# ---------------------------------------------------------------------------


def test_credit_esg_rating_in_esg_list(tcs_profile: CompanyProfile) -> None:
    if not tcs_profile.credit_history.esg_ratings:
        pytest.skip("ESG credit rating evidence not available")
    entry = tcs_profile.credit_history.esg_ratings[0]
    assert entry.agency
    assert entry.instrument == "ESG"


def test_credit_debt_list_separate_from_esg(tcs_profile: CompanyProfile) -> None:
    # TCS has no rated debt — debt_ratings should be empty for our test corpus
    for entry in tcs_profile.credit_history.debt_ratings:
        assert (
            entry.instrument != "ESG"
        ), "Debt ratings list must not contain ESG entries"


# ---------------------------------------------------------------------------
# Capital events — buyback
# ---------------------------------------------------------------------------


def test_buyback_event_exists(tcs_profile: CompanyProfile) -> None:
    if not tcs_profile.capital_events.buybacks:
        pytest.skip("Buyback evidence not available")
    bb = tcs_profile.capital_events.buybacks[0]
    assert bb.sub_type in ("announcement", "extinguishment", "schedule", "unknown")


# ---------------------------------------------------------------------------
# Compound: profile has multiple domains populated
# ---------------------------------------------------------------------------


def test_profile_company_id(tcs_profile: CompanyProfile) -> None:
    assert tcs_profile.company_id == "TCS"


def test_multiple_domains_populated(tcs_profile: CompanyProfile) -> None:
    domains_populated = sum(
        [
            bool(tcs_profile.financial.snapshots),
            bool(tcs_profile.esg.snapshots),
            bool(tcs_profile.ownership.snapshots),
            bool(tcs_profile.credit_history.esg_ratings),
            bool(tcs_profile.capital_events.buybacks),
        ]
    )
    assert domains_populated >= 2, "Expected at least 2 domains to be populated"
