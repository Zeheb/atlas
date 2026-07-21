# ADR-0009 — Orthogonal Concerns and Consumer-Agnostic Contracts

**Date:** 2026-07-21
**Status:** Accepted

---

## Context

The M2.3 (thesis generation) design review asked a concrete question: should
`reasoning.contracts.Finding` (C7) become the one canonical finding type
throughout Atlas, or should a new `ThesisClaim` type be introduced for
synthesized conclusions?

Answering it required tracing what C7 `Finding` actually requires to
construct (a `Claim`, which requires a `subject_ref` and a tuple of
`EvidenceReference`s) against what the eleven deterministic report-section
builders actually have available (a bare `list[str]` of evidence ids, with no
`Claim` ever constructed, because there is no LLM confidence judgment to
encode). Forcing one canonical type across both producers would have made the
deterministic path fabricate `Claim`s with no information gain, purely to
satisfy a type.

The first draft of the M2.3 proposal made the opposite mistake in the other
direction: it introduced `ThesisClaim` carrying `statement`, `confidence`,
`assertability`, `counter_case`, and `known_unknowns` — five fields that
already exist verbatim on C7 `Finding`. That draft was corrected during review.

Both mistakes are instances of the same failure, in opposite directions:
merging things that are not the same concern, and duplicating a type instead
of composing with it. This ADR names the rule that would have caught both
mistakes before they were drafted.

---

## Decision

**General principle:**

> Orthogonal concerns compose; they are not merged.

Two concerns are orthogonal when adding one's field to the other's type would
either make some existing field meaningless in certain states, or would let
the type be constructed in a way only one of the concerns can actually
interpret. When that test is true, the concerns get separate types, and one is
composed with (wraps, references, or sits alongside) the other. Neither is
extended to carry the other's vocabulary.

**Corollary (the contract boundary):**

> Shared subsystem contracts remain consumer-agnostic. Consumer-specific
> vocabulary is added by a thin wrapper or a sibling type, never by extending
> the shared contract.

A "shared contract" here means a type documented as consumed identically by
more than one subsystem — the §10 contracts in `reasoning/contracts.py` are
the canonical example, explicitly documented as consumed identically by
Conversation, Research, and (planned) Attention. A shared contract does not
get a field that only one of its consumers can populate or interpret.

### The test, stated as a question

Before adding a field to an existing type, or before introducing a new type
that duplicates an existing one's fields, ask:

> **Does this field's meaning depend on which consumer is using the type?**

If yes, it is consumer-specific vocabulary and belongs on a wrapper, not on the
shared type. If a proposed new type's fields are largely a copy of an existing
type's fields, that is evidence the new type should instead reference or wrap
the existing one.

---

## Examples from Atlas

### Where the principle applies cleanly

**C7 `Finding` vs. research dimensions (the case that produced this ADR).**
`ResearchDimension` is Research-subsystem vocabulary; C7 `Finding` is consumed
identically by Conversation, Research, and Attention. Adding `dimension` to C7
would make it meaningless for every Conversation-path `Finding` (a plain `atlas
ask` answer has no research dimension) and would coincide with the exact
contract-agnosticism `contracts.py`'s own docstring states as a design goal.
Resolution: `dimension` lives on `InvestigationResult` (already Research-only),
composed with the unmodified C7 `Finding` it wraps — not merged into it.

**Deterministic reports vs. reasoning contracts.** `research/sections/*.py`
builds its own `Finding` (text + evidence ids, no confidence judgment) from
`CompanyProfile`'s bare evidence-id lists. C7 `Finding` requires a `Claim`
(subject, assertability, confidence, structured `EvidenceReference`s). These
are not almost-the-same-type-with-different-names; they answer different
questions ("what does the profile say" vs. "what does the LLM conclude from
grounded context"), and forcing the deterministic path onto C7 would mean
manufacturing a confidence judgment that does not exist. Resolution: two
producers, two types, no wrapper — this is the principle correctly explaining
why *no* unification was attempted, not just where a wrapper is needed.

**`RetrievalPlanner` vs. `ResearchPlanner` (ADR-0006, ADR-0007).** "How to
retrieve for one question" and "what must be investigated before a view can be
formed" are different concerns operating at different scopes (one question vs.
N questions). Neither was merged into the other; `ResearchPlan` composes with
`SearchPlan` by having each `Investigation.question` become the raw input to a
separate `plan_retrieval()` call. Two planners, two frozen plan types, composed
by a fan-out, not a shared type with an `if research_mode:` branch inside it.

### Where the principle does not (yet) apply

**Providers vs. reasoning models.** `reasoning/llm/base.py` documents
`LLMProvider` (the transport: anthropic, ollama, omniroute, …) and model
identity (`Settings.reasoning_model`, a free-form string) as **orthogonal
axes**, in the module's own words — not a shared-contract question at all.
There is no type here whose fields depend on which consumer is using it; there
is one type (`LLMProvider`) naming one axis, and a separate free-form setting
naming the other. This example does not exercise the corollary, because there
is no shared contract being asked to serve two vocabularies — it is included
here as a **non-example** so the principle is not overclaimed as universal
architectural glue.

**C6 `Thesis` (reserved, `reasoning/contracts.py`) vs. `research.Thesis`
(M2.3's synthesis output).** These are two different objects that happen to
share a name. C6 is a placeholder for a future consumer-agnostic projection fed
*back* into `GroundingContext` so later reasoning can check new findings
against a previously established view (`Finding.contradicts_thesis` already
anticipates this). `research.Thesis` is M2.3's actual synthesis product —
dimensions, dispositions, plan/run fingerprints — all Research-specific
vocabulary. Defining C6 now, shaped like `research.Thesis`, would put
Research-only fields into a shared contract exactly as the corollary forbids.
The corollary's resolution is to leave C6 undefined until the actual
consumer-agnostic need (thesis-feedback-into-grounding, expected around M2.4)
forces its shape, and to have `research.Thesis` project down to whatever
minimal C6 turns out to require — not to guess that shape early. This is the
principle correctly explaining why a decision is **deferred**, not merged.

---

## Review checklist for future contributors

Before adding a field to an existing shared type, or introducing a new type
that resembles an existing one:

1. **Would this field's meaning change, or become undefined, depending on which
   subsystem constructs or reads the object?** If yes, it does not belong on
   the shared type.
2. **Is the new type's field list mostly a copy of an existing type's
   fields?** If yes, prefer wrapping/composing over duplicating — check
   whether the existing type can be referenced instead of restated.
3. **Is this actually two orthogonal concerns, or one concern with two
   consumers?** Two consumers of one concern (e.g. `Answer` and `research`
   both eventually presenting a `Finding`) do not need two types — only two
   genuinely different concerns (a *fact* vs. a *dimension label on a fact*)
   do.
4. **If this is a contract type (documented as consumed identically by
   multiple subsystems), does the new field name a vocabulary specific to only
   one of them?** `ResearchDimension`, `AssertabilityForConversationOnly`, and
   similar consumer-named concepts are the tell.
5. **Would constructing this type in some valid state make another one of its
   own fields meaningless?** That is the sharpest single test for "these are
   actually two concerns."

---

## Consequences

**Positive:**
- Gives future reviewers (and this review's own future self) a named test
  instead of re-deriving "should this be one type or two" from scratch each
  time.
- Directly prevented a real defect from shipping: the original M2.3 draft's
  `ThesisClaim` duplicated five existing C7 fields; applying test #2 above
  during review caught it before implementation.
- Explains, rather than merely permits, several already-made decisions
  (RetrievalPlanner/ResearchPlanner split, the two-`Finding`-type situation,
  deferring C6) — a principle that retroactively explains real decisions is
  more trustworthy than one written in the abstract.

**Negative / Trade-offs:**
- Composition costs more surface area up front than a single merged type with
  optional fields would. `InvestigationResult` wrapping an unmodified C7
  `Finding` is two names to know instead of one type with a `dimension: str |
  None` field.
- The principle requires judgment to apply (the five-question checklist
  above), not a mechanical check — it will not catch every case by rote, and a
  contributor moving quickly can still merge two concerns without noticing.

**Risks:**
- Overclaiming this principle as universal architectural glue is a real risk,
  which is why the providers-vs-models non-example is included explicitly:
  not every design decision in Atlas is an instance of this rule, and forcing
  the frame onto genuinely unrelated decisions would cheapen it.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| State only the corollary ("contracts stay consumer-agnostic") without the general principle | The corollary alone would not have caught the `ThesisClaim` field-duplication mistake, which was a same-subsystem (research-to-research) violation, not a contract-boundary violation |
| Treat this as guidance inside ADR-0007 (planner invariants) | Different in kind — ADR-0007 governs what makes something a *planner*; this governs how *any* two types should relate. Folding them together would make ADR-0007 a grab-bag of unrelated rules |
| Claim the principle explains all four reviewed examples equally | Overclaiming; the providers/models case does not exercise it and is kept as an explicit non-example instead |

---

## References

- ADR-0006 (research planning) — where `ResearchDimension` was first kept out
  of `Finding`
- ADR-0007 (planner invariants) — a sibling rule governing planner shape,
  distinct from this ADR's rule governing type boundaries
- ADR-0008 (thesis generation) — the design review that surfaced this
  principle, and whose `ThesisClaim` proposal this ADR's corollary corrected
- `src/atlas/reasoning/contracts.py` — the module docstring's own
  "consumed identically by Conversation, Research, and Attention" language,
  which is the contract-agnosticism this ADR formalizes
- `src/atlas/reasoning/llm/base.py` — the providers/models non-example
