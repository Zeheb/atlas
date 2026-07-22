# ADR-0008 — Thesis Generation (M2.3)

**Status:** Accepted (implemented)
**Date:** 2026-07-21, revised 2026-07-22 after implementation
**Related:** ADR-0003 (retrieval planning), ADR-0004 (retrieval evaluation),
ADR-0005 (benchmark framework), ADR-0006 (research planning),
ADR-0007 (planner invariants), ADR-0009 (orthogonal concerns)

> **Revision history.** This ADR was substantially wrong twice before
> implementation, and both corrections are recorded rather than erased.
>
> **First revision** removed a proposed `ThesisClaim` type that duplicated
> five fields already on `reasoning.contracts.Finding` (C7) — caught by
> applying ADR-0009's orthogonal-concerns test to this document's own
> proposal.
>
> **Second revision (this one)** followed a pre-implementation falsification
> review that found three further defects, one fatal. The design that shipped
> is materially smaller than either draft. Sections below marked
> **[FALSIFIED]** record what was wrong and why, because the errors are more
> instructive than the corrections.

## Context

M2.2.5 delivered decomposition: an open question becomes a `ResearchPlan`,
each investigation is grounded through retrieval, and the run returns
provenance-backed findings plus explicit unresolved entries. Atlas could
gather; it could not conclude. M2.3 makes it conclude, without ever asserting
anything the evidence does not support.

### [FALSIFIED] The contradiction premise was false

The pre-revision draft asserted: *"the reasoning layer already sets
`contradicts_thesis` and `counter_case` on C7 findings; M2.3's first job is to
stop discarding them."*

This was false. Both fields appear **only at their declaration**
(`contracts.py:225-226`). `ask._build_finding` never sets them, and
`SYSTEM_PROMPT`'s JSON schema never requests them — they have been dead fields
since M0. The entire contradiction design rested on a signal that has never
existed.

Consequence: contradiction detection is **out of scope for M2.3** (see §5).

### [FALSIFIED] The bespoke provenance gate was a duplicate

The draft proposed building closed-world citation validation. `ask.py:99-102`
already implements it: any evidence id outside `context.evidence_index` is
dropped, ungrounded judgments are dropped (G3/G4), and a result with nothing
grounded becomes a refusal (G8). `ReasoningResult.__post_init__` separately
enforces that citations cover every finding's evidence.

Building a second gate would have duplicated the most safety-critical path in
the codebase, with the usual consequence of duplication: two implementations
that must be kept in agreement forever.

### [PARTLY FALSIFIED] The `Finding` freeze was called a no-op

The draft described freezing `research.citations.Finding` as "No behavior
change". It is a type change: `the_call.py` aliases another finding's
`evidence_ids` **list object** in three places, and freezing properly means
coercing to a tuple.

In the event the risk proved smaller than the review predicted — every
consumer used iteration, `len()`, truthiness, `sorted()` or `in`, all
tuple-compatible, so zero production call sites changed and exactly one test
assertion did. Recorded because the estimate was wrong in a useful direction:
the aliasing was real, the blast radius was not.

## Decision

### 1. Synthesis is a reasoning pass, not a new engine

`research/thesis.py`'s `synthesize()` builds a `GroundingContext` whose claims
are the run's own already-grounded findings, then calls `ask()` with a
synthesis-specific prompt pair. Assembling that context correctly **is** the
provenance mechanism; there is no second check to keep in sync.

`ask()` gained optional `system_prompt=`/`build_prompt=` parameters
(defaulting to the M0 question-answering pair, so all four existing call sites
are unchanged). Everything after the model call validates against the
`GroundingContext`, never against the prompt text, which is what makes the
seam safe — asserted by tests that run the full guarantee set through a custom
prompt.

Inherited, not rebuilt: G10 (no invented citations), G3/G4 (no ungrounded
judgment), G8 (refusal rather than an empty answer).

### 2. `InvestigationResult` is the aggregation boundary

No wrapper type was introduced. `InvestigationResult` already paired an
`Investigation` (carrying `.dimension`) with its outcome; M2.3 added
`semantic_findings`, preserving the C7 findings the boundary previously
discarded. Per-finding confidence is what allows a synthesis to refuse to be
more certain than its inputs.

The C7 objects are stored **unmodified** — no research-layer field is added to
a shared contract, and `dimension` is read from the `Investigation` where it
already lived. This is ADR-0009's corollary applied concretely.

### 3. The provenance gate is completeness, and only completeness

`check_completeness(thesis, run)` enforces the one guarantee M2.3 did not
inherit: **no silent omission.** Every resolved investigation carries exactly
one `Disposition`; every unresolved one is named in `unresolved_dimensions`.
Phantom dispositions and phantom unresolved claims are rejected too.

This is what separates a thesis that is technically well-cited from one that
is honest: a synthesis can cite every id correctly, ground every claim, and
still mislead by quietly omitting the finding that undercut it. Nothing else
in the pipeline would notice.

Closed-world is re-asserted here but not re-implemented — it exists so a
future synthesizer bypassing `ask()` could not silently lose the guarantee.

The gate is a separate function rather than a `__post_init__` check because it
needs the run: a `Thesis` alone cannot know what was investigated. Same split
as `ResearchPlan.__post_init__` (structure) vs `analyze_research_plans`
(quality).

**The gate blocks rendering entirely.** It does not warn. A thesis that
dropped a finding is not a degraded thesis; it is a wrong one, and
`atlas thesis` exits non-zero without printing it.

### 4. Citation obligation is declared, never inferred

`Finding.kind` widened from `"fact" | "synthesis"` to five values, because the
old pair collapsed four different things into one label — with the concrete
consequence that an empty `evidence_ids` meant both *"this is a disclosure"*
and *"this claim is ungrounded"*, indistinguishably.

| Kind | Obligation |
|---|---|
| `FACT`, `DERIVED`, `CONCLUSION` | **REQUIRED** |
| `EVIDENCE_NOTE` | **OPTIONAL** |
| `DISCLOSURE` | **FORBIDDEN** |

Three levels, not two. `FORBIDDEN` is what a binary split would lose, and it
catches a real error class: a policy statement dressed up as evidence-backed.
`"synthesis"` remains a legacy alias mapping to OPTIONAL, since its original
intent cannot be recovered retroactively.

Rendered report output is byte-identical after the relabelling (all
interpretive kinds still carry the reader-facing `[synthesis]` tag), proven by
the golden test.

### 5. Contradiction detection is deferred to M2.4

M2.3 makes **no semantic claim about contradiction**. `Disposition` has
exactly two states — `incorporated` and `not_material` — and a third such as
`contradicting` would assert a relationship the system does not detect.

Three reasons, in order of weight:

1. **The existing C7 field models a different thing.**
   `Finding.contradicts_thesis` is singular and directional: it marks a new
   finding as conflicting with a *previously stored* thesis fed back through
   `GroundingContext.thesis` (the deferred C6 slot). That is
   thesis-versus-history.
2. **Cross-investigation contradiction is a separate capability** — sibling
   disagreement between two dimensions within one run, with no stored thesis
   involved. Same word, different relation.
3. **Implementing either belongs in the reasoning layer.** Populating them
   requires extending `SYSTEM_PROMPT`'s schema and `_build_finding`'s parser —
   changes affecting *every* `atlas ask` call, not just synthesis. That is a
   reasoning-layer milestone.

M2.3's guarantee is therefore that nothing was silently dropped, **not** that
relationships between investigations were classified. The synthesis prompt
still forbids averaging away disagreement, so a conflict the model notices
survives into the prose even though the system makes no structural claim
about it.

M2.4 inherits a clean extension point: `Disposition` gains states and `Thesis`
gains a relation record, neither retrofitted.

### 6. `research.Thesis` is not the deferred C6 contract

C6 remains undefined. `research.Thesis` carries Research-specific vocabulary
(dimensions, dispositions, run fingerprints) and would violate ADR-0009's
corollary if placed in `contracts.py`, which is consumed identically by
Conversation, Research, and Attention.

When thesis-feedback-into-grounding is actually built — expected around M2.4,
where a stored thesis must be re-checked against new filings for staleness —
C6 should be defined as the minimal consumer-agnostic projection it needs, and
`research.Thesis` should project down to it. Guessing its shape now would
repeat the mistake this ADR was twice revised for.

## Consequences

**Positive:**
- `atlas thesis` completes the pipeline: plan → investigate → synthesize →
  gate → render, with every statement traceable to evidence the run retrieved.
- Synthesis inherits five years of grounding guarantees rather than restating
  them; the closed world cannot drift between two implementations.
- The obligation vocabulary makes an existing provenance gap *visible* (see
  below) rather than hidden under a generic label.

**Negative / Trade-offs:**
- Synthesis costs an extra LLM call beyond the N investigation calls.
- The deterministic-baseline synthesizer named in the plan was not built;
  `synthesize()` requires a client. The ADR-0007 invariant-2 argument for a
  deterministic floor applies to *planners*, and synthesis is not a planner —
  but a baseline would still be useful as a control arm for measuring the LLM
  synthesizer, and its absence is a real gap rather than a decision.

**Risks / known gaps:**
- **Uncited claims in the deterministic report.** The relabelling audit found
  7 report findings with empty `evidence_ids`, several being substantive
  company claims (margin ranges, revenue growth, net cash), one labelled
  `fact`. The underlying snapshots carry `sources`; the section builders do
  not propagate them. Deliberately not fixed in M2.3 — it changes report
  output — and tracked separately.
- **Thesis quality is unmeasured.** No eval dimension scores whether a
  synthesis is *good*, only whether it is complete and grounded. The plan's
  commit 7 (a thesis-quality eval dimension) was not built.

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| A `ThesisClaim` type carrying statement/confidence/assertability/counter_case/known_unknowns | Duplicated five C7 fields; caught by ADR-0009's test. `InvestigationResult` already was the aggregation boundary |
| A bespoke closed-world provenance gate | `ask()` already implements it correctly; a second would need permanent agreement with the first |
| Contradiction as a third `Disposition` state | Asserts a relationship M2.3 does not detect. The signal it would rest on has never been populated |
| Defining C6 now, shaped like `research.Thesis` | Puts Research-only vocabulary into a contract consumed by three subsystems |
| Per-claim `contradicted_by` links | Bidirectional bookkeeping that can desync; a relation record naming both sides is one source of truth (moot once contradictions were deferred) |

## References

- `src/atlas/research/thesis.py` — `Thesis`, `Disposition`, `synthesize`,
  `check_completeness`
- `src/atlas/reasoning/ask.py` — the injectable prompt seam and the inherited
  guarantees
- `src/atlas/reasoning/prompt.py` — `SYNTHESIS_PROMPT`
- `tests/unit/test_research_completeness_gate.py` — six adversarial theses,
  each rejected
- ADR-0007 (planner invariants), ADR-0009 (orthogonal concerns)
