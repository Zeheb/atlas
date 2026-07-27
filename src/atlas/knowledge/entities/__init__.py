"""Knowledge-graph entity layer (M-P1.1, ADR-0013).

Re-activates the ``knowledge/entities`` scaffold with the identity model and a
conservative, in-memory, deterministic resolver. Emission of entities from
analyzers, CompanyProfile wiring, and persistence are later milestones.
"""
from atlas.knowledge.entities.model import Entity, EntityKind
from atlas.knowledge.entities.resolver import EntityResolver, normalize_name

__all__ = ["Entity", "EntityKind", "EntityResolver", "normalize_name"]
