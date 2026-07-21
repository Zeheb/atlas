# ADR-0004 — Retrieval Evaluation (M1.8)

**Date:** 2026-07-21
**Status:** Accepted

---

## Context

M1.7 (ADR-0003) shipped retrieval planning behind `--retrieval-plan` /
`CAP_RETRIEVAL_PLAN`, default OFF, gated on "eval-measured lift over the M1.5
baseline" — a gate that could not actually be evaluated, because nothing
measured retrieval. The existing harness (`eval/runner.py`, `eval/report.py`)
measures *answers*: correctness, grounding, judge scores. It had no
visibility into which passages were retrieved, why they ranked where they
did, or what the planner decided.

M1.8's objective, stated directly: **learn which planner decisions create
measurable value before optimizing the planner.** This milestone is
measurement infrastructure only — it adds no retrieval heuristics and
changes no scoring logic anywhere in `reasoning/`.

### What exists today (verified)

| Piece | Location | Note |
|---|---|---|
| `ReasoningRunner.run() -> (ReasoningResult, Answer, GroundingContext)` | `eval/runner.py` | 3-tuple; `RetrievalResult` never escaped `context.py` |
| `RetrievalResult(matches, plan, candidates_considered, docs_missing_metadata)` | `reasoning/retrieval.py` | ADR-0003 named "gains fields" as the sanctioned extension seam |
| `_rank_and_select` | `reasoning/retrieval.py` | computed every boost inline, then discarded the breakdown |
| `CaseResult` / `Report` / `aggregate` / `compare` | `eval/report.py` | flat frozen dataclasses; `from_dict` reads via `.get()`, so added fields are backward compatible |
| `EvalCache` keyed on (model, fingerprint, prompt) | `eval/cache.py` | a no-op plan costs no LLM calls once cached |
| `Report.git_commit`, `.model`, `.capabilities` | `eval/report.py` | already stamped — `eval_reports/*.json` is already a usable history |

---

## Decision

### 1. `RunOutcome` replaces the 3-tuple; diagnostics leave `context.py` via a frozen return type

`ReasoningRunner.run()` now returns a frozen `RunOutcome(context, result,
answer, plan, retrieval)` — all fields after `context` optional, so
retrieval-only runs and non-planning strategies are representable without a
special case. `build_context()` gains a diagnostics-carrying counterpart,
`build_context_with_diagnostics()`, returning a frozen `ContextBuildResult
(context, retrieval)`; `build_context()` itself becomes a one-line delegate
(`build_context_with_diagnostics(...).context`), so its signature and return
type are **unchanged** and none of its 39 existing call sites needed to
change.

This was chosen over a mutable `retrieval_sink` out-parameter (considered and
rejected during design review). The rejected design was justified by analogy
to `content_cache`, and that analogy doesn't hold: `content_cache` is a memo
table `build_context` creates and threads *downward* so the M1/M1.5 passes
share fetched content — it never carries a result back *out* to a caller. A
sink is the opposite direction, and there is no precedent for an
out-parameter anywhere in the reasoning layer, whose stated discipline is
that everything is frozen. A frozen return type is the third instance of an
established pattern (`RetrievalMatch`, `RetrievalResult`), not a new idiom.

### 2. Option A: two independent runs + a `ComparisonEngine` — no paired execution command

Considered and rejected: a new command that runs BASELINE and PLANNED
together in one process and produces a combined report. Rejected because
ranking-change metrics need both result *sets*, not simultaneous execution —
persisting each run's selected doc_ids/ranks/scores lets a comparison engine
join them on `case_id` afterward, which dissolves the entire argument for
pairing. Once that's true, paired execution loses on every criterion that
matters: it is a second orchestrator that must stay behaviorally identical to
production forever (directly undermining "evaluation measures exactly what
production executes" — `eval/comparison.py` instead runs `LiveReasoningRunner`
exactly as production does, twice), it is inherently 2-ary so a third
retrieval strategy would force a rewrite, and it cannot compare across
commits, dates, or providers, which two persisted `Report`s do for free
(`Report.git_commit`/`.model` are already stamped).

`--retrieval-only` still needed a path that stops after context assembly —
that is an early exit inside the one existing runner (`LiveReasoningRunner`),
not a second command. The execution architecture stays singular.

### 3. Baseline is a null `SearchPlan`, not a `plan=None` special case

`eval/strategies.py` defines `RetrievalStrategy` (a `question -> SearchPlan |
None` Protocol), `BaselineStrategy` (a null plan: query/numeric terms via the
same tokenizer `retrieve_passages` uses internally, no doc-type/date/period
preferences, `top_k=5`), and `PlannedStrategy` (wraps `HeuristicPlanner`).
Both strategies always produce a plan, so both get **identical retrieval
diagnostics** through the same `retrieve_with_plan` code path — candidate
counts, score breakdowns, metadata coverage are just as observable for the
baseline as for a planned run.

The risk this creates: eval's "baseline" then measures `retrieve_with_plan`,
while production `build_context(plan=None)` calls `retrieve_passages`. A
**mandatory equivalence test** (`test_eval_strategies.py`) pins
`retrieve_passages(q, k) == retrieve_with_plan(null_plan(q, k)).matches`
across representative fixtures. This holds because, with every preference
empty and `RerankHints()` inert, `_rank_and_select`'s `score = base * 100 +
0`, order-identical to `retrieve_passages`'s own `base` ranking — not an
assumption, a property of the additive-boost design ADR-0003 already
established.

`LiveReasoningRunner` takes an optional `strategy`; when `None` it falls back
to the pre-M1.8 `CAP_QUESTION_RETRIEVAL`/`CAP_RETRIEVAL_PLAN` capability
gating unchanged — M1.7's wiring and tests pass untouched.

### 4. LLM-free by default; `--retrieval-only` builds no LLM client at all

Retrieval and planner metrics need no LLM. `LiveReasoningRunner` gains a
`retrieval_only` flag: when set, `run()` returns after
`build_context_with_diagnostics` and never calls `ask()` —
`RunOutcome.result`/`.answer` are `None`, the injected client is never
touched. `client` becomes optional (`None` is valid) so the CLI's
`eval_run_cmd` builds **no** `LLMClient` at all in this mode — not one that
merely goes unused. `--with-answers` is the explicit, self-documenting
opposite (the default when neither flag is given); the two are mutually
exclusive at the CLI.

### 5. `ScoreBreakdown` and `RetrievalCaseMetrics`/`PlannerCaseMetrics`: observability additions, zero scoring change

`_rank_and_select` already computed every boost component to reach its
`total`; `ScoreBreakdown` (a new `RetrievalResult.breakdowns` field, plus a
`docs_searched` count needed for `metadata_coverage`) records what was
already computed — a regression test pins that recording it changes no
total score and no final ordering across every existing fixture. `CaseResult`
gains two optional nested dataclasses (`retrieval_metrics`,
`planner_metrics`, both `None` by default) built by pure functions
(`build_retrieval_metrics`, `build_planner_metrics`) from `RunOutcome.plan`/
`.retrieval`, so an M1.7-era report JSON lacking both fields still loads via
`Report.from_dict`'s existing `.get()`-based reconstruction — verified by
test, not just claimed.

`aggregate()` gains suite-level planner aggregates (intent distribution, rule
fire counts, top_k distribution, and **dead rules** — declared
`PlanningDecision` rule identifiers, enumerated once in
`planner.ALL_RULE_IDS`, that never fired across the suite) and retrieval
aggregates (mean candidates considered, mean metadata coverage, mean boost
share, doc-type distribution), plus a `refusal_rate` dimension folded into
`compare()`'s existing per-dimension diff.

### 6. `ComparisonEngine` composes `report.compare()`, doesn't replace it

`eval/comparison.py` is pure functions over two already-persisted `Report`s:
`ranking_change` (Jaccard overlap of selected `(doc_id, char_offset)` sets,
mean rank displacement over common items, churn in/out, `top1_changed`),
`retrieval_deltas` (composes `aggregate()`'s `"retrieval"` sub-dict),
`planner_attribution` (outcome deltas bucketed by the candidate's `intent`
and by each rule it fired — directly answering "which planner decisions
correlate with a changed outcome"), and `side_by_side` (per-case baseline-vs-
candidate answer text, selected passages, and scores — the human
read-through the milestone exists for). `compare_retrieval()` composes all
of the above plus `report.compare()` unchanged.

`CaseResult` gains one more optional field for this: `answer_prose` (the
answer text, or `"[REFUSED] <reason>"` — matching `judge.py`'s own existing
formatting convention exactly), kept only for the side-by-side, scoring
nothing.

### 7. Two-phase acceptance gate: advisory now, enforcement deferred

`eval/recommendation.py`'s `recommend(baseline, candidate)` computes a
`SAFE_TO_ENABLE` / `NOT_READY` / `INSUFFICIENT_DATA` verdict from explicit,
**unvalidated** thresholds (zero grounding regressions; correctness_pass_rate
delta ≥ 0; refusal_rate delta ≤ +0.02; evidence_use or usefulness delta ≥ 0;
≥20% of cases show a changed passage selection) and never raises or causes
any command to exit non-zero. `atlas eval compare-retrieval` always exits 0
regardless of verdict.

This is deliberate, not a placeholder for laziness: you cannot validate a
measure and enforce it with the same data. M1.8's purpose is establishing
whether these metrics predict retrieval quality at all; enforcing a
threshold derived from them now would be circular. Independently: enforcement
gates protect against regression *over time*, and there is nothing to regress
yet — "enable planning by default?" is a one-time human decision, not a
recurring CI condition. **Phase 2 promotion criterion, written now so it can
actually happen:** promote to an enforced gate once the recommendation has
matched the human enable/hold decision across ≥3 evaluation runs on distinct
git commits, with no threshold firing spuriously. Until then, advisory.

---

## Consequences

**Positive:**
- `atlas eval compare-retrieval` finally answers the question ADR-0003's
  gate posed but couldn't check: what does retrieval planning actually
  change, and does it help.
- Retrieval-only evaluation is free (no LLM calls, no LLM client
  constructed) and fully deterministic — repeatable on every commit, not
  just when budget allows a live judge run.
- Zero behavior change for any caller that doesn't opt in:
  `build_context()`'s signature/return type are unchanged, `retrieve_passages`
  is untouched, `strategy=None` reproduces pre-M1.8 `LiveReasoningRunner`
  behavior exactly, and an M1.7-era report still loads.
- `ALL_RULE_IDS`-based dead-rule detection gives a concrete, cheap answer to
  "which planner decisions never do anything" — the M1.8 objective, directly.

**Negative / Trade-offs:**
- The baseline-as-null-plan design depends on an equivalence test staying
  green; if `retrieve_passages` or `retrieve_with_plan`'s scoring ever
  diverges without updating both, the baseline measurement silently becomes
  invalid until that test is re-run.
- The Phase 1 thresholds are genuinely unvalidated guesses. `NOT_READY` from
  a threshold that turns out not to predict anything is a real risk this ADR
  accepts in exchange for not enforcing on no evidence.
- `answer_prose` adds free-text answer content to persisted report JSON
  (previously only structured scores/booleans) — larger report files, and a
  new field to consider before sharing a report outside the team.

**Risks:**
- `_bucket_delta`'s per-rule/per-intent buckets can have very few cases each
  on a small suite, producing deltas that read as signal but are actually
  noise — no minimum-bucket-size guard exists yet.
- Dead-rule detection is only as complete as `ALL_RULE_IDS`; a new
  `PlanningDecision` rule added to `planner.py` without updating that
  constant would silently under-count "dead" rules rather than erroring.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Mutable `retrieval_sink` out-parameter on `build_context()` | Only mutable object in an otherwise all-frozen layer; conflates `content_cache`'s downward-memo shape with an upward-result shape that is a different problem. A frozen `ContextBuildResult` delegate keeps `build_context()`'s signature and return type genuinely unchanged. |
| Paired baseline+planned execution command | Ranking-change metrics only need both result SETS, not simultaneous execution, once persisted — dissolves the argument for pairing. Loses on production-code reuse, extensibility to a 3rd strategy, and cross-commit/cross-provider comparison, which two independent reports get for free. |
| Always run end-to-end (no `--retrieval-only`) | Every iteration would cost LLM calls and inherit judge nondeterminism, when retrieval/planner metrics need neither — the whole point of measuring retrieval cheaply and often. |
| Immediate threshold enforcement | Validating a measure and enforcing it with the same data is circular; there is nothing to regress yet since this is a one-time enable decision, not a recurring gate. |
| A `plan=None` special case for the baseline strategy (no diagnostics) | Would make the baseline unmeasurable on exactly the metrics this milestone exists to produce — asymmetric observability defeats the comparison's purpose. |

---

## References

- [ADR-0003 — Retrieval Planning](0003-retrieval-planning.md) — `SearchPlan`,
  `RetrievalResult`, the candidate/ranking split this milestone measures
- [`src/atlas/eval/runner.py`](../../src/atlas/eval/runner.py) — `RunOutcome`,
  `LiveReasoningRunner`'s `strategy`/`retrieval_only`
- [`src/atlas/reasoning/context.py`](../../src/atlas/reasoning/context.py) —
  `ContextBuildResult`, `build_context_with_diagnostics`
- [`src/atlas/reasoning/retrieval.py`](../../src/atlas/reasoning/retrieval.py) —
  `ScoreBreakdown`, `RetrievalResult.docs_searched`
- [`src/atlas/eval/strategies.py`](../../src/atlas/eval/strategies.py) —
  `RetrievalStrategy`, `BaselineStrategy`, `PlannedStrategy`
- [`src/atlas/eval/report.py`](../../src/atlas/eval/report.py) —
  `RetrievalCaseMetrics`, `PlannerCaseMetrics`, the planner/retrieval
  aggregates, `refusal_rate`
- [`src/atlas/eval/comparison.py`](../../src/atlas/eval/comparison.py) —
  `ComparisonEngine`'s pure functions
- [`src/atlas/eval/recommendation.py`](../../src/atlas/eval/recommendation.py) —
  the Phase 1 advisory verdict
- `tests/unit/test_eval_strategies.py` — the mandatory baseline/
  `retrieve_passages` equivalence proof
