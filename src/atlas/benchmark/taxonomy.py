"""Retrieval-scenario taxonomy for the evaluation benchmark (M1.8.5 / ADR-0005).

This is a taxonomy of *retrieval problems a case can pose*, not of questions
in general — it exists so the benchmark can prove it covers the situations
retrieval actually has to handle, deliberately at the same granularity as
``reasoning.plan.RetrievalIntent`` (which classifies *what the question is
about*) and ``reasoning.planner.ALL_RULE_IDS`` (which classifies *what the
planner decided*). A case's scenario tag is only meaningful when its
provenance (``provenance.py``) is machine-verified against real corpus
evidence — see ``validation.py`` — otherwise this taxonomy would be exactly
the "abstract exercise" the benchmark is meant to avoid.
"""
from __future__ import annotations

from typing import Literal

RetrievalScenario = Literal[
    "document_routing",     # the answer lives in one specific doc kind
    "temporal",              # period-scoped ("FY24", "Q3FY23", "last three years")
    "ambiguity",             # underspecified question, several defensible readings
    "conflict_resolution",   # two disclosures genuinely disagree
    "sparse_evidence",       # relevant evidence exists but is thin
    "negative_retrieval",    # nothing relevant exists; the honest answer is absence
]

ALL_SCENARIO_IDS: frozenset[str] = frozenset({
    "document_routing",
    "temporal",
    "ambiguity",
    "conflict_resolution",
    "sparse_evidence",
    "negative_retrieval",
})

DifficultyClass = Literal["routine", "difficult"]

# One-line descriptions, for the `atlas eval coverage`/`validate-cases` CLI
# output and for authoring guidance -- not consumed by any scoring logic.
SCENARIO_DESCRIPTIONS: dict[str, str] = {
    "document_routing": "the answer lives in one specific document kind",
    "temporal": "the question is scoped to a specific fiscal period",
    "ambiguity": "the question is underspecified; several readings are defensible",
    "conflict_resolution": "two disclosures genuinely disagree",
    "sparse_evidence": "relevant evidence exists but is thin",
    "negative_retrieval": "nothing relevant exists; the honest answer is absence",
}
