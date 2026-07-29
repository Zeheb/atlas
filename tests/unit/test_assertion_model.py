"""Assertion / AssertionRun models, content addressing, and value fidelity.

Three properties, each guarding a distinct silent failure:

Determinism  -- an id that varies between runs makes full-vs-incremental
                comparison impossible, which is the whole reason the ids are
                content addresses rather than counters.
Distinctness -- two facts that differ in any component must get different
                ids, or one silently overwrites the other and a fact
                disappears from the profile with no error anywhere.
Value type   -- 5, 5.0 and "5" are three different assertions. Restoring
                them by inferring a type from the text collapses them.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas.analysis.base import AnalysisFact, FactKind, FactUnit, Provenance
from atlas.assertions.model import (
    Assertion,
    AssertionRun,
    assertion_id,
    assign_ordinals,
    decode_value,
    encode_value,
)

_FP = "fingerprint-abc"
_EV = "ev-001"


def _fact(
    kind: FactKind = FactKind.RISK_FACTOR,
    value: str | int | float | None = "Cyber Security Risk",
    unit: FactUnit | None = None,
    period: str | None = "2024-03-31",
    section: str = "mda_risk",
    char_offset: int | None = 100,
    excerpt: str | None = None,
) -> AnalysisFact:
    return AnalysisFact(
        kind=kind,
        value=value,
        unit=unit,
        period=period,
        confidence="high",
        provenance=Provenance(
            section=section, char_offset=char_offset, excerpt=excerpt
        ),
    )


def _assertion(fact: AnalysisFact, ordinal: int = 0) -> Assertion:
    return Assertion.from_fact(
        fact,
        evidence_id=_EV,
        analyzer_version="3.4",
        fingerprint=_FP,
        ordinal=ordinal,
    )


# ---------------------------------------------------------------------------
# Value encoding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "a string",
        "",
        "5",
        5,
        0,
        -7,
        10**20,
        5.0,
        1.1,
        -0.0,
        0.1 + 0.2,
        None,
    ],
)
def test_value_round_trips_with_exact_type(value: str | int | float | None) -> None:
    raw, value_type = encode_value(value)
    restored = decode_value(raw, value_type)
    assert restored == value
    assert type(restored) is type(value)


def test_int_and_float_and_str_of_the_same_number_stay_distinct() -> None:
    """The reason value_type is stored rather than inferred."""
    assert encode_value(5) != encode_value(5.0)
    assert encode_value(5) != encode_value("5")
    assert encode_value(5.0) != encode_value("5")


def test_strings_are_stored_verbatim_not_repr() -> None:
    """A repr'd string would carry quotes into the column and have to be
    unwrapped on the way out -- one more place to get it wrong."""
    assert encode_value("5") == ("5", "str")


def test_bool_is_rejected() -> None:
    """bool subclasses int. Storing True as 1 would misreport the source."""
    with pytest.raises(TypeError, match="bool"):
        encode_value(True)


def test_decode_rejects_a_null_body_for_a_non_null_type() -> None:
    with pytest.raises(ValueError, match="non-null"):
        decode_value(None, "int")


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_same_fact_always_produces_the_same_id() -> None:
    assert _assertion(_fact()).assertion_id == _assertion(_fact()).assertion_id


def test_id_is_independent_of_fields_that_are_not_addressed() -> None:
    """confidence, excerpt and fingerprint describe the extraction, not the
    claim. Two runs that differ only there are the same assertion."""
    plain = _assertion(_fact(excerpt=None))
    with_excerpt = _assertion(_fact(excerpt="some verbatim snippet"))
    assert plain.assertion_id == with_excerpt.assertion_id


# ---------------------------------------------------------------------------
# Distinctness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("kind", {"kind": FactKind.STRATEGY_PRIORITY}),
        ("value", {"value": "Talent Attrition Risk"}),
        ("period", {"period": "2025-03-31"}),
        ("section", {"section": "auditor_report_kam"}),
        ("char_offset", {"char_offset": 101}),
        ("unit", {"unit": FactUnit.PERCENT}),
    ],
)
def test_changing_any_addressed_component_changes_the_id(
    field: str, changed: dict[str, object]
) -> None:
    base = _assertion(_fact()).assertion_id
    other = _assertion(_fact(**changed)).assertion_id  # type: ignore[arg-type]
    assert base != other, f"{field} does not affect the id"


def test_changing_analyzer_version_changes_the_id() -> None:
    fact = _fact()
    first = Assertion.from_fact(
        fact, evidence_id=_EV, analyzer_version="3.4", fingerprint=_FP, ordinal=0
    )
    second = Assertion.from_fact(
        fact, evidence_id=_EV, analyzer_version="3.5", fingerprint=_FP, ordinal=0
    )
    assert first.assertion_id != second.assertion_id


def test_changing_evidence_id_changes_the_id() -> None:
    fact = _fact()
    first = Assertion.from_fact(
        fact, evidence_id="ev-a", analyzer_version="3.4", fingerprint=_FP, ordinal=0
    )
    second = Assertion.from_fact(
        fact, evidence_id="ev-b", analyzer_version="3.4", fingerprint=_FP, ordinal=0
    )
    assert first.assertion_id != second.assertion_id


def test_ordinal_separates_otherwise_identical_facts() -> None:
    """The annual_report RISK_FACTOR case.

    Every risk in that loop is built with the same section and the same
    char_offset -- the offset of the section, not of the risk -- and
    _extract_risks deduplicates on neither of its paths. Without the ordinal
    two equal risk strings collapse into one row and a fact disappears.
    """
    duplicate = _fact(value="Cyber Security Risk")
    first = _assertion(duplicate, ordinal=0)
    second = _assertion(duplicate, ordinal=1)
    assert first.assertion_id != second.assertion_id


# ---------------------------------------------------------------------------
# Ordinal assignment
# ---------------------------------------------------------------------------


def test_ordinals_are_scoped_to_kind_and_section() -> None:
    facts = [
        _fact(value="risk one"),
        _fact(value="risk two"),
        _fact(kind=FactKind.AUDIT_KAM_TITLE, section="auditor_report_kam"),
        _fact(value="risk three"),
    ]
    assert assign_ordinals(facts) == [0, 1, 0, 2]


def test_ordinal_scoping_keeps_unrelated_facts_stable() -> None:
    """A global counter would make every later id depend on how many
    unrelated facts preceded it, so extracting one extra fact anywhere
    would rewrite every id after it."""
    without = [_fact(value="a"), _fact(kind=FactKind.RISK_FACTOR, value="b")]
    with_extra = [
        _fact(value="a"),
        _fact(kind=FactKind.AUDIT_KAM_TITLE, section="auditor_report_kam"),
        _fact(kind=FactKind.RISK_FACTOR, value="b"),
    ]
    assert assign_ordinals(without)[-1] == assign_ordinals(with_extra)[-1]


def test_assign_ordinals_is_empty_for_no_facts() -> None:
    assert assign_ordinals([]) == []


# ---------------------------------------------------------------------------
# Fact round trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fact",
    [
        _fact(),
        _fact(kind=FactKind.FINANCIAL_REVENUE, value=60000.0, unit=FactUnit.CRORE_INR),
        _fact(
            kind=FactKind.OWNERSHIP_TOTAL_SHARES, value=3618087518, unit=FactUnit.COUNT
        ),
        _fact(value=None, period=None, char_offset=None),
        _fact(excerpt="a verbatim micro-proof"),
    ],
)
def test_fact_survives_the_round_trip(fact: AnalysisFact) -> None:
    restored = _assertion(fact).to_fact()
    assert restored.kind is fact.kind
    assert restored.value == fact.value
    assert type(restored.value) is type(fact.value)
    assert restored.unit == fact.unit
    assert restored.period == fact.period
    assert restored.confidence == fact.confidence
    assert restored.provenance.section == fact.provenance.section
    assert restored.provenance.char_offset == fact.provenance.char_offset
    assert restored.provenance.excerpt == fact.provenance.excerpt


# ---------------------------------------------------------------------------
# AssertionRun
# ---------------------------------------------------------------------------


def test_a_failed_run_records_its_error() -> None:
    """Recorded, not dropped: 'tried and raised' and 'never tried' are
    different states and only the second should trigger a retry."""
    run = AssertionRun(
        evidence_id=_EV,
        kind="annual_report",
        analyzer_version="3.4",
        fingerprint=_FP,
        result_confidence="low",
        source_date=datetime(2024, 5, 1, tzinfo=timezone.utc),
        analyzed_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        warnings=(),
        status="failed",
        error="ValueError: no period found",
    )
    assert run.status == "failed"
    assert run.error is not None


def test_assertion_id_helper_matches_the_dataclass_path() -> None:
    """The standalone function and Assertion.from_fact must agree, or the
    store and the model would address the same assertion differently."""
    fact = _fact()
    direct = assertion_id(
        evidence_id=_EV,
        kind=fact.kind.value,
        value="Cyber Security Risk",
        value_type="str",
        unit=None,
        period="2024-03-31",
        section="mda_risk",
        char_offset=100,
        analyzer_version="3.4",
        ordinal=0,
    )
    assert direct == _assertion(fact).assertion_id
