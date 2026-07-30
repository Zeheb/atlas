"""Every registered query returns a pinned result — #53.

The inventory for #51, written before the sweep it checks. Eighteen query
functions build their own ``QueryResult``, and a mechanical pass over that
many call sites misses one; a parametrized test names which one rather than
reporting that something, somewhere, is unpinned.

Driven by ``available_queries()``, not by a hand-written list. A list would
have to be edited whenever a query is registered, and the edit that gets
forgotten is exactly the one that leaves a new query unpinned — the failure
this test exists to make impossible.

The eighteen cases landed ``xfail(strict=True)`` and all eighteen XPASSed the
moment ``QueryResult`` gained the field, which is what proved the sweep closed
all of them rather than most. The marker came off in that same commit.
"""

from __future__ import annotations

import pytest

from atlas.company.model import CompanyProfile
from atlas.provenance import current_fingerprint
from atlas.query.engine import QueryResult, available_queries, run_query

_COMPANY = "TCS"


def _kwargs_for(query_name: str) -> dict[str, object]:
    """The extra required argument three queries take beyond the profile.

    Mirrors the CLI's own kwargs-building in ``query_cmd``; the corpus variant
    in ``tests/integration`` builds the same mapping. Pinning is a property of
    the envelope, so the arguments only have to be accepted, not meaningful.
    """
    if query_name in ("timeline", "compare"):
        return {"metric": "revenue"}
    if query_name == "drilldown":
        return {"evidence_id": "ev-absent-from-this-profile"}
    return {}


def _profile() -> CompanyProfile:
    """An empty profile: pinning must not depend on there being data.

    A query that returns no rows still answers "which build said so", and an
    empty result is the case most likely to take a short path out of a
    function before the envelope is fully built.
    """
    return CompanyProfile(company_id=_COMPANY)


def test_the_registry_is_not_empty() -> None:
    """Guards the parametrization below from passing vacuously."""
    assert len(available_queries()) >= 18


@pytest.mark.parametrize("name", available_queries())
def test_every_registered_query_pins_the_build(name: str) -> None:
    result = run_query(name, _profile(), **_kwargs_for(name))

    assert isinstance(result, QueryResult)
    assert result.fingerprint == current_fingerprint().digest()


def test_the_screen_surface_is_pinned_too() -> None:
    """``screen.py`` builds a QueryResult and is not registered in ``_QUERIES``.

    The inventory above cannot see it, which is the argument for pinning by
    field default rather than at each construction site: a surface the
    checklist does not cover is exactly the one that would ship unpinned.
    """
    from atlas.query.screen import screen

    result = screen({}, metric="revenue")

    assert result.fingerprint == current_fingerprint().digest()


def test_a_result_is_pinned_without_anyone_passing_a_fingerprint() -> None:
    """The default is the mechanism, so a new query surface is pinned for free."""
    assert QueryResult(query="q", company_id=_COMPANY, title="t").fingerprint == (
        current_fingerprint().digest()
    )


def test_an_explicit_fingerprint_is_kept() -> None:
    """The default must not overwrite a caller describing another build."""
    result = QueryResult(
        query="q", company_id=_COMPANY, title="t", fingerprint="another-build"
    )

    assert result.fingerprint == "another-build"
