# ADR-0007 — Planner Invariants

**Date:** 2026-07-21
**Status:** Accepted

---

## Context

Atlas has built two planners independently: `RetrievalPlanner` (M1.7, ADR-0003
— decides *how* to retrieve for one question) and `ResearchPlanner` (M2.2.5,
ADR-0006 — decides *what* to investigate before a view can be formed). Neither
was designed against the other; each was reviewed and approved on its own
merits.

Comparing them after the fact during the M2.3 design review surfaced that both
independently satisfy the same six structural properties. That is the signal
worth acting on: two components arrived at the same discipline without
coordination, which means the discipline describes something real about what a
"planner" is in this architecture, not a coincidence of two similar features.

This ADR names that discipline so a third planner — a synthesis planner behind
`ThesisSynthesizer` (M2.3), or any future one — is built against a stated rule
rather than rediscovered by review each time.

---

## Decision

Every planner in Atlas satisfies six invariants. A new type calling itself a
planner, or a review discovering a planner-shaped component that violates one
of these, should treat this list as the checklist.

### 1. Inspectable

Every plan carries the audit trail of the rules that built it — a tuple of
`(rule, input, output)` records (`PlanningDecision`, `ResearchDecision`, and
whatever the next planner's decision-record type is named). "Why did it plan
this?" must be answerable from the plan itself, never from re-reading the
source or reasoning about what the code probably did.

### 2. Deterministic baseline

The first implementation of any planner is rule-based: keyword/regex matching,
no LLM, no inference. `HeuristicPlanner` and `HeuristicResearchPlanner` are
both this. A smarter (e.g. LLM-backed) implementation may be added later behind
the same Protocol, but the deterministic floor is not removed — it remains the
baseline any smarter planner must beat, and it is what keeps the system
debuggable when the smarter one misbehaves.

### 3. Independently evaluable

A plan can be produced and scored without executing it. `--retrieval-only`
scores `SearchPlan`s with no LLM call; `--dry-run` scores `ResearchPlan`s the
same way. Planning quality must be measurable separately from execution
quality — otherwise a planner can only be judged by the cost of running it.

### 4. Never executes work

A planner decides and stops. It does not retrieve, does not call a model, does
not synthesize. `RetrievalPlanner` never touches the `KnowledgeBase`;
`ResearchPlanner` never calls `plan_retrieval()` or reasons over an answer.
Enforced by import-boundary tests, not comments — `reasoning/planner.py`'s
own docstring calls this "load-bearing, not decorative."

### 5. Frozen, self-validating output

Every plan is an immutable dataclass validated in `__post_init__`. This is the
boundary that makes a future model-backed planner safe to introduce: a
hallucinated document kind, an absurd `top_k`, or a plan naming more
dimensions than a declared width cap raises `ValueError` at construction,
before the malformed plan can reach anything that executes it.

### 6. Declared rule vocabulary

Each planner declares, next to its rules, the full set of rule ids it can ever
emit (`ALL_RULE_IDS`, `ALL_RESEARCH_RULE_IDS`). The evaluation harness diffs
declared-against-fired across a suite to surface dead rules — decisions that
exist in code but never produce any observed effect. Without a declared
vocabulary, only what fired can be counted; what *should* have fired, and
didn't, is invisible.

### A seventh property that is not an invariant: bounded plan width

Both planners cap how much they can plan in one call (`SearchPlan.top_k` bounds
passage count; `ResearchPlan.MAX_INVESTIGATIONS` bounds investigation count).
This is deliberately **not** listed as a seventh invariant, because the two
caps bound different things at different scales for different reasons — one
is a retrieval cost budget, the other is an anti-degeneracy guard against a
planner that names everything and calls that judgment. Each planner states its
own bound; there is no shared constant, and inventing one (`MAX_PLAN_WIDTH`)
would imply a false equivalence between a cost control and a correctness
control.

### Measuring whether a planner exercises judgment, correctly

A planner that emits the same output for every input passes every single-plan
test and is worthless. The obvious way to detect this — a diversity/entropy
metric over plan outputs — is actively wrong, and this was discovered by
constructing a planner that defeats it deliberately (`benchmark.coverage`'s
`test_everything_planner_is_rejected_even_when_ordering_varies`):

> **A diversity metric that a degenerate maximum also satisfies is not a
> gate.**

A research planner naming *every* dimension for *every* question produces a
perfectly uniform output distribution and therefore near-maximal entropy — the
checklist scores as maximally diverse. The correct measurement splits the
concern in two:

- **Structural constraints gate.** Variation across inputs (not a constant
  function) and bounded width (not naming everything). Both are pass/fail.
- **Distributional metrics describe.** Entropy, evenness, and similar
  statistics are reported for a human reader; they are never the criterion
  that decides pass/fail.

---

## Consequences

**Positive:**
- A third planner (the synthesis planner behind M2.3's `ThesisSynthesizer`)
  can be designed against a checklist instead of rediscovering these properties
  by review.
- Dead-rule detection, `--dry-run`/`--retrieval-only`-style zero-cost
  evaluation, and the anti-checklist gate all generalize immediately to any
  future planner that follows invariants 3 and 6.
- A reviewer auditing a new "planner-shaped" component has a concrete list to
  check it against, rather than an intuition of "does this feel plan-like."

**Negative / Trade-offs:**
- Every new planner now carries real ceremony (a decision-record type, a
  declared rule vocabulary, a frozen output type, a deterministic baseline)
  even when a first cut might be tempted to skip straight to an LLM-backed
  implementation. This is an intentional cost, not an oversight.

**Risks:**
- A future contributor could satisfy the letter of these invariants (e.g. a
  rule vocabulary that is declared but never actually checked against fired
  rules in CI) without the harness that makes them load-bearing. The
  invariants describe the target; the evaluation/benchmark harness is what
  enforces it, and both must be built together, as they were for both existing
  planners.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Leave the invariants undocumented, rediscover by review each time | Already happened once (M2.3 design review); codifying is cheaper than repeating the derivation |
| Add plan-width as a seventh invariant with a shared `MAX_PLAN_WIDTH` constant | The two existing caps bound different axes (retrieval cost vs. anti-degeneracy) at different scales; a shared constant implies a false equivalence |
| Make the anti-checklist gate an entropy threshold | Defeated by construction: a planner naming every dimension for every question scores maximal entropy while being maximally degenerate |

---

## References

- ADR-0003 (retrieval planning) — `RetrievalPlanner`, `SearchPlan`
- ADR-0006 (research planning) — `ResearchPlanner`, `ResearchPlan`, the
  anti-checklist gate's construction and adversarial tests
- `docs/architecture.md` §3 — the invariants as consumed by new contributors
  (this ADR is the record of the decision; `architecture.md` describes the
  resulting system)
