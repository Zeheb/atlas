"""Q&A-turn question text (M-P2.8, Q12).

Reuses the existing _RE_ANY_SPEAKER turn-boundary (no new segmentation
heuristic). ParticipantAppearance.question_text is populated only for analyst
appearances; management appearances are always None.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas.analysis.base import AnalysisResult, EntityMention
from atlas.analysis.earnings_transcript import (
    _bounded_question_text,
    _extract_analyst_mentions,
    _extract_management_mentions,
)
from atlas.company.builder import build_profile
from atlas.knowledge.entities import Entity, EntityResolver

_TRANSCRIPT = (
    "Moderator: We have the first question from the line of Ravi Menon \n"
    "from Macquarie. Please go ahead.\n"
    "Ravi Menon: \nThank you. Good evening. Just wanted to ask about the "
    "deal pipeline for next quarter.\n"
    "N G Subramaniam: \nHi Ravi, thanks for the question. We expect steady "
    "growth.\n"
    "Moderator: Next question from the line of Sudheer Guntupalli from \n"
    "Kotak Mahindra AMC. Please go ahead.\n"
    "Sudheer Guntupalli: \nGood evening, I wanted to understand the margin "
    "trajectory.\n"
    "N G Subramaniam: \nSure, let me address that.\n"
)


# --- correct turn bounding ------------------------------------------------------
def test_question_bounded_to_next_speaker_tag() -> None:
    mentions = _extract_analyst_mentions(_TRANSCRIPT, EntityResolver())
    ravi = next(m for m in mentions if m.entity.canonical_name == "Ravi Menon")
    assert ravi.question_text == (
        "Thank you. Good evening. Just wanted to ask about the deal "
        "pipeline for next quarter."
    )
    # Must NOT bleed into the responder's turn.
    assert "N G Subramaniam" not in ravi.question_text
    assert "steady growth" not in ravi.question_text


# --- multiple analysts ----------------------------------------------------------
def test_multiple_analysts_each_get_own_question() -> None:
    mentions = _extract_analyst_mentions(_TRANSCRIPT, EntityResolver())
    by_name = {m.entity.canonical_name: m.question_text for m in mentions}
    assert "deal pipeline" in by_name["Ravi Menon"]
    assert "margin trajectory" in by_name["Sudheer Guntupalli"]
    assert by_name["Ravi Menon"] != by_name["Sudheer Guntupalli"]


# --- management always None -----------------------------------------------------
def test_management_mentions_have_no_question_text() -> None:
    roster = (
        "CORPORATE PARTICIPANTS\n\nN G Subramaniam, COO - TCS\n\n"
        "CONFERENCE CALL PARTICIPANTS\nRavi Menon, Macquarie\n" + _TRANSCRIPT
    )
    mgmt = _extract_management_mentions(roster, EntityResolver())
    assert mgmt  # sanity: extraction actually found management
    assert all(m.question_text is None for m in mgmt)


# --- malformed / unbounded transcript length cap --------------------------------
def test_unbounded_question_capped_at_max_chars() -> None:
    huge = "Ravi Menon: \n" + ("word " * 2000)  # no next speaker tag at all
    text = _bounded_question_text(huge, "Ravi Menon", 0)
    assert text is not None
    from atlas.analysis.earnings_transcript import _MAX_QUESTION_CHARS

    assert len(text) <= _MAX_QUESTION_CHARS


def test_analysts_own_tag_never_found_returns_none() -> None:
    # Introduced by the moderator but never actually speaks in the extracted text.
    assert (
        _bounded_question_text("no speaker tags here at all", "Ravi Menon", 0) is None
    )


# --- trailing whitespace trimmed -------------------------------------------------
def test_trailing_whitespace_trimmed() -> None:
    text = (
        "Ravi Menon: \n  Question with trailing space.   \n\nN G Subramaniam: \nAnswer."
    )
    got = _bounded_question_text(text, "Ravi Menon", 0)
    assert got == "Question with trailing space."
    assert got == got.strip()


# --- empty value handling --------------------------------------------------------
def test_empty_question_after_tag_returns_none() -> None:
    # Speaker tag immediately followed by the next speaker tag -- nothing said.
    text = "Ravi Menon: \nN G Subramaniam: \nAnswer."
    assert _bounded_question_text(text, "Ravi Menon", 0) is None


def test_entity_mention_question_text_defaults_none() -> None:
    m = EntityMention(entity=Entity(entity_id="p:x", kind="person", canonical_name="X"))
    assert m.question_text is None


# --- builder ingestion -----------------------------------------------------------
def _result(mentions: list[EntityMention]) -> AnalysisResult:
    return AnalysisResult(
        evidence_id="bse-t1",
        kind="earnings_transcript",
        analyzer_version="2.3",
        confidence="low",
        source_date=datetime(2026, 4, 15, tzinfo=timezone.utc),
        entities=mentions,
    )


def _mention(name: str, role: str, question_text: str | None) -> EntityMention:
    return EntityMention(
        entity=Entity(
            entity_id=f"person:{name.lower().replace(' ', '-')}",
            kind="person",
            canonical_name=name,
        ),
        role=role,
        affiliation="X" if role == "analyst" else None,
        question_text=question_text,
    )


def test_builder_ingests_question_text_for_analyst() -> None:
    result = _result([_mention("Ravi Menon", "analyst", "What about margins?")])
    profile = build_profile("TCS", [result])
    assert profile.participants[0].question_text == "What about margins?"


def test_builder_forces_none_for_management_even_if_producer_set_it() -> None:
    # Defensive gate: builder must never let a question_text reach a
    # management appearance, even if some future producer mis-sets it.
    result = _result([_mention("N G Subramaniam", "management", "should not appear")])
    profile = build_profile("TCS", [result])
    assert profile.participants[0].question_text is None


# --- store round-trip -------------------------------------------------------------
def test_question_text_survives_store_round_trip(tmp_path) -> None:
    from atlas.company.store import CompanyStore

    result = _result([_mention("Ravi Menon", "analyst", "What about margins?")])
    profile = build_profile("TCS", [result])
    store = CompanyStore(tmp_path / "TCS" / "profile.json", "TCS")
    store.save(profile, [result])
    loaded = store.load()
    assert loaded.participants[0].question_text == "What about margins?"


def test_none_question_text_round_trips_as_none(tmp_path) -> None:
    from atlas.company.store import CompanyStore

    result = _result([_mention("Ravi Menon", "analyst", None)])
    profile = build_profile("TCS", [result])
    store = CompanyStore(tmp_path / "TCS" / "profile.json", "TCS")
    store.save(profile, [result])
    assert store.load().participants[0].question_text is None


# --- real-data validation: TCS / SBI -----------------------------------------------
def test_real_tcs_transcripts_produce_bounded_questions() -> None:
    import sqlite3
    from pathlib import Path

    from atlas.analysis.earnings_transcript import analyze
    from atlas.knowledge.base import KnowledgeBase

    if not Path("repositories/TCS/knowledge.db").exists():
        pytest.skip("TCS repository not found")
    con = sqlite3.connect("repositories/TCS/knowledge.db")
    ids = [
        r[0]
        for r in con.execute(
            "SELECT evidence_id FROM parsed_documents WHERE kind='earnings_transcript'"
        ).fetchall()
    ]
    kb = KnowledgeBase(Path("repositories/TCS"))
    total_analysts = 0
    total_with_question = 0
    for eid in ids:
        r = analyze(eid, kb)
        analysts = [m for m in r.entities if m.role == "analyst"]
        total_analysts += len(analysts)
        total_with_question += sum(1 for m in analysts if m.question_text)
    assert total_analysts > 0
    assert total_with_question > 0
    # Strong majority of real analyst turns must yield a bounded question.
    assert total_with_question / total_analysts > 0.9


def test_real_sbi_transcripts_produce_bounded_questions() -> None:
    import sqlite3
    from pathlib import Path

    from atlas.analysis.earnings_transcript import analyze
    from atlas.knowledge.base import KnowledgeBase

    if not Path("repositories/SBIN/knowledge.db").exists():
        pytest.skip("SBIN repository not found")
    con = sqlite3.connect("repositories/SBIN/knowledge.db")
    ids = [
        r[0]
        for r in con.execute(
            "SELECT evidence_id FROM parsed_documents WHERE kind='earnings_transcript'"
        ).fetchall()
    ]
    kb = KnowledgeBase(Path("repositories/SBIN"))
    total_analysts = 0
    total_with_question = 0
    for eid in ids:
        r = analyze(eid, kb)
        analysts = [m for m in r.entities if m.role == "analyst"]
        total_analysts += len(analysts)
        total_with_question += sum(1 for m in analysts if m.question_text)
    assert total_analysts > 0
    assert total_with_question > 0
    assert total_with_question / total_analysts > 0.8
