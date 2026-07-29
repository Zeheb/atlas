# Atlas Implementation State

**The canonical execution checkpoint.** Read this first; it outranks `COMMIT_PLAN.md`,
which outranks `EXECUTION_PLAN.md`. Where they disagree, this file is what happened and
the others are what was planned.

## Update cadence

Rewrite this file **before ending a session**, or whenever context runs low enough that
a handoff is likely — not on a per-commit or per-milestone tick. Milestone size varies
too much for milestones to be a useful clock (M1 is 11 commits, M5 is 4), and the file's
real job is to let the next chat resume cold. Optimize it for that.

---

## Position

| | |
|---|---|
| Branch | `claude/atlas-implementation-13a264` (worktree of `main`) |
| Last completed commit | `dea5322` — `feat(assertions): add stale_evidence query` |
| Next planned commit | **M7 commit 4** — `feat(rebuild): add stale-only mode` (#49 + #50 + #77). **Read the "Migration 3" note below before starting: this commit is larger than COMMIT_PLAN assumes.** |
| Tests | 3399 passed, 2 skipped, 663 deselected (`pytest -m "not integration"`) |
| Coverage | 92.10% (gate: `--cov-fail-under=80`) |

## Milestones

| Milestone | Status | Commits |
|---|---|---|
| M9 — Ontology version freeze | ✅ complete | `1ce7018` |
| M0 — Build fingerprint | ✅ complete | `2a3dd3e` … `b11ec95` |
| M-PRE — Determinism pre-flight | ✅ complete | `20ceb70` … `6d67436` |
| M1 — AssertionStore | ✅ complete | `81f58da` … `3d1cf87` |
| M2 — EntityStore | ✅ complete | `d8bf479` … `d1c28b4` |
| M3 — Profile from Tier 1 | ✅ complete | `f751de3` … `07e952b` |
| M4 — Rebuild engine | ✅ complete | `5e10dca` … `b82bdba` |
| M5 — Judgment store | ✅ complete | `c167876` … `d0d2a76` |
| M6 — Answer pinning | ✅ complete except #43b | `5bd6e4a` … `f52d3b2` |
| M7 — Selective invalidation | 🔄 3 of 4 commits | `33d61f7` … `dea5322` |
| M8 — Metrics pinning | ⬜ not started | |
| M10 — Backfill & operator CLI | ⬜ not started | |

`AssertionStore` is the default profile source as of `b82bdba` (#35 cutover).

## Outstanding roadmap items

- **#43b — record consulted `assertion_ids`. Deferred, with a reason the plan anticipated.**
  Assertion ids do not reach Tier 2: `results_for()` rebuilds `AnalysisResult`s via
  `Assertion.to_fact()`, which drops the id, and neither `company/model.py` nor
  `company/builder.py` mentions `assertion_id` anywhere. Populating the field honestly
  needs assertion ids threaded through the profile — a Tier 2 model change, which
  contradicts M6's "additive or it is wrong" constraint. The dishonest alternative,
  querying the store for every assertion belonging to the consulted documents, records
  what was *available*, which is exactly what #43 says not to record. The plan permits
  this slip ("may slip past M6 without blocking it"). Field exists, defaults to `()`,
  and the footer omits the segment rather than printing `0 assertions`.
- **`profile_built_at` is likewise unpopulated and has no issue number.** `CompanyProfile`
  has no `built_at`; only the stored envelope does (`store.py:747`). Wiring it means
  carrying it into `GroundingContext`. Worth an issue before M10.
- **M7 commit 4 — `--stale-only` (#49, #50, #77). Migration 3 is a prerequisite, and
  COMMIT_PLAN does not budget for it.** Selective invalidation by kind is impossible
  against the current schema: `assertion_runs.fingerprint` stores
  `BuildFingerprint.digest()`, the whole build, and sha256 does not invert — a stored
  digest cannot be asked *which* component moved, so `affects(kind)` has nothing to
  compare against. `stale_evidence()` therefore compares whole digests today, which is
  exact but never narrow. To make `--stale-only` narrow soundly, commit 4 must:
  1. add migration 3 putting an `affects_digest` column on `assertion_runs`
     (the runner from #68 exists and M2 already used it once for migration 2);
  2. have `assertions/writer.py` stamp `fingerprint.affects(result.kind)` alongside
     the full digest;
  3. teach `stale_evidence()` to narrow on it **only when the column is populated** —
     a pre-migration row has `NULL` and must be treated as stale, per the milestone's
     rule that ambiguity defaults to whole-store invalidation;
  4. then `--stale-only`, #50's scope tests, and #77's row-count invariant.
  Doing 4 without 1–3 produces a flag that silently under-invalidates, which the
  milestone names as worse than over-invalidating.
- **M8** — metrics pinning across ~30 query functions.
- **M10** — backfill, plus new issue **#78** (remove the analyzer profile path and the `profile_source` flag), which may only land after #59 confirms every repo migrated.

## Implementation discoveries

Repository-verified. Do not regress these.

1. **`merge_result()` already finalizes profiles.** Issue #62 was retired on this
   evidence: `store.py:809` calls `merge_result()`, which ends in
   `_finalize_profile()` (`builder.py:1101`). The original reading stopped at the
   call site without opening the callee. Caught by a `strict=True` xfail that
   XPASSed — which is what strict mode is for.
2. **The real M-PRE divergence was `sources`, not finalization.** `_finalize_profile`
   sorts 16 containers and no `sources` list, so incremental merges kept arrival
   order. #66 is the fix.
3. **`mention_id` is anchored to immutable document position**, never to resolver
   output (#74). Resolver output is order-dependent; document position is not.
4. **Every order-insensitive collection must be canonicalized** at the point it is
   built, not at the point it is compared.
5. **Corpus-order tests and within-result-order tests verify different invariants.**
   Neither substitutes for the other.
6. **Equivalence fixtures must put ≥2 results in the same snapshot** or the test
   passes vacuously — every `sources` list holds one element and proves nothing.
7. **`asserted_at` is excluded from `judgment_id` at the call site**, not by widening
   `hashing.EXCLUDED_FROM_HASH`. Widening that frozen list would also change what the
   rebuild comparison ignores.
8. **`list` as a method name shadows the builtin in class-scope annotations.**
   `JudgmentStore._raw_judgments` returns a tuple because a `list[...]` annotation
   inside the class body resolves to the method (mypy `valid-type`/`attr-defined`).
   `ThesisStore` never hit this only because it annotates no list returns.
9. **`ask()` is the only non-deserializing `ReasoningResult` construction site in `src/`.**
   Pinning both of its paths pins every answer surface, present and future. An
   inventory test fails when a third site appears.
10. **`InvestigationResult` drops the `ReasoningResult`** and keeps only
   `semantic_findings`, so per-dimension pinning is not retained. Not a gap: the durable
   artifact is the `Thesis`, and `synthesize()` re-asks through `ask()`.
11. **A pre-pinning answer must render byte-identically** — no footer, no blank line, no
   placeholder. Every pre-M6 renderer expectation depends on it.
12. **`CompanyStore.merge()` has no production caller.** `store.py:704` is a docstring
   example; every other call site is a test. `rebuild()` uses `save()`, not `merge()`.
   This is why `allow_reanalysis` was safe to add.
13. **A profile cannot be un-merged.** `FinancialSnapshot.facts` are merged from every
   source that touched the period and the merged *value* carries no attribution. "Drop
   that evidence's contribution" can only be spelled "re-derive without it", which is
   what `merge(allow_reanalysis=True)` does.
14. **`results_for()` raises on a stale document, it does not skip it.** Serving a
   profile silently missing a document is the failure the project exists to prevent, so
   `stale_evidence()`'s job is to *predict* that refusal, not to mirror a filter.
15. **The graphify graph is built from `main` and its line numbers are stale.** It was
   useful as a hint set for M7 commit 1, and wrong on every location; the code matched
   COMMIT_PLAN exactly. Verify in code, always. Rebuild the graph before trusting it.
16. **Python 3.14 (PEP 758) allows `except A, B:` without parentheses.**
   `provenance.py:118` uses it. It is valid, not a latent syntax error.

## Accepted deviations

| ID | Deviation | Status |
|----|-----------|--------|
| D1 | Equivalence tests split: synthetic variant unmarked (the CI gate) + golden-corpus variant marked `integration` | **Accepted, applied.** CI runs `pytest -m "not integration"`, so a corpus-only gate would be invisible. |
| D2 | `itertools.permutations` over a fixed small result set instead of adding Hypothesis | **Accepted.** No new dependency; exhaustive at this size. |
| D3 | M-PRE's "regenerate golden fixtures" risk does not exist | **Confirmed non-event.** No test compares stored profile bytes. |
| D4 | #62 re-sorts existing stored profiles on next merge | Informational; intended, not a bug. |
| — | M-PRE landed as 3 commits, not 1 | Applied; strictly more reversible. |
| — | New issue #78 — remove the analyzer path in M10 | Additive, confirmed. |
| — | #62 retired outright | Applied; work already in the tree. |
| D5 | Pinning fields named `consulted_assertion_ids` / `consulted_evidence_ids`, not the plan's `assertion_ids` / `evidence_ids` | **Applied.** `evidence_ids` is already taken on `Claim` and `Finding` one level down the same contract hierarchy, and on `ReasoningResult` that meaning is occupied by `citations`. A field named `evidence_ids` there reads as a synonym for citations; rendering it as sources would attribute claims to documents that never supported them while the citation chain still validated. |
| D6 | `#44` footer rendered in `reasoning/render.py` + two CLI blocks, not in `research/render.py` or `query/render.py` | **Applied.** `research/render.py` renders `ReportData`, which holds no `ReasoningResult`. `query/render.py` is M8 commit 3 (`QueryResult` has no fingerprint until #51). COMMIT_PLAN outranks the issue text. |
| D7 | `JudgmentStore.delete` landed in the CLI commit, not the store commit | **Applied.** #38 includes deletion; the CLI commit is the one that introduces its only caller. |
| D8 | `merge(allow_reanalysis=True)` re-derives via `build_profile` instead of subtracting the stale evidence in place | **Applied, forced.** Merged snapshot values carry no per-source attribution, so in-place subtraction does not exist. New `ReanalysisUnavailableError` (a `StaleResultError` subclass) refuses rather than rebuilding from an incomplete result set. |
| D9 | `affects()` excludes `builder_version` | **Applied, determinate.** Assertions are Tier 1, written by `assertions/writer.py` from analyzer output; the builder assembles Tier 2 downstream. A builder bump cannot change an assertion row. |
| D10 | `stale_evidence()` compares whole digests, not per-kind sub-digests | **Applied, forced by the schema.** See the Migration 3 note under outstanding items. Exact but never narrow — the milestone's stated default when the narrow answer is unavailable. |

## Gates

Every commit must be independently green on all five:

```bash
uv run black --check src tests && uv run ruff check src tests && uv run mypy src && uv run pytest -m "not integration" -q
```

Tooling runs under `uv run` only — there is no worktree-local venv until `uv` creates one.

Binding constraints: coverage gate means a new module ships with its tests **in the same
commit**; mypy is `strict` on `src/`; ruff `BLE` bans bare `except Exception`; commits are
conventional-commit enforced.

## Standing policy

- **Strict xfail.** A planned-failing test lands `xfail(strict=True)`; the fix commit
  removes the marker. An XPASS is a failure and is evidence the roadmap assumption is
  wrong — investigate before writing production code.
- Architecture, tier boundaries, fingerprint design, migration strategy and the assertion
  model are frozen. No new dependencies.
- Repository evidence outranks planning assumptions, always.
