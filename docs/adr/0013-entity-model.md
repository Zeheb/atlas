# ADR-0013 — Person/Organization Entity Model and Resolution

**Date:** 2026-07-23
**Status:** Accepted

---

## Context

Atlas records the names of people and organizations as bare strings, in several
places that never reconcile with one another: `company.model.DirectorChange.name`
("as stated in filing"), the participant directory parsed inside
`analysis/earnings_transcript.py` (parsed, then discarded), and the named >1%
public shareholders in the shareholding-pattern XBRL (skipped in favor of
aggregates). Five benchmark questions in the Atlas Evaluation Matrix (Q13, Q14,
Q15, Q24, Q45) are graded on `struct.entity_identity` — "the fact names a
resolvable entity rather than a string" — and none can advance while every name
is an unresolved string.

The frozen execution plan's Phase 1 (M-P1.1) calls for "a resolvable Person/Org
entity model + resolution," explicitly as the foundation the later emission
milestones (M-P1.2–M-P1.6) consume. It also names one decision this ADR must
settle: whether entity attributes are new `FactKind`s, or a separate model.

Two placement facts bear on the decision. First, `analysis` is a pipeline stage
("text → typed facts"); `FactKind` belongs there because a fact-type vocabulary
is intrinsic to that transformation. An Entity is not a fact — it is a domain
noun referenced by many analyzers and assembled above them. Second, the
`knowledge/` package was scaffolded at project start as a four-part knowledge
graph — `entities/`, `events/`, `timeline/`, `relationships/` — of which
"documents → retrievable text" is only the built slice. A later commit trimmed
the architecture *description* to built reality but left the scaffold in place.

---

## Decision

**A Person/Organization is a separate domain entity, owned by the knowledge
layer, resolved by a conservative deterministic resolver. It is not a
`FactKind`.**

1. **Separate model, not a FactKind.** Entities are the *referents* of facts,
   not facts. Modeling them as `FactKind`s would conflate referent with fact and
   — because the `FactKind` ontology is frozen — would drag M-P1.1 behind the
   Phase-2 unfreeze (ADR-0012) for no benefit. A separate model lets Phase 1
   proceed independently.

2. **Owned by `knowledge`, re-activating the scaffold.** The model lives in
   `src/atlas/knowledge/entities/` (`model.py`, `resolver.py`), turning frozen
   scaffold into live code. This is the correct long-term home: an entity is a
   domain object, and placing it in `analysis` would bind a cross-cutting domain
   noun to one pipeline stage. `knowledge` sits below every consumer
   (`analysis`, `company`, …), so all future milestones may import it with no
   new cross-layer edge and no import-boundary change.

3. **Deterministic, conservative resolver.** `EntityResolver` maps observed
   name strings to `Entity` objects. It is the required deterministic baseline
   (ADR-0007 planner-invariant discipline); an LLM resolver may later sit behind
   the same surface, but the deterministic floor remains. It **prefers
   under-merging to over-merging**: a candidate merges only when it matches
   exactly one existing entity; zero or ≥2 matches create a new (separate)
   entity. Person matching is surname + positional initial-expansion, compared
   against each entity's canonical form only; organization matching is exact
   normalized-token equality.

4. **Two `entity_id` invariants, test-enforced.**
   - *Stability:* the id is assigned once at creation from the first-observed
     name and never changes — not on merge, not when a fuller `canonical_name`
     is discovered. `Entity` is frozen, so a canonical update produces a
     replacement carrying the same id.
   - *Uniqueness:* no two distinct entities share an id; a disambiguation suffix
     is appended when a distinct entity's first-seen slug would otherwise
     collide.

5. **In-memory only.** No persistence in M-P1.1; ids are stable and unique
   within a resolver's lifetime. A cross-run stable-id scheme is designed when
   persistence lands, alongside CompanyProfile wiring.

---

## Consequences

**Positive:**
- The five `struct.entity_identity` questions gain the primitive they need,
  without touching the frozen FactKind ontology.
- The knowledge-graph layer the scaffold always intended is re-activated at its
  designed location, rather than a domain object being smuggled into a pipeline
  stage for implementation convenience.
- Under-merge-by-default keeps a provenance-first corpus safe: the resolver
  never fabricates a merge, so it never silently corrupts attribution.

**Negative / Trade-offs:**
- Under-merging means some genuine variants stay separate (two records for one
  person) until a later, richer resolver reconciles them. Accepted: recoverable,
  and far cheaper than the alternative failure.
- The architecture doc's §2 knowledge-layer description now understates the
  layer (it still says "documents → text"). Deferred deliberately: the doc
  "describes the real system," and entities are not yet load-bearing until an
  analyzer emits them (Phase-1 completion), when §2 is expanded.

**Risks:**
- Organization matching (exact only) will under-merge suffix variants ("Acme
  Ltd" vs "Acme Services Ltd" are correctly *not* merged, but "Acme Ltd" vs
  "Acme Limited" also won't merge yet). Suffix normalization is a later
  refinement, deliberately out of the M-P1.1 baseline to avoid over-merging.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Model entities as new `FactKind`s | Conflates referent with fact; would drag M-P1.1 behind the Phase-2 ontology unfreeze for no benefit |
| Place the model in `analysis/entities.py` (beside `FactKind`) | Convenience-driven — it only avoided an architecture-doc note. Binds a cross-cutting domain object to one pipeline stage; fails the long-term-ownership test |
| Aggressive initial-based merging | Over-merges distinct people sharing initials and a common surname ("K S Rao" fusing Kumar/Krishna/Kiran) — a silent attribution error in a provenance-first system |
| Persist entities now (EntityStore) | No consumer until CompanyProfile wiring; would ship dead surface. Deferred with the rest of persistence |
| ADR number 0012 | 0012 is reserved for the FactKind unfreeze (Phase 2) in the frozen execution plan; taking it would force a later reconciliation of the frozen ADR ledger |

---

## References

- Atlas Evaluation Matrix — §6 (`struct.entity_identity`), Part II Phase 1
  (M-P1.1–M-P1.6), ADR ledger (0012 reserved for the FactKind unfreeze)
- ADR-0007 (planner invariants) — the deterministic-baseline discipline this
  resolver follows
- ADR-0009 (orthogonal concerns) — why an entity (referent) is not merged into
  the fact vocabulary
- ADR-0012 (FactKind ontology unfreeze) — reserved; the Phase-2 dependency this
  ADR's separate-model decision keeps M-P1.1 clear of
- `src/atlas/knowledge/entities/model.py`, `resolver.py` — the implementation
- `src/atlas/company/model.py` — `DirectorChange.name`, the bare-string status
  quo this model will later resolve
