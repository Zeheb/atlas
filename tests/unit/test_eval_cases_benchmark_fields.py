"""EvalCase's optional benchmark fields (M1.8.5 commit 2, ADR-0005).

test_eval_cases.py (pre-existing) and every eval/runner test that loads the
bundled suite are untouched and still pass -- confirming the four new
fields are additive: absent in JSON -> None on EvalCase, no behavior change
for any pre-M1.8.5 case.

Commit 8 (case authoring, same milestone) later populated these fields on
~33 NEW cases in the bundled suite -- this file's assertions were updated
to check the original t01-t44 specifically (still field-free) rather than
the whole suite, since the whole suite legitimately carries these fields now.
"""
from __future__ import annotations

import pytest

from atlas.eval.cases import EvalCase, _case, load_cases

_ORIGINAL_IDS = {f"t{i:02d}" for i in range(1, 45)}


def _base(**overrides: object) -> dict[str, object]:
    d: dict[str, object] = {
        "id": "x01", "category": "A", "question": "q", "subject": "TCS",
        "expected_behavior": "answer", "rubric": "r",
    }
    d.update(overrides)
    return d


# --- Backward compatibility: original 44 unaffected by the new fields --------------
def test_bundled_suite_still_contains_the_original_44_cases() -> None:
    cases = load_cases()
    ids = {c.id for c in cases}
    assert _ORIGINAL_IDS <= ids


def test_original_44_cases_have_no_benchmark_fields() -> None:
    for c in load_cases():
        if c.id not in _ORIGINAL_IDS:
            continue
        assert c.scenario is None
        assert c.difficulty is None
        assert c.provenance is None
        assert c.retrieval_label is None
        assert c.capabilities == ()


def test_expanded_suite_has_cases_with_benchmark_fields_populated() -> None:
    # Proves the new fields are actually exercised somewhere in the real
    # bundled file, not just supported in principle.
    cases = load_cases()
    with_provenance = [c for c in cases if c.provenance is not None]
    assert with_provenance, "expected at least one corpus-derived/negative case in the bundled suite"


# --- Parsing from JSON --------------------------------------------------------------
def test_case_without_benchmark_keys_parses_to_none() -> None:
    c = _case(_base())
    assert c.scenario is None and c.difficulty is None
    assert c.provenance is None and c.retrieval_label is None


def test_case_with_scenario_and_difficulty_parses() -> None:
    c = _case(_base(scenario="temporal", difficulty="difficult"))
    assert c.scenario == "temporal"
    assert c.difficulty == "difficult"


def test_case_with_provenance_dict_parses() -> None:
    c = _case(_base(provenance={
        "origin": "corpus_derived", "supporting_evidence_ids": ["ev-1"],
        "verification_method": "manual", "verified_at": "2026-07-21", "verified_by": "z",
    }))
    assert c.provenance is not None
    assert c.provenance.origin == "corpus_derived"
    assert c.provenance.supporting_evidence_ids == ("ev-1",)


def test_case_with_retrieval_label_dict_parses() -> None:
    c = _case(_base(retrieval_label={
        "relevant_evidence_ids": ["ev-1", "ev-2"], "relevant_kinds": ["annual_report"],
    }))
    assert c.retrieval_label is not None
    assert c.retrieval_label.relevant_evidence_ids == ("ev-1", "ev-2")
    assert c.retrieval_label.relevant_kinds == ("annual_report",)


# --- Structural validation at load time ---------------------------------------------
def test_invalid_scenario_rejected() -> None:
    with pytest.raises(ValueError):
        _case(_base(scenario="not_a_real_scenario"))


def test_invalid_difficulty_rejected() -> None:
    with pytest.raises(ValueError):
        _case(_base(difficulty="extreme"))


def test_construct_directly_with_invalid_scenario_rejected() -> None:
    with pytest.raises(ValueError):
        EvalCase(
            id="x", category="A", question="q", subject="TCS",
            expected_behavior="answer", rubric="r", scenario="bogus",
        )


def test_provenance_dict_missing_origin_raises_keyerror() -> None:
    # Deliberately a KeyError (not silently None) -- "origin" is the one
    # required key with no sensible default.
    with pytest.raises(KeyError):
        _case(_base(provenance={"verification_method": "m"}))


# --- All 6 declared scenarios and both difficulties are individually valid ----------
@pytest.mark.parametrize("scenario", [
    "document_routing", "temporal", "ambiguity",
    "conflict_resolution", "sparse_evidence", "negative_retrieval",
])
def test_every_declared_scenario_is_accepted(scenario: str) -> None:
    _case(_base(scenario=scenario))  # must not raise


@pytest.mark.parametrize("difficulty", ["routine", "difficult"])
def test_every_declared_difficulty_is_accepted(difficulty: str) -> None:
    _case(_base(difficulty=difficulty))  # must not raise


# --- capabilities field (M-E.3, ADR-0011) -------------------------------------------
def test_case_without_capabilities_parses_to_empty_tuple() -> None:
    assert _case(_base()).capabilities == ()


def test_case_with_capabilities_parses_and_coerces_to_tuple() -> None:
    c = _case(_base(capabilities=["struct.typed_fact", "reason.derived_metric"]))
    assert c.capabilities == ("struct.typed_fact", "reason.derived_metric")


def test_invalid_capability_rejected() -> None:
    with pytest.raises(ValueError):
        _case(_base(capabilities=["struct.not_a_real_capability"]))


def test_construct_directly_with_invalid_capability_rejected() -> None:
    with pytest.raises(ValueError):
        EvalCase(
            id="x", category="A", question="q", subject="TCS",
            expected_behavior="answer", rubric="r",
            capabilities=("bogus.capability",),
        )


def test_capabilities_is_a_separate_axis_from_requires() -> None:
    # requires holds CAP_* milestone gates; capabilities holds AtlasCapability
    # ids. A milestone gate id is NOT a valid capability, which is the sharpest
    # proof the two axes are kept distinct (ADR-0011).
    from atlas.eval.cases import CAP_SINGLE_NAME
    with pytest.raises(ValueError):
        _case(_base(capabilities=[CAP_SINGLE_NAME]))


def test_no_bundled_case_carries_capabilities_yet() -> None:
    # Matrix §9: authoring the 45 questions as cases is deferred -- M-E.3 ships
    # the field only. If this ever fails, the deferral was crossed and the
    # authoring milestone (not M-E.3) should own it.
    assert all(c.capabilities == () for c in load_cases())
