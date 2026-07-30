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
| Branch | `claude/continue-implementation-commits-064c2e` (worktree of `main`) |
| Last completed commit | `fb17fe8` — `test(query): assert every registered query returns a pinned result` |
| Next planned commit | **M8 commit 2** — `feat(query): pin fingerprint on QueryResult` (#51), and **remove the `xfail(strict=True)` in `tests/unit/test_query_pinning.py`** in the same commit |
| Tests | 3453 passed, 2 skipped, 663 deselected, 18 xfailed (`pytest -m "not integration"`) |
| Coverage | 92.15% (gate: `--cov-fail-under=80`) |

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
| M7 — Selective invalidation | ✅ complete (7 commits, not 4) | `33d61f7` … `ca9d51d` |
| M8 — Metrics pinning | 🔄 1 of 3 commits | `fb17fe8` |
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
- **M8 commit 2 — the sweep is 18 call sites, not ~30.** `_QUERIES`
  (`query/engine.py:1823`) registers exactly 18 names, and the inventory test
  parametrizes over `available_queries()`, so the xfail list is the checklist. One
  approach worth *verifying* before taking it: a default on the dataclass field
  (`fingerprint: str = field(default_factory=...)`) would pin all 18 without editing
  any construction site. Not yet checked for an import cycle — `query/engine.py`
  imports `company.model`, and `provenance` imports `company.builder`. If it cycles,
  fall back to editing the construction sites, which is what COMMIT_PLAN assumes.
  Either way the strict xfail is what proves the sweep was complete.
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
17. **Narrowing staleness only works if the reader narrows with it.** `select_run()`
   refuses any run whose stored value does not match the running build, so narrowing
   `stale_evidence()` alone produced a `--stale-only` that re-analysed the narrow set
   and left every other document unreadable — under-invalidation, which the milestone
   names as worse than over-invalidating. Both now go through
   `store.run_is_current()`; one rule, two call sites. Held by
   `test_the_reader_serves_every_row_this_calls_current`.
18. **A document with no run is not stale.** `stale_evidence()` reads existing rows, so
   `--stale-only` never picks up newly acquired evidence. Deliberate and tested — a
   full `--from evidence` rebuild is what ingests it — but it means `--stale-only` is
   not a substitute for a first build.

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
| D10 | ~~`stale_evidence()` compares whole digests, not per-kind sub-digests~~ | **Superseded by D11.** True only until migration 3 existed. |
| D11 | M7 commit 4 landed as 4 commits (migration, writer stamping, query narrowing, reader narrowing) plus `--stale-only`, and the reader changed | **Applied, forced.** COMMIT_PLAN budgets one commit and assumes the schema already supports per-kind comparison; it does not. The reader change is not in any issue and is not optional: narrowing one side alone ships a flag that under-invalidates (discovery 17). Decision confirmed by the user before implementation. |
| D12 | `--stale-only` does not re-analyse documents with no stored run | **Applied, deliberate.** Not stale, just new; a full `--from evidence` rebuild ingests them. Widening it would make the flag's cost depend on how much unanalysed evidence a repository holds. |

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
