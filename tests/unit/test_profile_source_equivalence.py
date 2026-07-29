"""Profiles built from analyzers and from assertions must be identical (#26).

The whole milestone rests on this one claim, so the test is written to be hard
to pass by accident:

* two documents share a ``(period, basis)`` snapshot, so the ``sources`` lists
  actually hold more than one element. A fixture giving each result its own
  snapshot makes every list a single item and the comparison vacuous -- that
  exact mistake was made once already, in M-PRE;
* the profiles are asserted to be non-empty before they are compared, because
  two empty profiles are trivially identical;
* comparison is byte-identity of the canonical serialisation, not a field
  sample. A section that comes back one entry short or subtly reordered is
  precisely what a partial comparison would wave through.

Per D1 this is the CI variant, built from synthetic results. The golden-corpus
variant lives in tests/integration/ and carries the ``integration`` marker.
"""

from __future__ import annotations

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
from atlas.assertions.store import AssertionStore
from atlas.assertions.writer import write_result
from atlas.knowledge.entities.model import Entity
from atlas.provenance import current_fingerprint
from tests.support.equivalence import assert_profiles_identical, build_and_serialize
from tests.support.roundtrip import make_fact, make_result

_COMPANY = "TCS"


def _financials(
    evidence_id: str, *, revenue: int, source_date: datetime
) -> AnalysisResult:
    """One quarterly filing. Two of these share a period on purpose.

    The section name has to start with "consolidated" or "standalone":
    ``_basis_from_section`` (builder.py:89) drops any financial fact whose
    section it cannot attribute to a basis, so a plausible-looking "p_and_l"
    produces an empty profile and a vacuously passing comparison.
    """
    result = make_result(
        "financial_results",
        facts=[
            make_fact(
                FactKind.FINANCIAL_REVENUE,
                revenue,
                unit=FactUnit.CRORE_INR,
                period="2026-03-31",
                section="consolidated_p_and_l",
            ),
            make_fact(
                FactKind.FINANCIAL_PAT,
                12434,
                unit=FactUnit.CRORE_INR,
                period="2026-03-31",
                section="consolidated_p_and_l",
            ),
            make_fact(
                FactKind.RISK_FACTOR,
                "Currency volatility",
                unit=None,
                period=None,
                section="mda_risk",
            ),
        ],
    )
    result.evidence_id = evidence_id
    result.source_date = source_date
    return result


def _named_holder(name: str, category: str, *, char_offset: int) -> EntityMention:
    """One >1% public shareholder as shareholding_pattern emits it."""
    return EntityMention(
        entity=Entity(
            entity_id=f"organization:{name.lower().replace(' ', '-')}",
            kind="organization",
            canonical_name=name,
        ),
        role=category,
        provenance=Provenance(section="shareholding", char_offset=char_offset),
    )


def _corpus() -> list[AnalysisResult]:
    return [
        _financials(
            "ev-early",
            revenue=64988,
            source_date=datetime(2026, 4, 9, tzinfo=timezone.utc),
        ),
        _financials(
            "ev-late",
            revenue=64988,
            source_date=datetime(2026, 4, 20, tzinfo=timezone.utc),
        ),
    ]


@pytest.fixture
def seeded_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository whose assertion store holds the corpus, and whose analyzer
    path returns the same results without touching a document."""
    root = tmp_path / _COMPANY
    root.mkdir()
    results = _corpus()

    store = AssertionStore(root)
    for result in results:
        write_result(store, result, fingerprint=current_fingerprint().digest())

    def _from_analyzers(
        target: Path, *, source: object = None, on_error: object = None
    ) -> object:
        from atlas.company.store import LoadReport

        if source == "assertions":
            from atlas.assertions.reader import results_for

            return LoadReport(results=results_for(target), source="assertions")
        return LoadReport(results=results, source="analyzers", parsed=len(results))

    monkeypatch.setattr(
        "tests.support.equivalence.load_profile_results", _from_analyzers
    )
    return root


def _build_both(root: Path, tmp_path: Path) -> tuple[dict, dict]:
    from_analyzers = build_and_serialize(
        root, _COMPANY, source="analyzers", out=tmp_path / "analyzers.json"
    )
    from_assertions = build_and_serialize(
        root, _COMPANY, source="assertions", out=tmp_path / "assertions.json"
    )
    return from_analyzers, from_assertions


def test_the_fixture_is_not_vacuous(seeded_root: Path, tmp_path: Path) -> None:
    """Two empty profiles are identical, and prove nothing.

    Also pins the M-PRE lesson: at least one sources list must hold two
    entries, or the ordering the comparison is meant to catch never arises.
    """
    from_analyzers, _ = _build_both(seeded_root, tmp_path)

    snapshots = from_analyzers.get("financial", {}).get("snapshots", [])
    assert snapshots, "profile has no financial snapshots; the comparison is vacuous"
    assert any(
        len(snapshot.get("sources", [])) >= 2 for snapshot in snapshots
    ), "no snapshot draws on two documents; sources ordering is untested"


def test_profiles_are_byte_identical(seeded_root: Path, tmp_path: Path) -> None:
    from_analyzers, from_assertions = _build_both(seeded_root, tmp_path)

    assert_profiles_identical(
        from_analyzers,
        from_assertions,
        left_label="analyzer-sourced",
        right_label="assertion-sourced",
    )


def test_named_shareholders_survive_the_source_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The divergence the golden corpus found, reproduced without it.

    Four named holders in one section: the analyzer emits them in document
    order, the reader returns them ordered by content address. Green since
    #33 gave _finalize_profile a sort for the entity-derived containers; it
    was a strict xfail for exactly one milestone before that.
    """
    root = tmp_path / "SHP"
    root.mkdir()
    holders = [
        _named_holder("Sbi Nifty 50 Etf", "mutual_fund", char_offset=0),
        _named_holder("ICICI Prudential Value Fund", "mutual_fund", char_offset=100),
        _named_holder("LIC of India", "insurance", char_offset=200),
        _named_holder("Escrow Account", "other_non_institution", char_offset=300),
    ]
    result = make_result("shareholding_pattern", facts=[], entities=holders)
    result.evidence_id = "ev-shp"
    store = AssertionStore(root)
    write_result(store, result, fingerprint=current_fingerprint().digest())

    from atlas.assertions.reader import results_for
    from atlas.company.builder import build_profile

    from_analyzers = build_profile(_COMPANY, [result])
    from_assertions = build_profile(_COMPANY, results_for(root))

    assert [holder.canonical_name for holder in from_assertions.named_shareholders] == [
        holder.canonical_name for holder in from_analyzers.named_shareholders
    ]


def test_the_comparison_can_fail(seeded_root: Path, tmp_path: Path) -> None:
    """A comparison that cannot fail is not a gate.

    Two profiles for different companies must be reported as different, with
    the difference named rather than a bare False.
    """
    from_analyzers, _ = _build_both(seeded_root, tmp_path)
    altered = dict(from_analyzers)
    altered["company_id"] = "INFY"

    with pytest.raises(AssertionError, match="company_id"):
        assert_profiles_identical(
            from_analyzers, altered, left_label="left", right_label="right"
        )
