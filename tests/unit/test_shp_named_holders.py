"""Named >1% public shareholder emission from SHP XBRL (M-P1.3, ADR-0014, Q24).

Central discipline: public holders only, promoter/ambiguous excluded, EntityKind
decided from the ownership category (never the name), under-emit rather than
misattribute. Holding percentage is deferred.
"""

from __future__ import annotations

from datetime import datetime, timezone

from atlas.analysis.base import AnalysisResult, EntityMention
from atlas.analysis.shareholding_pattern import (
    _axis_of,
    _extract_named_public_holders,
    _public_holder_class,
)
from atlas.company.builder import build_profile
from atlas.company.model import CompanyProfile, NamedShareholder
from atlas.company.store import CompanyStore
from atlas.knowledge.entities import Entity, EntityResolver


# --- classifier: kind from category, promoter excluded ------------------------
def test_axis_strips_prefix_and_suffix() -> None:
    assert _axis_of("D_MutualFundsOrUti_Context1") == "MutualFundsOrUti"


def test_public_categories_map_to_kind() -> None:
    assert _public_holder_class("MutualFundsOrUti") == ("mutual_fund", "organization")
    assert _public_holder_class("InsuranceCompanies") == ("insurance", "organization")
    assert _public_holder_class("OtherInstitutions") == (
        "other_institution",
        "organization",
    )
    assert _public_holder_class("OtherNonInstitutions") == (
        "other_non_institution",
        "organization",
    )
    assert _public_holder_class(
        "ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh"
    ) == ("individual_hni", "person")


def test_promoter_and_ambiguous_excluded() -> None:
    assert _public_holder_class("OthersIndianShareholders") is None
    assert _public_holder_class("ShareholdingOfPromoterAndPromoterGroup") is None
    assert _public_holder_class("SomeUnknownAxis") is None  # under-emit


def test_retail_up_to_two_lakh_not_emitted() -> None:
    # Only the ">2 lakh" individual axis is a named >1% holder; the retail
    # "UpTo" axis must not classify as an individual holder.
    assert (
        _public_holder_class(
            "ResidentIndividualShareholdersHoldingNominalShareCapitalUpToRsTwoLakh"
        )
        is None
    )


# --- extractor: emits public, skips promoter ----------------------------------
def _fmap() -> dict[tuple[str, str], str]:
    return {
        ("NameOfTheShareholder", "D_MutualFundsOrUti_Context1"): "SBI Mutual Fund",
        (
            "NameOfTheShareholder",
            "D_InsuranceCompanies_Context1",
        ): "Life Insurance Corporation of India",
        (
            "NameOfTheShareholder",
            "D_OthersIndianShareholders_Context15",
        ): "TATA SONS PRIVATE LIMITED",
        (
            "NameOfTheShareholder",
            "D_ResidentIndividualShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh_Context2",
        ): "Ashish Kacholia",
        ("SomeOtherTag", "D_MutualFundsOrUti_Context1"): "not a name",
    }


def test_extracts_public_holders_only() -> None:
    ms = _extract_named_public_holders(_fmap(), EntityResolver())
    names = {m.entity.canonical_name for m in ms}
    assert "SBI Mutual Fund" in names
    assert "Life Insurance Corporation of India" in names
    assert "Ashish Kacholia" in names
    assert "TATA SONS PRIVATE LIMITED" not in names  # promoter excluded


def test_kind_and_category_from_axis() -> None:
    ms = {
        m.entity.canonical_name: m
        for m in _extract_named_public_holders(_fmap(), EntityResolver())
    }
    assert ms["SBI Mutual Fund"].entity.kind == "organization"
    assert ms["SBI Mutual Fund"].role == "mutual_fund"
    assert ms["Ashish Kacholia"].entity.kind == "person"
    assert ms["Ashish Kacholia"].role == "individual_hni"


def test_no_affiliation_or_holding_pct() -> None:
    ms = _extract_named_public_holders(_fmap(), EntityResolver())
    assert all(m.affiliation is None for m in ms)  # holding % / affiliation deferred


def test_dedup_within_filing() -> None:
    fmap = {
        ("NameOfTheShareholder", "D_MutualFundsOrUti_Context1"): "SBI Mutual Fund",
        ("NameOfTheShareholder", "D_MutualFundsOrUti_Context2"): "SBI Mutual Fund",
    }
    assert len(_extract_named_public_holders(fmap, EntityResolver())) == 1


# --- builder ingest + store round-trip ----------------------------------------
def _shp_result(evidence_id: str, mentions: list[EntityMention]) -> AnalysisResult:
    return AnalysisResult(
        evidence_id=evidence_id,
        kind="shareholding_pattern",
        analyzer_version="1.1",
        confidence="high",
        source_date=datetime(2026, 3, 31, tzinfo=timezone.utc),
        entities=mentions,
    )


def _mention(name: str, category: str, kind: str) -> EntityMention:
    return EntityMention(
        entity=Entity(
            entity_id=f"{kind}:{name.lower().replace(' ', '-')}",
            kind=kind,
            canonical_name=name,
        ),
        role=category,
        affiliation=None,
    )


def test_builder_ingests_named_shareholders() -> None:
    result = _shp_result(
        "bse-shp-1",
        [
            _mention("SBI Mutual Fund", "mutual_fund", "organization"),
            _mention("Ashish Kacholia", "individual_hni", "person"),
        ],
    )
    profile = build_profile("ACME", [result])
    got = {(h.canonical_name, h.kind, h.category) for h in profile.named_shareholders}
    assert ("SBI Mutual Fund", "organization", "mutual_fund") in got
    assert ("Ashish Kacholia", "person", "individual_hni") in got


def test_named_shareholders_survive_store_round_trip(tmp_path) -> None:
    result = _shp_result(
        "bse-shp-2",
        [_mention("Life Insurance Corporation of India", "insurance", "organization")],
    )
    profile = build_profile("ACME", [result])
    store = CompanyStore(tmp_path / "ACME" / "profile.json", "ACME")
    store.save(profile, [result])
    loaded = store.load()
    assert [(h.canonical_name, h.category) for h in loaded.named_shareholders] == [
        ("Life Insurance Corporation of India", "insurance")
    ]


def test_empty_named_shareholders_round_trip(tmp_path) -> None:
    store = CompanyStore(tmp_path / "ACME" / "profile.json", "ACME")
    store.save(CompanyProfile(company_id="ACME"), [])
    assert store.load().named_shareholders == []
