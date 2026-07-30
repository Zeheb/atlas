"""``CompanyStore.merge(result, *, allow_reanalysis=False)`` — #76.

The unbudgeted work M7 was resized for. Re-running one analyzer at a bumped
version and merging the result is M7's happy path, and until this flag
existed ``merge()`` raised ``StaleResultError`` on exactly that case and told
the caller to rebuild from scratch.

Two properties matter more than the feature.

The default must change nothing. ``allow_reanalysis=False`` still raises,
and every pre-existing merge test passes untouched -- reversal is not
passing the flag.

Re-analysis must not quietly shrink a profile. Re-deriving needs every
previously ingested result back in hand; when the profile source cannot
supply one, rebuilding anyway would drop a whole document from the profile
and leave it looking perfectly well-formed. That path raises instead.

Why rebuild rather than subtract: a FinancialSnapshot's ``facts`` are merged
from every source that touched the period, and the merged value carries no
attribution. There is no operation that removes one contributor from it. So
"drop that evidence's contribution" is spelled "re-derive without it".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.assertions.store import AssertionStore
from atlas.assertions.writer import write_result
from atlas.company.builder import build_profile
from atlas.company.store import (
    CompanyStore,
    ReanalysisUnavailableError,
    StaleResultError,
)
from atlas.provenance import current_fingerprint
from tests.support.roundtrip import make_fact, make_result

_COMPANY = "TCS"


def _revenue_result(
    evidence_id: str,
    *,
    revenue: float,
    period: str = "2026-03-31",
    analyzer_version: str = "1.0",
) -> AnalysisResult:
    result = make_result(
        "financial_results",
        facts=[
            make_fact(
                FactKind.FINANCIAL_REVENUE,
                revenue,
                unit=FactUnit.CRORE_INR,
                period=period,
                section="consolidated_p_and_l",
            )
        ],
        entities=[],
        analyzer_version=analyzer_version,
    )
    result.evidence_id = evidence_id
    return result


@pytest.fixture
def store(tmp_path: Path) -> CompanyStore:
    """A store whose parent directory is the repository root, as in production."""
    return CompanyStore(tmp_path / "profile.json", _COMPANY)


def _seed_tier1(root: Path, results: list[AnalysisResult]) -> None:
    """Put *results* in the assertion store, which is what merge reloads from."""
    assertion_store = AssertionStore(root)
    fingerprint = current_fingerprint()
    for result in results:
        write_result(assertion_store, result, fingerprint=fingerprint)


def _revenue(profile: object, index: int = 0) -> float:
    snapshots = profile.financial.snapshots  # type: ignore[attr-defined]
    value: float = snapshots[index].facts[FactKind.FINANCIAL_REVENUE]
    return value


# ---------------------------------------------------------------------------
# The default is unchanged
# ---------------------------------------------------------------------------


def test_the_default_still_raises(store: CompanyStore) -> None:
    original = _revenue_result("fr-001", revenue=64988.0)
    store.save(build_profile(_COMPANY, [original]), [original])
    bumped = _revenue_result("fr-001", revenue=65999.0, analyzer_version="2.0")

    with pytest.raises(StaleResultError, match="fr-001"):
        store.merge(bumped)


def test_the_default_leaves_the_profile_untouched(store: CompanyStore) -> None:
    original = _revenue_result("fr-001", revenue=64988.0)
    store.save(build_profile(_COMPANY, [original]), [original])
    before = (store._path).read_text(encoding="utf-8")
    bumped = _revenue_result("fr-001", revenue=65999.0, analyzer_version="2.0")

    with pytest.raises(StaleResultError):
        store.merge(bumped)

    assert (store._path).read_text(encoding="utf-8") == before


def test_allow_reanalysis_is_keyword_only(store: CompanyStore) -> None:
    """A positional third argument must not silently become the flag."""
    original = _revenue_result("fr-001", revenue=64988.0)
    store.save(build_profile(_COMPANY, [original]), [original])

    with pytest.raises(TypeError):
        store.merge(original, True)  # type: ignore[misc,call-arg]


def test_the_flag_does_not_affect_the_idempotent_path(store: CompanyStore) -> None:
    original = _revenue_result("fr-001", revenue=64988.0)
    store.save(build_profile(_COMPANY, [original]), [original])

    profile = store.merge(original, allow_reanalysis=True)

    assert _revenue(profile) == pytest.approx(64988.0)
    assert store.get_ingested_ids() == {"fr-001"}


def test_the_flag_does_not_affect_the_new_evidence_path(store: CompanyStore) -> None:
    """A document never seen before merges incrementally, flag or not."""
    first = _revenue_result("fr-001", revenue=64988.0)
    store.save(build_profile(_COMPANY, [first]), [first])
    second = _revenue_result("fr-002", revenue=62000.0, period="2025-12-31")

    profile = store.merge(second, allow_reanalysis=True)

    assert len(profile.financial.snapshots) == 2
    assert store.get_ingested_ids() == {"fr-001", "fr-002"}


# ---------------------------------------------------------------------------
# Re-analysis
# ---------------------------------------------------------------------------


def test_reanalysis_replaces_the_stale_value(
    store: CompanyStore, tmp_path: Path
) -> None:
    original = _revenue_result("fr-001", revenue=64988.0)
    _seed_tier1(tmp_path, [original])
    store.save(build_profile(_COMPANY, [original]), [original])
    bumped = _revenue_result("fr-001", revenue=65999.0, analyzer_version="2.0")

    profile = store.merge(bumped, allow_reanalysis=True)

    assert _revenue(profile) == pytest.approx(65999.0)


def test_reanalysis_records_the_new_analyzer_version(
    store: CompanyStore, tmp_path: Path
) -> None:
    """Otherwise the next merge of the same document raises all over again."""
    original = _revenue_result("fr-001", revenue=64988.0)
    _seed_tier1(tmp_path, [original])
    store.save(build_profile(_COMPANY, [original]), [original])
    bumped = _revenue_result("fr-001", revenue=65999.0, analyzer_version="2.0")

    store.merge(bumped, allow_reanalysis=True)

    assert store.merge(bumped, allow_reanalysis=False) is not None


def test_reanalysis_keeps_every_other_document(
    store: CompanyStore, tmp_path: Path
) -> None:
    """The failure that would be invisible: a profile one document lighter."""
    first = _revenue_result("fr-001", revenue=64988.0)
    second = _revenue_result("fr-002", revenue=62000.0, period="2025-12-31")
    _seed_tier1(tmp_path, [first, second])
    store.save(build_profile(_COMPANY, [first, second]), [first, second])
    bumped = _revenue_result("fr-001", revenue=65999.0, analyzer_version="2.0")

    profile = store.merge(bumped, allow_reanalysis=True)

    assert store.get_ingested_ids() == {"fr-001", "fr-002"}
    by_period = {s.period: s for s in profile.financial.snapshots}
    assert by_period["2025-12-31"].facts[FactKind.FINANCIAL_REVENUE] == pytest.approx(
        62000.0
    )
    assert by_period["2026-03-31"].facts[FactKind.FINANCIAL_REVENUE] == pytest.approx(
        65999.0
    )


def test_reanalysis_matches_a_full_rebuild(store: CompanyStore, tmp_path: Path) -> None:
    """Re-derivation must land where build_profile would, not merely near it."""
    first = _revenue_result("fr-001", revenue=64988.0)
    second = _revenue_result("fr-002", revenue=62000.0, period="2025-12-31")
    _seed_tier1(tmp_path, [first, second])
    store.save(build_profile(_COMPANY, [first, second]), [first, second])
    bumped = _revenue_result("fr-001", revenue=65999.0, analyzer_version="2.0")

    merged = store.merge(bumped, allow_reanalysis=True)

    from atlas.assertions.reader import results_for

    reloaded = {r.evidence_id: r for r in results_for(tmp_path)}
    reloaded["fr-001"] = bumped
    expected = build_profile(_COMPANY, [reloaded[k] for k in sorted(reloaded)])
    assert merged.financial.snapshots == expected.financial.snapshots


def test_reanalysis_drops_the_stale_contribution_entirely(
    store: CompanyStore, tmp_path: Path
) -> None:
    """A period the old result created, and the new one does not, must go."""
    original = _revenue_result("fr-001", revenue=64988.0, period="2026-03-31")
    _seed_tier1(tmp_path, [original])
    store.save(build_profile(_COMPANY, [original]), [original])
    moved = _revenue_result(
        "fr-001", revenue=65999.0, period="2025-12-31", analyzer_version="2.0"
    )

    profile = store.merge(moved, allow_reanalysis=True)

    assert [s.period for s in profile.financial.snapshots] == ["2025-12-31"]


# ---------------------------------------------------------------------------
# Refusing to shrink
# ---------------------------------------------------------------------------


def test_reanalysis_refuses_when_a_document_cannot_be_reloaded(
    store: CompanyStore, tmp_path: Path
) -> None:
    """Tier 1 holds only one of the two ingested documents."""
    first = _revenue_result("fr-001", revenue=64988.0)
    second = _revenue_result("fr-002", revenue=62000.0, period="2025-12-31")
    _seed_tier1(tmp_path, [first])
    store.save(build_profile(_COMPANY, [first, second]), [first, second])
    bumped = _revenue_result("fr-001", revenue=65999.0, analyzer_version="2.0")

    with pytest.raises(ReanalysisUnavailableError, match="fr-002"):
        store.merge(bumped, allow_reanalysis=True)


def test_a_refused_reanalysis_writes_nothing(
    store: CompanyStore, tmp_path: Path
) -> None:
    first = _revenue_result("fr-001", revenue=64988.0)
    second = _revenue_result("fr-002", revenue=62000.0, period="2025-12-31")
    _seed_tier1(tmp_path, [first])
    store.save(build_profile(_COMPANY, [first, second]), [first, second])
    before = store._path.read_text(encoding="utf-8")
    bumped = _revenue_result("fr-001", revenue=65999.0, analyzer_version="2.0")

    with pytest.raises(ReanalysisUnavailableError):
        store.merge(bumped, allow_reanalysis=True)

    assert store._path.read_text(encoding="utf-8") == before


def test_reanalysis_unavailable_is_a_stale_result_error() -> None:
    """Existing `except StaleResultError` handlers must keep catching it.

    Two of them exist in the equivalence tests, and both mean "cannot be
    merged incrementally, rebuild from scratch" -- the right response here.
    """
    assert issubclass(ReanalysisUnavailableError, StaleResultError)


def test_the_error_names_what_could_not_be_reloaded(
    store: CompanyStore, tmp_path: Path
) -> None:
    """A refusal that does not say which document is a refusal you cannot act on."""
    first = _revenue_result("fr-001", revenue=64988.0)
    second = _revenue_result("fr-002", revenue=62000.0, period="2025-12-31")
    _seed_tier1(tmp_path, [first])
    store.save(build_profile(_COMPANY, [first, second]), [first, second])
    bumped = _revenue_result("fr-001", revenue=65999.0, analyzer_version="2.0")

    with pytest.raises(ReanalysisUnavailableError) as excinfo:
        store.merge(bumped, allow_reanalysis=True)

    assert "fr-002" in str(excinfo.value)
    assert "assertions" in str(excinfo.value)
