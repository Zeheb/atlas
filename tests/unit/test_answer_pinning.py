"""Pinning fields on the answer envelope (#42), and reading pre-pinning theses (#45).

The milestone is additive or it is wrong. So the tests here are as much
about what did NOT change -- every existing construction site still works
unannotated, every grounding invariant still fires -- as about the new
fields themselves.

The one distinction worth protecting is ``consulted_*`` versus
``citations``. Citations are what the findings rest on; consulted ids are
what was read, including documents that contributed nothing. Collapsing
them would attribute claims to documents that never supported them, and the
grounding chain would still validate, so nothing else would catch it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.reasoning.ask import ask
from atlas.reasoning.contracts import (
    Claim,
    EvidenceReference,
    Finding,
    GroundingContext,
    Question,
    ReasoningResult,
    SubjectRef,
)
from atlas.reasoning.llm import FakeLLMClient
from atlas.research.memory import ThesisStore
from atlas.research.thesis import Thesis

_SUBJECT = SubjectRef(subject_id="TCS", display="Tata Consultancy Services")


def _result(**overrides: object) -> ReasoningResult:
    claim = Claim(
        subject_ref=_SUBJECT,
        statement="Revenue grew.",
        assertability="fact",
        confidence="high",
        evidence=(EvidenceReference(evidence_id="ev-1"),),
    )
    kwargs: dict[str, object] = {
        "question": Question(raw_text="Did revenue grow?", subject_ref=_SUBJECT),
        "findings": (
            Finding(
                statement="Revenue grew.",
                assertability="fact",
                confidence="high",
                supporting_claims=(claim,),
            ),
        ),
        "overall_confidence": "high",
        "citations": frozenset({"ev-1"}),
    }
    kwargs.update(overrides)
    return ReasoningResult(**kwargs)  # type: ignore[arg-type]


# --- additive ----------------------------------------------------------------


def test_the_new_fields_default_to_unpinned() -> None:
    result = _result()
    assert result.fingerprint is None
    assert result.consulted_assertion_ids == ()
    assert result.consulted_evidence_ids == ()
    assert result.profile_built_at is None


def test_an_existing_construction_site_still_works_unchanged() -> None:
    """Every caller predates these fields and none of them passes one."""
    assert _result().overall_confidence == "high"


def test_the_grounding_invariant_still_fires() -> None:
    """G1: citations must cover what the findings rest on. Unchanged by M6."""
    with pytest.raises(ValueError, match="missing ids its findings rest on"):
        _result(citations=frozenset())


def test_the_refusal_invariant_still_fires() -> None:
    """G8, likewise unchanged."""
    with pytest.raises(ValueError, match="must have no findings"):
        _result(refused=True, refusal_reason="out of scope")


# --- the pinning fields ------------------------------------------------------


def test_pinning_fields_are_recorded_as_given() -> None:
    result = _result(
        fingerprint="digest-abc",
        consulted_assertion_ids=("a1", "a2"),
        consulted_evidence_ids=("ev-1",),
        profile_built_at="2026-07-14T10:00:00+00:00",
    )
    assert result.fingerprint == "digest-abc"
    assert result.consulted_assertion_ids == ("a1", "a2")
    assert result.consulted_evidence_ids == ("ev-1",)
    assert result.profile_built_at == "2026-07-14T10:00:00+00:00"


def test_consulted_ids_are_sorted_and_deduplicated() -> None:
    """Two runs that consulted the same set must compare equal."""
    result = _result(
        consulted_assertion_ids=["a2", "a1", "a2"],
        consulted_evidence_ids=["ev-2", "ev-1", "ev-1"],
    )
    assert result.consulted_assertion_ids == ("a1", "a2")
    assert result.consulted_evidence_ids == ("ev-1", "ev-2")


def test_consulted_evidence_may_exceed_citations() -> None:
    """A document that was read and contributed nothing is not a citation."""
    result = _result(consulted_evidence_ids=("ev-1", "ev-2", "ev-3"))
    assert result.citations == frozenset({"ev-1"})
    assert set(result.consulted_evidence_ids) > set(result.citations)


def test_consulted_ids_do_not_widen_citations() -> None:
    """Otherwise the grounding check would pass on ungrounded claims."""
    result = _result(consulted_evidence_ids=("ev-9",))
    assert "ev-9" not in result.citations


# --- #43a population in ask() ------------------------------------------------


def _context(*, evidence_index: frozenset[str] | None = None) -> GroundingContext:
    claim = Claim(
        subject_ref=_SUBJECT,
        statement="operating margin = 24.2 (annual, period 2026-03-31)",
        assertability="fact",
        confidence="high",
        evidence=[EvidenceReference(evidence_id="ev-1")],
    )
    return GroundingContext(
        subject_ref=_SUBJECT,
        claims=[claim],
        evidence_index=evidence_index or frozenset({"ev-1"}),
    )


def _answer_payload() -> dict[str, object]:
    return {
        "refused": False,
        "overall_confidence": "high",
        "findings": [
            {
                "statement": "Margins held at 24.2%.",
                "assertability": "fact",
                "confidence": "high",
                "supporting_evidence_ids": ["ev-1"],
            }
        ],
    }


def _ask(payload: dict[str, object], context: GroundingContext) -> ReasoningResult:
    return ask(
        Question(raw_text="How have margins been?", subject_ref=_SUBJECT),
        context,
        FakeLLMClient(response=json.dumps(payload)),
    )


def test_an_answer_carries_the_current_build_fingerprint() -> None:
    from atlas.provenance import current_fingerprint

    result = _ask(_answer_payload(), _context())

    assert result.fingerprint == current_fingerprint().digest()


def test_an_answer_records_the_whole_consulted_closed_world() -> None:
    """Including the document that contributed nothing to any finding."""
    context = _context(evidence_index=frozenset({"ev-1", "ev-2"}))

    result = _ask(_answer_payload(), context)

    assert result.consulted_evidence_ids == ("ev-1", "ev-2")
    assert result.citations == frozenset({"ev-1"})


def test_two_identical_questions_pin_the_same_fingerprint() -> None:
    """An unchanged store must not produce a moving digest."""
    first = _ask(_answer_payload(), _context())
    second = _ask(_answer_payload(), _context())

    assert first.fingerprint == second.fingerprint


def test_a_refusal_is_pinned_too() -> None:
    """Otherwise 'why did Atlas refuse this' has no build to point at."""
    context = _context(evidence_index=frozenset({"ev-1", "ev-2"}))

    result = _ask({"refused": True, "refusal_reason": "out of scope"}, context)

    assert result.refused
    assert result.fingerprint is not None
    assert result.consulted_evidence_ids == ("ev-1", "ev-2")


def test_an_unparseable_response_is_pinned_too() -> None:
    result = ask(
        Question(raw_text="How have margins been?", subject_ref=_SUBJECT),
        _context(),
        FakeLLMClient(response="not json"),
    )

    assert result.refused
    assert result.fingerprint is not None


def test_assertion_ids_stay_empty_until_43b() -> None:
    """Recording what retrieval actually read is the half that may slip."""
    assert _ask(_answer_payload(), _context()).consulted_assertion_ids == ()


# --- #45 pre-pinning theses --------------------------------------------------


def _thesis(result: ReasoningResult) -> Thesis:
    return Thesis(
        question="Did revenue grow?",
        subjects=("TCS",),
        run_fingerprint="run-1",
        view_id="view-1",
        as_of="2026-07-14T10:00:00+00:00",
        result=result,
    )


def test_a_pinned_thesis_round_trips(tmp_path: Path) -> None:
    store = ThesisStore(tmp_path / "theses.json", "TCS")
    store.save(
        _thesis(
            _result(
                fingerprint="digest-abc",
                consulted_assertion_ids=("a1",),
                consulted_evidence_ids=("ev-1",),
                profile_built_at="2026-07-14T10:00:00+00:00",
            )
        )
    )
    loaded = store.load("view-1").result
    assert loaded.fingerprint == "digest-abc"
    assert loaded.consulted_assertion_ids == ("a1",)
    assert loaded.consulted_evidence_ids == ("ev-1",)
    assert loaded.profile_built_at == "2026-07-14T10:00:00+00:00"


def test_a_pre_pinning_thesis_loads_without_error(tmp_path: Path) -> None:
    """Files written before M6 carry none of the four keys."""
    path = tmp_path / "theses.json"
    store = ThesisStore(path, "TCS")
    store.save(_thesis(_result()))

    envelope = json.loads(path.read_text("utf-8"))
    for key in (
        "fingerprint",
        "consulted_assertion_ids",
        "consulted_evidence_ids",
        "profile_built_at",
    ):
        del envelope["theses"][0]["result"][key]
    path.write_text(json.dumps(envelope), encoding="utf-8")

    loaded = store.load("view-1").result
    assert loaded.fingerprint is None
    assert loaded.consulted_assertion_ids == ()
    assert loaded.consulted_evidence_ids == ()
    assert loaded.profile_built_at is None


def test_a_pre_pinning_thesis_keeps_everything_else(tmp_path: Path) -> None:
    """Backward compatibility that lost the findings would be no better."""
    path = tmp_path / "theses.json"
    store = ThesisStore(path, "TCS")
    store.save(_thesis(_result()))

    envelope = json.loads(path.read_text("utf-8"))
    del envelope["theses"][0]["result"]["fingerprint"]
    path.write_text(json.dumps(envelope), encoding="utf-8")

    loaded = store.load("view-1").result
    assert [f.statement for f in loaded.findings] == ["Revenue grew."]
    assert loaded.citations == frozenset({"ev-1"})


def test_the_store_version_did_not_have_to_change(tmp_path: Path) -> None:
    """The new shape is a superset, so old files stay readable as they are."""
    from atlas.research.memory import STORE_VERSION

    assert STORE_VERSION == "1"
