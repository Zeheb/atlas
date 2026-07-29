"""The equivalence gate (#32, #34) — the CI variant.

One invariant, stated four ways: a profile must depend on the facts, and on
nothing else about how they arrived.

    full == incremental == shuffled == reversed

Full builds everything at once. Incremental merges one document at a time,
which is what actually happens as filings arrive. Shuffled and reversed are
the same documents in orders nobody intended but a backfill will produce.

Byte-identity after canonicalisation, using the same comparison the rebuild
command uses. Anything weaker passes on a reordered list, which is the exact
failure this project exists to eliminate.

Per D1 this is the CI gate, built from synthetic results; the golden-corpus
variant carries the ``integration`` marker. The fixture is deliberately
awkward: two documents share a ``(period, basis)`` snapshot so the sources
lists hold more than one entry, and a third arrives on the same day as one of
them so the builder's stable sort has a genuine tie to keep.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.analysis.base import (
    AnalysisResult,
    EntityMention,
    FactKind,
    FactUnit,
    Provenance,
)
from atlas.company.builder import build_profile
from atlas.company.model import CompanyProfile
from atlas.company.store import CompanyStore, StaleResultError, load_profile_payload
from atlas.knowledge.entities.model import Entity
from atlas.rebuild import explain_difference
from tests.support.roundtrip import make_fact, make_result

_COMPANY = "TCS"


def _filing(
    evidence_id: str, *, revenue: int, day: int, period: str = "2026-03-31"
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
            ),
            make_fact(
                FactKind.FINANCIAL_PAT,
                revenue // 5,
                unit=FactUnit.CRORE_INR,
                period=period,
                section="consolidated_p_and_l",
            ),
        ],
        entities=[],
    )
    result.evidence_id = evidence_id
    result.source_date = datetime(2026, 4, day, tzinfo=timezone.utc)
    return result


def _corpus() -> list[AnalysisResult]:
    """Four filings: two sharing a snapshot, two sharing a source_date."""
    return [
        _filing("ev-a", revenue=64988, day=9),
        _filing("ev-b", revenue=64988, day=20),
        _filing("ev-c", revenue=61237, day=20, period="2025-12-31"),
        _filing("ev-d", revenue=59381, day=25, period="2025-09-30"),
    ]


def _serialise(profile: CompanyProfile, results: list[AnalysisResult], path: Path):
    CompanyStore(path, _COMPANY).save(profile, results)
    return load_profile_payload(path)


def _full(results: list[AnalysisResult], path: Path):
    return _serialise(build_profile(_COMPANY, results), results, path)


def _incremental(results: list[AnalysisResult], path: Path):
    """Merge one document at a time, the way filings actually arrive."""
    store = CompanyStore(path, _COMPANY)
    store.save(build_profile(_COMPANY, results[:1]), results[:1])
    for result in results[1:]:
        try:
            store.merge(result)
        except StaleResultError:  # pragma: no cover - fixture keeps one version
            pytest.fail("fixture reused an evidence_id under a new analyzer_version")
    return load_profile_payload(path)


@pytest.fixture
def reference(tmp_path: Path) -> dict:
    return _full(_corpus(), tmp_path / "full.json")


def _assert_same(candidate: dict, reference: dict, *, label: str) -> None:
    differences = explain_difference(reference, candidate)
    assert not differences, (
        f"{label} differs from the full build "
        f"({len(differences)} field difference(s)):\n  " + "\n  ".join(differences[:20])
    )


def test_the_fixture_is_not_vacuous(reference: dict) -> None:
    """Two empty profiles are identical and prove nothing; a snapshot drawing
    on one document proves nothing about ordering."""
    snapshots = reference["financial"]["snapshots"]

    assert len(snapshots) >= 2, "too few snapshots to test ordering"
    assert any(
        len(snapshot["sources"]) >= 2 for snapshot in snapshots
    ), "no snapshot draws on two documents; sources ordering is untested"


def test_full_build_is_idempotent(tmp_path: Path, reference: dict) -> None:
    """#34: same inputs, same bytes, every time."""
    again = _full(_corpus(), tmp_path / "again.json")

    _assert_same(again, reference, label="a second full build")


def test_incremental_equals_full(tmp_path: Path, reference: dict) -> None:
    _assert_same(
        _incremental(_corpus(), tmp_path / "incremental.json"),
        reference,
        label="the incremental build",
    )


def test_reversed_order_equals_full(tmp_path: Path, reference: dict) -> None:
    _assert_same(
        _full(list(reversed(_corpus())), tmp_path / "reversed.json"),
        reference,
        label="the reverse-order build",
    )


def test_shuffled_order_equals_full(tmp_path: Path, reference: dict) -> None:
    """Seeded, so a failure is reproducible rather than a rumour."""
    shuffled = _corpus()
    random.Random(20260729).shuffle(shuffled)

    _assert_same(
        _full(shuffled, tmp_path / "shuffled.json"),
        reference,
        label="the shuffled-order build",
    )


def test_incremental_in_reverse_equals_full(tmp_path: Path, reference: dict) -> None:
    """The combination a backfill actually produces: arrival order is neither
    the document order nor the reverse of it, and merges happen one at a time."""
    _assert_same(
        _incremental(list(reversed(_corpus())), tmp_path / "incremental-rev.json"),
        reference,
        label="the reverse-order incremental build",
    )


# ---------------------------------------------------------------------------
# Documents that name entities
# ---------------------------------------------------------------------------


def _holder(name: str, category: str, *, char_offset: int) -> EntityMention:
    return EntityMention(
        entity=Entity(
            entity_id=f"organization:{name.lower().replace(' ', '-')}",
            kind="organization",
            canonical_name=name,
        ),
        role=category,
        provenance=Provenance(section="shareholding", char_offset=char_offset),
    )


def _shareholding(evidence_id: str, *, day: int, holders: list[str]) -> AnalysisResult:
    result = make_result(
        "shareholding_pattern",
        facts=[],
        entities=[
            _holder(name, "mutual_fund", char_offset=100 * index)
            for index, name in enumerate(holders)
        ],
    )
    result.evidence_id = evidence_id
    result.source_date = datetime(2026, 4, day, tzinfo=timezone.utc)
    return result


def _entity_corpus() -> list[AnalysisResult]:
    return [
        _shareholding("ev-shp-1", day=10, holders=["Sbi Nifty 50 Etf", "LIC of India"]),
        _shareholding(
            "ev-shp-2",
            day=24,
            holders=["ICICI Prudential Value Fund", "Escrow Account"],
        ),
    ]


def test_entity_fixture_is_not_vacuous(tmp_path: Path) -> None:
    payload = _full(_entity_corpus(), tmp_path / "entities.json")

    assert len(payload["named_shareholders"]) == 4


def test_named_shareholders_do_not_depend_on_document_order(tmp_path: Path) -> None:
    """The residual order-dependence #33 budgets for.

    named_shareholders is appended per result (builder.py:588) and is the one
    container _finalize_profile does not sort (builder.py:1041-1056), so
    reversing the corpus reverses the blocks. Nothing to do with the assertion
    store: the analyzer path alone is order-dependent here.
    """
    reference = _full(_entity_corpus(), tmp_path / "entities.json")

    reversed_build = _full(
        list(reversed(_entity_corpus())), tmp_path / "entities-rev.json"
    )

    _assert_same(reversed_build, reference, label="the reverse-order build")
