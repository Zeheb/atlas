# ADR-0014 — Entity Emission Channel on AnalysisResult

**Date:** 2026-07-23
**Status:** Accepted

---

## Context

ADR-0013 established `Entity` as a separate domain model (in `knowledge/entities/`),
deliberately not a `FactKind`. M-P1.2 (emit transcript participants, benchmark
Q13) then needed a way for an analyzer to *surface* resolved entities, and the
`AnalysisResult` envelope had no channel for them: it exposes only `facts`
(FactKind-typed) and `excerpts` (verbatim text). The benchmark's "emit
participant FactKinds" phrasing cannot be taken literally — the `FactKind`
ontology is frozen until Phase 2 (ADR-0012), and ADR-0013 chose a separate
model precisely to avoid that dependency.

A full architecture review evaluated every plausible owner (a new FactKind;
resolution in the builder; a tuple return from `analyze()`; overloading
`excerpts`) and rejected each as a freeze violation, a misplacement of document
parsing into the assembly layer, or an analyzer-interface break. The analyzer is
the only component holding both the document text (to locate participants) and
access to the M-P1.1 resolver — it is the correct producer.

A grounding finding removed the main cost objection: **`AnalysisResult` is never
serialized.** `CompanyStore` persists only a `_ResultRecord` stub (evidence_id,
kind, analyzer_version, source_date, analyzed_at); `facts` and `excerpts` are
already dropped on persist. A new output category on the envelope therefore
carries no serialization, cache, or backward-compatibility cost at the analysis
layer.

---

## Decision

**Add `entities: list[EntityMention]` to `AnalysisResult` — the envelope's third
output category, beside `facts` and `excerpts`.**

- **`EntityMention` (defined in `analysis/base.py`)** composes a knowledge-layer
  `Entity` (identity only — ADR-0013) with the analysis-context attributes that
  are *not* identity: `role`, `affiliation`, and `provenance`. Per ADR-0009 these
  live on the wrapper, never on the shared `Entity`. Provenance is an analysis
  concept, which is also why `EntityMention` lives in `analysis`, not `knowledge`
  (the knowledge layer cannot import `analysis.Provenance`).
- **The analyzer is the producer.** It resolves observed names via the M-P1.1
  `EntityResolver` and appends `EntityMention`s. The field defaults to `[]`, so
  every existing analyzer and consumer is unaffected; the `analyze(evidence_id,
  kb) -> AnalysisResult` signature is unchanged.
- **The company builder is the first consumer.** It projects `result.entities`
  into a `CompanyProfile.participants` list (`ParticipantAppearance`), which
  `CompanyStore` serializes — this is where the real (and small) `Entity`
  serialization lives.

---

## Consequences

**Positive:**
- Entities flow analyzer → builder through the same envelope as facts, one
  consistent contract, honoring ADR-0013 (entities are their own category, not
  facts) without touching the frozen ontology.
- Zero analysis-layer serialization / cache / backward-compat cost, because
  `AnalysisResult` is transient.
- Analyzer interface is stable — an optional, defaulted field only.

**Negative / Trade-offs:**
- The `AnalysisResult` envelope now has three output categories instead of two.
  This is the correct home for a genuinely new output, but it does widen the
  contract that all 11 analyzers nominally share.
- Entity ids are resolved per-document in M-P1.2, so the same person across two
  transcripts may carry different ids. Cross-call unification is a later
  refinement (the builder can run a single profile-level resolver when needed).

**Risks:**
- If a future path *does* serialize `AnalysisResult` in full, `EntityMention`
  will need a serializer. Flagged here so that path adds it deliberately.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| New participant `FactKind` | Frozen ontology (Phase 2 / ADR-0012) + ADR-0013 says entities are not FactKinds |
| Resolve in the builder | Misplaces transcript document-parsing into the assembly layer |
| `analyze()` returns `(AnalysisResult, list[Entity])` | Breaks the analyzer signature across all 11 analyzers + registry |
| Overload `excerpts` with participant text | `excerpts` is text-for-review; loses the resolved structured identity |
| Payload is bare `list[Entity]` | Cannot carry `affiliation`, which Q13 requires, and ADR-0013 keeps `Entity` identity-only — hence `EntityMention` composition |

---

## References

- ADR-0013 (entity model) — the separate-model decision this channel surfaces
- ADR-0009 (orthogonal concerns) — compose-don't-merge: attributes on the
  `EntityMention` wrapper, never on `Entity`
- ADR-0012 (FactKind unfreeze) — reserved; the freeze this channel routes around
- Atlas Evaluation Matrix — Part II Phase 1, "Execution note — M-P1.2 entity
  emission channel"
- `src/atlas/analysis/base.py` — `EntityMention`, `AnalysisResult.entities`
- `src/atlas/analysis/earnings_transcript.py` — the first producer
- `src/atlas/company/model.py`, `store.py` — `ParticipantAppearance` and its
  persistence
