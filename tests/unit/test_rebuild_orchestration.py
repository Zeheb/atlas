"""Rebuild orchestration (#29): which stages run, and what gets written.

The module contains no extraction, assembly or serialisation logic of its own
-- every stage is tested where it lives. What is worth testing here is the
wiring, and one guarantee that is easy to get wrong: ``--verify`` must leave
the repository exactly as it found it. A check that can damage the thing it
checks does not get run on anything that matters.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.analysis.base import AnalysisResult, FactKind, FactUnit
from atlas.assertions.store import AssertionStore
from atlas.assertions.writer import write_result
from atlas.company.store import LoadReport, load_profile_payload
from atlas.provenance import current_fingerprint
from atlas.rebuild import PROFILE_FILENAME, rebuild
from tests.support.roundtrip import make_fact, make_result

_COMPANY = "TCS"


def _result(evidence_id: str = "ev-1", *, revenue: int = 64988) -> AnalysisResult:
    result = make_result(
        "financial_results",
        facts=[
            make_fact(
                FactKind.FINANCIAL_REVENUE,
                revenue,
                unit=FactUnit.CRORE_INR,
                period="2026-03-31",
                section="consolidated_p_and_l",
            )
        ],
    )
    result.evidence_id = evidence_id
    result.source_date = datetime(2026, 4, 9, tzinfo=timezone.utc)
    return result


@pytest.fixture
def analyzer_output(monkeypatch: pytest.MonkeyPatch) -> list[AnalysisResult]:
    """Stand in for parse+analyze; the orchestration is what is under test."""
    results = [_result()]

    def _load(root: Path, *, source: object = None, on_error: object = None):
        if source == "assertions":
            from atlas.assertions.reader import results_for

            return LoadReport(results=results_for(root), source="assertions")
        return LoadReport(
            results=list(results), source="analyzers", parsed=len(results)
        )

    monkeypatch.setattr("atlas.rebuild.load_results", _load)
    return results


# ---------------------------------------------------------------------------
# --from evidence
# ---------------------------------------------------------------------------


def test_rebuild_from_evidence_writes_a_profile(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    outcome = rebuild(tmp_path, _COMPANY, source="evidence")

    assert outcome.written_to == tmp_path / PROFILE_FILENAME
    assert outcome.written_to.exists()
    assert outcome.documents == 1


def test_rebuild_from_evidence_refreshes_the_assertion_store(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """Otherwise a later --from assertions rebuild reads the previous run."""
    rebuild(tmp_path, _COMPANY, source="evidence")

    stored = AssertionStore(tmp_path).evidence_ids()

    assert stored == ("ev-1",)


def test_a_first_build_reports_changed_as_none(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """Nothing to change from is not the same as nothing changed."""
    outcome = rebuild(tmp_path, _COMPANY, source="evidence")

    assert outcome.changed is None


def test_rebuilding_unchanged_inputs_reports_no_change(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """#34 in miniature: the same inputs must produce the same profile."""
    rebuild(tmp_path, _COMPANY, source="evidence")

    outcome = rebuild(tmp_path, _COMPANY, source="evidence")

    assert outcome.changed is False
    assert outcome.differences == ()


def test_changed_inputs_are_reported_with_the_difference(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    rebuild(tmp_path, _COMPANY, source="evidence")
    analyzer_output[:] = [_result(revenue=70000)]

    outcome = rebuild(tmp_path, _COMPANY, source="evidence")

    assert outcome.changed is True
    assert any("financial_revenue" in line for line in outcome.differences)


# ---------------------------------------------------------------------------
# --from assertions
# ---------------------------------------------------------------------------


def test_rebuild_from_assertions_uses_the_store(tmp_path: Path) -> None:
    """The fast path, and the reason the store exists: no document is read."""
    store = AssertionStore(tmp_path)
    write_result(store, _result(), fingerprint=current_fingerprint())

    outcome = rebuild(tmp_path, _COMPANY, source="assertions")

    assert outcome.source == "assertions"
    assert outcome.documents == 1
    assert not (tmp_path / "knowledge.db").exists()


def test_both_sources_produce_the_same_profile(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    rebuild(tmp_path, _COMPANY, source="evidence")

    outcome = rebuild(tmp_path, _COMPANY, source="assertions")

    assert outcome.changed is False


# ---------------------------------------------------------------------------
# --verify
# ---------------------------------------------------------------------------


def test_verify_writes_nothing_when_a_profile_exists(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """Asserted on mtime and bytes: a check that can damage what it checks
    will not be run on anything that matters."""
    rebuild(tmp_path, _COMPANY, source="evidence")
    path = tmp_path / PROFILE_FILENAME
    before_mtime = path.stat().st_mtime_ns
    before_bytes = path.read_bytes()

    outcome = rebuild(tmp_path, _COMPANY, source="evidence", verify=True)

    assert outcome.written_to is None
    assert path.stat().st_mtime_ns == before_mtime
    assert path.read_bytes() == before_bytes


def test_verify_creates_no_profile_when_none_exists(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    outcome = rebuild(tmp_path, _COMPANY, source="evidence", verify=True)

    assert outcome.written_to is None
    assert not (tmp_path / PROFILE_FILENAME).exists()
    assert outcome.changed is None


def test_verify_detects_a_difference_without_writing_it(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    rebuild(tmp_path, _COMPANY, source="evidence")
    stored_before = load_profile_payload(tmp_path / PROFILE_FILENAME)
    analyzer_output[:] = [_result(revenue=70000)]

    outcome = rebuild(tmp_path, _COMPANY, source="evidence", verify=True)

    assert outcome.changed is True
    assert load_profile_payload(tmp_path / PROFILE_FILENAME) == stored_before


def test_verify_compares_what_a_write_would_have_produced(
    tmp_path: Path, analyzer_output: list[AnalysisResult]
) -> None:
    """A verify that serialised differently from a save would pass on a
    difference the save then introduces."""
    rebuild(tmp_path, _COMPANY, source="evidence")

    verified = rebuild(tmp_path, _COMPANY, source="evidence", verify=True)
    written = rebuild(tmp_path, _COMPANY, source="evidence")

    assert verified.changed == written.changed is False
