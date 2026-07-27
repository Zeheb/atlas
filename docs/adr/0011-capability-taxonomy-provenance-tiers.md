# ADR-0011 — Capability Taxonomy and Evidence Provenance Tiers

**Date:** 2026-07-23
**Status:** Accepted

---

## Context

The Atlas Evaluation Matrix (adopted as the project's canonical capability
benchmark) grades Atlas against 45 real research questions and sequences a
roadmap by benchmark-coverage-per-unit-effort. Making that benchmark permanent
evaluation infrastructure — rather than a one-time planning document — requires
two architectural concepts to exist in code, not just in prose. This ADR
records both. Neither changes any reasoning, retrieval, or analysis behavior;
both are description layers the benchmark uses to route and grade.

**Decision 1 — a second benchmark axis.** `benchmark/taxonomy.py` already owned
one axis, `RetrievalScenario`, which classifies *the retrieval problem a case
poses* (its purpose is suite coverage — "can the suite detect a retrieval
regression?"). The matrix needs a second, independent axis classifying *what
the system must be able to do to answer a question at all* (its purpose is
grade assignment and roadmap routing — "what must be built?"). A retrieval
scenario is a property of a *case*; a capability is a property of a *question*.
Without the second axis, every roadmap decision is argued in prose the eval
harness cannot check, and the benchmark's central finding — that structuring
gaps (`struct.*`), not acquisition, dominate the 45 — is unmeasurable.

The obvious wrong move is to reuse the `CAP_*` constants already in
`eval/cases.py`. Those are *milestone availability gates* ("does this build
have the feature, so should the case run or be marked pending?"). A capability
describes what a question demands, independent of any milestone. A single case
legitimately carries both. Merging them would make "what the question needs"
and "what this build provides" the same field, which they are not.

**Decision 2 — evidence provenance tiers.** Atlas's organising constraint is
that *every claim must be traceable to a document Atlas actually acquired.* The
roadmap's later phases deliberately admit non-filing evidence — market-structure
circulars, macro/trade data, brokerage notes, forum threads, regulatory
registers. A forum post *is* a document under the constraint, so nothing
structural stops it being weighed like an audited annual report. Something must.
The benchmark's evidence-family analysis already sorts every external family by
a three-way provenance quality, and that sorting is load-bearing: it is why the
roadmap admits market *structure* (document-backed) while excluding market
*price* (no document behind it) under an otherwise identical surface.

---

## Decision

**We adopt two orthogonal classification concepts, and implement each at the
point its first consumer exists.**

### 1. `AtlasCapability` — the capability axis (implemented, M-E.1)

A closed vocabulary of **24 capabilities in six families**, living in
`benchmark/taxonomy.py` beside `RetrievalScenario`, mirroring its
Literal↔frozenset↔descriptions discipline:

- **Acquisition** (`acq.*`) — does Atlas hold the document? (kind coverage,
  history depth, entity coverage, tier admission)
- **Structuring** (`struct.*`) — does the document become a typed, comparable
  fact? (typed fact, time series, entity identity, event linkage)
- **Retrieval** — *intentionally empty* (see the admission rule below)
- **Reasoning** (`reason.*`) — can a defensible answer be formed? (grounded
  answer, derived metric, comparative, judgment qualification)
- **Memory** (`mem.*`) — does knowledge persist and accumulate? (view
  persistence, view history, staleness, recurrence)
- **External** (`ext.*`) — is non-filing evidence available and correctly
  weighted? (market structure, market price, third-party opinion, macro/trade,
  entity background)
- **Evaluation** (`eval.*`) — can the benchmark detect a good answer?
  (gradeable, provenance-checkable, stability)

**The admission rule** (test-enforced in `test_benchmark_taxonomy.py`, so the
vocabulary cannot silently re-inflate):

> A question-grading capability is admitted only if it is **either** primary
> for at least one benchmark question, **or** a declared prerequisite gate for
> another capability — **and** it is not a restatement of a `RetrievalScenario`
> member.

The anti-restatement clause is why the **retrieval family is empty by
construction**. Atlas's retrieval is strong enough (an audited planner, the
boosts-never-filters fallback guarantee, `negative_retrieval` already a
scenario) that it is nowhere the weakest link in the 45; under
"a question's grade is its weakest required capability," no retrieval capability
can ever be primary, and each candidate merely renamed a scenario tag. Retrieval
difficulty is therefore measured wholly on axis 1, never duplicated on axis 2.

`eval.*` is **exempt by construction, not by exception**: it grades *cases*
(whether the suite can detect a good answer), not questions, so the admission
rule — scoped to question-grading capabilities — does not reach it. Its mapping
to zero benchmark questions is correct.

### 2. Evidence provenance tiers — the concept (ratified now; field deferred)

Three tiers, to become an `Evidence.tier` attribute:

- **Tier 1 — Primary.** The entity's own regulated disclosure. Auditable,
  dated, attributable. (All current Atlas evidence is Tier 1.)
- **Tier 2 — Official secondary.** A regulator, exchange, or government body
  reporting *about* the entity or its environment.
- **Tier 3 — Third-party assertion.** Opinion, commentary, or aggregation with
  no regulatory obligation. Represents *someone claims X*, not *X*.

The tier is the mechanism that lets Atlas admit a forum post as a document
without weighing it like a filing. **The field is not implemented in this ADR.**
Its first consumer is the `acq.tier_admission` capability, which does not fire
until the roadmap's Phase 5 (milestone M-P5.1 builds `Evidence.tier` alongside
the first external connector). Adding the field now would ship a dead attribute
every producer sets to `TIER_1` and no consumer reads — exactly the kind of
speculative surface ADR-0009 warns against. This ADR fixes the *concept and its
three values* so that the split decisions the benchmark already relies on
(EF3a market-structure Tier 2 vs. EF3b market-price Tier 3; EF6a registers
Tier 1 vs. EF6b reported-background Tier 3) have a ratified vocabulary to name,
and defers the attribute to the phase that consumes it.

---

## Consequences

**Positive:**
- The benchmark's grade and roadmap arguments become machine-checkable: a case
  can carry the capability its question demands, and coverage over the 24 can be
  measured rather than asserted.
- The two-axis split makes the orthogonality that ADR-0005's framework implied
  explicit and enforced — a capability can never quietly restate a retrieval
  scenario and double-count retrieval in roadmap arithmetic.
- The tier vocabulary gives the provenance-first constraint a graded form,
  which is what lets Atlas plan to admit weaker sources *without* abandoning the
  constraint — the tier records how much to trust, rather than a binary
  in/out.

**Negative / Trade-offs:**
- Two capability-shaped vocabularies now coexist (`AtlasCapability` and
  `eval/cases.py`'s `CAP_*`). The docstring and this ADR must keep the
  distinction load-bearing; a future contributor who conflates them would
  reintroduce the exact merge this ADR forbids.
- Ratifying the tier concept while deferring the field means the split evidence
  families (EF3a/EF3b, EF6a/EF6b) name a tier that has no runtime representation
  yet. The gap between decision and implementation is intentional but must be
  tracked to Phase 5.

**Risks:**
- The admission rule requires judgment for future capabilities (is a proposed
  capability primary for some question, or a real gate?). The test enforces
  count and disjointness, not the semantic judgment behind each member.
- Tier assignment for genuinely mixed sources (a regulator republishing a
  third-party score) will need a rule when the field is built; this ADR fixes
  the three values but not the assignment procedure, which Phase 5 must supply.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Reuse `eval/cases.py`'s `CAP_*` constants instead of a new axis | They answer a different question — milestone availability, not question demand. A case needs both; merging them collapses two orthogonal facts into one field |
| Keep a populated `retrieval` capability family | Every candidate restated a `RetrievalScenario` member and was primary for no question; keeping them double-counts retrieval and violates the admission rule. Empty-by-construction is the cleaner orthogonality statement |
| A single continuous evidence "trust score" instead of three discrete tiers | A score invites fabricated precision and hides the actual decision (which *class* of source is this?). The three tiers map to auditable source classes; a 0–1 score does not |
| Implement `Evidence.tier` now | No consumer until Phase 5; the field would be dead surface set to `TIER_1` everywhere, which ADR-0009's discipline argues against |
| Fold both decisions into ADR-0005 (benchmark framework) | ADR-0005 is the framework that measures whether the *suite* is adequate; these are two new vocabularies the framework consumes. Distinct enough to record separately, per the one-decision-per-ADR house style |

---

## References

- Atlas Evaluation Matrix — §5 (evidence families and provenance tiers), §6
  (`AtlasCapability` taxonomy, orthogonality, admission rule), §9 (this ADR
  listed as an implied artifact)
- ADR-0004 (retrieval evaluation), ADR-0005 (benchmark framework) — the
  measurement machinery this axis feeds
- ADR-0009 (orthogonal concerns) — the compose-don't-merge discipline behind
  both the two-axis split and the deferral of `Evidence.tier`
- `src/atlas/benchmark/taxonomy.py` — `AtlasCapability`, `ALL_CAPABILITY_IDS`,
  `CAPABILITY_DESCRIPTIONS` (M-E.1)
- `src/atlas/eval/cases.py` — the `CAP_*` milestone gates this ADR keeps
  distinct from capabilities
