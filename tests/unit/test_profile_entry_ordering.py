"""Entry lists must not inherit the order their facts arrived in.

``test_profile_equivalence`` permutes *results* and proves the snapshot
containers are order-invariant. That is not the whole exposure. Several
profile containers are appended one entry per **fact**, in ``result.facts``
order, and permuting results never disturbs the order of facts *within* one
result -- so a container that ties on its sort key keeps arrival order and no
existing test can see it.

The two tiers order facts differently by construction. The analyzer path
hands the builder facts in the order the analyzer emitted them; the assertion
path reconstructs them from stored rows ordered by content address
(``reader.py``, ``(source_date, evidence_id, assertion_id)``). Same facts,
different sequence. Any container whose sort key is not total therefore
serialises differently depending on which tier built it.

Found in production, not in review: the TCS M10 backfill (#59) refused with
184 differences between the analyzer-path and assertion-path profiles, all of
them in ``governance.risk_factors`` and ``strategy.entries``, and every one a
pure permutation -- 207 risk factors on both sides, identical multiset of
``(text, evidence_id, period)``, nothing added and nothing lost. The stored
profile was fine; the two routes to it disagreed about order. This is the
reopened #33.

Reversing the facts within a single result is the smallest faithful model of
that divergence, and it is what these tests do.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from atlas.analysis.base import (
    AnalysisFact,
    AnalysisResult,
    FactKind,
    Provenance,
)
from atlas.company.builder import build_profile
from atlas.company.store import CompanyStore

_TICKER = "TCS"
_PERIOD = "2024-03-31"
_SOURCE_DATE = datetime(2024, 6, 1, tzinfo=timezone.utc)


def _fact(kind: FactKind, value: str, period: str | None = None) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=None,
        period=period,
        confidence="high",
        provenance=Provenance(section="body", char_offset=None),
    )


def _result(kind: str, facts: list[AnalysisFact]) -> AnalysisResult:
    return AnalysisResult(
        evidence_id="ev-01",
        kind=kind,
        analyzer_version="1.0",
        confidence="high",
        source_date=_SOURCE_DATE,
        facts=facts,
    )


def _payload(base: Path, result: AnalysisResult) -> str:
    """The stored profile object, verbatim including list order."""
    store = CompanyStore(base, _TICKER)
    store.save(build_profile(_TICKER, [result]), [result])
    raw = json.loads(store._path.read_text(encoding="utf-8"))
    return json.dumps(raw["profile"], indent=2)


def _risk_facts() -> list[AnalysisFact]:
    """Three risk factors sharing one period.

    They must share ``period``: that is the whole sort key today, so entries
    differing on it would sort correctly and observe nothing. Real filings
    carry many risk factors per reporting period, so a tie here is the normal
    case rather than a contrived one.
    """
    return [
        _fact(FactKind.RISK_FACTOR, "Concentration in a single geography", _PERIOD),
        _fact(FactKind.RISK_FACTOR, "Attrition in senior engineering roles", _PERIOD),
        _fact(
            FactKind.RISK_FACTOR, "Currency exposure on unhedged receivables", _PERIOD
        ),
    ]


def _guidance_facts() -> list[AnalysisFact]:
    """Three guidance statements sharing one ``source_date``.

    ``strategy.entries`` sorts on ``source_date`` alone, and every entry
    derived from one document carries that document's date, so a single
    transcript with more than one guidance statement always ties.
    """
    return [
        _fact(FactKind.STRATEGY_GUIDANCE, "Margin band of 26-28% for the year"),
        _fact(FactKind.STRATEGY_GUIDANCE, "Double-digit growth in constant currency"),
        _fact(FactKind.STRATEGY_GUIDANCE, "Headcount broadly flat through H2"),
    ]


def test_the_fixtures_actually_tie(tmp_path: Path) -> None:
    """Guard the guard.

    Both assertions below are vacuous unless the entries genuinely collide on
    the sort key in force. A future edit that gives each entry its own period
    or date would leave them passing and blind.
    """
    risk_payload = json.loads(
        _payload(tmp_path / "risk", _result("annual_report", _risk_facts()))
    )
    entries = risk_payload["governance"]["risk_factors"]
    assert len(entries) >= 2, "fixture produced too few risk factors to observe order"
    assert (
        len({e["period"] for e in entries}) == 1
    ), "fixture no longer ties on period; the ordering test proves nothing"

    guidance_payload = json.loads(
        _payload(
            tmp_path / "guidance", _result("earnings_transcript", _guidance_facts())
        )
    )
    guidance = guidance_payload["strategy"]["entries"]
    assert len(guidance) >= 2, "fixture produced too few guidance entries"


def test_risk_factors_do_not_inherit_fact_order(tmp_path: Path) -> None:
    """Same period, three texts, two fact orderings, one profile."""
    facts = _risk_facts()
    forward = _payload(tmp_path / "fwd", _result("annual_report", list(facts)))
    reverse = _payload(
        tmp_path / "rev", _result("annual_report", list(reversed(facts)))
    )
    assert forward == reverse


def test_strategy_entries_do_not_inherit_fact_order(tmp_path: Path) -> None:
    """Same source_date, three statements, two fact orderings, one profile."""
    facts = _guidance_facts()
    forward = _payload(tmp_path / "fwd", _result("earnings_transcript", list(facts)))
    reverse = _payload(
        tmp_path / "rev", _result("earnings_transcript", list(reversed(facts)))
    )
    assert forward == reverse
