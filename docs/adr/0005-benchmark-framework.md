# ADR-0005 — Benchmark Framework (M1.8.5)

**Date:** 2026-07-21
**Status:** Accepted

---

## Context

M1.8 (ADR-0004) built the machinery to measure retrieval — `RunOutcome`,
`RetrievalStrategy`, per-case retrieval/planner metrics, `ComparisonEngine`,
and an advisory recommendation verdict. Pointing that machinery at the
existing 44-case benchmark immediately exposed that **the benchmark itself
was the weakest link**, measured, not assumed:

| Finding | Value |
|---|---|
| Cases | 44, all `subject=TCS` |
| Planner intents with 0 cases | `esg` |
| Intents with exactly 1 case | `governance`, `narrative`, `ownership`, `risk` |
| Cases falling through to `general` intent | 24 / 44 (55%) |
| Dead planner rules | `period_extraction`, `top_k_narrow_specific_metric` |
| Cases where the planned plan is byte-identical to baseline | 24 / 44 (55%) |

That last row is the structural defect M1.8.5 exists to fix: for a
`general`-intent question the planner emits no doc-type preferences, no
periods, and inert `RerankHints` — which *is* `BaselineStrategy`'s null plan.
For 55% of the suite, planning was provably a no-op, so M1.8's own
`fraction_changed_selection` metric could never move regardless of planner
quality — the verdict was being decided by benchmark composition, not by
retrieval quality.

M1.8.5's objective is **benchmark quality, not retrieval quality**. It adds
no retrieval heuristics and changes no reasoning/retrieval behavior — every
line of `reasoning/contracts.py`, `ask.py`, `prompt.py`, `render.py`,
`retrieval.py`, `planner.py`, `plan.py`, and `context.py` is untouched
relative to the M1.8 baseline.

---

## Decision

### 1. Benchmark is a first-class subsystem, not a sub-concern of eval

New package `src/atlas/benchmark/` (`taxonomy.py`, `provenance.py`,
`coverage.py`, `validation.py`), depending only on `reasoning` (planner,
plan, text) and `knowledge` (KnowledgeBase) — deliberately **not** on
`atlas.eval`. `analyze_suite()` and `validate_cases()` take a structural
Protocol (`CaseLike`/`ValidatableCase`) rather than importing
`eval.cases.EvalCase` directly, so the dependency direction stays
`eval -> benchmark`, never the reverse. `eval.cases.EvalCase` imports
`benchmark.provenance`/`benchmark.taxonomy` for its four new optional fields;
that is the only coupling between the two packages.

### 2. Gold retrieval labels, with provenance that is machine-checked, not declared

`EvalCase` gains four optional fields — `scenario`, `difficulty`,
`provenance` (`CaseProvenance`), `retrieval_label` (`RetrievalLabel`) — all
`None`/`()` by default, so the original 44 cases parse unchanged.

Only two provenance origins exist: **`corpus_derived`** (the case is built
from real evidence that genuinely supports it) and
**`corpus_validated_negative`** (the case asserts an absence, and that
absence is machine-verified). There is deliberately no third,
unverified-synthetic origin — a benchmark case that skips verification is
exactly what this milestone exists to prevent.

`benchmark/validation.py`'s `validate_cases()` enforces this for real:

- **`corpus_derived`**: every evidence id named in `provenance.
  supporting_evidence_ids` and `retrieval_label.relevant_evidence_ids` must
  resolve in that *subject's* `KnowledgeBase` (`get_many`), and if
  `relevant_kinds` is declared, each named id's real `kind` must be among
  them. A label naming a document that doesn't exist, or mislabeling its
  kind, fails.
- **`corpus_validated_negative`**: the **inverted** check — actually run
  `build_context_with_diagnostics`/`plan_retrieval` (the real production
  path, not a reimplementation) over the subject's candidate pool and assert
  nothing clears the accept bar. "Verified absent" is a test result, not an
  assertion. If the corpus later grows to contain the answer (M1.8.6), this
  fails loudly and the case must be reclassified — precisely the behavior
  wanted when new companies are acquired.
- Every case tagged `difficult` must carry `provenance`, and every
  non-negative difficult case must carry a `retrieval_label`.

This is what keeps the taxonomy honest: a scenario tag is only valid if real,
checked documents back it.

**A genuine finding from building this, not a hypothetical:** constructing
verified `corpus_validated_negative` cases against a large real corpus
(SBIN: ~39,000 distinct keyword vocabulary across its cited evidence; TCS
~19,700) proved much harder than expected. Natural-sounding financial
questions ("What buyback has SBI announced?") reliably produced false
positives — the accept bar needs only 2 distinct word matches anywhere
across hundreds of windows, and common words like "share," "announced," and
the company name itself co-occur everywhere as boilerplate. Genuinely
negative cases required cross-industry jargon foreign to the subject's
sector (asking a bank about "blast furnace coking coal," asking an IT
services company about "sinter pellet reserves") — confirmed word-by-word
absent from the subject's full corpus vocabulary before being confirmed by a
real zero-match retrieval run. This is itself evidence for why the inverted
machine check exists: an author's intuition about what's "obviously absent"
is not reliable at this corpus scale.

### 3. `CoverageAnalyzer` — one implementation, two surfaces, extended with real metrics

`benchmark/coverage.py`'s `analyze_suite()` (pure, no I/O beyond the real
`plan_retrieval`) and `analyze_corpus()` (needs a `KnowledgeBase`) are the
single implementation shared by:

- **`atlas eval coverage`** — static analysis, no LLM, no retrieval run.
- **`CoverageSnapshot`**, embedded in every `atlas eval run` report
  (`eval/report.py`) — exactly `analyze_suite()`'s output plus a suite
  fingerprint, never a second, independently-computed notion of "coverage."

Two additional benchmark-quality metrics were adopted as designed:
**distribution skew** (normalized Shannon entropy per dimension — directly
surfaced the 55%-`general` problem as a low-entropy intent distribution) and
**redundancy** (pairwise Jaccard over `reasoning.text.keywords`, flagging
near-duplicate questions above 0.8 similarity). A third, separate "diversity"
score was declined — it is the inverse of the other two, and a composite
number would be exactly the abstract-taxonomy-exercise this milestone exists
to avoid.

`retrieval_deltas`/`retrieval_quality_deltas` in `eval/comparison.py` and a
new `eval/retrieval_quality.py` (precision@k, recall@k, MRR, forbidden-
retrieved, computed from `RetrievalCaseMetrics.selected` and
`RetrievalLabel`) upgrade M1.8's "the selection changed" into "the selection
got better," for the ~33 labelled cases.

### 4. Corpus expansion is explicitly out of scope — M1.8.6 does that

M1.8.5 uses only the three repositories that already existed (TCS, SBIN,
TATASTEEL — all with `profile.json` + `knowledge.db`). No company is
acquired in this milestone. The reasoning, recorded when this was decided:
**you cannot know which companies to acquire until the coverage report
exists.** Acquiring during M1.8.5 would mean guessing at gaps; acquiring
after means closing *measured* gaps — this milestone's coverage report
becomes M1.8.6's requirements document. Mixing the two would also have
confused two failure modes: a benchmark-design bug is not an
acquisition-pipeline failure, and ADR-0002's known acquisition limits
(pre-2016 404s, `.zip` corporate-governance reports, stale HTML shells) are
live network risk that has no place inside a milestone meant to stay short.

**The honest cost, stated plainly:** even after this milestone, the corpus
is three mega-cap Indian blue chips — no mid-caps, no promoter-led firms in
the classic sense, no recent IPOs, no thin/sparse filers by nature (only
`sparse_evidence` scenario cases *within* these three companies), one
market. The original request's bar — "declare the corpus sufficiently
representative" — is **not claimed here**. It moves to M1.8.6's gate: no
dimension in this milestone's coverage report flagged underrepresented, and
the four structurally-dead doc-type boosts (`agm_notice`,
`corporate_governance_report`, `dividend`, `regulatory_filing` — retrievable
in zero profiles across all three companies) either backed by real
retrievable evidence or removed from `planner._INTENT_DOC_TYPES`.

---

## Consequences

**Positive:**
- Every one of the 9 `RetrievalIntent` values, all 7 `ALL_RULE_IDS`, and all
  6 `RetrievalScenario` values now have ≥3 real, corpus-derived cases behind
  them — measured via `atlas eval coverage`, not asserted.
- `general`-intent share dropped from 55% to 29.3% (below the 30% floor) —
  the structural no-op problem that made M1.8's verdict unmeasurable is
  fixed for the majority of the suite.
- Subject balance: TCS's share of the suite dropped from 100% to 54.5%
  (below the 60% floor) by adding SBIN and TATASTEEL cases — multi-company
  cases work end-to-end today (`LiveReasoningRunner` already resolved
  `repository_base_path / case.subject`; no case had simply used it before).
- `atlas eval validate-cases` gives the benchmark the same provenance-first
  discipline production Atlas already holds itself to: nothing is claimed
  about the corpus that hasn't been checked against it.
- Zero behavior change: contract files and every reasoning/retrieval module
  are byte-identical to the M1.8 baseline; the original 44 cases parse
  identically (verified by test).

**Negative / Trade-offs:**
- 33 of the 99 cases now carry hand-authored gold labels that must be kept
  in sync with the corpus; if a cited document is ever re-parsed with a
  different kind or removed, `validate-cases` will correctly start failing
  and someone has to investigate rather than the benchmark silently going
  stale.
- The corpus vocabulary finding (§2) means future negative cases will need
  the same careful, cross-industry-jargon construction technique — natural
  "this is obviously absent" phrasing is not reliable at this corpus scale
  and should not be trusted without running `validate-cases`.
- Distribution skew/entropy is reported per dimension but has no enforced
  floor (only `missing`/`underrepresented` counts and the two explicit share
  ceilings do) — a suite could technically clear every floor while still
  being skewed within a dimension's non-empty categories.

**Risks:**
- `benchmark.coverage.analyze_corpus`'s "structurally dead doc-type" list
  depends on `planner._INTENT_DOC_TYPES`, a private symbol read directly
  from `planner.py` without modifying it (to keep that file's diff empty,
  per this milestone's constraint) — if that table's shape changes in a
  future milestone, this read needs to be revisited alongside it.
- The two flagged redundant-question pairs are both explainable (one is a
  pre-existing literal duplicate in the original 44 — `t16`/`t42`, both "Is
  this management credible?" — the tool's first-ever detection of it; the
  other, `t54`/`t67`, is a deliberate near-duplicate contrasting a
  period-scoped question against its period-ambiguous counterpart) but nothing
  currently prevents a future author from introducing an *unintentional*
  redundant pair undetected beyond running `atlas eval coverage` by hand.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Acquire 2-3 additional companies during M1.8.5 | Cannot know which companies close the actual gaps until the coverage report exists to name them; acquiring first is guessing, acquiring after is measured. Also mixes benchmark-design risk with acquisition-pipeline risk (ADR-0002's known limits) inside one short milestone. |
| Author negative cases from a taxonomy without corpus verification | Exactly the "abstract taxonomy exercise" the milestone exists to avoid; the corpus-vocabulary finding (§2) shows intuition about what's "obviously absent" is unreliable at this scale — several initially-plausible negative questions turned out to have real, if coincidental, corpus overlap. |
| A single "diversity" composite score alongside skew/redundancy | It is the mathematical inverse of the other two; a third number invites treating benchmark quality as one abstract scalar rather than inspectable per-dimension signals. |
| Recompute coverage independently in the CLI command vs. the embedded snapshot | Would risk two implementations silently diverging; `CoverageSnapshot` is exactly `analyze_suite()`'s output, proven byte-identical by test. |
| Label every one of the 99 cases with a gold retrieval target | Cost scales with the whole suite for a benefit (precision@k/recall@k/MRR) only needed on cases specifically testing retrieval scenarios; scoped to the ~33 corpus-derived/negative cases instead, keeping labelling effort bounded. |

---

## References

- [ADR-0004 — Retrieval Evaluation](0004-retrieval-evaluation.md) — the
  measurement machinery this milestone's benchmark improvements feed
- [`src/atlas/benchmark/taxonomy.py`](../../src/atlas/benchmark/taxonomy.py) —
  `RetrievalScenario`, `ALL_SCENARIO_IDS`
- [`src/atlas/benchmark/provenance.py`](../../src/atlas/benchmark/provenance.py) —
  `CaseProvenance`, `RetrievalLabel`
- [`src/atlas/benchmark/coverage.py`](../../src/atlas/benchmark/coverage.py) —
  `CoverageAnalyzer`'s single implementation
- [`src/atlas/benchmark/validation.py`](../../src/atlas/benchmark/validation.py) —
  machine-checked provenance, including the inverted negative check
- [`src/atlas/eval/retrieval_quality.py`](../../src/atlas/eval/retrieval_quality.py) —
  precision@k/recall@k/MRR from gold labels
- [`src/atlas/eval/data/acceptance_v2_1.json`](../../src/atlas/eval/data/acceptance_v2_1.json) —
  the expanded 99-case suite (44 original + 55 new: 33 labelled/difficult, 22
  routine fillers for subject balance)
- `atlas eval coverage`, `atlas eval validate-cases` — the CLI surface
