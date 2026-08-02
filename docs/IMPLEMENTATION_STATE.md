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
| Branch | `claude/atlas-implementation-continue-c2bdbd` (worktree of `main`) |
| Last completed commit | `86cc982` — `chore: refresh TCS and SBIN investor-presentation runs after the 2.1 bump` |
| Next planned commit | **M10 commit 5** — `refactor(company): remove analyzer profile path and flag` (#78). Unblocked: #59 is complete and all three repositories verify clean. |
| Tests | 3523 passed, 2 skipped, 663 deselected, 0 xfailed (`pytest -m "not integration"`) |
| Coverage | 92.51% (gate: `--cov-fail-under=80`) |

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
| M8 — Metrics pinning | ✅ complete | `fb17fe8` … `6a00109` |
| M10 — Backfill & operator CLI | 🔄 commit 4 done (all three migrated, all verifying); commit 5 (#78) pending | `2a62903` … `86cc982` |

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
- **M10 commit 4 (#59) — TCS migrated and verified; SBIN and TATASTEEL still pending.**
  It rewrites `assertions.db` in the operator's real repositories, which is outside
  the worktree and cannot be undone by `git revert`.
  **Do not run it without the operator asking for it.**

  **TCS, done.** 140 documents, 140 runs, 737 assertions, 548,864-byte
  `assertions.db`, fingerprint `3f6dba65…0fa8`, `Verified: profile unchanged`,
  and `atlas rebuild --company TCS --verify` clean afterwards. It took two
  refusals and a code fix to get there, and both refusals were the gate working.

  **The operational prerequisite #59 needs and the plan never stated:** refresh
  `profile.json` *before* migrating whenever the stored profile predates the
  evidence corpus. #55 compares the assertion-path profile against the profile on
  disk, so a Tier 2 artifact older than Tier 0 refuses on staleness alone. TCS's
  profile was built `2026-07-03T07:45:17Z` and covered 122 evidence ids; 42 of its
  156 documents — including 18 annual reports carrying 414 KB–1.09 MB of text each
  — were first parsed ~20 hours later. The refusal listed 1,661 differences, but
  the candidate covered 140 evidence ids against the stored 122, **a strict
  superset with nothing lost**. This checkpoint previously said the remedy was
  `atlas rebuild` *after* migrating; that is impossible, because the migration
  refuses and never writes a store to rebuild from. Rebuild first, then migrate.
  **All three repositories share this staleness** — SBIN 27 documents parsed after
  its profile was built, TATASTEEL 30 — so both will refuse the same way.

  **#55 is correct and must not be weakened.** Across three repositories it
  refused four times and was right every time: a stale Tier 2 artifact (TCS),
  an order-dependence bug (#33, TCS), a second stale artifact (TATASTEEL), and
  an analyzer emitting three conflicting values for one key (TATASTEEL). Every
  individual row was valid in each case and no other layer would have
  complained. Each refusal printed enough to find the cause in one pass.

  **SBIN and TATASTEEL are migrated.** SBIN: 307 documents, 307 runs, 365
  assertions, 409,600 bytes, `0f3d37e`. TATASTEEL: 287 documents, 287 runs,
  948 assertions, 827,392 bytes, `85bd33a`. Both verified, both clean under
  `atlas rebuild --verify` at the time of their commit.

- **#59 is complete. All three repositories are migrated and verify clean** as of
  `86cc982`. Final state:

  | | TCS | SBIN | TATASTEEL |
  |---|---|---|---|
  | documents | 140 | 307 | 287 |
  | runs | 190 | 571 | 287 |
  | assertions | 788 | 421 | 948 |
  | `assertions.db` | 589,824 B | 565,248 B | 827,392 B |
  | `rebuild --verify` | clean | clean | clean |

  TCS and SBIN hold more runs than documents because `--stale-only` appended
  2.1 investor-presentation runs beside the 2.0 ones rather than replacing
  them; both fingerprints are in the store and the reader serves the one
  matching the running build (#71). TATASTEEL has one run per document because
  its migration built the store from scratch after the bump.

- **`--stale-only` after an analyzer bump is the closing step of a migration,
  not an optional tidy-up.** `2bdaae0` bumped `investor_presentation` 2.0 → 2.1
  after TCS and SBIN were already migrated, and `rebuild --verify` raised
  `StaleAssertionsError` on both until they were refreshed. Any future analyzer
  fix during a rollout leaves the same debt. Evidence that the refresh was
  correctly scoped: across 447 `ingested_results` rows on the two repositories,
  the only non-timestamp change was `analyzer_version` 2.0 → 2.1 on exactly the
  50 and 264 investor-presentation rows, and both canonical profile objects were
  byte-identical afterwards.
- **#78** (remove the analyzer profile path and the `profile_source` flag) may only
  land after #59 confirms every repo migrated. It is therefore blocked behind the
  same decision.

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
19. **`atlas.query` can import `atlas.provenance` at module level.** Nothing in
   provenance's closure (`analysis.base`, `analysis.patterns`, `analysis.registry`,
   `knowledge.base`, `company.builder`) imports `atlas.query`. Verified by importing
   both in one process, not only by reading the graph. `reasoning/ask.py:46` is the
   precedent.
20. **`citation.build_pin()` is the one spelling of `Atlas <digest>`.** Both the answer
   footer and the query renderer call it. A second copy would let two surfaces name the
   same build differently, which defeats the only reason either line is printed.
21. **#33 was closed on tests that cannot see half the defect. Reopened in M10, fixed
   again.** Permuting *results* — what every equivalence test does — never disturbs
   the order of facts *within* one result. Containers appended one entry per fact
   (`governance.risk_factors`, keyed on `period` alone; `strategy.entries`, on
   `source_date` alone) therefore kept analyzer emission order, and the assertion
   reader emits in content-address order, so the two tiers serialised the same data
   differently. TCS's backfill refused with 184 such differences, every one a pure
   permutation: 207 risk factors both sides, identical multiset of
   `(text, evidence_id, period)`. The regression test reverses the facts inside a
   single result, which is the smallest faithful model of the tier divergence.
   Every non-total key in `_finalize_profile` now runs to the full field set.
   **The general lesson: a sort key that is not total is a latent order-dependence,
   and "the tests pass" only means no fixture happened to tie.**
22. **D1 was load-bearing, and this is the proof.** #26 and #32 assert exactly the
   equivalence that #33 broke and are green in CI — but only in their synthetic
   variants, whose fixtures produce no ties. The golden-corpus variants that would
   have caught it are marked `integration` and never run. The first real exercise of
   Tier 1 against a full corpus was a production migration, not a test.
23. **`rebuild --from evidence` is itself a backfill.** It writes every analyzed
   result into the assertion store (`rebuild.py:161-168`) before building the
   profile, so a rebuild leaves a populated `assertions.db` and the migration that
   follows reports `Already held: N run(s)` and is a content-identical no-op
   replacement. Harmless — content addresses make the stores equivalent — but it
   means `migrate assertions` and `rebuild --from evidence` are not distinct
   operations at Tier 1. See #82.
24. **A dict-merged fact container makes the analyzer's emission order load-bearing,
   and one analyzer defect was hiding behind it.** The builder writes snapshot
   facts as `snaps[key][fact.kind] = value` — last write wins over `result.facts`
   order. Tata Steel's 2QFY22 deck emitted three `FINANCIAL_FCF` facts for one
   period, so the analyzer path kept the last-emitted and the assertion path kept
   whichever the content-address ordering put last. The values were a debt
   repayment figure and two gross-debt balances, read out of the *next slide's*
   waterfall chart because `_BLOCK_WINDOW` is 300 characters with no
   page-boundary guard and the extractors join pages with a plain `"\n"`.
   **The fix was the analyzer, not the merge.** Making Tier 1 reproduce emission
   order faithfully would have made both tiers agree on a debt repayment figure
   labelled free cash flow, with a synthesized excerpt asserting it. Corpus-wide
   there is exactly **one** such collision in 734 documents, and duplicate
   emission into a dict-merged container is intentional nowhere — "first
   occurrence wins" is the documented policy at six sites across four analyzers.
   Whether the reader should restore emission order is still open (#83) and is
   now a robustness question, not a correctness one.
25. **A behaviour change in an analyzer must move its `ANALYZER_VERSION`.** The
   fingerprint's claim is that this build's code reproduces the rows stamped with
   it. `2bdaae0` changed what `investor_presentation` emits, so leaving it at 2.0
   would have made the fingerprint lie about precisely the rows that motivated
   the change. The cost is bounded and visible: `affects()` carries the constant
   per kind, so exactly one analyzer's runs went stale.
26. **`AssertionStore(path)` takes a repository *root*, not a database file**, and
   opening one creates it. Both matter to `migrate.py`: staging is a temp *directory*
   inside the repository (`migrate.py` moves `store.path`, not the directory), and
   counting existing rows checks `(root / DB_FILENAME).exists()` first, or a dry run
   converts "no store" into "empty store" and has modified what it inspected.

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
| D13 | `QueryResult.fingerprint` is pinned by field default (`str`), not populated per construction site as an `Optional` like `ReasoningResult` | **Applied.** `QueryResult` has no serialization path anywhere in `src`, so `None` ("written before pinning") is unreachable and an unpinned result could only mean a forgotten call site. One of the 19 sites — `query/screen.py:155` — is not in `_QUERIES` and is invisible to #53's inventory; the default covers it and every surface added later. |
| D14 | #52's "text fixtures updated" is a non-event | **Confirmed, like D3.** No fixture holds rendered query output; the three `render_result` call sites in tests are all integration substring assertions. |
| D15 | #57's "merge with `doctor` naming per the audit" is a non-event | **Confirmed.** No `doctor` command exists anywhere in `src`. The command landed as `atlas store verify`, in the existing `store` group beside `status`. |
| D17 | #59 landed as eight commits, not one, and three of them change production code | **Applied, forced.** COMMIT_PLAN says "no code change" for M10 commit 4. Running it produced a `.gitignore` gap (`assertions.db` untracked and unignored), a stale Tier 2 artifact needing a rebuild, and a real order-dependence bug (#33). `86cdb96` ignore rules, `bdbda9d` TCS profile refresh, `f93c3a8` the #33 fix, then the migration itself. A data operation that finds three defects is not a data operation. |
| D18 | The #33 fix extends every non-total sort key in `_finalize_profile`, not only the two that diverged | **Applied.** `risk_factors` and `strategy.entries` are what TCS exposed, but eleven other containers had the same defect latent. SBIN and TATASTEEL are migrated next, and a partial fix only moves the refusal to whichever container first ties there. Leading fields are unchanged, so profiles that never tied serialise exactly as before. |
| D16 | Migration verification raises `MigrationVerificationError` rather than returning `committed=False` | **Applied.** A report with `committed=False` reads identically to a dry run, and a refused migration must not be mistakable for a successful no-op. The error carries the staged path and the differences; a verification failure is the one exit that keeps the staging directory, because it is the only artifact that can say which document moved. |

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
