"""AnalysisResult to rows: identity, fidelity, and the failure path.

What these tests are actually guarding:

Ordinals   -- the only thing separating facts that agree on every hashed
              component. Two identical risk strings from one loop must not
              collapse into one row.
Fidelity   -- int, float, str and None must come back as themselves. The
              store column is text, so a lost value_type turns 5 into "5"
              everywhere downstream with nothing to signal it.
Failure    -- a run that raised must be recorded, not dropped. Dropped, the
              document stays indistinguishable from one never analyzed and
              is retried forever.
"""

from __future__ import annotations

import dataclasses
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
from atlas.assertions.store import AssertionStore
from atlas.assertions.writer import (
    analyze_and_write,
    failure_run,
    result_to_mentions,
    result_to_rows,
    write_result,
)
from atlas.knowledge.base import KnowledgeBase, ParsedDocument
from atlas.provenance import current_fingerprint
from tests.support.roundtrip import default_entities, foreign_fingerprint

_EVIDENCE = "bse-news-e1"
_KIND = "financial_results"
# The writer takes a BuildFingerprint, not a digest: a run's whole digest
# and its per-kind sub-digest must come from one build.
_FINGERPRINT = current_fingerprint()
_SOURCE_DATE = "2026-04-09T00:00:00+00:00"


def _fact(
    kind: FactKind = FactKind.RISK_FACTOR,
    value: str | int | float | None = "Cyber security risk",
    unit: FactUnit | None = None,
    section: str = "mda_risk",
    char_offset: int | None = 100,
) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period="2026-03-31",
        confidence="high",
        provenance=Provenance(
            section=section, char_offset=char_offset, excerpt="an excerpt"
        ),
    )


def _result(
    facts: list[AnalysisFact] | None = None,
    *,
    analyzer_version: str = "1.0",
    warnings: list[str] | None = None,
) -> AnalysisResult:
    return AnalysisResult(
        evidence_id=_EVIDENCE,
        kind=_KIND,
        analyzer_version=analyzer_version,
        confidence="high",
        source_date=datetime(2026, 4, 9, tzinfo=timezone.utc),
        analyzed_at=datetime(2026, 7, 29, 10, 30, tzinfo=timezone.utc),
        warnings=warnings if warnings is not None else [],
        facts=facts if facts is not None else [_fact()],
    )


def _seed_document(kb: KnowledgeBase, kind: str = _KIND) -> ParsedDocument:
    document = ParsedDocument(
        evidence_id=_EVIDENCE,
        kind=kind,
        title="Test Filing",
        source_date=_SOURCE_DATE,
        local_path=f"other/{_EVIDENCE}.pdf",
        parsed_at=datetime.now(timezone.utc),
        parser_version="test",
        status="ok",
        char_count=10,
    )
    kb._upsert(document, "some extracted text")
    return document


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def test_envelope_becomes_the_run_row() -> None:
    result = _result(warnings=["page 3 unreadable"])

    run, _ = result_to_rows(result, fingerprint=_FINGERPRINT)

    assert run.evidence_id == _EVIDENCE
    assert run.kind == _KIND
    assert run.analyzer_version == "1.0"
    assert run.fingerprint == _FINGERPRINT.digest()
    assert run.result_confidence == "high"
    assert run.source_date == result.source_date
    assert run.analyzed_at == result.analyzed_at
    assert run.warnings == ("page 3 unreadable",)
    assert run.status == "ok"
    assert run.error is None


def test_mapping_is_deterministic() -> None:
    """Same result, same fingerprint, same ids -- in any process."""
    result = _result([_fact(), _fact(value="Supply chain risk")])

    first, _ = result_to_rows(result, fingerprint=_FINGERPRINT)
    second_run, second = result_to_rows(result, fingerprint=_FINGERPRINT)
    _, again = result_to_rows(result, fingerprint=_FINGERPRINT)

    assert first == second_run
    assert [item.assertion_id for item in second] == [
        item.assertion_id for item in again
    ]


def test_identical_facts_get_distinct_ids_by_ordinal() -> None:
    """The annual_report risk loop: same section, same offset, same value."""
    result = _result([_fact(), _fact()])

    _, assertions = result_to_rows(result, fingerprint=_FINGERPRINT)

    assert [item.ordinal for item in assertions] == [0, 1]
    assert len({item.assertion_id for item in assertions}) == 2


def test_ordinals_are_scoped_to_kind_and_section() -> None:
    """A fact in another section must not shift a later fact's ordinal."""
    result = _result(
        [
            _fact(section="mda_risk"),
            _fact(kind=FactKind.FINANCIAL_REVENUE, value=100, section="financials"),
            _fact(section="mda_risk"),
        ]
    )

    _, assertions = result_to_rows(result, fingerprint=_FINGERPRINT)

    assert [item.ordinal for item in assertions] == [0, 0, 1]


def test_no_facts_yields_a_run_and_no_assertions() -> None:
    run, assertions = result_to_rows(_result([]), fingerprint=_FINGERPRINT)

    assert run.status == "ok"
    assert assertions == ()


# ---------------------------------------------------------------------------
# Fidelity through the store
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["five", 5, 5.0, 0.1 + 0.2, -0.0, None],
    ids=["str", "int", "float", "inexact-float", "negative-zero", "none"],
)
def test_value_survives_the_round_trip(
    tmp_path: Path, value: str | int | float | None
) -> None:
    store = AssertionStore(tmp_path)
    result = _result(
        [_fact(kind=FactKind.FINANCIAL_REVENUE, value=value, unit=FactUnit.CRORE_INR)]
    )

    write_result(store, result, fingerprint=_FINGERPRINT)

    stored = store.read_run(_EVIDENCE, "1.0")
    assert stored is not None
    restored = stored.assertions[0].to_fact()
    assert restored.value == value
    assert type(restored.value) is type(value)


def test_written_rows_read_back_unchanged(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    result = _result([_fact(), _fact(value="Supply chain risk")])
    run, assertions = result_to_rows(result, fingerprint=_FINGERPRINT)

    write_result(store, result, fingerprint=_FINGERPRINT)

    stored = store.read_run(_EVIDENCE, "1.0")
    assert stored is not None
    assert stored.run == run
    assert set(stored.assertions) == set(assertions)


def test_bumped_analyzer_version_yields_new_ids_and_keeps_the_old(
    tmp_path: Path,
) -> None:
    store = AssertionStore(tmp_path)
    write_result(store, _result(), fingerprint=_FINGERPRINT)

    write_result(store, _result(analyzer_version="2.0"), fingerprint=_FINGERPRINT)

    first = store.read_run(_EVIDENCE, "1.0")
    second = store.read_run(_EVIDENCE, "2.0")
    assert first is not None and second is not None
    assert first.assertions[0].assertion_id != second.assertions[0].assertion_id


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


def test_failure_run_records_the_error_and_no_facts(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path)
    document = _seed_document(kb)
    store = AssertionStore(tmp_path)

    run = failure_run(
        document,
        analyzer_version="1.0",
        fingerprint=_FINGERPRINT,
        error="ValueError: no tables found",
    )
    store.write_run(run, ())

    stored = store.read_run(_EVIDENCE, "1.0")
    assert stored is not None
    assert stored.run.status == "failed"
    assert stored.run.error == "ValueError: no tables found"
    assert stored.run.result_confidence == "low"
    assert stored.assertions == ()


def test_analyzer_exception_is_recorded_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = KnowledgeBase(tmp_path)
    _seed_document(kb)
    store = AssertionStore(tmp_path)

    def _explode(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
        raise RuntimeError("table parser gave up")

    monkeypatch.setattr("atlas.assertions.writer.analyze", _explode)

    run = analyze_and_write(_EVIDENCE, kb, store, fingerprint=_FINGERPRINT)

    assert run.status == "failed"
    assert run.error == "RuntimeError: table parser gave up"
    stored = store.read_run(_EVIDENCE, run.analyzer_version)
    assert stored is not None
    assert stored.assertions == ()


def test_failure_after_success_leaves_no_stale_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rerun that fails must not leave the previous run's facts looking current."""
    kb = KnowledgeBase(tmp_path)
    _seed_document(kb)
    store = AssertionStore(tmp_path)
    good = _result(analyzer_version="1.0")

    def _succeed(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
        return good

    monkeypatch.setattr("atlas.assertions.writer.analyze", _succeed)
    monkeypatch.setattr(
        "atlas.assertions.writer.analyzer_versions", lambda: {_KIND: "1.0"}
    )
    analyze_and_write(_EVIDENCE, kb, store, fingerprint=_FINGERPRINT)

    def _explode(evidence_id: str, kb: KnowledgeBase) -> AnalysisResult:
        raise RuntimeError("regression")

    monkeypatch.setattr("atlas.assertions.writer.analyze", _explode)
    analyze_and_write(_EVIDENCE, kb, store, fingerprint=_FINGERPRINT)

    stored = store.read_run(_EVIDENCE, "1.0")
    assert stored is not None
    assert stored.run.status == "failed"
    assert stored.assertions == ()


def test_successful_analysis_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = KnowledgeBase(tmp_path)
    _seed_document(kb)
    store = AssertionStore(tmp_path)

    monkeypatch.setattr(
        "atlas.assertions.writer.analyze",
        lambda evidence_id, kb: _result(),
    )

    run = analyze_and_write(_EVIDENCE, kb, store, fingerprint=_FINGERPRINT)

    assert run.status == "ok"
    stored = store.read_run(_EVIDENCE, "1.0")
    assert stored is not None
    assert len(stored.assertions) == 1


def test_unknown_evidence_raises(tmp_path: Path) -> None:
    """No document, no kind, no analyzer version -- nothing to key a row on."""
    kb = KnowledgeBase(tmp_path)
    store = AssertionStore(tmp_path)

    with pytest.raises(ValueError, match="not in knowledge base"):
        analyze_and_write("missing", kb, store, fingerprint=_FINGERPRINT)


def test_unregistered_kind_raises(tmp_path: Path) -> None:
    kb = KnowledgeBase(tmp_path)
    _seed_document(kb, kind="press_clipping")
    store = AssertionStore(tmp_path)

    with pytest.raises(ValueError, match="no analyzer registered"):
        analyze_and_write(_EVIDENCE, kb, store, fingerprint=_FINGERPRINT)


# ---------------------------------------------------------------------------
# One fingerprint object, two stamped values (#47 / migration 3)
# ---------------------------------------------------------------------------
#
# The writer takes a BuildFingerprint rather than a digest string so that the
# whole digest and the per-kind sub-digest cannot come from different builds.
# Nothing downstream could detect that: both columns would hold perfectly
# well-formed hashes, and the row would read as current under one comparison
# and stale under the other. The tests below are about that pairing, not about
# either value on its own.


def test_the_run_carries_both_digests() -> None:
    result = _result()

    run, _ = result_to_rows(result, fingerprint=_FINGERPRINT)

    assert run.fingerprint == _FINGERPRINT.digest()
    assert run.affects_digest == _FINGERPRINT.affects(_KIND)


def test_the_two_digests_are_different_values() -> None:
    """A sub-digest equal to the whole digest would narrow nothing."""
    run, _ = result_to_rows(_result(), fingerprint=_FINGERPRINT)

    assert run.affects_digest != run.fingerprint


def test_both_digests_come_from_the_same_build() -> None:
    """The invariant. Written against a foreign fingerprint, BOTH values move.

    If the writer took two strings, a caller could pair this build's whole
    digest with another build's sub-digest and no layer would object.
    """
    foreign = foreign_fingerprint()

    mine, _ = result_to_rows(_result(), fingerprint=_FINGERPRINT)
    theirs, _ = result_to_rows(_result(), fingerprint=foreign)

    assert theirs.fingerprint != mine.fingerprint
    assert theirs.affects_digest != mine.affects_digest
    assert theirs.fingerprint == foreign.digest()
    assert theirs.affects_digest == foreign.affects(_KIND)


def test_bumping_one_analyzer_moves_only_the_affected_kind() -> None:
    """What the sub-digest is for: selectivity the whole digest cannot express."""
    other_kind = "buyback"
    bumped = dataclasses.replace(
        _FINGERPRINT,
        analyzer_versions={**_FINGERPRINT.analyzer_versions, _KIND: "99.0"},
    )

    assert bumped.digest() != _FINGERPRINT.digest()
    assert bumped.affects(_KIND) != _FINGERPRINT.affects(_KIND)
    assert bumped.affects(other_kind) == _FINGERPRINT.affects(other_kind)


def test_the_sub_digest_reaches_the_database(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)

    write_result(store, _result(), fingerprint=_FINGERPRINT)

    stored = store.runs_for(_EVIDENCE)[0]
    assert stored.fingerprint == _FINGERPRINT.digest()
    assert stored.affects_digest == _FINGERPRINT.affects(_KIND)


def test_assertions_carry_the_whole_digest_only() -> None:
    """Their table has no sub-digest column: invalidation is per run."""
    _, assertions = result_to_rows(_result(), fingerprint=_FINGERPRINT)

    assert assertions
    assert all(item.fingerprint == _FINGERPRINT.digest() for item in assertions)


def test_mentions_carry_the_whole_digest_only() -> None:
    result = _result()
    result.entities = list(default_entities())

    mentions = result_to_mentions(result, fingerprint=_FINGERPRINT)

    assert mentions
    assert all(item.fingerprint == _FINGERPRINT.digest() for item in mentions)


def test_a_failure_run_is_also_stamped_with_both(tmp_path: Path) -> None:
    """Otherwise re-analysis after fixing an analyzer looks like work done."""
    kb = KnowledgeBase(tmp_path)
    document = _seed_document(kb)

    run = failure_run(
        document,
        analyzer_version="1.0",
        fingerprint=_FINGERPRINT,
        error="ValueError: boom",
    )

    assert run.status == "failed"
    assert run.fingerprint == _FINGERPRINT.digest()
    assert run.affects_digest == _FINGERPRINT.affects(document.kind)


def test_an_unregistered_kind_raises_rather_than_storing_null() -> None:
    """A NULL sub-digest marks the row permanently stale, silently."""
    result = _result()
    result.kind = "press_clipping"

    with pytest.raises(ValueError, match="no registered analyzer"):
        result_to_rows(result, fingerprint=_FINGERPRINT)
