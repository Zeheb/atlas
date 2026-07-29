"""Full rebuild == incremental rebuild, for the profile payload.

The architectural invariant is that everything above evidence is
reproducible, which is worth nothing if two routes to the same profile
disagree. Two routes exist today: build_profile() over every result at once,
and CompanyStore.merge() applied one result at a time.

These tests compare the stored ``profile`` object verbatim -- key order and
list order included, not just parsed equality. Ordering IS the failure mode
here: a profile whose facts dict or sources list depends on ingestion order
serialises differently from run to run, which makes any downstream byte
comparison useless and hides real drift in the noise.

Two properties the fixture must have, both learned by getting them wrong:

1. At least two results must land in the SAME (period, basis) snapshot.
   One result per snapshot leaves every sources list a single element, and
   the comparison passes while observing nothing.

2. Those two results must contribute DISJOINT fact kinds. The builder merges
   facts with dict.update(), so two results writing the same kind for the
   same period would differ in VALUE depending on processing order -- a
   deeper divergence than ordering, not the one this milestone fixes, and
   an xfail nothing here could clear.

The envelope's ``built_at`` and ``ingested_results`` are excluded: the first
is wall-clock, the second legitimately records the order results arrived.
Only the profile itself must be route-independent.

Synthetic fixtures throughout, so this runs unmarked in CI. The
golden-corpus counterpart is deselected from CI by design -- it needs real
acquired PDFs on disk.
"""

from __future__ import annotations

import itertools
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
from atlas.company.builder import build_profile
from atlas.company.store import CompanyStore

_Q2 = "2024-09-30"
_Q1 = "2024-06-30"

_DT_BRSR = datetime(2024, 6, 1, tzinfo=timezone.utc)
_DT_Q1 = datetime(2024, 7, 10, tzinfo=timezone.utc)
_DT_EARLY = datetime(2024, 10, 1, tzinfo=timezone.utc)
_DT_LATE = datetime(2024, 11, 1, tzinfo=timezone.utc)

_TICKER = "TCS"


def _fact(
    kind: FactKind,
    value: object,
    unit: FactUnit | None = None,
    period: str | None = None,
    section: str = "consolidated_pl_table",
) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence="high",
        provenance=Provenance(section=section, char_offset=None),
    )


def _financial(
    evidence_id: str,
    period: str,
    source_date: datetime,
    extra: list[AnalysisFact],
) -> AnalysisResult:
    """A financial_results result carrying period metadata plus *extra*.

    The metadata facts are identical across results for one period, so
    overwriting them is a no-op. Everything that varies goes in *extra*.
    """
    return AnalysisResult(
        evidence_id=evidence_id,
        kind="financial_results",
        analyzer_version="1.1",
        confidence="high",
        source_date=source_date,
        facts=[
            _fact(
                FactKind.REPORT_PERIOD_END,
                period,
                FactUnit.ISO_DATE,
                section="cover_letter",
            ),
            _fact(FactKind.REPORT_PERIOD_TYPE, "quarterly", section="cover_letter"),
            *extra,
        ],
    )


def _esg(evidence_id: str) -> AnalysisResult:
    period = "2024-03-31"
    return AnalysisResult(
        evidence_id=evidence_id,
        kind="brsr",
        analyzer_version="1.0",
        confidence="high",
        source_date=_DT_BRSR,
        facts=[
            _fact(
                FactKind.ESG_GHG_SCOPE1,
                5000.0,
                FactUnit.TCO2E,
                period=period,
                section="emissions",
            ),
        ],
    )


def _results() -> list[AnalysisResult]:
    """A fixed result set. Two entries share the Q2 snapshot.

    ``fr-early`` and ``fr-late`` both describe 2024-09-30 and contribute
    disjoint kinds (revenue vs PAT), so they merge into one snapshot with
    two sources and no value conflict.

    Returned deliberately NOT in chronological order. Evidence does not
    arrive chronologically -- backfilling an older filing after a newer one
    is routine -- and an arrival order already matching the sorted order
    would make both routes agree by luck rather than by construction.
    """
    return [
        _financial(
            "fr-late",
            _Q2,
            _DT_LATE,
            [_fact(FactKind.FINANCIAL_PAT, 12000.0, FactUnit.CRORE_INR, period=_Q2)],
        ),
        _esg("brsr-01"),
        _financial(
            "fr-early",
            _Q2,
            _DT_EARLY,
            [
                _fact(
                    FactKind.FINANCIAL_REVENUE, 60000.0, FactUnit.CRORE_INR, period=_Q2
                )
            ],
        ),
        _financial(
            "fr-q1",
            _Q1,
            _DT_Q1,
            [
                _fact(
                    FactKind.FINANCIAL_REVENUE, 59000.0, FactUnit.CRORE_INR, period=_Q1
                )
            ],
        ),
    ]


def _profile_payload(store: CompanyStore) -> str:
    """The stored profile, verbatim.

    json.loads preserves the file's key order, so re-dumping compares
    ordering as written -- which is the point. Drops the envelope's
    wall-clock ``built_at`` and its ``ingested_results`` arrival log.
    """
    raw = json.loads(store._path.read_text(encoding="utf-8"))
    return json.dumps(raw["profile"], indent=2)


def _built_at_once(base: Path, results: list[AnalysisResult]) -> str:
    store = CompanyStore(base, _TICKER)
    store.save(build_profile(_TICKER, results), results)
    return _profile_payload(store)


def _built_incrementally(base: Path, results: list[AnalysisResult]) -> str:
    store = CompanyStore(base, _TICKER)
    for result in results:
        store.merge(result)
    return _profile_payload(store)


def test_the_fixture_actually_shares_a_snapshot(tmp_path: Path) -> None:
    """Guard the guard.

    Every assertion below is vacuous unless some snapshot carries more than
    one source. A future edit that splits these results into separate
    snapshots would leave the equivalence tests passing and blind.
    """
    payload = json.loads(_built_at_once(tmp_path / "check", _results()))
    source_counts = [
        len(snapshot["sources"]) for snapshot in payload["financial"]["snapshots"]
    ]
    assert max(source_counts) >= 2, (
        "fixture no longer puts two results in one snapshot; the equivalence "
        "tests cannot observe sources ordering and prove nothing"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "_finalize_profile() sorts 16 containers but never the sources lists "
        "inside them, so a full build orders sources by (priority, "
        "source_date) while an incremental merge keeps arrival order. Fact "
        "keys differ for the same reason -- json.dumps has no sort_keys. "
        "Fixed by M-PRE commit 2 (#66 + #61)."
    ),
)
def test_full_build_equals_incremental_merge(tmp_path: Path) -> None:
    results = _results()
    assert _built_at_once(tmp_path / "full", results) == _built_incrementally(
        tmp_path / "incr", results
    )


def test_full_build_is_order_invariant(tmp_path: Path) -> None:
    """build_profile() sorts its input, so every permutation must agree.

    Exhaustive over the 24 permutations of a 4-result set rather than
    sampled: at this size exhaustive is cheap and beats taking on a
    property-testing dependency.
    """
    results = _results()
    expected = _built_at_once(tmp_path / "baseline", results)
    for index, order in enumerate(itertools.permutations(results)):
        actual = _built_at_once(tmp_path / f"perm{index}", list(order))
        assert actual == expected, f"permutation {index} diverged"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "build_profile()'s sort key is (priority, source_date) and sorted() "
        "is stable, so two same-kind results sharing a source_date keep "
        "input order and append to sources in that order. Fixed by M-PRE "
        "commit 2 (#66)."
    ),
)
def test_same_day_filings_of_the_same_kind_are_order_invariant(
    tmp_path: Path,
) -> None:
    """The residual tie exposure in build_profile()'s stable sort.

    Same-day filings of one kind are ordinary -- a company can file two
    results the same day -- so this is a real input, not a contrived one.
    """
    same_day = datetime(2024, 10, 10, tzinfo=timezone.utc)
    first = _financial(
        "fr-a",
        _Q2,
        same_day,
        [_fact(FactKind.FINANCIAL_REVENUE, 60000.0, FactUnit.CRORE_INR, period=_Q2)],
    )
    second = _financial(
        "fr-b",
        _Q2,
        same_day,
        [_fact(FactKind.FINANCIAL_PAT, 12000.0, FactUnit.CRORE_INR, period=_Q2)],
    )

    forward = _built_at_once(tmp_path / "forward", [first, second])
    reverse = _built_at_once(tmp_path / "reverse", [second, first])
    assert forward == reverse
