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
| Last completed commit | `c167876` — `feat(judgment): add Judgment model` |
| Next planned commit | **M5 commit 2** — `feat(judgment): add append-only JudgmentStore` (#37 + #39) |
| Tests | 3265 passed, 2 skipped, 663 deselected (`pytest -m "not integration"`) |
| Coverage | 91.91% (gate: `--cov-fail-under=80`) |

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
| M5 — Judgment store | 🔄 1 of 4 commits | `c167876` |
| M6 — Answer pinning | ⬜ not started | |
| M7 — Selective invalidation | ⬜ not started | |
| M8 — Metrics pinning | ⬜ not started | |
| M10 — Backfill & operator CLI | ⬜ not started | |

`AssertionStore` is the default profile source as of `b82bdba` (#35 cutover).

## Outstanding roadmap items

- **M5** commits 2–4: `JudgmentStore` (#37, #39), `atlas judgment add|list|supersede` (#38), rebuild-survival + import-boundary tests (#40, #41).
- **M6** — answer pinning. #43b (`assertion_ids`) is explicitly allowed to slip past the milestone.
- **M7** — selective invalidation. Commit 1 (`allow_reanalysis` on `CompanyStore.merge`, #76) is unbudgeted work; land it first and alone.
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
