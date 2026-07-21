# ADR-0006 — Research Planning (M2.2.5)

**Status:** Accepted
**Date:** 2026-07-21
**Supersedes:** none
**Related:** ADR-0003 (retrieval planning), ADR-0004 (retrieval evaluation), ADR-0005 (benchmark framework)

## Context

M1.7 (ADR-0003) built a planner that decides *how* to retrieve for one
question. M2.0–M2.2 improved retrieval itself (hybrid, temporal,
multi-company). M2.3 will generate an investment thesis behind a
machine-checked provenance gate.

Reading the code before designing this milestone surfaced a gap that the
approved M1.8.6→M2.5 roadmap did not account for.

**`atlas.research` and the retrieval stack are disjoint pipelines.** Grepping
`src/atlas/research/` for `KnowledgeBase|retrieve_|build_context|SearchPlan|
reasoning` returns one hit, and it is the word "reasoning" inside a prose
comment. The report pipeline (`research/report.py`) is a pure `CompanyProfile`
+ `Repository` assembler. `atlas ask` (retrieval + LLM) and `atlas research`
(deterministic sections) share no code path.

That matters because M2.3 was scoped to synthesize over `the_call.py`'s
`other_sections` findings — the *report* pipeline — while every retrieval
improvement lands in the *retrieval* pipeline. Without a bridge, three
milestones of retrieval work never reach the flagship thesis output.

A second constraint shapes the design. `report.py`'s module docstring states:

> No company-specific branching anywhere in this file — the same fixed section
> list runs for every ticker; a section that finds nothing for a given company
> says so rather than being skipped, so a reader always sees the full shape of
> what Atlas checked.

The fixed report is an audit artifact: it is trustworthy precisely because
nothing was quietly omitted. A planner that *selected which analyses to run*
would break that guarantee deliberately.

## Decision

Introduce a **ResearchPlanner** as a second planner sitting strictly above the
retrieval planner, and a new `atlas investigate` surface. The deterministic
report is not modified.

```
Question -> ResearchPlanner -> ResearchPlan (N Investigations)
              each Investigation.question -> RetrievalPlanner -> SearchPlan
                                          -> retrieval/reasoning
                                          -> Finding(kind="fact")
            -> InvestigationResults -> [M2.3 synthesis]
```

The planner's job is **decomposition** (one open question into many grounded
sub-investigations), **not selection** (which analyses to skip).

### 1. One vocabulary, not two

`ResearchDimension`'s nine values are exactly `report.py`'s body section keys,
asserted by test against the real `_BODY_BUILDERS` tuple. The deterministic
report and the research planner name the same nine things the same way, or the
test fails.

Known inherited blind spot, recorded rather than silently accepted: there is no
standalone `capital_allocation` dimension — that judgment is currently split
across `balance_sheet` and `what_changed`. Adding a tenth dimension is a
report-layer change (it needs a matching section builder), so it belongs in
whichever milestone adds that builder, not here.

### 2. Deterministic floor, same as M1.7

`HeuristicResearchPlanner` uses keyword rules only: no LLM, no KB, no I/O. A
future `LLMResearchPlanner` implements the same Protocol and is validated by the
same frozen `ResearchPlan.__post_init__`, so a hallucinated dimension raises
`ValueError` rather than reaching the executor.

The import boundary is enforced by an **AST-based** test, not a source grep:
the module docstring legitimately names `atlas.reasoning` when explaining the
layering, and a boundary test that a comment can break is worse than none.

### 3. Provenance made structural, not merely tested

`InvestigationResult` cannot represent an ungrounded claim. It holds **either** a
`Finding` carrying ≥1 `evidence_id`, **or** an `unresolved_reason` — never both,
never neither, enforced in `__post_init__`. Refusals, retrieval misses, and
executor errors all become explicit unresolved results.

Implementation note worth recording: the reasoning layer already refuses a
finding with no supporting evidence ("No finding could be grounded in the
available evidence"), so in practice the executor sees a refusal rather than an
uncited answer. The executor's own no-citation branch is therefore
defense-in-depth for any future path that yields prose without citations, and
the type-level guard is what actually makes the guarantee structural.

One failing investigation never aborts the run — the same batch-robustness rule
`eval/runner.py`'s `_run_case` already applies.

### 4. `--dry-run` is a true zero-LLM path

The plan is a pure function of the question, so `--dry-run` builds no LLM client
at all — not one that is built and left unused. Asserted with an exploding
`build_llm_client` stub, exactly as ADR-0004's `--retrieval-only` is.

It also reads nothing from disk: an un-acquired ticker still plans fine.

### 5. The anti-checklist gate

The failure mode this milestone most needs to avoid is a planner that expands
every question to the same dimensions, adding latency and no judgment — the
direct analogue of ADR-0005's finding that 55% of eval cases fell through to a
no-op `general` intent.

`benchmark.coverage.analyze_research_plans()` is the gate. Two structural
checks, both of which must pass:

- **no variation** — every question yields an identical dimension set, so the
  planner is a constant function wearing a planner's interface;
- **maximal width** — plans routinely name ≥90% of the vocabulary, so planning
  excludes nothing.

**Per-dimension entropy is deliberately NOT the gate.** A planner emitting all
nine dimensions every time produces a perfectly uniform dimension distribution
and therefore near-maximal entropy: the checklist would score as maximally
diverse. This is not hypothetical — `test_everything_planner_is_rejected_even_
when_ordering_varies` constructs exactly that planner, confirms it scores
`set_entropy == 1.0`, and asserts the gate rejects it anyway.

`ResearchPlan.__post_init__` additionally caps plan width at
`MAX_INVESTIGATIONS = 8` of 9, so the degenerate case cannot even be
constructed by the real planner.

An empty analysis reports `is_checklist=True` with the reason "diversity is
unmeasured, not proven" — silence is not a pass.

### 6. Two audited judgments in the planner

Rather than silent behavior:

- multiple subjects override keyword classification into a `comparison` intent
  (`comparison_subjects_detected`), since two subjects are unambiguously
  comparative however the question is phrased;
- `competitive_position` is dropped for single-subject plans
  (`dimension_dropped_single_subject`) — with no peer set it cannot be
  answered, and emitting an unanswerable investigation is worse than an
  audited omission.

## Consequences

**Gained.** The bridge between the two pipelines: M2.0–M2.2's retrieval work
now reaches a research output. `atlas investigate` accepts open-ended questions
("Should I invest in TCS?") that `atlas ask` structurally could not serve. M2.3
inherits exactly one job — synthesis over already-grounded findings — rather
than also owning decomposition.

**Cost.** N sub-investigations mean N retrieval passes and N LLM calls where
there was one. Mitigated by `Investigation.priority` (supporting a top-N cap)
and the existing `EvalCache`.

**Deliberately deferred.** Multi-subject investigations currently ground against
the first subject's profile and knowledge base. This is a visible limitation
with a named home: true multi-subject grounding is M2.2's contribution, and when
it lands only `run_investigation` changes.

**Not claimed.** This milestone gathers evidence; it does not conclude. No
investment view is formed here — that is M2.3, behind its own provenance gate.

## Alternatives considered

**Fold decomposition into M2.3.** Rejected: M2.3 is already the highest-risk
milestone (open-ended synthesis plus a novel machine-checked provenance gate),
and enlarging it works against the one milestone that most needs to stay narrow.
Splitting follows the M1.7/M1.8 precedent — build the planner, then evaluate it.

**Make `atlas research` question-aware.** Rejected: it would erode the
no-branching guarantee that makes the fixed-shape report trustworthy as an
audit. A new surface costs one command and preserves both properties.

**Let the planner select which report sections to run.** Rejected for the same
reason, and it misidentifies the value: the planner's contribution is
decomposition into retrievable sub-questions, not omission.
