"""Benchmark taxonomies — two orthogonal axes (M1.8.5 / ADR-0005; M-E.1).

This module holds two independent classification axes the benchmark uses.
They are deliberately kept side by side because their orthogonality is the
whole point (see the Atlas Evaluation Matrix §6):

1. ``RetrievalScenario`` — a taxonomy of *retrieval problems a case can pose*,
   not of questions in general. It exists so the benchmark can prove it covers
   the situations retrieval actually has to handle, at the same granularity as
   ``reasoning.plan.RetrievalIntent`` (what the question is *about*) and
   ``reasoning.planner.ALL_RULE_IDS`` (what the planner *decided*). A case's
   scenario tag is only meaningful when its provenance (``provenance.py``) is
   machine-verified against real corpus evidence — see ``validation.py`` —
   otherwise this taxonomy would be exactly the "abstract exercise" the
   benchmark is meant to avoid. It is a property of a *case*; its purpose is
   suite coverage ("can the suite detect a retrieval regression?").

2. ``AtlasCapability`` — a taxonomy of *what the system must be able to do to
   answer a benchmark question at all*. It is a property of a *question*; its
   purpose is grade assignment and roadmap routing ("what must be built?").

The two are orthogonal in purpose, and where they would coincide the scenario
axis is authoritative: no ``AtlasCapability`` restates a ``RetrievalScenario``
member, which is why the whole "retrieval" capability family is empty by
construction (a question blocked by retrieval difficulty is measured on axis 1,
never duplicated here). See ``test_benchmark_taxonomy.py`` for the enforced
invariants.

``AtlasCapability`` is NOT the same thing as the ``CAP_*`` constants in
``eval.cases`` — do not merge them. Those are *milestone availability gates*
("does this build have the feature, so should the case run or be marked
pending?"). ``AtlasCapability`` describes *what the question demands*,
independent of any milestone. A single case can legitimately carry both: a
capability the question requires, and a ``CAP_*`` gate saying whether this
build provides it.
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


# ---------------------------------------------------------------------------
# Axis 2 — AtlasCapability (M-E.1; ratified in ADR-0011): what the system must
# be able to do to answer a benchmark question at all. Members are the 24
# admitted capabilities from the Atlas Evaluation Matrix §6, grouped into six
# families. The order here follows §6's family order and is not significant to
# any logic.
# ---------------------------------------------------------------------------
AtlasCapability = Literal[
    # Acquisition — does Atlas hold the document?
    "acq.kind_coverage",       # the kind is in the ontology AND a connector fetches it
    "acq.history_depth",       # the corpus reaches back far enough for the period
    "acq.entity_coverage",     # enough other companies are held, densely per sector
    "acq.tier_admission",      # Atlas admits evidence outside Tier-1 primary filings
    # Structuring — does the document become a typed, comparable fact?
    "struct.typed_fact",       # a FactKind exists for the concept
    "struct.time_series",      # the fact is period-anchored and comparable across periods
    "struct.entity_identity",  # the fact names a resolvable entity, not a string
    "struct.event_linkage",    # two facts across documents/periods link as one chain
    # Retrieval — intentionally EMPTY. Retrieval difficulty is measured wholly
    # on RetrievalScenario (axis 1); no capability restates a scenario member.
    # See the module docstring and the admission rule in §6.
    # Reasoning — can a defensible answer be formed?
    "reason.grounded_answer",         # cited answer from retrieved context
    "reason.derived_metric",          # compute a metric not disclosed directly
    "reason.comparative",             # compare across entities / a defined reference set
    "reason.judgment_qualification",  # state how strongly a claim is grounded
    # Memory — does knowledge persist and accumulate?
    "mem.view_persistence",    # a formed view is stored and recallable
    "mem.view_history",        # prior versions of a view are diffable over time
    "mem.staleness",           # a recalled view is checked against current evidence
    "mem.recurrence",          # a concept recurring across documents/years is detected
    # External evidence — is non-filing evidence available and correctly weighted?
    "ext.market_structure",    # index membership, lock-in, float/overhang — document-backed
    "ext.market_price",        # traded price, share count, multiples — the charter exclusion
    "ext.third_party_opinion", # brokerage, expert, forum, analyst commentary
    "ext.macro_trade",         # sector, macro, commodity, trade-flow data
    "ext.entity_background",   # person/org background outside the filing
    # Evaluation — can the benchmark detect whether the answer was good?
    "eval.gradeable",             # a checkable expected answer exists
    "eval.provenance_checkable",  # the answer's citations verify against the corpus
    "eval.stability",             # repeat runs are comparable
]

ALL_CAPABILITY_IDS: frozenset[str] = frozenset({
    "acq.kind_coverage",
    "acq.history_depth",
    "acq.entity_coverage",
    "acq.tier_admission",
    "struct.typed_fact",
    "struct.time_series",
    "struct.entity_identity",
    "struct.event_linkage",
    "reason.grounded_answer",
    "reason.derived_metric",
    "reason.comparative",
    "reason.judgment_qualification",
    "mem.view_persistence",
    "mem.view_history",
    "mem.staleness",
    "mem.recurrence",
    "ext.market_structure",
    "ext.market_price",
    "ext.third_party_opinion",
    "ext.macro_trade",
    "ext.entity_background",
    "eval.gradeable",
    "eval.provenance_checkable",
    "eval.stability",
})

# One-line descriptions, for authoring guidance and CLI output -- not consumed
# by any scoring logic (mirrors SCENARIO_DESCRIPTIONS).
CAPABILITY_DESCRIPTIONS: dict[str, str] = {
    "acq.kind_coverage": "the document kind is in the ontology and a connector fetches it",
    "acq.history_depth": "the corpus reaches back far enough for the question's period",
    "acq.entity_coverage": "enough other companies are held, densely enough per sector, to compare",
    "acq.tier_admission": "Atlas admits evidence outside Tier-1 primary filings",
    "struct.typed_fact": "a FactKind exists for the concept",
    "struct.time_series": "the fact is period-anchored and comparable across periods",
    "struct.entity_identity": "the fact names a resolvable entity rather than a string",
    "struct.event_linkage": "two facts in different documents or periods link as one chain",
    "reason.grounded_answer": "a cited answer from retrieved context",
    "reason.derived_metric": "compute a metric not disclosed directly",
    "reason.comparative": "compare across entities or against a defined reference set",
    "reason.judgment_qualification": "state how strongly a claim is grounded",
    "mem.view_persistence": "a formed view is stored and recallable",
    "mem.view_history": "prior versions of a view are diffable over time",
    "mem.staleness": "a recalled view is checked against current evidence",
    "mem.recurrence": "the same concept recurring across documents or years is detected",
    "ext.market_structure": "index membership, lock-in expiry, float and overhang — document-backed",
    "ext.market_price": "traded price, share count, trading multiples — the sole charter exclusion",
    "ext.third_party_opinion": "brokerage, expert, forum, analyst commentary",
    "ext.macro_trade": "sector, macro, commodity, trade-flow data",
    "ext.entity_background": "person/org background outside the filing",
    "eval.gradeable": "a checkable expected answer exists",
    "eval.provenance_checkable": "the answer's citations verify against the corpus",
    "eval.stability": "repeat runs are comparable",
}
