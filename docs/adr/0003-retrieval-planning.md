# ADR-0003 — Retrieval Planning (M1.7)

**Date:** 2026-07-21
**Status:** Accepted

---

## Context

Through M1.6, retrieval is a single lexical sweep with no notion of *what
kind of question this is*. `build_context()` (`reasoning/context.py`) takes a
raw question string and hands it straight to `retrieve_passages()`
(`reasoning/retrieval.py`), which scores every window in every candidate
document with one formula (`matched_words + 2*matched_numbers`) and returns
the top-K. A question about board changes and a question about FY24 revenue
are retrieved identically.

Atlas already knows each document's `kind` (`EvidenceKind`,
`acquisition/evidence.py`) and `source_date` — persisted as `parsed_documents`
columns since `KnowledgeBase`'s original schema — but retrieval never uses
them. Separately, `parsed_documents.kind` is corrected in place by
`acquisition/classifier.py`'s inline reclassification pass (ADR-0002), so any
retrieval-time consumer of that column automatically inherits the corrected
taxonomy rather than BSE's raw label.

This milestone inserts one deterministic, side-effect-free planning stage
ahead of retrieval:

```
Question -> RetrievalPlanner -> SearchPlan -> Retriever -> GroundingContext -> Reasoning
```

The planner never retrieves evidence, never reasons, never calls an LLM,
never touches the `KnowledgeBase`. It is a pure function `str -> SearchPlan`.
The initial implementation (`HeuristicPlanner`) is keyword/regex rules only —
the same "deterministic floor" philosophy already applied to
`retrieval.py`'s lexical matching and `classifier.py`'s Sub-line rules. A
future LLM-based planner implements the same `RetrievalPlanner` protocol and
produces the same frozen, self-validating `SearchPlan`, so the interface does
not move when that milestone arrives.

Consistent with the M1.5 precedent (ADR referenced inline in `retrieval.py`
and `context.py`): a new capability is wired in behind a flag/eval-capability,
default OFF, until `atlas eval compare` shows measured lift over the M1.5
baseline.

---

## Decision

**Retrieval planning ships as an additive layer that can only reorder
candidates, never exclude them.** Every plan-derived preference (doc type,
date window, period, recency, numeric emphasis) is an additive score boost
applied during ranking; none of them ever removes a candidate from
eligibility. This is what makes "a planned retrieval can never return fewer
results than an unplanned one, for the same `top_k`" a structural property of
the code rather than a policy convention to remember.

### 1. RetrievalPlanner boundary

`reasoning/planner.py` defines:

```python
class RetrievalPlanner(Protocol):
    def plan(self, question: str) -> SearchPlan: ...

class HeuristicPlanner:   # the only implementation in M1.7
    def plan(self, question: str) -> SearchPlan: ...
```

`HeuristicPlanner` imports nothing from `atlas.knowledge`, `atlas.reasoning.llm`,
or any network/filesystem library — enforced by an AST-walk test
(`test_reasoning_planner.py`'s import-boundary assertions), not just a code
comment. It classifies intent via ordered keyword rules (governance ->
capital_action -> esg -> ownership -> risk -> guidance -> narrative ->
financial_metric -> general fallback — narrower intents checked first so,
e.g., "what did management **say** about margins" resolves to `narrative`
rather than treating "margins" as an isolated `financial_metric` lookup),
extracts fiscal periods (`FY2024`, `Q3FY24`, ...) via regex, and adjusts
`top_k` via two explicit rules (broaden for "list/all/every" questions,
narrow for a pointed single-metric lookup). Every rule that fires emits a
`PlanningDecision(rule, input, output)` — the plan's own audit trail.

### 2. `SearchPlan` data model

`reasoning/plan.py` — deliberately **not** added to `reasoning/contracts.py`.
That file holds the §10 contracts (C1-C9), which are contract-version-locked;
`SearchPlan` is an internal interface between two components inside the
reasoning package, the same category `RetrievalMatch` already occupies in
`retrieval.py`. All types are frozen dataclasses with `__post_init__`
validation (`ValueError` on anything malformed), matching `contracts.py`'s own
discipline.

Key fields: `intent` (a 9-value `RetrievalIntent` Literal), `query_terms` /
`numeric_terms`, `preferred_doc_types` (`DocTypePreference(kind, weight)`,
validated against real `EvidenceKind` values), `date_window`, `periods`,
`top_k`, `rerank` (`RerankHints`: `prefer_recent`, `prefer_numeric`,
`max_per_document`), `decisions` (the `PlanningDecision` trail), and
`to_dict()` (a thin `dataclasses.asdict()` wrapper, JSON-serializable with no
custom encoder — for eval reports, caching, and future replay).

Two things this model deliberately omits, decided during design review:

- **No `strategy` field.** Which retrieval *mechanism* runs (lexical today;
  hybrid/vector later) is deployment/execution configuration owned by the
  retriever, not a property of the question. If a future hybrid retriever
  needs the question's opinion on this, that arrives as a differently-named
  hint (e.g. `needs_semantic: bool`) then, not by resurrecting a `strategy`
  field that had exactly one legal value in M1.7.
- **No `confidence` on `PlanningDecision`.** A deterministic rule engine has
  no meaningful confidence to report — every firing of the same rule carries
  an identical constant. Adding it now would invite downstream branching on a
  value that never varies, and an LLM planner's confidence semantics won't
  mean the same thing as the heuristic's. Add it in the milestone where it is
  a real, varying signal.
- **No `from_dict`.** `to_dict()` ships because it's free and never drifts
  (pure recursion over dataclass fields); `from_dict` is where the real work
  is (reconstructing nested frozen types) and has no consumer until an LLM
  planner exists. It will be added then, constructing through the same
  `__post_init__`-validated constructors — the safety boundary for a
  model-generated plan is unchanged either way.

### 3. Retriever integration

`§10` contracts (`GroundingContext`, `Claim`, `EvidenceReference`,
`ReasoningResult`, `Answer`) are untouched, as are `ask.py`, `prompt.py`, and
`render.py`. This matters concretely: `budget_note` (`GroundingContext`'s one
free-text field) is rendered directly into the LLM's user prompt
(`prompt.py`), so plan diagnostics are deliberately kept OUT of it — they
surface via the `SearchPlan`/`RetrievalResult` objects the *caller* already
holds, not through anything that reaches the model.

`knowledge/base.py` gains `KnowledgeBase.get_many(ids)` — one
`SELECT ... WHERE evidence_id IN (...)` (chunked at 500 ids) replacing what
would otherwise be N `get()` round trips when scoring doc-type/date boosts
across many candidates. Read-only, no schema change.

`retrieval.py` gains `retrieve_with_plan(kb, doc_ids, plan, ...) ->
RetrievalResult`, split into two internal stages:

- `_generate_candidates` applies the **unchanged** accept bar
  (`_clears_accept_bar`) and never consults `preferred_doc_types` or
  `date_window` — its output set is provably identical to what
  `retrieve_passages` would consider for the same inputs. This is what makes
  the fallback guarantee structural: ranking can only reorder and truncate
  what this stage already accepted.
- `_rank_and_select` applies every plan-derived boost additively on top of
  the unchanged `matched_words + 2*matched_numbers` base score, then
  dedups/truncates to `top_k` exactly as `retrieve_passages` already does
  (plus `rerank.max_per_document` when the plan sets it).

`retrieve_passages` itself is **untouched** — same function, same behavior,
same tests. It stays the M1.5 code path for any caller that never builds a
plan.

`RetrievalResult(matches, plan, candidates_considered, docs_missing_metadata)`
is the plan-aware counterpart to a bare match list — internal, like
`RetrievalMatch`, capped at four fields on purpose (an observability seam,
not a scratch pad). It does not escape `context.py`.

`build_context()` gains an optional `plan: SearchPlan | None = None`
parameter. `plan=None` reproduces M1.5 behavior byte-identical (verified by
test — same claims, same `retrieved` tuple, same `budget_note`). A `plan` may
be supplied without `question` (the plan already carries its own
`raw_question`); supplying both requires them to agree, or `ValueError`.

### 4. Document-type awareness

One vocabulary (`EvidenceKind`), one mapping table
(`planner.py`'s `_INTENT_DOC_TYPES`), no parallel taxonomy. `SearchPlan`
validates `DocTypePreference.kind` against real `EvidenceKind` values at
construction, so a hallucinated kind (from a future LLM planner) cannot reach
the retriever. The retriever resolves a document's kind from KB metadata
(`get_many`), never from a title string — the same anti-fragile-parsing
principle `classifier.py` already applies to its own Sub-line rules. A
document with no KB row, or a kind not in the table, scores with boost 0 and
remains fully eligible (`docs_missing_metadata` records this without
crashing).

### 5. Rollout gating

`cli.py`'s `ask` command gains `--retrieval-plan` (requires
`--question-retrieval`; a no-op, not an error, if given alone — a flag-
ordering slip shouldn't fail the whole command) and `--explain-plan` (prints
the `PlanningDecision` trail). `eval/cases.py` gains `CAP_RETRIEVAL_PLAN`,
layered on top of the existing `CAP_QUESTION_RETRIEVAL` runner-mode switch —
no bundled eval case declares either capability in `requires`, so neither
changes which cases run; both only toggle `LiveReasoningRunner`'s internal
behavior. Both flags/capabilities default OFF pending
`atlas eval compare` showing measured lift over the M1.5 baseline — the exact
gate ADR-M1.5 already established for question-conditioned retrieval.

---

## Consequences

**Positive:**
- Retrieval ranking can finally distinguish "what did management say"
  (favor transcripts) from "what was reported revenue" (favor financial
  results/annual reports) — previously identical lexical sweeps.
- The planner/retriever split gives a real seam for every named future
  capability (LLM planner, hybrid/vector retrieval, a real reranker, richer
  metadata filtering, plan caching/replay) without another architectural
  change — each lands on an existing extension point (the `RetrievalPlanner`
  protocol, `_rank_and_select`, `SearchPlan`'s optional fields, `to_dict`).
- The fallback guarantee (planned retrieval >= unplanned retrieval, same
  `top_k`) is enforced by the code's own structure (candidate generation
  never consults plan preferences), not by a policy someone has to remember
  to preserve when this code is touched later.
- Zero behavior change for any caller that doesn't opt in: `plan=None` is
  byte-identical to M1.5, `retrieve_passages` and its tests are untouched,
  and no §10 contract file changed.

**Negative / Trade-offs:**
- The heuristic planner's intent taxonomy (9 intents) and doc-type mapping
  table are hand-calibrated, not learned or eval-validated per-intent yet —
  they will need real eval measurement (`atlas eval compare`) before the
  flag can default on.
- `PlanningDecision` carries no confidence, so a caller cannot yet
  distinguish "the planner was quite sure" from "the planner barely
  matched a keyword" — acceptable for a deterministic rule engine (every
  firing of the same rule is identical), but a real limitation once an LLM
  planner's decisions vary in reliability.
- Period matching (`_period_boost`) is a whitespace-insensitive substring
  match against a plan's `FY2024`/`Q3FY2024`-style strings — it will miss
  prose that spells the period out differently (e.g. "the year ended March
  2024") since it's a bonus signal only, never a filter, this degrades
  gracefully but does mean recall on period-scoped boosts is imperfect.

**Risks:**
- `get_many()`'s SQLite chunking is set at 500 ids per query, comfortably
  under the ~999-variable limit; if a future caller passes IDs alongside
  other bound parameters in the same statement this margin could need
  revisiting, though no current call site does.
- The `_INTENT_DOC_TYPES` table is a single point of encoded domain
  knowledge (which doc kinds matter for which intent) — as with
  `classifier.py`'s calibrated keyword lists, it will need revisiting as new
  `EvidenceKind` values or new intents are added, and nothing currently
  guards against it silently going stale.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Expand candidate scope to the whole KB (`ok_ids()`) rather than profile-cited evidence only | Bigger recall win, but changes the closed-world sourcing story and cost profile in the same milestone as introducing planning — decided to keep candidate scope unchanged and treat corpus-wide retrieval as a separate future milestone. |
| Hard-filter by preferred doc type (or filter-then-relax) instead of soft-boosting | A mis-planned intent would silently lose all evidence for a hard filter, or require a second unfiltered pass to detect and relax — soft-boost-with-guaranteed-fallback gets the same practical effect (preferred kinds win when available) without ever risking an empty result from a wrong guess. |
| Let `build_context()` construct the plan internally (`question=...` implies planning) | Would hide the seam and make plan inspection/logging harder; keeping "callers plan, then pass the `SearchPlan` in" makes the planner a standalone testable unit and keeps swapping in an LLM planner a caller-side change only. |
| Default `--retrieval-plan`/`CAP_RETRIEVAL_PLAN` on | Simpler, but forecloses A/B measurement against the M1.5 baseline — follows the exact ADR-M1.5 precedent (default off pending eval-measured activation) instead. |
| Add `confidence` to `PlanningDecision` now, for forward-compatibility with an LLM planner | A constant field with no varying signal invites downstream code to branch on it meaninglessly; deferred to the milestone where confidence is real. |
| Write `SearchPlan.from_dict()` alongside `to_dict()` | No consumer exists until an LLM planner does; an unused parser is maintenance debt without a caller to keep it honest. Deferred. |
| Keep `SearchPlan.strategy: Literal["lexical"]` as an extension seam for hybrid/vector retrieval | A single-valued field with no consumer encodes the wrong ownership (mechanism is deployment config, not a plan property) — removed; a differently-scoped hint field can be added when hybrid retrieval actually needs one. |

---

## References

- [ADR-0001 — Evidence Ontology](0001-evidence-ontology.md) — `EvidenceKind`,
  the one document-type vocabulary this milestone reuses rather than
  re-inventing
- [ADR-0002 — Acquisition Layer V1 Freeze](0002-acquisition-v1-freeze.md) —
  inline classification (`classifier.py`) that keeps `parsed_documents.kind`
  correct, which this milestone's doc-type boosts depend on
- [`src/atlas/reasoning/plan.py`](../../src/atlas/reasoning/plan.py) — the
  `SearchPlan` data model
- [`src/atlas/reasoning/planner.py`](../../src/atlas/reasoning/planner.py) —
  `HeuristicPlanner`, the M1.7 deterministic implementation
- [`src/atlas/reasoning/retrieval.py`](../../src/atlas/reasoning/retrieval.py) —
  `retrieve_with_plan`, `RetrievalResult`, the candidate/ranking split
- [`src/atlas/reasoning/context.py`](../../src/atlas/reasoning/context.py) —
  `build_context`'s `plan` parameter and the question/plan agreement check
- [`src/atlas/knowledge/base.py`](../../src/atlas/knowledge/base.py) —
  `KnowledgeBase.get_many()`
- `tests/unit/test_reasoning_plan.py`, `test_reasoning_planner.py`,
  `test_reasoning_retrieval_plan.py`, `test_reasoning_context_plan.py` — the
  M1.7 test surface, including the fallback-guarantee and import-boundary
  proofs referenced above
