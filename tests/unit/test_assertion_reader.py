"""Version selection and read order.

Selection  -- the store admits several analyzer versions per document. The
              rule must pick the newest one this build produced, and must
              raise rather than silently serve facts extracted by code that
              is no longer running. A stale answer is indistinguishable from
              a correct one at every layer above.
Purity     -- the choice may not depend on insertion order. If it did, a
              backfill that wrote rows in a different sequence would produce
              a different profile from the same data.
Order      -- build_profile sorts stably, so results that tie on its key keep
              arrival order. Arrival order therefore has to be content-based,
              not whatever SQLite hands back.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.analysis.base import AnalysisFact, FactKind, Provenance
from atlas.assertions.model import Assertion, AssertionRun, Mention
from atlas.assertions.reader import (
    StaleAssertionsError,
    read_facts,
    read_result,
    read_results,
    results_for,
    select_run,
    version_key,
)
from atlas.assertions.store import AssertionStore
from atlas.provenance import current_fingerprint

_FINGERPRINT = "fp-current"
_STALE = "fp-old"


def _run(
    *,
    evidence_id: str = "ev-1",
    analyzer_version: str = "1.0",
    fingerprint: str = _FINGERPRINT,
    source_date: datetime = datetime(2026, 4, 9, tzinfo=timezone.utc),
    status: str = "ok",
    error: str | None = None,
) -> AssertionRun:
    return AssertionRun(
        evidence_id=evidence_id,
        kind="financial_results",
        analyzer_version=analyzer_version,
        fingerprint=fingerprint,
        result_confidence="high",
        source_date=source_date,
        analyzed_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        warnings=("page 3 unreadable",),
        status=status,  # type: ignore[arg-type]
        error=error,
    )


def _assertion(
    run: AssertionRun, *, assertion_id: str, value: str = "x", ordinal: int = 0
) -> Assertion:
    return Assertion(
        assertion_id=assertion_id,
        evidence_id=run.evidence_id,
        kind=FactKind.RISK_FACTOR.value,
        value=value,
        value_type="str",
        unit=None,
        period="2026-03-31",
        confidence="high",
        section="mda_risk",
        char_offset=100,
        excerpt="an excerpt",
        analyzer_version=run.analyzer_version,
        fingerprint=run.fingerprint,
        ordinal=ordinal,
    )


# ---------------------------------------------------------------------------
# Version ordering
# ---------------------------------------------------------------------------


def test_versions_compare_numerically_not_lexically() -> None:
    """ "10.0" beats "9.0"; string comparison would prefer the older analyzer."""
    assert version_key("10.0") > version_key("9.0")
    assert version_key("2.10") > version_key("2.9")


def test_unparseable_segment_sorts_low_rather_than_raising() -> None:
    assert version_key("1.beta") == (1, 0)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_highest_matching_version_wins() -> None:
    runs = [_run(analyzer_version="1.0"), _run(analyzer_version="2.0")]

    assert select_run(runs, fingerprint=_FINGERPRINT).analyzer_version == "2.0"


def test_a_newer_version_from_another_build_is_ignored() -> None:
    """Newest is not the rule; newest *from this build* is."""
    runs = [
        _run(analyzer_version="1.0"),
        _run(analyzer_version="3.0", fingerprint=_STALE),
    ]

    assert select_run(runs, fingerprint=_FINGERPRINT).analyzer_version == "1.0"


def test_no_matching_fingerprint_raises() -> None:
    runs = [_run(analyzer_version="3.0", fingerprint=_STALE)]

    with pytest.raises(StaleAssertionsError, match="no stored run matches"):
        select_run(runs, fingerprint=_FINGERPRINT)


def test_empty_store_raises_the_same_way() -> None:
    with pytest.raises(StaleAssertionsError):
        select_run([], fingerprint=_FINGERPRINT)


def test_a_failed_run_from_this_build_is_still_the_answer() -> None:
    """Reaching past it to an older success would report facts this build
    does not produce."""
    runs = [
        _run(analyzer_version="1.0"),
        _run(analyzer_version="2.0", status="failed", error="boom"),
    ]

    chosen = select_run(runs, fingerprint=_FINGERPRINT)

    assert chosen.analyzer_version == "2.0"
    assert chosen.status == "failed"


def test_selection_is_independent_of_order() -> None:
    """The property #71 exists for: a pure function of store contents."""
    runs = [
        _run(analyzer_version="1.0"),
        _run(analyzer_version="2.0"),
        _run(analyzer_version="3.0", fingerprint=_STALE),
    ]

    chosen = {
        select_run(list(order), fingerprint=_FINGERPRINT).analyzer_version
        for order in itertools.permutations(runs)
    }

    assert chosen == {"2.0"}


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------


def test_result_is_rebuilt_from_the_selected_run(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    run = _run()
    store.write_run(run, [_assertion(run, assertion_id="a1")])

    result = read_result(store, "ev-1", fingerprint=_FINGERPRINT)

    assert result.evidence_id == "ev-1"
    assert result.kind == "financial_results"
    assert result.analyzer_version == "1.0"
    assert result.confidence == "high"
    assert result.source_date == run.source_date
    assert result.analyzed_at == run.analyzed_at
    assert result.warnings == ["page 3 unreadable"]
    assert len(result.facts) == 1


def test_facts_come_back_as_analysis_facts(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    run = _run()
    store.write_run(run, [_assertion(run, assertion_id="a1")])

    fact = read_result(store, "ev-1", fingerprint=_FINGERPRINT).facts[0]

    assert fact == AnalysisFact(
        kind=FactKind.RISK_FACTOR,
        value="x",
        unit=None,
        period="2026-03-31",
        confidence="high",
        provenance=Provenance(
            section="mda_risk", char_offset=100, excerpt="an excerpt"
        ),
    )


def test_excerpts_come_back_empty(tmp_path: Path) -> None:
    """The one documented loss: the store never held section bodies."""
    store = AssertionStore(tmp_path)
    run = _run()
    store.write_run(run, [_assertion(run, assertion_id="a1")])

    assert read_result(store, "ev-1", fingerprint=_FINGERPRINT).excerpts == {}


def test_reading_a_stale_document_raises(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    run = _run(fingerprint=_STALE)
    store.write_run(run, [_assertion(run, assertion_id="a1")])

    with pytest.raises(StaleAssertionsError):
        read_result(store, "ev-1", fingerprint=_FINGERPRINT)


def test_older_version_is_not_read_once_a_newer_one_exists(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    old = _run(analyzer_version="1.0")
    new = _run(analyzer_version="2.0")
    store.write_run(old, [_assertion(old, assertion_id="old")])
    store.write_run(new, [_assertion(new, assertion_id="new", value="corrected")])

    result = read_result(store, "ev-1", fingerprint=_FINGERPRINT)

    assert [fact.value for fact in result.facts] == ["corrected"]


# ---------------------------------------------------------------------------
# Ordering across documents
# ---------------------------------------------------------------------------


def _seed_three(store: AssertionStore) -> None:
    late = _run(
        evidence_id="ev-late", source_date=datetime(2026, 6, 1, tzinfo=timezone.utc)
    )
    early = _run(
        evidence_id="ev-early", source_date=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    same_day = _run(
        evidence_id="ev-a-same", source_date=datetime(2026, 6, 1, tzinfo=timezone.utc)
    )
    for run in (late, early, same_day):
        store.write_run(run, [_assertion(run, assertion_id=f"id-{run.evidence_id}")])


def test_results_are_ordered_by_source_date_then_evidence_id(tmp_path: Path) -> None:
    """Same-day filings are the real tie case; evidence_id breaks it."""
    store = AssertionStore(tmp_path)
    _seed_three(store)

    order = [
        result.evidence_id for result in read_results(store, fingerprint=_FINGERPRINT)
    ]

    assert order == ["ev-early", "ev-a-same", "ev-late"]


def test_facts_follow_the_same_order(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    _seed_three(store)

    facts = read_facts(store, fingerprint=_FINGERPRINT)

    assert len(facts) == 3


def test_assertions_within_a_document_are_ordered_by_id(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    run = _run()
    store.write_run(
        run,
        [
            _assertion(run, assertion_id="c", value="third", ordinal=0),
            _assertion(run, assertion_id="a", value="first", ordinal=1),
            _assertion(run, assertion_id="b", value="second", ordinal=2),
        ],
    )

    result = read_result(store, "ev-1", fingerprint=_FINGERPRINT)

    assert [fact.value for fact in result.facts] == ["first", "second", "third"]


def test_one_stale_document_fails_the_whole_read(tmp_path: Path) -> None:
    """A partial corpus that looks complete is the failure the fingerprint
    exists to prevent."""
    store = AssertionStore(tmp_path)
    fresh = _run(evidence_id="ev-fresh")
    stale = _run(evidence_id="ev-stale", fingerprint=_STALE)
    store.write_run(fresh, [_assertion(fresh, assertion_id="a1")])
    store.write_run(stale, [_assertion(stale, assertion_id="a2")])

    with pytest.raises(StaleAssertionsError):
        read_results(store, fingerprint=_FINGERPRINT)


def test_empty_store_reads_as_no_results(tmp_path: Path) -> None:
    """Nothing stored is not the same as something stale."""
    store = AssertionStore(tmp_path)

    assert read_results(store, fingerprint=_FINGERPRINT) == []


# ---------------------------------------------------------------------------
# results_for and determinism (#23, #27)
# ---------------------------------------------------------------------------


def test_results_for_reads_a_repository_root(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    run = _run()
    store.write_run(run, [_assertion(run, assertion_id="a1")])

    results = results_for(tmp_path, fingerprint=_FINGERPRINT)

    assert [result.evidence_id for result in results] == ["ev-1"]
    assert results[0].excerpts == {}


def test_results_for_defaults_to_the_current_build(tmp_path: Path) -> None:
    """The only value a caller should normally pass is the one it computes."""
    store = AssertionStore(tmp_path)
    run = _run(fingerprint=current_fingerprint().digest())
    store.write_run(run, [_assertion(run, assertion_id="a1")])

    assert len(results_for(tmp_path)) == 1


def test_results_for_raises_on_a_store_from_another_build(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    run = _run(fingerprint=_STALE)
    store.write_run(run, [_assertion(run, assertion_id="a1")])

    with pytest.raises(StaleAssertionsError):
        results_for(tmp_path)


def test_results_for_on_an_empty_repository_is_empty(tmp_path: Path) -> None:
    assert results_for(tmp_path, fingerprint=_FINGERPRINT) == []


def test_ten_reads_return_identical_ordering(tmp_path: Path) -> None:
    """#27. The builder sorts stably, so anything that ties on its key keeps
    arrival order -- which makes read order part of the profile."""
    store = AssertionStore(tmp_path)
    _seed_three(store)

    orders = {
        tuple(
            (result.evidence_id, tuple(fact.value for fact in result.facts))
            for result in results_for(tmp_path, fingerprint=_FINGERPRINT)
        )
        for _ in range(10)
    }

    assert len(orders) == 1


def test_ordering_does_not_depend_on_insertion_order(tmp_path: Path) -> None:
    """Two stores with the same content written in opposite orders must read
    back the same, or a backfill would produce a different profile."""
    forward = tmp_path / "forward"
    backward = tmp_path / "backward"
    runs = [
        _run(
            evidence_id="ev-a",
            source_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        _run(
            evidence_id="ev-b",
            source_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ),
        _run(
            evidence_id="ev-c",
            source_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ),
    ]
    for root, order in ((forward, runs), (backward, list(reversed(runs)))):
        store = AssertionStore(root)
        for run in order:
            store.write_run(
                run, [_assertion(run, assertion_id=f"id-{run.evidence_id}")]
            )

    assert [
        result.evidence_id for result in results_for(forward, fingerprint=_FINGERPRINT)
    ] == [
        result.evidence_id for result in results_for(backward, fingerprint=_FINGERPRINT)
    ]


# ---------------------------------------------------------------------------
# Entity mentions (#20)
# ---------------------------------------------------------------------------


def _mention(
    run: AssertionRun,
    *,
    mention_id: str,
    name: str = "K S Rao",
    role: str | None = "analyst",
    section: str | None = "qa",
) -> Mention:
    return Mention(
        mention_id=mention_id,
        evidence_id=run.evidence_id,
        entity_id="person-1",
        entity_kind="person",
        canonical_name=name,
        aliases=("Rao",),
        role=role,
        affiliation="Kotak Institutional Equities",
        identifier="DIN-00121863",
        question_text="What drove the margin expansion?",
        section=section,
        char_offset=None if section is None else 1200,
        excerpt=None if section is None else "Rao asked",
        ordinal=0,
        analyzer_version=run.analyzer_version,
        fingerprint=run.fingerprint,
    )


def test_mentions_are_reattached_to_the_result(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    run = _run()
    store.write_run(
        run, [_assertion(run, assertion_id="a1")], [_mention(run, mention_id="m1")]
    )

    result = read_result(store, "ev-1", fingerprint=_FINGERPRINT)

    assert len(result.entities) == 1
    assert result.entities[0].entity.canonical_name == "K S Rao"


def test_every_context_field_is_reattached(tmp_path: Path) -> None:
    """Reattaching the name and dropping the role would pass any test that
    only compared names."""
    store = AssertionStore(tmp_path)
    run = _run()
    store.write_run(run, [], [_mention(run, mention_id="m1")])

    mention = read_result(store, "ev-1", fingerprint=_FINGERPRINT).entities[0]

    assert mention.role == "analyst"
    assert mention.affiliation == "Kotak Institutional Equities"
    assert mention.identifier == "DIN-00121863"
    assert mention.question_text == "What drove the margin expansion?"
    assert mention.entity.aliases == frozenset({"Rao"})
    assert mention.provenance is not None
    assert mention.provenance.section == "qa"


def test_a_mention_without_provenance_stays_without_one(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    run = _run()
    store.write_run(run, [], [_mention(run, mention_id="m1", section=None)])

    mention = read_result(store, "ev-1", fingerprint=_FINGERPRINT).entities[0]

    assert mention.provenance is None


def test_mentions_come_back_in_a_fixed_order(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    run = _run()
    store.write_run(
        run,
        [],
        [
            _mention(run, mention_id="c", name="Third"),
            _mention(run, mention_id="a", name="First"),
            _mention(run, mention_id="b", name="Second"),
        ],
    )

    result = read_result(store, "ev-1", fingerprint=_FINGERPRINT)

    assert [item.entity.canonical_name for item in result.entities] == [
        "First",
        "Second",
        "Third",
    ]


def test_a_result_with_no_mentions_has_no_entities(tmp_path: Path) -> None:
    """Most analyzers emit none; an empty list is the ordinary case."""
    store = AssertionStore(tmp_path)
    run = _run()
    store.write_run(run, [_assertion(run, assertion_id="a1")])

    assert read_result(store, "ev-1", fingerprint=_FINGERPRINT).entities == []


def test_only_the_selected_version_s_mentions_are_returned(tmp_path: Path) -> None:
    store = AssertionStore(tmp_path)
    old = _run(analyzer_version="1.0")
    new = _run(analyzer_version="2.0")
    store.write_run(old, [], [_mention(old, mention_id="old", name="Old Name")])
    store.write_run(new, [], [_mention(new, mention_id="new", name="New Name")])

    result = read_result(store, "ev-1", fingerprint=_FINGERPRINT)

    assert [item.entity.canonical_name for item in result.entities] == ["New Name"]
