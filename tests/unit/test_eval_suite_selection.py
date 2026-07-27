"""Named suite presets for free-tier operation (harness redesign).

core/grounding/refusals/full select subsets of the bundled §8.6 acceptance
set; anything else is treated as a custom suite file path, preserving the
pre-existing `--suite <path>` behavior.
"""

from __future__ import annotations

import json

import pytest

from atlas.eval.cases import load_cases, resolve_suite


def test_full_returns_every_bundled_case() -> None:
    assert [c.id for c in resolve_suite("full")] == [c.id for c in load_cases()]


def test_core_is_small_and_always_available() -> None:
    cases = resolve_suite("core")
    assert 1 < len(cases) < len(load_cases())
    assert all(c.requires == () for c in cases)
    # Spans more than one category — a smoke check, not a single-path check.
    assert len({c.category for c in cases}) > 1


def test_grounding_is_exactly_category_h() -> None:
    cases = resolve_suite("grounding")
    assert cases  # non-empty
    assert all(c.category == "H" for c in cases)
    all_h = [c for c in load_cases() if c.category == "H"]
    assert {c.id for c in cases} == {c.id for c in all_h}


def test_refusals_is_every_non_answer_case_across_categories() -> None:
    cases = resolve_suite("refusals")
    assert cases
    assert all(c.expected_behavior != "answer" for c in cases)
    expected = {c.id for c in load_cases() if c.expected_behavior != "answer"}
    assert {c.id for c in cases} == expected
    # Distinct from "grounding": includes t25 (category E, honest_negative),
    # which category H does not.
    assert "t25" in {c.id for c in cases}


def test_grounding_and_refusals_are_not_identical_sets() -> None:
    grounding_ids = {c.id for c in resolve_suite("grounding")}
    refusal_ids = {c.id for c in resolve_suite("refusals")}
    assert grounding_ids != refusal_ids


def test_preset_name_is_case_insensitive() -> None:
    assert [c.id for c in resolve_suite("CORE")] == [
        c.id for c in resolve_suite("core")
    ]


def test_non_preset_value_falls_back_to_file_path(tmp_path) -> None:
    custom = tmp_path / "custom.json"
    custom.write_text(
        json.dumps(
            [
                {
                    "id": "x1",
                    "category": "A",
                    "question": "q",
                    "subject": "TCS",
                    "expected_behavior": "answer",
                    "rubric": "r",
                },
            ]
        ),
        encoding="utf-8",
    )
    cases = resolve_suite(str(custom))
    assert [c.id for c in cases] == ["x1"]


def test_nonexistent_path_that_is_not_a_preset_raises() -> None:
    with pytest.raises(FileNotFoundError):
        resolve_suite("this/path/does/not/exist.json")
