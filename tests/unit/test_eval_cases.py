"""Eval suite schema + loader (eval commit 1)."""

from __future__ import annotations

from atlas.eval.cases import CAP_SINGLE_NAME, CAP_THESIS, EvalCase, load_cases


def test_loads_all_44_acceptance_tests() -> None:
    # M1.8.5 (ADR-0005) expanded the bundled suite beyond the original 44 --
    # this asserts the original §8.6 acceptance tests are all still present
    # (t01..t44), not that the suite's total size is frozen at 44.
    cases = load_cases()
    assert len(cases) >= 44
    assert all(isinstance(c, EvalCase) for c in cases)
    ids = {c.id for c in cases}
    assert {f"t{i:02d}" for i in range(1, 45)} <= ids


def test_ids_are_unique() -> None:
    ids = [c.id for c in load_cases()]
    assert len(ids) == len(set(ids))


def test_every_case_has_valid_expected_behavior() -> None:
    for c in load_cases():
        assert c.expected_behavior in ("answer", "refuse", "honest_negative")


def test_t25_t39_are_honest_negative() -> None:
    # §12.6 amendment 5: retires the refuse-vs-honest-negative scorer artifact.
    by_id = {c.id: c for c in load_cases()}
    assert by_id["t25"].expected_behavior == "honest_negative"
    assert by_id["t39"].expected_behavior == "honest_negative"
    assert by_id["t25"].must_not_contain  # the fabrication guards remain the teeth


def test_availability_gates_on_capabilities() -> None:
    caps = frozenset({CAP_SINGLE_NAME})
    thesis_case = EvalCase(
        id="x",
        category="G",
        question="q",
        subject="TCS",
        expected_behavior="answer",
        rubric="",
        requires=(CAP_THESIS,),
    )
    base_case = EvalCase(
        id="y",
        category="A",
        question="q",
        subject="TCS",
        expected_behavior="answer",
        rubric="",
    )
    assert not thesis_case.is_available(caps)
    assert base_case.is_available(caps)


def test_refusal_cases_present_for_out_of_scope() -> None:
    by_id = {c.id: c for c in load_cases()}
    for cid in ("t36", "t37", "t38", "t40"):  # valuation, cheap, Buffett, TAM
        assert by_id[cid].expected_behavior == "refuse"


def test_promise_and_thesis_cases_are_gated() -> None:
    by_id = {c.id: c for c in load_cases()}
    assert "promise_ledger" in by_id["t22"].requires
    assert "thesis" in by_id["t29"].requires
    assert by_id["t01"].requires == ()  # base retrieval case is always available
