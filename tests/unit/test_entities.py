"""Person/Org entity model and resolver (M-P1.1, ADR-0013).

Covers normalization, the conservative merge rule (initials, ambiguity), and
the two governing invariants: entity_id STABILITY (never changes on merge /
canonical update) and entity_id UNIQUENESS (no two distinct entities collide).
"""

from __future__ import annotations

import pytest

from atlas.knowledge.entities import Entity, EntityResolver, normalize_name


# --- model --------------------------------------------------------------------
def test_entity_rejects_empty_id() -> None:
    with pytest.raises(ValueError):
        Entity(entity_id="", kind="person", canonical_name="K S Rao")


def test_entity_rejects_bad_kind() -> None:
    with pytest.raises(ValueError):
        Entity(entity_id="x", kind="alien", canonical_name="K S Rao")  # type: ignore[arg-type]


# --- normalize_name -----------------------------------------------------------
def test_normalize_strips_honorifics_and_punctuation() -> None:
    assert normalize_name("Dr. K. S. Rao") == ("k", "s", "rao")
    assert normalize_name("Shri Kumar  S Rao") == ("kumar", "s", "rao")


def test_normalize_empty() -> None:
    assert normalize_name("  Mr.  ") == ()


# --- create / basic resolve ---------------------------------------------------
def test_resolve_creates_entity() -> None:
    r = EntityResolver()
    e = r.resolve("Kumar S Rao", "person")
    assert e.kind == "person"
    assert e.canonical_name == "Kumar S Rao"
    assert e.entity_id == "person:kumar-s-rao"
    assert len(r.entities()) == 1


def test_resolve_identical_name_is_same_entity() -> None:
    r = EntityResolver()
    a = r.resolve("Kumar S Rao", "person")
    b = r.resolve("Kumar S Rao", "person")
    assert a.entity_id == b.entity_id
    assert len(r.entities()) == 1


def test_resolve_empty_name_raises() -> None:
    with pytest.raises(ValueError):
        EntityResolver().resolve("Mr.", "person")


# --- initial expansion (the named failure mode) -------------------------------
def test_initials_merge_when_unambiguous() -> None:
    r = EntityResolver()
    first = r.resolve("K S Rao", "person")
    second = r.resolve("Kumar S Rao", "person")  # unambiguous expansion
    assert first.entity_id == second.entity_id
    assert len(r.entities()) == 1
    assert second.canonical_name == "Kumar S Rao"  # canonical upgraded to fuller form
    assert "K S Rao" in second.aliases


def test_full_names_with_same_initials_do_not_over_merge() -> None:
    r = EntityResolver()
    a = r.resolve("Kumar S Rao", "person")
    b = r.resolve("Krishna S Rao", "person")  # different full given name
    assert a.entity_id != b.entity_id
    assert len(r.entities()) == 2


def test_ambiguous_initials_under_merge_not_over_merge() -> None:
    # Registry already holds two distinct people who share initials+surname.
    # An initials-only form is compatible with BOTH -> the resolver must NOT
    # guess; it creates a separate (third) entity.
    r = EntityResolver()
    r.resolve("Kumar S Rao", "person")
    r.resolve("Krishna S Rao", "person")
    amb = r.resolve("K S Rao", "person")
    assert len(r.entities()) == 3
    assert amb.canonical_name == "K S Rao"


def test_absorbed_initials_alias_does_not_promiscuously_match() -> None:
    # "K S Rao" merges into Kumar; a later "Krishna S Rao" must NOT match via
    # the absorbed initials alias (matching is against canonical only).
    r = EntityResolver()
    r.resolve("K S Rao", "person")
    r.resolve("Kumar S Rao", "person")  # canonical now "Kumar S Rao"
    krishna = r.resolve("Krishna S Rao", "person")
    assert len(r.entities()) == 2
    assert krishna.canonical_name == "Krishna S Rao"


# --- organization matching (exact only) ---------------------------------------
def test_org_exact_match_merges() -> None:
    r = EntityResolver()
    a = r.resolve("Acme Services Ltd", "organization")
    b = r.resolve("acme services ltd", "organization")
    assert a.entity_id == b.entity_id


def test_org_does_not_merge_on_suffix_difference() -> None:
    r = EntityResolver()
    r.resolve("Acme Ltd", "organization")
    r.resolve("Acme Services Ltd", "organization")
    assert len(r.entities()) == 2


def test_person_and_org_never_cross_match() -> None:
    r = EntityResolver()
    p = r.resolve("Acme Services Ltd", "person")
    o = r.resolve("Acme Services Ltd", "organization")
    assert p.entity_id != o.entity_id
    assert len(r.entities()) == 2


# --- INVARIANT: id stability --------------------------------------------------
def test_id_is_stable_across_merge_and_canonical_change() -> None:
    r = EntityResolver()
    first = r.resolve("K S Rao", "person")
    original_id = first.entity_id
    merged = r.resolve("Kumar S Rao", "person")  # canonical changes...
    assert merged.entity_id == original_id  # ...id does not
    assert r.entities()[0].entity_id == original_id


# --- INVARIANT: id uniqueness -------------------------------------------------
def test_ids_are_unique_across_all_entities() -> None:
    r = EntityResolver()
    for name in [
        "K S Rao",
        "Kumar S Rao",
        "Krishna S Rao",
        "K S Rao",
        "Acme Ltd",
        "Acme Services Ltd",
        "Sunil Singhania",
    ]:
        r.resolve(name, "person" if "Ltd" not in name else "organization")
    ids = [e.entity_id for e in r.entities()]
    assert len(ids) == len(set(ids))


def test_colliding_first_seen_slug_is_disambiguated() -> None:
    # Force the id-collision path: "K S Rao" first (id person:k-s-rao, canonical
    # later upgraded), then two distinct fulls, then an ambiguous "K S Rao"
    # whose first-seen slug would collide -> must get a suffixed id.
    r = EntityResolver()
    r.resolve("K S Rao", "person")  # id person:k-s-rao
    r.resolve("Kumar S Rao", "person")  # merges; canonical -> Kumar S Rao
    r.resolve("Krishna S Rao", "person")  # distinct
    amb = r.resolve("K S Rao", "person")  # ambiguous -> new entity, slug collides
    assert amb.entity_id != "person:k-s-rao"
    assert amb.entity_id.startswith("person:k-s-rao-")
    ids = [e.entity_id for e in r.entities()]
    assert len(ids) == len(set(ids))
