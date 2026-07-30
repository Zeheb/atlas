"""``rebuild --stale-only`` (#49), its scope (#50) and its row-count invariant (#77).

The flag exists because a bump to one analyzer used to cost a full
re-analysis of the repository. What has to be true for it to be worth having
is narrow and checkable:

Scope     -- exactly the documents this build cannot serve are re-analyzed.
             One too few serves rows nothing running produced; one too many
             is the full rebuild the flag replaces.
Rows      -- an untouched document's assertion rows are the same rows
             afterwards, not equal-looking replacements. #77, checked by
             counting and by comparing content addresses.
Profile   -- the result equals what a full rebuild would have produced. A
             cheaper answer that differs is not the same answer.

The scope is decided by ``stale_evidence_ids()``, which compares the per-kind
sub-digest, so the fixtures here bump one analyzer rather than inventing a
digest: an invented one could never have been produced by a build and cannot
exercise the comparison.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.assertions.store import AssertionStore
from atlas.assertions.writer import write_result
from atlas.company.store import LoadReport
from atlas.provenance import BuildFingerprint, current_fingerprint
from atlas.rebuild import PROFILE_FILENAME, rebuild
from tests.support.roundtrip import make_fact, make_result

_COMPANY = "TCS"

#: Two kinds, so a bump can reach one and leave the other alone. Both have
#: registered analyzers -- ``affects()`` raises otherwise.
_FRESH_KIND = "buyback"
_STALE_KIND = "financial_results"


def _result(evidence_id: str, kind: str, *, revenue: int = 64988) -> AnalysisResult:
    result = make_result(
        kind,
        facts=[
            make_fact(
                FactKind.FINANCIAL_REVENUE,
                revenue,
                unit=FactUnit.CRORE_INR,
                period="2026-03-31",
                section="consolidated_p_and_l",
            )
        ],
        entities=[],
    )
    result.evidence_id = evidence_id
    result.source_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
    return result


def _older_build() -> BuildFingerprint:
    """A build whose ``financial_results`` analyzer sat one version back.

    Only that kind's sub-digest moves, which is the case the flag is for: the
    whole digest moves too, so a whole-digest comparison would condemn the
    ``buyback`` document as well.
    """
    current = current_fingerprint()
    return dataclasses.replace(
        current,
        analyzer_versions={**current.analyzer_versions, _STALE_KIND: "0.9"},
    )


@pytest.fixture
def store(tmp_path: Path) -> AssertionStore:
    """A store holding one stale document and one the build can still serve."""
    store = AssertionStore(tmp_path)
    write_result(store, _result("ev-stale", _STALE_KIND), fingerprint=_older_build())
    write_result(
        store, _result("ev-fresh", _FRESH_KIND), fingerprint=current_fingerprint()
    )
    return store


@pytest.fixture
def analyzed(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Stand in for parse+analyze, recording which documents were asked for.

    What ``--stale-only`` must get right is which documents reach the
    analyzers at all, and that is invisible in the profile it produces.
    """
    asked: dict[str, list[str]] = {"only": []}
    available = {
        "ev-stale": _result("ev-stale", _STALE_KIND),
        "ev-fresh": _result("ev-fresh", _FRESH_KIND),
    }

    def _load(
        root: Path,
        *,
        source: object = None,
        on_error: object = None,
        only: object = None,
    ) -> LoadReport:
        if source == "assertions":
            from atlas.assertions.reader import results_for

            return LoadReport(results=results_for(root), source="assertions")
        wanted = sorted(available) if only is None else sorted(only)  # type: ignore[arg-type]
        asked["only"] = wanted
        results = [available[evidence_id] for evidence_id in wanted]
        return LoadReport(results=results, source="analyzers", parsed=len(results))

    monkeypatch.setattr("atlas.rebuild.load_results", _load)
    return asked


# --- scope (#50) -------------------------------------------------------------


def test_only_the_stale_document_is_re_analyzed(
    tmp_path: Path, store: AssertionStore, analyzed: dict[str, list[str]]
) -> None:
    """The whole point: one analyzer bump, one document re-read."""
    outcome = rebuild(tmp_path, _COMPANY, source="evidence", stale_only=True)

    assert analyzed["only"] == ["ev-stale"]
    assert outcome.reanalyzed == ("ev-stale",)


def test_the_profile_still_covers_every_document(
    tmp_path: Path, store: AssertionStore, analyzed: dict[str, list[str]]
) -> None:
    """Narrow re-analysis, whole corpus. The untouched half comes from rows."""
    outcome = rebuild(tmp_path, _COMPANY, source="evidence", stale_only=True)

    assert outcome.documents == 2


def test_a_clean_store_re_analyzes_nothing(
    tmp_path: Path, analyzed: dict[str, list[str]]
) -> None:
    """Zero is the answer the flag exists to give, and it still builds."""
    store = AssertionStore(tmp_path)
    write_result(
        store, _result("ev-fresh", _FRESH_KIND), fingerprint=current_fingerprint()
    )

    outcome = rebuild(tmp_path, _COMPANY, source="evidence", stale_only=True)

    assert outcome.reanalyzed == ()
    assert analyzed["only"] == []
    assert outcome.documents == 1


def test_stale_only_needs_from_evidence(tmp_path: Path, store: AssertionStore) -> None:
    """Reading the store again returns the same stale rows."""
    with pytest.raises(ValueError, match="needs --from evidence"):
        rebuild(tmp_path, _COMPANY, source="assertions", stale_only=True)


def test_the_store_is_current_afterwards(
    tmp_path: Path, store: AssertionStore, analyzed: dict[str, list[str]]
) -> None:
    """The state that makes the next ordinary rebuild work."""
    rebuild(tmp_path, _COMPANY, source="evidence", stale_only=True)

    assert store.stale_evidence_ids() == ()


# --- row-count invariant (#77) ----------------------------------------------


def _rows(store: AssertionStore, evidence_id: str) -> tuple[str, ...]:
    stored = store.read_run(evidence_id, "1.0")
    assert stored is not None
    return tuple(item.assertion_id for item in stored.assertions)


def test_an_untouched_document_keeps_its_exact_rows(
    tmp_path: Path, store: AssertionStore, analyzed: dict[str, list[str]]
) -> None:
    """#77. Not "the same number of rows" -- the same rows.

    Content addresses, so a re-analysis that produced identical-looking
    assertions with different provenance would fail this rather than pass it.
    """
    before = _rows(store, "ev-fresh")

    rebuild(tmp_path, _COMPANY, source="evidence", stale_only=True)

    assert _rows(store, "ev-fresh") == before


def test_the_store_gains_no_rows_for_untouched_documents(
    tmp_path: Path, store: AssertionStore, analyzed: dict[str, list[str]]
) -> None:
    """A second run of the same version must not accumulate rows."""
    before = store.stats()

    rebuild(tmp_path, _COMPANY, source="evidence", stale_only=True)

    after = store.stats()
    assert after.documents == before.documents
    assert after.runs == before.runs
    assert after.assertions == before.assertions


# --- equivalence with a full rebuild ----------------------------------------


def test_the_profile_equals_a_full_rebuilds(
    tmp_path: Path, store: AssertionStore, analyzed: dict[str, list[str]]
) -> None:
    """A cheaper answer that differs from the correct one is not the answer."""
    from atlas.company.store import load_profile_payload
    from atlas.rebuild import profiles_match

    rebuild(tmp_path, _COMPANY, source="evidence", stale_only=True)
    narrow = load_profile_payload(tmp_path / PROFILE_FILENAME)

    rebuild(tmp_path, _COMPANY, source="evidence")
    full = load_profile_payload(tmp_path / PROFILE_FILENAME)

    assert profiles_match(narrow, full)


# --- verify ------------------------------------------------------------------


def test_verify_writes_nothing_at_all(
    tmp_path: Path, store: AssertionStore, analyzed: dict[str, list[str]]
) -> None:
    """Neither the profile nor the assertion store, so the stale rows survive.

    A check that repairs what it is checking cannot be run twice and cannot be
    run on a repository someone is relying on.
    """
    before = store.stats()

    outcome = rebuild(
        tmp_path, _COMPANY, source="evidence", stale_only=True, verify=True
    )

    assert outcome.written_to is None
    assert not (tmp_path / PROFILE_FILENAME).exists()
    assert store.stale_evidence_ids() == ("ev-stale",)
    assert store.stats().assertions == before.assertions


def test_verify_still_reports_what_it_would_re_analyze(
    tmp_path: Path, store: AssertionStore, analyzed: dict[str, list[str]]
) -> None:
    outcome = rebuild(
        tmp_path, _COMPANY, source="evidence", stale_only=True, verify=True
    )

    assert outcome.reanalyzed == ("ev-stale",)
    assert outcome.documents == 2
