"""Management-answerer emission + the Q45 cross-reference (M-P1.5).

Covers: management-roster extraction (both layouts + under-emit), analyst
extraction unaffected, and the derived `former_answerers` query — which
establishes identity by a single ephemeral, query-time resolver pass (not
stored ids, not string equality), and under-emits rather than misattributes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from atlas.analysis.earnings_transcript import (
    _extract_analyst_mentions,
    _extract_management_mentions,
)
from atlas.company.model import (
    CompanyProfile,
    DirectorChange,
    GovernanceProfile,
    ParticipantAppearance,
)
from atlas.knowledge.entities import EntityResolver
from atlas.query.engine import former_answerers

# Real-shaped rosters.
_COMMA_ROSTER = (
    "CORPORATE PARTICIPANTS\n\n"
    "T V Narendran, CEO & MD - Tata Steel Limited\n"
    "Koushik Chatterjee, ED & CFO - Tata Steel Limited\n\n"
    "CONFERENCE CALL PARTICIPANTS\n"
    "Amit Dixit, ICICI Securities\n"
    "Moderator: We have the first question from the line of Amit Dixit "
    "from ICICI Securities. Please go ahead.\n"
)
_HONORIFIC_ROSTER = (
    "MANAGEMENT:\nMR. C.S. SETTY\nCHAIRMAN\n\nMR. ASHWANI BHATIA\n"
    "MANAGING DIRECTOR\n\nModerator: first question from the line of "
    "Mahrukh Adajania from Nuvama. Please go ahead.\n"
)


# --- management roster extraction (both layouts) ------------------------------
def test_comma_roster_extracts_management() -> None:
    ms = _extract_management_mentions(_COMMA_ROSTER, EntityResolver())
    names = {m.entity.canonical_name for m in ms}
    assert "T V Narendran" in names
    assert "Koushik Chatterjee" in names
    assert all(m.role == "management" for m in ms)
    # analyst-roster names below the boundary are NOT captured as management
    assert "Amit Dixit" not in names


def test_honorific_roster_extracts_management() -> None:
    ms = _extract_management_mentions(_HONORIFIC_ROSTER, EntityResolver())
    names = {m.entity.canonical_name for m in ms}
    assert "C.S. Setty" in names
    assert "Ashwani Bhatia" in names
    assert all(m.role == "management" for m in ms)


def test_no_roster_under_emits() -> None:
    assert _extract_management_mentions("no roster here, just prose", EntityResolver()) == []


def test_analyst_extraction_unaffected_by_management() -> None:
    # Regression: both extractors run on the same content, distinct roles.
    r = EntityResolver()
    analysts = _extract_analyst_mentions(_COMMA_ROSTER, r)
    mgmt = _extract_management_mentions(_COMMA_ROSTER, r)
    assert {m.entity.canonical_name for m in analysts} == {"Amit Dixit"}
    assert all(m.role == "analyst" for m in analysts)
    assert all(m.role == "management" for m in mgmt)


# --- cross-reference query (Q45) ----------------------------------------------
def _profile(participants, resignations) -> CompanyProfile:
    p = CompanyProfile(company_id="TCS")
    p.participants = participants
    p.governance = GovernanceProfile(director_changes=resignations)
    return p


def _mgmt(name: str, eid: str = "person:x", ev: str = "bse-t1") -> ParticipantAppearance:
    return ParticipantAppearance(eid, name, "management", None, ev, "2023-01-15")


def _resign(name: str, role: str = "Director") -> DirectorChange:
    return DirectorChange(
        source_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        change_type="resignation", name=name, role=role, evidence_id="bse-bo1",
    )


def test_cross_ref_matches_across_name_variant() -> None:
    # "T V Narendran" (transcript) resolves to "T. V. Narendran" (board outcome)
    # -> fresh resolution, not string equality.
    prof = _profile([_mgmt("T V Narendran")], [_resign("T. V. Narendran", "CEO & MD")])
    rows = former_answerers(prof).sections[0].rows
    assert len(rows) == 1
    assert rows[0][0] == "T V Narendran"


def test_cross_ref_ignores_analysts() -> None:
    prof = _profile(
        [ParticipantAppearance("person:a", "Some Analyst", "analyst", "X", "bse-t1", "2023-01-15")],
        [_resign("Some Analyst")],
    )
    assert former_answerers(prof).sections[0].rows == []


def test_cross_ref_excludes_management_without_resignation() -> None:
    prof = _profile([_mgmt("Rajesh Gopinathan")], [_resign("Someone Else")])
    assert former_answerers(prof).sections[0].rows == []


def test_cross_ref_does_not_match_different_people_same_surname() -> None:
    # Conservative: full given names differ -> not the same entity, no match.
    prof = _profile([_mgmt("Kumar S Rao")], [_resign("Krishna S Rao")])
    assert former_answerers(prof).sections[0].rows == []


def test_cross_ref_ignores_appointments() -> None:
    prof = CompanyProfile(company_id="TCS")
    prof.participants = [_mgmt("N Chandrasekaran")]
    prof.governance = GovernanceProfile(director_changes=[
        DirectorChange(source_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                       change_type="appointment", name="N Chandrasekaran", role="Chairman",
                       evidence_id="bse-bo2"),
    ])
    assert former_answerers(prof).sections[0].rows == []


def test_cross_ref_independent_of_stored_entity_id() -> None:
    # Participant carries an arbitrary stored (per-document) id; the match must
    # still succeed via fresh resolution, proving it does not read stored ids.
    prof = _profile(
        [_mgmt("Koushik Chatterjee", eid="person:doc-local-99")],
        [_resign("Koushik Chatterjee", "CFO")],
    )
    rows = former_answerers(prof).sections[0].rows
    assert len(rows) == 1 and rows[0][0] == "Koushik Chatterjee"


def test_cross_ref_no_management_notes_guidance() -> None:
    prof = _profile([], [_resign("Anyone")])
    result = former_answerers(prof)
    assert result.sections[0].rows == []
    assert any("management" in n.lower() for n in result.notes)
