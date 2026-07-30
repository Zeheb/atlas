"""Every registered query returns a pinned result — #53.

The inventory for #51, written before the sweep it checks. Eighteen query
functions build their own ``QueryResult``, and a mechanical pass over that
many call sites misses one; a parametrized test names which one rather than
reporting that something, somewhere, is unpinned.

Driven by ``available_queries()``, not by a hand-written list. A list would
have to be edited whenever a query is registered, and the edit that gets
forgotten is exactly the one that leaves a new query unpinned — the failure
this test exists to make impossible.

Every case is ``xfail(strict=True)`` here: ``QueryResult`` carries no
``fingerprint`` yet, so all eighteen must fail. The #51 commit removes the
marker, and strict mode is what proves that commit closed all of them rather
than most.
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


@pytest.mark.xfail(
    strict=True,
    reason="#51 has not landed: QueryResult has no fingerprint field yet",
)
@pytest.mark.parametrize("name", available_queries())
def test_every_registered_query_pins_the_build(name: str) -> None:
    result = run_query(name, _profile(), **_kwargs_for(name))

    assert isinstance(result, QueryResult)
    assert getattr(result, "fingerprint", None) == current_fingerprint().digest()
