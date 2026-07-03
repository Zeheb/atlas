"""Integration tests for CompanyStore against real TCS filings.

Proves that:
  1. A CompanyProfile built from real evidence can be saved to disk.
  2. The loaded profile is identical to the original.
  3. A new AnalysisResult merged incrementally produces the same profile as a
     full rebuild from scratch.
  4. The store file is valid JSON with the expected envelope structure.
  5. Merging the same result twice is idempotent.

Run with: pytest -m integration -v -s
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.analysis.base import FactKind
from atlas.analysis.registry import analyze
from atlas.company.builder import build_profile
from atlas.company.model import CompanyProfile
from atlas.company.store import STORE_VERSION, CompanyStore, _serialize_profile
from atlas.knowledge.base import KnowledgeBase

pytestmark = pytest.mark.integration

_PROJECT_ROOT = Path(__file__).parents[2]
_TCS_REPO = _PROJECT_ROOT / "repositories" / "TCS"

# Evidence IDs used across tests
_ANN_ID = "bse-news-e4ffa3fc-e4f0-4da0-89fe-75d2f7b7b956"   # FY2026 annual results
_Q2_ID = "bse-news-373a3674-df22-42d5-ac50-1d77941355cd"    # Q2 FY2025 quarterly results
_SHP_ID = "bse-shp-532540-129"                                # Q4 FY26 shareholding
_CREDIT_ID = "bse-news-f5e7effc-aded-46c5-acad-a9c72a80da77" # NSE ESG credit rating
_BUYBACK_ID = "bse-news-e2b7edf6-e25b-4a08-a7da-cdb7f6e7befa"

# Split the evidence into an "initial" set (saved to disk) and one "new" result
# that will be merged incrementally.
_INITIAL_IDS = [_ANN_ID, _Q2_ID, _SHP_ID, _CREDIT_ID]
_NEW_ID = _BUYBACK_ID


# ---------------------------------------------------------------------------
# Module-scoped fixtures (KB built once, shared across all tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tcs_root(isolated_repo_factory) -> Path:
    if not _TCS_REPO.exists():
        pytest.skip("TCS repository not found")
    return isolated_repo_factory(
        _TCS_REPO, evidence_ids=[_ANN_ID, _Q2_ID, _SHP_ID, _CREDIT_ID, _BUYBACK_ID]
    )


@pytest.fixture(scope="module")
def kb(tcs_root: Path):
    instance = KnowledgeBase(tcs_root)
    from atlas.acquisition.repository import Repository
    repo = Repository(tcs_root)
    for eid in (_ANN_ID, _Q2_ID, _SHP_ID, _CREDIT_ID, _BUYBACK_ID):
        entry = repo.get(eid)
        if entry is not None:
            instance.parse(entry)
    yield instance


@pytest.fixture(scope="module")
def initial_results(kb: KnowledgeBase) -> list:
    results = []
    for eid in _INITIAL_IDS:
        try:
            results.append(analyze(eid, kb))
        except Exception:
            pass
    return results


@pytest.fixture(scope="module")
def new_result(kb: KnowledgeBase):
    try:
        return analyze(_NEW_ID, kb)
    except Exception:
        pytest.skip(f"Could not analyze {_NEW_ID}")


@pytest.fixture(scope="module")
def initial_profile(initial_results) -> CompanyProfile:
    return build_profile("TCS", initial_results)


# ---------------------------------------------------------------------------
# Test 1 — save and load produces an identical profile
# ---------------------------------------------------------------------------


def test_save_and_load_produces_identical_profile(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)

    loaded = store.load()

    assert _serialize_profile(loaded) == _serialize_profile(initial_profile)


def test_loaded_company_id_matches(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)
    assert store.load().company_id == "TCS"


def test_loaded_financial_snapshots_count(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)
    loaded = store.load()
    assert len(loaded.financial.snapshots) == len(initial_profile.financial.snapshots)


def test_loaded_financial_revenue_preserved(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results
) -> None:
    annual_snaps = [s for s in initial_profile.financial.snapshots if s.period_type == "annual"]
    if not annual_snaps:
        pytest.skip("No annual snapshot in initial profile")
    orig_rev = annual_snaps[0].facts.get(FactKind.FINANCIAL_REVENUE)
    if orig_rev is None:
        pytest.skip("No revenue fact in annual snapshot")

    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)
    loaded = store.load()

    loaded_annual = [s for s in loaded.financial.snapshots if s.period_type == "annual"]
    loaded_rev = loaded_annual[0].facts.get(FactKind.FINANCIAL_REVENUE)
    assert loaded_rev == pytest.approx(orig_rev)


# ---------------------------------------------------------------------------
# Test 2 — merge produces the same profile as a full rebuild
# ---------------------------------------------------------------------------


def test_merge_new_result_matches_rebuild_from_scratch(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results, new_result
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)

    merged = store.merge(new_result)
    rebuilt = build_profile("TCS", initial_results + [new_result])

    assert _serialize_profile(merged) == _serialize_profile(rebuilt)


def test_merge_adds_result_to_ingested_ids(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results, new_result
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)

    assert new_result.evidence_id not in store.get_ingested_ids()
    store.merge(new_result)
    assert new_result.evidence_id in store.get_ingested_ids()


def test_merge_initial_ids_all_tracked(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)
    tracked = store.get_ingested_ids()
    for r in initial_results:
        assert r.evidence_id in tracked


# ---------------------------------------------------------------------------
# Test 3 — idempotent merge
# ---------------------------------------------------------------------------


def test_merge_same_result_twice_is_idempotent(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results, new_result
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)

    profile_first = store.merge(new_result)
    profile_second = store.merge(new_result)

    assert _serialize_profile(profile_first) == _serialize_profile(profile_second)


def test_idempotent_merge_does_not_grow_ingested_list(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results, new_result
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)

    store.merge(new_result)
    store.merge(new_result)

    raw = json.loads(store._path.read_text())
    evidence_ids = [r["evidence_id"] for r in raw["ingested_results"]]
    assert evidence_ids.count(new_result.evidence_id) == 1


# ---------------------------------------------------------------------------
# Test 4 — stored file is valid JSON with correct envelope
# ---------------------------------------------------------------------------


def test_store_file_is_valid_json(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)
    content = store._path.read_text(encoding="utf-8")
    parsed = json.loads(content)
    assert isinstance(parsed, dict)


def test_store_envelope_has_required_keys(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)
    raw = json.loads(store._path.read_text())
    for key in ("store_version", "builder_version", "company_id", "built_at",
                 "ingested_results", "profile"):
        assert key in raw, f"Missing key: {key}"


def test_store_version_in_envelope(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)
    raw = json.loads(store._path.read_text())
    assert raw["store_version"] == STORE_VERSION


def test_ingested_results_have_required_fields(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results
) -> None:
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)
    raw = json.loads(store._path.read_text())
    for rec in raw["ingested_results"]:
        for field in ("evidence_id", "kind", "analyzer_version", "source_date", "analyzed_at"):
            assert field in rec, f"Missing field {field!r} in ingested result record"


def test_profile_facts_use_string_keys(
    tmp_path: Path, initial_profile: CompanyProfile, initial_results
) -> None:
    """FactKind enum keys must be stored as plain strings, not Python enum repr."""
    store = CompanyStore(tmp_path / "TCS.json", "TCS")
    store.save(initial_profile, initial_results)
    raw = json.loads(store._path.read_text())
    for snap in raw["profile"]["financial"]["snapshots"]:
        for key in snap.get("facts", {}):
            assert isinstance(key, str)
            assert not key.startswith("FactKind.")
