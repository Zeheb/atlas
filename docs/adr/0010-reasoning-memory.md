# ADR-0010 — C6 Reasoning Memory (M2.4)

**Status:** Accepted (implemented; amended by M2.4.1 before publication)
**Date:** 2026-07-21, revised 2026-07-22 after two rounds of design review
**Related:** ADR-0004 (retrieval evaluation, advisory-verdict precedent),
ADR-0007 (planner invariants), ADR-0008 (thesis generation), ADR-0009
(orthogonal concerns)

> **M2.4.1 amendment.** A post-implementation stabilization pass found
> `RecalledView.subject_ref` had no reader anywhere in the codebase —
> `_render_recalled_view` renders `context.subject_ref` instead, and
> `check_staleness` takes `repo_root` explicitly. It failed the same trim
> test this ADR's §3 applied to `RecalledClaim`'s `period`/`value`/`unit`;
> the trim simply wasn't applied to the field the same review added. Removed
> before this contract version was ever pushed, so the change amends
> unpublished contract version 2 rather than requiring a version bump. See
> §3 below, updated in place.
>
> A companion review of `Question.thesis_ref` reached the opposite
> conclusion: left declared and unpopulated. It is a blueprint-reserved seam
> (unlike `subject_ref`, which M2.4 itself added), and populating it would
> have duplicated `GroundingContext.thesis.view_id` with no invariant
> enforcing agreement between the two — the exact hazard being removed
> elsewhere in this same pass.

> **Revision history.** This design was reviewed twice before implementation
> and corrected both times. Both corrections are recorded because the errors
> are more instructive than the final shape.
>
> **First revision** renamed the proposed `StandingView`/`ViewStatement` types
> to `RecalledView`/`RecalledClaim` (a name that does not presuppose the only
> consumer is a thesis), and split validation (`staleness.py`) from
> persistence (`memory.py`) into separate modules so the two evolve
> independently.
>
> **Second revision** reverted a change this review itself had made:
> `GroundingContext.thesis` was about to be renamed to match the new type
> name. The user correctly rejected this — the field name is a reserved seam
> from the original blueprint (`thesis: None = None  # C6, deferred to M2`)
> and renaming it for cosmetic consistency would discard that seam's
> identity for no functional gain. Only the type widens:
> `None` → `RecalledView | None`. The same revision trimmed `RecalledClaim`
> back to three fields after an earlier draft had spuriously added four more
> (§3 below) — the draft's own justification for the extra fields ("avoid a
> future contract bump") was exactly the reasoning a falsification pass
> exists to catch, and the user named this directly.

## Context

M2.3 (ADR-0008) shipped `atlas thesis`: Atlas can form a grounded,
gate-checked view of a company. It cannot remember one. Every question starts
from zero, so Atlas can never ask the question a research platform exists to
ask — *does this new filing change what we concluded?*

Four acceptance cases had been pending on a `thesis` capability since the
suite was written, and they define this milestone rather than being invented
for it:

| Case | Question | Needs |
|---|---|---|
| t29 | *What's the single weakest assumption in my thesis?* | view in context |
| t33 | *Given my thesis, does anything in the filings support or undercut it?* | view + evidence |
| t34 | *Does anything in the most recent filings contradict my thesis?* | historical contradiction |
| t35 | *Given my thesis, what is the one metric I should watch?* | view in context |

This is the same pattern as M1's t43 (drill-to-source): a capability slot and
the cases exercising it already existed; the milestone activates them.

### What the repository already provided

- **`GroundingContext.thesis: None = None  # C6, deferred to M2`** — the
  reserved slot, present since the original blueprint.
- **`Question.thesis_ref: str | None`** — a second reserved seam: the
  selector, complementary to the object.
- **`Finding.contradicts_thesis` / `counter_case`** — declared since M0,
  never populated (found by ADR-0008's own falsification review).
- **`Claim`'s optional `period`/`value`/`unit`** — the existing shape for a
  *structured* proposition, considered and rejected as a template for
  `RecalledClaim` (§3).
- **`CompanyStore`** — a storage template: versioned envelope, refuses
  mismatched `store_version`, idempotent merge.
- **`discover_companies()`** — already enumerates every subject with a saved
  profile. The portfolio already exists; this milestone adds no portfolio
  type.
- **`ask()`'s injectable prompt seam** (ADR-0008) — a recalled view changes
  what the model is asked, not what it may cite.

## Decision

### 1. C6 is the recalled view, not the memory system

C6 is *what Atlas recalls having concluded*, injected into grounding so
reasoning can check new evidence against it. It is the consumer-agnostic
slice of memory that reasoning consumes — not a general-purpose memory
subsystem.

```
research/memory.py     research/staleness.py      contracts.py       reasoning/
+---------------+      +------------------+     +--------------+   +---------+
| ThesisStore   |      | check_staleness  |     | RecalledView |-->| ask()   |
| persistence   |      | validation       |     |    (C6)      |   | prompt  |
| ONLY          |      | ONLY, pure       |     | RecalledClaim|   | +parser |
+-------+-------+      +--------+---------+     +------^-------+   +----+----+
        |                       |                      |                |
        |  Thesis.to_view() ----+----------------------+     populates  v
        v                       v                              contradicts_thesis
  stored Theses          StalenessReport                        counter_case
```

`staleness.py` takes a `RecalledView` plus repository state and never imports
`ThesisStore` — enforced by an AST-based import-boundary test that scans only
module-level statements, so the module's own docstring can *mention*
`research.memory` in prose without tripping it. `sweep_staleness`, the one
function that composes both, imports `ThesisStore` locally inside its own
body — the same deferred-import convention `cli.py` already uses for every
command's dependencies.

Three separations carry the design:

- **Memory (research) vs. the injected view (contract).** `research.Thesis`
  carries dimensions, dispositions, and run fingerprints — Research
  vocabulary that ADR-0009's corollary forbids in a contract consumed
  identically by Conversation, Research, and Attention. `RecalledView` is the
  projection; `research.Thesis` projects into it via `to_view()`, never the
  reverse.
- **Staleness (mechanical) vs. materiality (reasoning).** Whether evidence
  changed is a deterministic function of the repository. Whether it *matters*
  is t34's question, answered by the LLM via `contradicts_thesis`/
  `counter_case`, not by `staleness.py`.
- **Reference vs. evidence.** A recalled view is shown to the model; it is
  never added to `GroundingContext.evidence_index`, so a stale or withdrawn
  conclusion can never become citable. Enforced structurally — nothing in
  context assembly unions view ids into the index — and tested explicitly.

### 2. Named generally; the reserved field name is untouched

The types are `RecalledView`/`RecalledClaim`, not `StandingView` or anything
containing "Thesis". The general concept is *a position held on a question at
a time, whatever produced it* — an Atlas thesis today, a user-registered view
(`origin: Literal["atlas", "user"]`), later a remembered prior answer. Naming
the type after theses would misdescribe two of those three on day one, and
would add a third type named `Thesis` after two types named `Finding` already
caused confusion during ADR-0008.

`GroundingContext.thesis` keeps its field name. The blueprint reserved that
slot deliberately; only its type widens, `None` → `RecalledView | None`. A
name change would have been cosmetic and would have discarded the seam's
continuity with the original design for no behavioral gain.

What deliberately does **not** fit into C6, and must not be forced in: an M3
promise (`Claim.resolution`) carries a deadline and a resolution status. Same
temporal flavor, different shape. Merging them into one "memory record" type
would repeat the orthogonal-concerns violation ADR-0009 exists to prevent —
C6 stays positions-only; promises get their own slot when M3 arrives.

### 3. `RecalledClaim` carries only what this milestone uses

`RecalledClaim` is `statement: str`, `evidence_ids: frozenset[str]`,
`confidence: ConfidenceLevel`. Nothing else.

An earlier draft of this design added `period`/`value`/`unit`/`assertability`
to `RecalledClaim`, mirroring `Claim`, on the reasoning that claim-level
contradiction ("margin was said to be rising in FY26; the new filing reports
a fall") would then need no future contract change. That reasoning was wrong
and is recorded rather than deleted: nothing in M2.4 consumes those fields,
and the justification — avoiding a hypothetical second contract bump — is
precisely what a falsification pass exists to reject. A bump when a milestone
actually needs the fields is cheaper than carrying dead structure on a §10
contract in the meantime.

M2.4's contradiction detection is LLM-level, and the model reads prose, so
`statement` alone is sufficient. When claim-level comparison is specified by
a real milestone, the fields arrive then — copied from `Claim`, whose shape
already proves them out.

**M2.4.1 amendment:** the same trim test, applied after implementation,
found `RecalledView.subject_ref` in the same state the drafted
`period`/`value`/`unit` had been in — declared, unread by anything.
`_render_recalled_view` renders `context.subject_ref`
(`prompt.py`) and `check_staleness` takes `repo_root` explicitly
(`staleness.py`); nothing reads the view's own copy. Removed. `RecalledView`
is now `view_id`, `question`, `claims`, `as_of`, `origin` — no `subject_ref`.

### 4. The closed world is never widened by memory

A recalled view's evidence ids are shown in the prompt, explicitly labelled
"NOT citable now unless it also appears in VALID EVIDENCE IDS below"
(`_render_recalled_view`), but are never unioned into
`GroundingContext.evidence_index`. Current retrieval alone determines what
can be cited. This is what stops a stale conclusion from resurrecting
withdrawn evidence through the back door of memory.

### 5. Staleness is deterministic and advisory; materiality is a reasoning question

`check_staleness(view, repo_root, policy)` is pure and LLM-free:
`hard_stale` is true only when a cited evidence id no longer resolves in the
`KnowledgeBase` at all; `new_evidence_since` is an informational count of
evidence acquired after the view's `as_of`. Advisory, not blocking — matching
ADR-0004's Phase-1 precedent that a low-confidence or stale signal is
surfaced, not enforced. Whether new evidence actually *contradicts* the view
is left entirely to `contradicts_thesis`/`counter_case`, populated by the
model when it sees a `RECALLED VIEW` block.

### 6. Persistence is explicit policy, not a synthesis side effect

`atlas thesis` never saves anything unless `--remember` is passed. This
matters because iterating on a question — re-running `atlas thesis` to
refine phrasing or wait for new evidence — should not silently accumulate
views nobody meant to keep. `ThesisStore.save()` is idempotent on
`view_id` (`compute_view_id(run_fingerprint, question)`, sha256, deterministic
— no uuid, matching every other fingerprint idiom in this codebase), so an
unchanged re-synthesis is a no-op rather than a duplicate, but a *changed* one
sits alongside its predecessor as history rather than overwriting it. History
was judged more honest than supersession for a research tool: knowing that
Atlas once concluded something different is itself information.

### 7. No planner, no portfolio type

- **No memory planner.** Selecting a view is a lookup by `view_id` or "every
  view for this subject" — `atlas memory show <view_id>` scans
  `discover_companies()` plus one `ThesisStore` per subject and returns the
  match. There is no decision to make, so ADR-0007's planner invariants do
  not apply; not everything must be a planner.
- **No `PortfolioMemory` type.** `discover_companies()` plus one store per
  subject already is the portfolio. `atlas memory list`/`check` are sweeps —
  plain functions over that existing enumeration — not a new stateful type.

## Falsification pass

| Attack | Verdict |
|---|---|
| `RecalledClaim` duplicates `Claim` (C3) | **Survives.** A `Claim` asserts something currently true and requires >=1 `EvidenceReference` (G10); a recalled claim records a past conclusion and must survive its evidence being withdrawn — it cannot satisfy G10 by construction. Merging would also let the model read a prior judgment as current evidence. |
| `RecalledView` duplicates `research.Thesis` | **Survives.** It is a projection, ADR-0009's prescribed shape for exactly this situation. `research.Thesis` carries dimensions/dispositions/fingerprints that would violate the corollary if placed in `contracts.py`. |
| C6 should be a Protocol instead of a dataclass | **Rejected.** Every other C5/C6/C7/C8 contract is serialized and self-validating; a Protocol is neither. |
| `ThesisStore` should layer over `CompanyStore` | **Survives, kept separate.** A profile is derived from evidence and freely rebuildable; a thesis is a judgment made at a time and is not reproducible. Storing them together means rebuilding a profile could destroy judgments. |
| `StalenessReport` duplicates `GateResult` (ADR-0008) | **Survives, with restraint.** Same shape, different question and inputs: `GateResult` asks "is this thesis internally honest" against an `InvestigationRun`; `StalenessReport` asks "is it still current" against the repository. Deliberately not generalized into a shared `Verdict[T]` — that abstraction would serve only the shape, not a real need. |
| Structured fields on `RecalledClaim` are speculative | **Killed on review.** See §3 — trimmed to the three fields M2.4 actually uses. |
| Reviving `contradicts_thesis`/`counter_case` changes every `ask()` call | **Mitigated.** The prompt block and schema fields are emitted only when `context.thesis is not None`, matching the existing `question`/`plan` optionality pattern. A byte-identical-prompt test asserts zero effect when a view is absent, not just "no crash". |
| Hidden coupling reasoning -> research | **None found.** Projection flows research -> contracts only (`Thesis.to_view()`); `reasoning` never imports `research`, enforced by the same AST import-boundary mechanism ADR-0007 already uses for planners. |
| Staleness coupled to storage | **Fixed by the first revision.** `staleness.py` and `memory.py` are separate modules; the former never imports the latter, enforced by an AST-based test, not convention. |
| Eval reproducibility | **Real defect, design changed.** If `atlas eval run` read a case's recalled view from the user's actual on-disk `ThesisStore`, a run's outcome would depend on what happens to be persisted on the machine running it — the same case could pass or fail for reasons unrelated to the code under test. Fixed: `EvalCase.recalled_view` is a plain-data fixture (`RecalledViewFixture`/`RecalledClaimFixture` in `eval/cases.py`, which has never imported `atlas.reasoning`); `eval/runner.py` projects it into a real `RecalledView` at run time, gated on the `thesis` capability like every other runner-mode switch. |
| `GroundingContext.thesis` retype is a hidden contract break | **Real hazard, contained.** The field name is unchanged so the reserved seam survives; only `None` widens to `RecalledView \| None`. Runtime-compatible for every existing construction site (all use keyword arguments with defaults), but a real §10 contract-version bump, done deliberately rather than incidentally. |

## Consequences

**Positive:**
- The four pending acceptance cases (t29/t33/t34/t35) are active, closing out
  the last capability gap the V2.1 acceptance suite named.
- Two C7 fields (`contradicts_thesis`/`counter_case`) that have been declared
  and dead since M0 are finally populated, with a "do not force a
  contradiction where none exists" instruction directly in the prompt so the
  model does not manufacture disagreement to satisfy the schema.
- `reasoning`/`research` orthogonality is preserved: the reserved C6 seam is
  filled without either package importing the other's internals, and without
  widening what memory is allowed to make citable.

**Negative / Trade-offs:**
- A second contract bump is a near-certainty once claim-level (rather than
  LLM-judged) contradiction detection is specified — accepted deliberately,
  since carrying the fields now would mean dead structure on a live contract
  in the meantime.
- `ThesisStore`'s reconstruction on load is observable-field-faithful, not
  byte-identical: one synthetic `Claim` is rebuilt per finding, carrying all
  of that finding's evidence ids, because nothing downstream reads
  claim-level granularity within a finding. Documented as a deliberate,
  bounded simplification in `memory.py`'s module docstring, not an oversight.

**Risks / known gaps:**
- **Contradiction quality is unmeasured.** M2.4 detects that the model
  *claims* a contradiction against a recalled view; whether the claim is
  correct needs gold labels, which is a benchmark question flagged here, not
  solved.
- **User-authored view registration has no input format yet.** A user can
  supply an `origin: "user"` view structurally, but no CLI path builds one
  from free text — doing so would need an LLM to structure the input,
  reopening provenance questions this milestone otherwise avoids. Left open
  (see below).
- **View history has no pruning.** Because re-synthesis sits alongside its
  predecessor rather than superseding it, a subject investigated repeatedly
  accumulates views without bound. No eviction policy exists yet; not a
  problem at current usage volumes.

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| `StandingView`/`ViewStatement` (first draft names) | Presupposed the only consumer is a thesis; corrected in the first revision to `RecalledView`/`RecalledClaim`. |
| Renaming `GroundingContext.thesis` to match the new type name | Cosmetic only; discards the reserved seam's continuity with the original blueprint for no functional gain. Rejected in the second revision. |
| `RecalledClaim` mirroring `Claim`'s full shape (`period`/`value`/`unit`/`assertability`) | Speculative — nothing in M2.4 consumes the extra fields; "avoid a future bump" is the reasoning a falsification pass exists to catch. Trimmed in the second revision. |
| A single `StalenessEngine` class | Every analogous component in this codebase (`benchmark.coverage.analyze_research_plans`, `thesis.check_completeness`, `eval.recommendation.recommend`) is a module of pure functions plus a frozen config type; a class here would hold no state between calls. |
| A `PortfolioMemory` type | `discover_companies()` plus one `ThesisStore` per subject already is the portfolio; a sweep is a function, not a type. |
| A memory planner (ADR-0007-style) selecting which view to recall | Selection is a lookup (by `view_id`, or "every view for this subject"), not a decision with alternatives to weigh — there is nothing for a planner to plan. |
| Reading a case's recalled view from the real `ThesisStore` in `atlas eval run` | Makes evaluation outcomes depend on what happens to be persisted on the machine running the suite. Replaced with a fixture the harness owns. |
| Re-synthesis superseding its predecessor rather than sitting alongside it | Tidier, but less honest — losing the fact that Atlas once concluded something different is a real loss of information for a research tool. Left as an open question, not decided either way. |

## Open Questions

1. **View identity across re-synthesis.** `view_id` is idempotent on
   unchanged evidence and changes when evidence changes, but nothing
   currently marks an older view as superseded when a newer one for the same
   question exists. History is more honest; supersession is tidier. Not
   resolved.
2. **User-authored view input format.** JSON file, structured CLI prompts, or
   free text parsed by an LLM? Free text reopens provenance questions this
   milestone otherwise avoids. Not resolved; no CLI path for `origin: "user"`
   views exists yet.
3. **Does `Claim.resolution` (the M3 promise ledger) belong in C6?**
   Memory-adjacent and temporally similar, but a different shape (a promise
   carries a deadline and resolution status, not a confidence-weighted
   claim). Recommendation: keep it in M3, as a separate slot.

## References

- `src/atlas/reasoning/contracts.py` — `RecalledClaim`, `RecalledView`,
  `GroundingContext.thesis` retype (contract version 2)
- `src/atlas/research/thesis.py` — `Thesis.to_view()`, `compute_view_id`
- `src/atlas/research/memory.py` — `ThesisStore` (persistence only)
- `src/atlas/research/staleness.py` — `check_staleness`, `sweep_staleness`
  (validation only, pure)
- `src/atlas/reasoning/prompt.py` — `_render_recalled_view`, rule 7
- `src/atlas/reasoning/ask.py` — `contradicts_thesis`/`counter_case` parsing
- `src/atlas/eval/cases.py`, `src/atlas/eval/runner.py` — fixture-driven
  `CAP_THESIS` activation
- `src/atlas/cli.py` — `atlas thesis --remember`, `atlas memory
  {list,show,check}`
- `tests/unit/test_research_staleness.py`,
  `tests/unit/test_reasoning_contradicts_thesis.py`,
  `tests/unit/test_eval_runner_thesis.py`,
  `tests/unit/test_cli_memory.py` — the properties this ADR claims,
  enforced by test
- ADR-0004 (advisory-verdict precedent), ADR-0007 (planner invariants,
  import-boundary test mechanism), ADR-0008 (thesis generation, the deferred
  C6 seam), ADR-0009 (orthogonal concerns, consumer-agnostic contracts)
