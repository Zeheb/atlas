# ADR-0008 — Thesis Generation (M2.3)

**Status:** Proposed
**Date:** 2026-07-21 (revised 2026-07-21)
**Related:** ADR-0003 (retrieval planning), ADR-0004 (retrieval evaluation),
ADR-0005 (benchmark framework), ADR-0006 (research planning),
ADR-0007 (planner invariants), ADR-0009 (orthogonal concerns)

> **Revision note.** The original draft of this ADR proposed a `ThesisClaim`
> type that duplicated five fields already present on `reasoning.contracts.
> Finding` (C7): `statement`, `confidence`, `assertability`, `counter_case`,
> `known_unknowns`. A follow-up review (recorded in ADR-0009) applied the
> orthogonal-concerns test to that proposal and found the duplication. This
> revision removes `ThesisClaim` entirely, treats the existing
> `InvestigationResult` (M2.2.5) as the aggregation boundary, and models
> sibling contradictions as `Thesis`-level relation records rather than
> per-claim links. The provenance gate, the obligation model, and the
> no-silent-omission rule are unchanged from the original draft — those were
> correct the first time.

## Context

M2.2.5 delivered decomposition: an open question becomes a `ResearchPlan`, each
investigation is grounded through the retrieval pipeline, and the result is a
set of provenance-backed findings plus explicit unresolved entries. Atlas can
now *gather*. It cannot yet *conclude*.

M2.3's job is exactly one thing: turn `InvestigationResult`s into an argued
view, without ever asserting anything the evidence does not support.

### Three discoveries that shape this design

**1. Atlas already has two types named `Finding`.**

| | `reasoning.contracts.Finding` (C7) | `research.citations.Finding` |
|---|---|---|
| Status | §10 contract, frozen, self-validating | not frozen, rendering-oriented |
| Carries | `statement`, `assertability`, `confidence`, `supporting_claims`, `contradicts_thesis`, `counter_case`, `known_unknowns` | `text`, `evidence_ids`, `section`, `page`, `kind` |
| Enforces | *"A judgment Finding requires >=1 supporting claim (G3/G4)"* | nothing |

The C7 type is already conclusion-shaped. It has fields for contradiction
(`contradicts_thesis`, `counter_case`) and uncertainty (`confidence`,
`known_unknowns`) that predate this milestone.

**2. M2.2.5's `investigate.py` discards that metadata.**
`run_investigation` flattens `ReasoningResult.findings` (rich C7 objects) into
`answer.prose` plus a list of evidence ids. Assertability, confidence,
contradiction flags and per-finding known-unknowns are computed by the
reasoning layer on every investigation and thrown away at the research
boundary.

So M2.3 must **stop discarding existing vocabulary**, not invent parallel
vocabulary for the same concepts.

**3. `InvestigationResult` (M2.2.5) is already the right aggregation unit.**
It already pairs one `Investigation` (which carries `.dimension`) with its
grounded outcome. Once discovery 2 is fixed — `InvestigationResult` gains the
preserved C7 findings — it already carries everything a "thesis claim" would
have needed: which dimension, which findings, whether it resolved. No new type
is required to hold that pairing. This removes the `ThesisClaim` wrapper the
original draft proposed; see the revision note above and ADR-0009 for the
general rule this instance follows.

### One constraint inherited from the existing product

`the_call.py` states, in Atlas's own output: *"Atlas does not issue a buy/sell
recommendation and has no market price data — this is an evidence briefing, not
a rating."*

**M2.3 does not change this.** A `Thesis` carries an argued view about what the
evidence shows; it carries no rating, no target price, and no position sizing.
Anything else would make Atlas an unlicensed advisor, and the architecture
should make that structurally impossible rather than merely discouraged.

---

## 1. Decision: preserve C7, widen `Finding.kind`, no new claim type

### 1a. `investigate.py` preserves C7 findings instead of flattening them

`InvestigationResult` gains an additive field carrying the reasoning layer's
own findings unmodified:

```
InvestigationResult
    investigation       Investigation        # unchanged (M2.2.5) — carries .dimension
    finding              research.citations.Finding | None   # unchanged (M2.2.5) — flattened prose, for report rendering
    semantic_findings    tuple[contracts.Finding, ...] = ()  # NEW — the raw C7 findings, preserved
    unresolved_reason, plan, retrieval                        # unchanged (M2.2.5)
```

`semantic_findings` is additive and defaults to `()`, so every existing
M2.2.5 test and call site is unaffected. This is composition, not a merge:
`dimension` lives where it already lived (on `Investigation`, reached via
`InvestigationResult.investigation.dimension`); the C7 `Finding` is carried
unmodified, with no research-layer field added to it. This is the worked
example in ADR-0009.

### 1b. `research.citations.Finding.kind` widens (the gate's input)

The five proposed values are not speculative — all five already exist in the
codebase, under two labels:

| Proposed kind | Exists today at | Currently labelled |
|---|---|---|
| `FACT` | `balance_sheet.py:65` | `"fact"` |
| `DERIVED` | `the_call.py:95` (inherits underlying evidence ids) | `"synthesis"` |
| `EVIDENCE_NOTE` | `the_call.py:100` ("No sufficiently reliable risk factor…") | `"synthesis"` |
| `DISCLOSURE` | `the_call.py:109` ("Atlas does not issue…") | `"synthesis"` |
| `CONCLUSION` | — | does not exist yet |

Widening `kind` is therefore *recording a distinction that is already real*,
not adding a taxonomy. `research.citations.Finding` should additionally be
**made frozen**, matching every other data type in this dependency chain — it
is currently the only mutable `@dataclass` here.

### 1c. No `ThesisClaim`. The thesis-level narrative reuses `Finding(kind=DERIVED)`

A `Thesis` needs one thing neither `InvestigationResult` nor a bare C7
`Finding` provides: a synthesized overview statement whose evidence is the
union of what it draws on. That is exactly what `DERIVED` already means
(`the_call.py:95` does this today, mechanically). M2.3's `Thesis.narrative` is
a `research.citations.Finding` with `kind=DERIVED` — reusing the existing,
now-frozen type rather than introducing a container for it.

**Rejected: a `ThesisClaim` type duplicating C7's fields.** This was the
original draft's mistake (see revision note). Rejected under ADR-0009's test:
its fields were "mostly a copy of an existing type's fields."

**Rejected: conclusions as a sixth `kind` on `Finding` with optional
fields.** Still rejected, for the reason the original draft gave: it makes
`Finding`'s validity conditional on a string field, untestable the way the
frozen types elsewhere are testable. `CONCLUSION` is a real, distinct `kind`
value (§1b) used for *rendering* a thesis claim as a `Finding` when it appears
in a report — it does not imply a new container type.

---

## 2. Decision: the provenance gate

Unchanged from the original draft. Restated here because it is the part of
this design that must not soften under any future revision.

### 2a. Obligation is declared, never inferred

The gate must **never** infer obligation from whether citations happen to be
present. That inference is precisely the latent bug this review found: today
`evidence_ids == []` means both *"this is a disclosure"* and *"this is
ungrounded"*, and no code can tell them apart.

Each `kind` maps to a declared obligation:

| Kind | Obligation | Rationale |
|---|---|---|
| `FACT` | **REQUIRED** | a claim about the company must be traceable |
| `DERIVED` | **REQUIRED** | inherits the ids of the findings it derives from |
| `CONCLUSION` | **REQUIRED** | plus every id must trace to an investigation (§2b) |
| `EVIDENCE_NOTE` | **OPTIONAL** | a statement about evidence quality or absence may cite what it examined, or nothing |
| `DISCLOSURE` | **FORBIDDEN** | a statement about Atlas's own limits is not an evidence claim; citing evidence for it is a category error |

Three levels, not two. `FORBIDDEN` is the one that would be lost in a binary
must-cite/optional split, and it catches a real error class: a policy
statement dressed up as an evidence-backed finding.

### 2b. The closed-world rule

Every evidence id cited anywhere in a `Thesis` — in a `claims` entry's
underlying C7 findings, or in `narrative`'s evidence ids — must appear in the
**evidence index of the `InvestigationRun` that produced the thesis**.

This is what stops the synthesis step from citing real-but-unretrieved
documents — a hallucination that passes a naive "does this id exist?" check.
It is the same inverted-check discipline `benchmark/validation.py` already
applies to negative cases.

### 2c. No silent omission

The deterministic report's trustworthiness comes from a reader always seeing
the full extent of what Atlas checked (`report.py`). The thesis inherits that
property:

> Every investigation in the plan must be accounted for in the thesis's
> `dispositions` as exactly one of: **supporting**, **contradicting**,
> **not material**, or **unresolved** — regardless of whether it also appears
> in `claims`.

A synthesis that quietly drops an inconvenient finding fails the gate. This is
the single most valuable rule in this document: it is what prevents a thesis
that is technically well-cited and substantively dishonest.

### 2d. The gate is a separate function, not only `__post_init__`

`Thesis.__post_init__` enforces what is checkable from the object alone
(non-empty claims, no duplicate dimensions, well-formed dispositions). The
**gate** is a distinct pure function that additionally checks the thesis
against the `InvestigationRun` — the closed-world rule and no-silent-omission
need the run in scope.

This mirrors M2.2.5 precisely: `ResearchPlan.__post_init__` validates
structure; `benchmark.coverage.analyze_research_plans` judges quality against
a corpus of plans.

---

## 3. Proposed data model

Illustrative shapes, not implementation. Every new type frozen and
self-validating, per ADR-0007's invariant 5. No type here duplicates an
existing one's fields — each addition is checked against ADR-0009 §"the
test": composition over merging, reference over copying.

```
Materiality    = Literal["supporting", "contradicting", "not_material", "unresolved"]
Resolution     = Literal["unresolved", "prefer_left", "prefer_right", "both_hold"]

Contradiction                                     # a RELATION, not a data copy
    left_dimension        ResearchDimension        # look up the statement via Thesis.claims
    right_dimension       ResearchDimension        # same
    description           str                      # the diagnosed disagreement, in words
    resolution            Resolution
    resolution_rationale  str                      # required even for "unresolved"

Disposition                                       # the no-silent-omission ledger; ONE per investigation in the plan
    dimension             ResearchDimension
    materiality           Materiality
    rationale             str                      # required when materiality == "not_material"

Thesis
    question              str
    subjects              tuple[str, ...]
    plan_fingerprint       str                      # which ResearchPlan produced this
    run_fingerprint        str                      # which InvestigationRun grounded it
    claims                 tuple[InvestigationResult, ...]   # RESOLVED results only, reused as-is (M2.2.5)
    narrative              Finding                  # research.citations.Finding, kind=DERIVED
    contradictions         tuple[Contradiction, ...]
    dispositions           tuple[Disposition, ...]  # one per investigation in the plan, no exceptions
    overall_confidence     ConfidenceLevel          # REUSED from contracts.py, never redefined
    unresolved_dimensions  tuple[ResearchDimension, ...]
    synthesizer_version    str
```

**What's gone from the original draft, and why:** `ThesisClaim` (duplicated
C7 fields — ADR-0009); per-claim `contradicted_by` links (bidirectional
bookkeeping that can desync — a `Contradiction` referencing both sides by
dimension key is the single source of truth); `known_unknowns` as a top-level
`Thesis` field (each `InvestigationResult`'s underlying C7 findings already
carry their own `known_unknowns` — a thesis-level rollup, if wanted, is
computed from `claims`, not stored twice).

**No `stance`, `rating`, `target_price`, or `position_size` field.** Their
absence is deliberate and load-bearing (see Context).

`ConfidenceLevel` is imported from `reasoning/contracts.py`, never redefined —
the corollary in ADR-0009 applied to the one vocabulary this type needs.

---

## 4. Invariants

**Thesis is immutable and self-validating** — yes, unambiguously. Same
discipline as `SearchPlan` and `ResearchPlan`, and for the same reason: it is
the boundary where a model's output becomes structured data, so a malformed
thesis must raise at construction rather than propagate into a report a human
will read.

Enforced in `__post_init__`:

1. `claims` non-empty (a thesis that concludes nothing is not a thesis).
2. Every entry in `claims` is a *resolved* `InvestigationResult`
   (`.finding is not None` or `.semantic_findings` non-empty) — an unresolved
   result belongs in `dispositions` only, never in `claims`.
3. No two entries in `claims` share a `dimension` (mirrors `ResearchPlan`'s own
   no-duplicate-dimension rule).
4. Every `Contradiction.resolution_rationale` non-empty — including for
   `"unresolved"`, where the rationale explains *why* it cannot be resolved.
5. Every `Contradiction`'s `left_dimension`/`right_dimension` refers to a
   dimension present in `claims`.
6. Every `Disposition` with `materiality="not_material"` carries a rationale.
7. `dispositions` covers every investigation in the plan exactly once — no
   duplicates, no gaps (this is checkable from the object plus the plan
   fingerprint alone; cross-referencing the actual run is the gate's job, §8).
8. `narrative.kind == DERIVED` and `narrative.evidence_ids` is non-empty.

Enforced by the **gate** (needs the `InvestigationRun`, not just the `Thesis`):

9. **Closed world**: every cited id, anywhere in the thesis, appears in the
   run's evidence index.
10. **No silent omission**: every `InvestigationResult` in the run maps to
    exactly one `Disposition` (structural invariant 7 checks internal
    consistency; this checks the thesis against the actual run).
11. **Unresolved carry-through**: every unresolved investigation appears in
    `unresolved_dimensions`.

**Uncertainty never weakens grounding.** Confidence and citation obligation are
orthogonal axes, and the gate must treat them as such:

> A low-confidence claim is cited exactly as strictly as a high-confidence one.
> `confidence` may never be used to excuse a missing citation.

This is the specific failure mode to design against — "we weren't sure, so we
didn't cite it" is how a grounding guarantee dies quietly. Uncertainty is
expressed through each claim's underlying C7 `confidence`/`known_unknowns`/
`counter_case`, through `unresolved_dimensions`, and through
`Contradiction.resolution="unresolved"` — never through weaker citation.

---

## 5. Contradiction handling

Contradictions are **first-class and preserved**, never averaged into a
hedge.

1. **Detected from existing signal.** The reasoning layer already sets
   `contradicts_thesis` and `counter_case` on C7 findings; §1a's fix means
   this signal survives into `InvestigationResult.semantic_findings` instead
   of being discarded. Cross-investigation contradiction (two dimensions
   disagreeing with each other, as opposed to one finding disagreeing with a
   prior C6 thesis fed back through `GroundingContext` — a different concept,
   see §6) is detected at synthesis time by comparing `claims` entries.
2. **Resolved explicitly or not at all.** `resolution` is one of four values
   and always carries a rationale. "Both hold" is a legitimate answer — a
   company can have improving margins and deteriorating cash conversion.
3. **Never silently dropped.** Guaranteed by no-silent-omission (§2c).
4. **Referenced, not copied.** A `Contradiction` names the two dimensions in
   disagreement; the actual statements are read from `Thesis.claims`, never
   restated in the `Contradiction` record. One source of truth for what each
   side actually said.

The benchmark already has a `conflict_resolution` retrieval scenario
(ADR-0005), so evaluation cases for this exist in vocabulary terms; M2.3 adds
thesis-level cases against it.

---

## 6. `research.Thesis` and the deferred C6 slot are different objects

`reasoning/contracts.py` reserves a `C6 Thesis` slot: `GroundingContext.thesis:
None = None  # C6, deferred to M2`, and C7 `Finding.contradicts_thesis`
already anticipates checking a new finding against a previously-established
view fed back into grounding.

That is **not** the object this ADR defines. C6, when it is defined, must be a
consumer-agnostic projection (subject, claims, evidence ids, confidence —
nothing research-specific), because `GroundingContext` is consumed by
Conversation, Research, and Attention alike. `research.Thesis` as specified in
§3 is Research-specific (dimensions, dispositions, plan/run fingerprints) and
would violate ADR-0009's corollary if placed in `contracts.py`.

**Decision:** `research.Thesis` lives in `research/`. C6 stays undefined until
thesis-feedback-into-grounding is actually built — expected around M2.4, where
a stored thesis needs to be re-checked against new filings for staleness. When
that milestone defines C6, `research.Thesis` should project down to whatever
minimal shape C6 turns out to need, rather than C6 being guessed now from
`research.Thesis`'s shape. See ADR-0009 for the general argument.

---

## 7. Pipeline

```
InvestigationRun  (M2.2.5, extended per §1a to preserve semantic_findings)
      │
      ▼
ThesisSynthesizer          plan-only at first: deterministic baseline
      │                    (an LLM synthesizer implements the same Protocol,
      │                     per ADR-0007 invariant 2)
      ▼
Thesis  (frozen, self-validating — invariants 1-8)
      │
      ▼
provenance gate            closed-world + no-silent-omission (invariants 9-11)
      │                    needs the InvestigationRun in scope
      │
      ├── PASS ──► render (claims as Findings, narrative already a Finding)
      └── FAIL ──► structured GateViolation list; nothing is rendered
```

A failing gate **blocks rendering entirely**. It does not warn. A thesis that
cites unretrieved evidence or silently drops a contradicting finding is not a
degraded thesis; it is a wrong one.

Per ADR-0007 invariant 2, the first synthesizer is a **deterministic
baseline** — it can produce a defensible thesis from the highest-confidence
finding per dimension with no LLM at all. This is not a throwaway: it is the
control arm the LLM synthesizer is measured against by the existing
`ComparisonEngine`, exactly as `BaselineStrategy` serves retrieval.

---

## 8. Acceptance criteria

1. **Gate blocks, not warns**: a thesis citing an id outside the run's
   evidence index is rejected; nothing renders.
2. **Adversarial gate tests**: deliberately constructed bad theses (uncited
   conclusion, disclosure carrying citations, dropped contradiction,
   cited-but-unretrieved id, unresolved investigation missing from
   `dispositions`) are each rejected by a named test. *A gate never shown to
   fail is not a gate* — the M2.2.5 precedent.
3. **No silent omission**: property test over generated runs — every
   `InvestigationResult` appears in exactly one `Disposition`.
4. **Uncertainty orthogonality**: a low-confidence claim with no citations is
   rejected exactly as a high-confidence one is.
5. **No rating surface**: `Thesis` exposes no stance/rating/target field;
   asserted by test over its field set, so a future edit cannot add one
   silently.
6. **Contradictions preserved**: a run containing two genuinely contradicting
   findings produces a thesis where both remain visible via `claims`, linked
   by a `Contradiction`.
7. **Deterministic baseline exists** and produces a gate-passing thesis with
   no LLM call at all (`--dry-run` equivalent, per ADR-0007 invariant 3).
8. **Vocabulary reuse**: `ConfidenceLevel` imported from `contracts.py`;
   `narrative` constructed as a `Finding(kind=DERIVED)`, not a new type;
   asserted by import test and by a test that no new "claim" type was
   introduced (field-set comparison against `InvestigationResult`).
9. **`the_call.py` unchanged**: `git diff --stat main` empty for
   `research/report.py` and `research/sections/`. The mechanical synthesis
   stays as the comparison baseline.
10. **`InvestigationResult`'s M2.2.5 tests are unaffected**: `semantic_findings`
    defaults to `()`; every existing test in `test_research_investigate.py`
    passes unmodified.
11. Full suite green; no pre-existing test modified except for additive
    fields.

---

## 9. Milestone breakdown

Narrow by construction: synthesis only. No retrieval change, no planner
change, no report change.

| # | Commit | Scope |
|---|---|---|
| 1 | `refactor(research): widen Finding.kind; make Finding frozen` | the 5 kinds + obligation map; existing call sites relabelled `"synthesis"` → `DERIVED`/`EVIDENCE_NOTE`/`DISCLOSURE`. No behavior change. |
| 2 | `feat(research): preserve C7 finding metadata through investigate` | `InvestigationResult.semantic_findings`, additive; stop discarding `assertability`/`confidence`/`contradicts_thesis`/`counter_case`/`known_unknowns` at the research boundary |
| 3 | `feat(research): Thesis data model` | `Thesis`, `Contradiction`, `Disposition`; frozen, self-validating; invariants 1–8. No `ThesisClaim`. |
| 4 | `feat(research): provenance gate` | closed-world + no-silent-omission + `GateViolation`; invariants 9–11; adversarial tests |
| 5 | `feat(research): deterministic baseline synthesizer` | no LLM; the control arm |
| 6 | `feat(research): LLM synthesizer behind the same Protocol` | plus `atlas thesis` CLI with a gate-blocked render path |
| 7 | `feat(eval): thesis quality dimension + acceptance verification` | benchmark cases incl. `conflict_resolution`; comparison of baseline vs LLM synthesizer |

Commits 1–2 are preparatory and behavior-preserving; the milestone's risk is
concentrated in 4 and 6, which is why the gate lands before the LLM
synthesizer that needs it.

### Explicitly out of scope

Portfolio/memory (M2.4), staleness detection and C6's actual definition (M2.4,
per §6), diligence orchestration (M2.5), any rating or price target
(permanently), and multi-subject grounding (still M2.2's, per ADR-0006).
