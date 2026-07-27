"""Transcript participant emission (M-P1.2, ADR-0014, Q13).

Covers the analyst extractor, the EntityMention composition, the builder's
ingest into CompanyProfile.participants, and the store round-trip.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.analysis.base import AnalysisResult, EntityMention
from atlas.analysis.earnings_transcript import _extract_analyst_mentions
from atlas.company.builder import build_profile
from atlas.company.model import CompanyProfile
from atlas.company.store import CompanyStore
from atlas.knowledge.entities import Entity, EntityResolver

# Real-shaped moderator intros (Chorus-call convention; newline varies around
# the inner "from", as in the actual TCS transcripts).
_QA = (
    "Moderator: We have the first question from the line of Ravi Menon \n"
    "from Macquarie. Please go ahead.\n"
    "Ravi Menon: Thanks. My question...\n"
    "Moderator: Next question from the line of Sudheer Guntupalli from \n"
    "Kotak Mahindra AMC. Please go ahead.\n"
    "Moderator: Next question from the line of Ravi Menon from Macquarie. "
    "Please go ahead.\n"  # same analyst again -> deduped
)


# --- extractor ----------------------------------------------------------------
def test_extracts_analyst_name_and_affiliation() -> None:
    ms = _extract_analyst_mentions(_QA, EntityResolver())
    got = {(m.entity.canonical_name, m.affiliation, m.role) for m in ms}
    assert ("Ravi Menon", "Macquarie", "analyst") in got
    assert ("Sudheer Guntupalli", "Kotak Mahindra AMC", "analyst") in got


def test_dedupes_repeat_questioner_within_transcript() -> None:
    ms = _extract_analyst_mentions(_QA, EntityResolver())
    ravi = [m for m in ms if m.entity.canonical_name == "Ravi Menon"]
    assert len(ravi) == 1


def test_mentions_carry_provenance() -> None:
    ms = _extract_analyst_mentions(_QA, EntityResolver())
    assert all(m.provenance is not None and m.provenance.section == "qa" for m in ms)


def test_no_analysts_yields_empty() -> None:
    assert _extract_analyst_mentions("no q and a here", EntityResolver()) == []


# --- EntityMention model ------------------------------------------------------
def test_entity_mention_composes_entity_without_mutating_it() -> None:
    e = Entity(entity_id="person:x", kind="person", canonical_name="X")
    m = EntityMention(entity=e, role="analyst", affiliation="Y")
    assert m.entity is e  # composition, not copy/mutation
    assert m.role == "analyst" and m.affiliation == "Y"


# --- builder ingest -----------------------------------------------------------
def _transcript_result(
    evidence_id: str, mentions: list[EntityMention]
) -> AnalysisResult:
    return AnalysisResult(
        evidence_id=evidence_id,
        kind="earnings_transcript",
        analyzer_version="2.1",
        confidence="low",
        source_date=datetime(2026, 4, 15, tzinfo=timezone.utc),
        entities=mentions,
    )


def _mention(name: str, affil: str) -> EntityMention:
    return EntityMention(
        entity=Entity(
            entity_id=f"person:{name.lower().replace(' ', '-')}",
            kind="person",
            canonical_name=name,
        ),
        role="analyst",
        affiliation=affil,
    )


def test_builder_ingests_participants() -> None:
    result = _transcript_result(
        "bse-news-t1",
        [
            _mention("Ravi Menon", "Macquarie"),
            _mention("Kumar Rakesh", "BNP Paribas"),
        ],
    )
    profile = build_profile("TCS", [result])
    got = {
        (p.canonical_name, p.affiliation, p.evidence_id, p.source_date)
        for p in profile.participants
    }
    assert ("Ravi Menon", "Macquarie", "bse-news-t1", "2026-04-15") in got
    assert ("Kumar Rakesh", "BNP Paribas", "bse-news-t1", "2026-04-15") in got


def test_builder_no_entities_leaves_participants_empty() -> None:
    profile = build_profile("TCS", [_transcript_result("bse-news-t2", [])])
    assert profile.participants == []


# --- store round-trip ---------------------------------------------------------
def test_participants_survive_store_round_trip(tmp_path) -> None:
    result = _transcript_result(
        "bse-news-t3", [_mention("Gaurav Rateria", "Morgan Stanley")]
    )
    profile = build_profile("TCS", [result])
    store = CompanyStore(tmp_path / "TCS" / "profile.json", "TCS")
    store.save(profile, [result])
    loaded = store.load()
    assert [(p.canonical_name, p.affiliation) for p in loaded.participants] == [
        ("Gaurav Rateria", "Morgan Stanley")
    ]


def test_empty_participants_round_trip(tmp_path) -> None:
    # Backward-compat: a profile with no participants serializes and reloads.
    profile = CompanyProfile(company_id="TCS")
    store = CompanyStore(tmp_path / "TCS" / "profile.json", "TCS")
    store.save(profile, [])
    assert store.load().participants == []
