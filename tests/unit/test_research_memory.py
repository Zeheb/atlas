"""ThesisStore (M2.4 commit 3).

Persistence only -- these tests never construct a StalenessReport or import
staleness.py, which is the whole point of the module split. The load-bearing
tests are the round-trip ones: save then load must reproduce every field
Thesis.to_view() and the completeness gate actually read, even though the
underlying Claim graph is deliberately reconstructed rather than preserved
byte-for-byte (see the module docstring for why).
"""
from __future__ import annotations

import json

import pytest

from atlas.reasoning.contracts import Claim, EvidenceReference, SubjectRef
from atlas.research.investigate import InvestigationResult, InvestigationRun
from atlas.research.citations import Finding
from atlas.research.memory import (
    IncompatibleStoreVersionError,
    STORE_VERSION,
    ThesisNotFoundError,
    ThesisStore,
)
from atlas.research.plan import Investigation, ResearchPlan
from atlas.research.thesis import synthesize

SUBJECT = SubjectRef(subject_id="TCS", display="TCS")


def _investigation(dimension: str) -> Investigation:
    return Investigation(
        dimension=dimension,
        question=f"What does {dimension} show?",
        subjects=("TCS",),
        rationale="it is one of the dimensions a view must rest on",
        priority=5,
    )


def _semantic(statement: str, eid: str):
    from atlas.reasoning.contracts import Finding as SemanticFinding

    return SemanticFinding(
        statement=statement, assertability="judgment", confidence="high",
        supporting_claims=(Claim(
            subject_ref=SUBJECT, statement=statement, assertability="fact",
            confidence="high", evidence=[EvidenceReference(evidence_id=eid)],
        ),),
        known_unknowns=("no segment-level detail",),
    )


def _resolved(dimension: str, eid: str = "ev-1") -> InvestigationResult:
    return InvestigationResult(
        investigation=_investigation(dimension),
        finding=Finding(text=f"{dimension} looks fine.", evidence_ids=[eid]),
        semantic_findings=(_semantic(f"{dimension} looks fine.", eid),),
    )


def _run(*results: InvestigationResult) -> InvestigationRun:
    used = results or (_resolved("business_quality"),)
    return InvestigationRun(
        plan=ResearchPlan(
            raw_question="Should I invest in TCS?", intent="invest_decision",
            subjects=("TCS",),
            investigations=tuple(_investigation(r.dimension) for r in used),
        ),
        results=used,
    )


class _Fake:
    def __init__(self, cite: list[str] | None = None) -> None:
        self._cite = cite if cite is not None else ["ev-1"]

    def complete(self, *, system: str, user: str) -> str:
        return json.dumps({
            "refused": False, "overall_confidence": "medium",
            "findings": [{
                "statement": "Durable business, fairly priced.",
                "assertability": "judgment", "confidence": "medium",
                "supporting_evidence_ids": self._cite,
                "known_unknowns": ["no segment-level detail"],
            }],
        })


def _thesis(*results: InvestigationResult):
    run = _run(*results)
    return synthesize(run, _Fake(cite=list({r.finding.evidence_ids[0] for r in (results or (_resolved("business_quality"),))})))


# --- Round trip: everything to_view() and the gate actually read --------------------
def test_round_trip_preserves_view_id(tmp_path) -> None:
    thesis = _thesis()
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)

    assert store.load(thesis.view_id).view_id == thesis.view_id


def test_round_trip_preserves_question_and_as_of(tmp_path) -> None:
    thesis = _thesis()
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)
    loaded = store.load(thesis.view_id)

    assert loaded.question == thesis.question
    assert loaded.as_of == thesis.as_of
    assert loaded.run_fingerprint == thesis.run_fingerprint


def test_round_trip_preserves_finding_statement_and_confidence(tmp_path) -> None:
    thesis = _thesis()
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)
    loaded = store.load(thesis.view_id)

    original = thesis.result.findings[0]
    reloaded = loaded.result.findings[0]
    assert reloaded.statement == original.statement
    assert reloaded.confidence == original.confidence
    assert reloaded.assertability == original.assertability


def test_round_trip_preserves_evidence_ids(tmp_path) -> None:
    """The field to_view() actually reads -- must survive exactly."""
    thesis = _thesis()
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)
    loaded = store.load(thesis.view_id)

    assert loaded.result.findings[0].evidence_ids == thesis.result.findings[0].evidence_ids


def test_round_trip_preserves_known_unknowns(tmp_path) -> None:
    thesis = _thesis()
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)
    loaded = store.load(thesis.view_id)

    assert loaded.result.findings[0].known_unknowns == thesis.result.findings[0].known_unknowns


def test_round_trip_preserves_citations(tmp_path) -> None:
    thesis = _thesis()
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)

    assert store.load(thesis.view_id).citations == thesis.citations


def test_round_trip_preserves_dispositions(tmp_path) -> None:
    thesis = _thesis(_resolved("business_quality", "ev-1"), _resolved("risks", "ev-2"))
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)
    loaded = store.load(thesis.view_id)

    assert loaded.incorporated_dimensions == thesis.incorporated_dimensions


def test_round_trip_preserves_unresolved_dimensions(tmp_path) -> None:
    run = InvestigationRun(
        plan=ResearchPlan(
            raw_question="Should I invest in TCS?", intent="invest_decision",
            subjects=("TCS",),
            investigations=(_investigation("business_quality"), _investigation("valuation")),
        ),
        results=(
            _resolved("business_quality", "ev-1"),
            InvestigationResult(
                investigation=_investigation("valuation"),
                unresolved_reason="refused: no evidence",
            ),
        ),
    )
    thesis = synthesize(run, _Fake())
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)
    loaded = store.load(thesis.view_id)

    assert loaded.unresolved_dimensions == ("valuation",)


def test_reloaded_thesis_produces_an_equivalent_view(tmp_path) -> None:
    """The whole point: to_view() on the reloaded thesis must match the
    original's, since that projection is all downstream reasoning ever
    reads."""
    thesis = _thesis()
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)
    loaded = store.load(thesis.view_id)

    original_view = thesis.to_view()
    reloaded_view = loaded.to_view()
    assert reloaded_view.view_id == original_view.view_id
    assert reloaded_view.claims[0].statement == original_view.claims[0].statement
    assert reloaded_view.claims[0].evidence_ids == original_view.claims[0].evidence_ids
    assert reloaded_view.claims[0].confidence == original_view.claims[0].confidence


def test_reloaded_thesis_still_satisfies_thesis_invariants(tmp_path) -> None:
    """Round-tripping must not produce a Thesis that violates its own
    __post_init__ -- construction itself is the assertion."""
    thesis = _thesis()
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)
    store.load(thesis.view_id)  # must not raise


# --- Idempotency (CompanyStore.merge's convention) -----------------------------------
def test_saving_the_same_view_id_twice_does_not_duplicate(tmp_path) -> None:
    thesis = _thesis()
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)
    store.save(thesis)

    assert len(store.list()) == 1


def test_saving_distinct_theses_keeps_both(tmp_path) -> None:
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    t1 = _thesis(_resolved("business_quality", "ev-1"))
    t2 = _thesis(_resolved("business_quality", "ev-2"))
    store.save(t1)
    store.save(t2)

    assert len(store.list()) == 2
    assert {t.view_id for t in store.list()} == {t1.view_id, t2.view_id}


# --- list() / exists() ---------------------------------------------------------------
def test_list_is_empty_when_store_does_not_exist(tmp_path) -> None:
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    assert store.list() == ()
    assert not store.exists()


def test_exists_is_true_after_save(tmp_path) -> None:
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(_thesis())
    assert store.exists()


def test_list_returns_oldest_first(tmp_path) -> None:
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    t1 = _thesis(_resolved("business_quality", "ev-1"))
    t2 = _thesis(_resolved("business_quality", "ev-2"))
    store.save(t1)
    store.save(t2)

    listed = store.list()
    assert listed[0].view_id == t1.view_id
    assert listed[1].view_id == t2.view_id


# --- Errors ----------------------------------------------------------------------------
def test_load_missing_view_id_raises(tmp_path) -> None:
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(_thesis())
    with pytest.raises(ThesisNotFoundError):
        store.load("does-not-exist")


def test_load_from_nonexistent_store_raises(tmp_path) -> None:
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    with pytest.raises(ThesisNotFoundError):
        store.load("anything")


def test_save_rejects_a_thesis_for_a_different_subject(tmp_path) -> None:
    thesis = _thesis()  # subject TCS
    store = ThesisStore(tmp_path / "theses.json", "SBIN")
    with pytest.raises(ValueError, match="does not match store subject"):
        store.save(thesis)


def test_incompatible_store_version_raises(tmp_path) -> None:
    path = tmp_path / "theses.json"
    path.write_text(json.dumps({"store_version": "999", "subject": "TCS", "theses": []}))
    store = ThesisStore(path, "TCS")
    with pytest.raises(IncompatibleStoreVersionError):
        store.list()


# --- The file itself ------------------------------------------------------------------
def test_stored_file_is_json_with_store_version(tmp_path) -> None:
    path = tmp_path / "theses.json"
    store = ThesisStore(path, "TCS")
    store.save(_thesis())

    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["store_version"] == STORE_VERSION
    assert envelope["subject"] == "TCS"
    assert len(envelope["theses"]) == 1


def test_no_thesis_result_is_ever_refused(tmp_path) -> None:
    """Thesis.__post_init__ already forbids constructing a refused result;
    the store's own reconstruction must not accidentally set refused=True."""
    thesis = _thesis()
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(thesis)
    assert store.load(thesis.view_id).result.refused is False
