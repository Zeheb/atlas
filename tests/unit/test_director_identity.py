"""Director identity emission from the Annual Report (M-P1.4, narrowed).

Scope: director NAME + DIN only. Age and tenure are deliberately NOT emitted —
the AR corporate-governance section does not preserve per-director bindings for
them. Only clean "Name (DIN XXXXXXXX)" adjacencies; under-emit rather than
misattribute.
"""
from __future__ import annotations

from datetime import datetime, timezone

from atlas.analysis.annual_report import _RE_DIRECTOR_DIN, _extract_directors
from atlas.analysis.base import AnalysisResult, EntityMention
from atlas.company.builder import build_profile
from atlas.company.model import CompanyProfile, DirectorIdentity
from atlas.knowledge.entities import Entity, EntityResolver


# --- EntityMention.identifier field (Option B) --------------------------------
def test_entity_mention_identifier_defaults_none() -> None:
    m = EntityMention(entity=Entity(entity_id="p:x", kind="person", canonical_name="X"))
    assert m.identifier is None


def test_entity_mention_carries_identifier() -> None:
    m = EntityMention(
        entity=Entity(entity_id="p:x", kind="person", canonical_name="X"),
        role="director", identifier="07121802",
    )
    assert m.identifier == "07121802"


# --- extractor: clean adjacency only ------------------------------------------
def test_extracts_clean_name_din_adjacency() -> None:
    text = "appoint Rajesh Gopinathan (DIN 06365813) as Director"
    ms = _extract_directors(text, EntityResolver())
    assert len(ms) == 1
    assert ms[0].entity.canonical_name == "Rajesh Gopinathan"
    assert ms[0].identifier == "06365813"
    assert ms[0].role == "director"


def test_din_preserves_leading_zeros() -> None:
    ms = _extract_directors("Keki Mistry (DIN 00008886)", EntityResolver())
    assert ms[0].identifier == "00008886"


def test_honorific_stripped_from_name() -> None:
    ms = _extract_directors("Ms. Aarthi Subramanian (DIN 07121802)", EntityResolver())
    assert ms[0].entity.canonical_name == "Aarthi Subramanian"


def test_no_age_or_tenure_emitted() -> None:
    # Dissociated aggregate columns near a name must never bind as attributes.
    text = "Keki Mistry (DIN 00008886)\nAge (years)\n51\n71\n61\nTenure 3 15 6"
    ms = _extract_directors(text, EntityResolver())
    assert len(ms) == 1
    # EntityMention has no age/tenure slot; only identity + DIN travel.
    assert ms[0].identifier == "00008886"
    assert ms[0].affiliation is None


def test_bare_din_without_adjacent_name_not_emitted() -> None:
    # Garbled OCR: DIN present but no clean preceding name -> under-emit.
    assert _extract_directors("(Independent)\n29-06-2014 | 3 years\nDIN:00267211", EntityResolver()) == []


def test_dedup_same_director_din_within_document() -> None:
    text = "Rajesh Gopinathan (DIN 06365813) ... Rajesh Gopinathan (DIN 06365813)"
    assert len(_extract_directors(text, EntityResolver())) == 1


# --- builder + store ----------------------------------------------------------
def _ar_result(evidence_id: str, mentions: list[EntityMention]) -> AnalysisResult:
    return AnalysisResult(
        evidence_id=evidence_id, kind="annual_report", analyzer_version="3.1",
        confidence="high", source_date=datetime(2025, 6, 30, tzinfo=timezone.utc),
        entities=mentions,
    )


def _director(name: str, din: str) -> EntityMention:
    return EntityMention(
        entity=Entity(entity_id=f"person:{name.lower().replace(' ', '-')}", kind="person", canonical_name=name),
        role="director", identifier=din,
    )


def test_builder_ingests_directors() -> None:
    result = _ar_result("bse-ar-1", [_director("Rajesh Gopinathan", "06365813")])
    profile = build_profile("TCS", [result])
    assert [(d.canonical_name, d.din) for d in profile.directors] == [("Rajesh Gopinathan", "06365813")]


def test_builder_skips_mention_without_identifier() -> None:
    # A non-director entity mention (no DIN) must not become a director.
    m = EntityMention(entity=Entity(entity_id="person:x", kind="person", canonical_name="X"), role="analyst")
    profile = build_profile("TCS", [_ar_result("bse-ar-2", [m])])
    assert profile.directors == []


def test_directors_survive_store_round_trip(tmp_path) -> None:
    from atlas.company.store import CompanyStore
    result = _ar_result("bse-ar-3", [_director("Keki Minoo Mistry", "00008886")])
    profile = build_profile("TCS", [result])
    store = CompanyStore(tmp_path / "TCS" / "profile.json", "TCS")
    store.save(profile, [result])
    loaded = store.load()
    assert [(d.canonical_name, d.din) for d in loaded.directors] == [("Keki Minoo Mistry", "00008886")]


def test_empty_directors_round_trip(tmp_path) -> None:
    from atlas.company.store import CompanyStore
    store = CompanyStore(tmp_path / "TCS" / "profile.json", "TCS")
    store.save(CompanyProfile(company_id="TCS"), [])
    assert store.load().directors == []
