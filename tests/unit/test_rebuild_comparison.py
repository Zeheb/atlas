"""The canonical comparison helper (#31).

Everything the rebuild engine asks reduces to this: did anything change? Two
properties make the answer trustworthy, and both are easy to lose.

Wall clock excluded -- two builds always differ in built_at, so a comparison
that saw it would report a difference every time and be switched off within a
week.

One exclusion list -- the list lives in canonical_for_hash and is already used
by the assertion ids and the fingerprint. A second copy here would drift, and
the symptom would be a rebuild reporting a field nobody meant to compare.
"""

from __future__ import annotations

from atlas.assertions.hashing import EXCLUDED_FROM_HASH
from atlas.rebuild import (
    canonical_profile,
    explain_difference,
    profile_digest,
    profiles_match,
)

_PROFILE = {
    "company_id": "TCS",
    "built_at": "2026-07-29T10:00:00+00:00",
    "financial": {
        "snapshots": [
            {
                "period": "2026-03-31",
                "facts": {"financial_revenue": 64988.0},
                "sources": ["ev-early", "ev-late"],
            }
        ]
    },
}


def _with(**overrides: object) -> dict[str, object]:
    return {**_PROFILE, **overrides}


def test_identical_profiles_match() -> None:
    assert profiles_match(_PROFILE, dict(_PROFILE))


def test_key_order_does_not_matter() -> None:
    """Two dicts built in different orders are the same profile."""
    reordered = dict(reversed(list(_PROFILE.items())))

    assert profiles_match(_PROFILE, reordered)


def test_built_at_is_ignored() -> None:
    """The field that differs between every pair of builds."""
    assert profiles_match(_PROFILE, _with(built_at="2027-01-01T00:00:00+00:00"))


def test_a_changed_value_does_not_match() -> None:
    changed = {
        **_PROFILE,
        "financial": {
            "snapshots": [
                {
                    "period": "2026-03-31",
                    "facts": {"financial_revenue": 64989.0},
                    "sources": ["ev-early", "ev-late"],
                }
            ]
        },
    }

    assert not profiles_match(_PROFILE, changed)


def test_a_reordered_list_does_not_match() -> None:
    """Order inside a list is content. This is the failure the whole project
    is about, so the comparison must not normalise it away."""
    reordered = {
        **_PROFILE,
        "financial": {
            "snapshots": [
                {
                    "period": "2026-03-31",
                    "facts": {"financial_revenue": 64988.0},
                    "sources": ["ev-late", "ev-early"],
                }
            ]
        },
    }

    assert not profiles_match(_PROFILE, reordered)


def test_a_missing_entry_does_not_match() -> None:
    assert not profiles_match(_PROFILE, {"company_id": "TCS"})


def test_the_exclusion_list_is_not_restated_here() -> None:
    """One list, in one place. If this module grew its own, the two would
    drift and the drift would show up as a spurious rebuild difference."""
    canonical = canonical_profile(_PROFILE)

    for excluded in EXCLUDED_FROM_HASH:
        assert f'"{excluded}"' not in canonical


def test_digest_is_stable_and_ignores_the_clock() -> None:
    assert profile_digest(_PROFILE) == profile_digest(
        _with(built_at="2030-01-01T00:00:00+00:00")
    )


def test_digest_moves_when_content_moves() -> None:
    assert profile_digest(_PROFILE) != profile_digest(_with(company_id="INFY"))


def test_matching_profiles_have_nothing_to_explain() -> None:
    assert (
        explain_difference(_PROFILE, _with(built_at="2030-01-01T00:00:00+00:00")) == []
    )


def test_a_difference_is_named_not_just_reported() -> None:
    """A red boolean sends someone reading two thousand lines of JSON."""
    differences = explain_difference(_PROFILE, _with(company_id="INFY"))

    assert differences
    assert any("company_id" in line for line in differences)
