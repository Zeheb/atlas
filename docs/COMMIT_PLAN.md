# Atlas Commit Plan — EXECUTION_PLAN.md Revision 2

Baseline: `EXECUTION_PLAN.md` revision 2, treated as frozen. Deviations are flagged, not taken.

---

## Constraints that shape every commit

Verified from the repo. These are not preferences; they are what "green" means here.

| # | Constraint | Source | Consequence |
|---|---|---|---|
| C1 | `--cov-fail-under=80` is in `addopts` | `pyproject.toml:66` | Every commit runs the coverage gate. A new module without tests **in the same commit** fails CI. |
| C2 | `mypy strict = true` on `src/` | `pyproject.toml:59`, `ci.yml:40` | Every new module fully annotated, including `-> None`. |
| C3 | Ruff `BLE` selected — bans bare `except Exception` | `pyproject.toml:52` | Migration and store code must catch named exceptions. |
| C4 | CI runs `pytest -m "not integration"` | `ci.yml:51` | Anything marked `integration` **does not gate CI**. |
| C5 | Four independent CI jobs: black, ruff, mypy, pytest | `ci.yml:10-51` | A commit is green only if all four pass. Format/lint failures are as blocking as test failures. |
| C6 | Conventional commits enforced pre-commit | `.pre-commit-config.yaml` | `type(scope): subject`. |

**C1 is the dominant constraint on commit granularity.** The roadmap splits module and tests into separate issues (#3 module, #6 tests). Issues may stay split; **commits may not**. Every commit below pairs implementation with its tests.

---

## Deviations flagged — decisions needed before M-PRE

### D1 — The equivalence gate cannot be "green in CI" as written · **BLOCKING, decide before M-PRE**

**Roadmap says:** M4 DoD — "the equivalence gate green in CI." Issues #26, #32, #55 — "across the golden corpus."

**Repository evidence:** CI runs `pytest -m "not integration"` (`ci.yml:51`). The golden corpus is `pytestmark = pytest.mark.integration` (`tests/corpus/test_corpus.py:30`). Every file in `tests/integration/` carries the marker. Golden-corpus tests **never run in CI today**, by deliberate design — commit `fda598c` is titled "ci: deselect integration tests."

So the plan's most important test, placed where the plan implies, would be invisible to CI.

**Smallest resolution — recommended:** split each equivalence test in two.
- A **synthetic** variant built from hand-constructed `AnalysisResult` objects, unmarked, running in CI on every push. This is the gate.
- A **golden-corpus** variant marked `integration`, run locally and pre-merge. This is the confidence check.

Same test body, parametrized over a fixture that supplies either result set. No CI change, no marker change, no new job. The invariant gets a real CI gate and the corpus check keeps its current lifecycle.

**Rejected alternative:** adding an `integration` CI job. It needs real acquired PDFs on the runner, which is why they were deselected in the first place. Reversing that decision is out of scope for this plan.

**Roadmap edit required if approved:** #26, #32, #32-PRE, #55 each become two tests. No milestone resize — the second variant is a parametrize decorator, not new work.

### D2 — Property tests over permutations need a dependency the repo does not have · **decide before M-PRE**

**Audit recommended:** Hypothesis for permutation property tests.

**Repository evidence:** `pyproject.toml:29-37` dev group is pytest, pytest-cov, ruff, black, mypy, pre-commit, types-requests. No Hypothesis.

**Smallest resolution — recommended:** use `itertools.permutations` over a fixed 4–6 result set, parametrized. Exhaustive at that size, zero new dependencies, deterministic failure output. Adding Hypothesis is defensible later; it is not needed to prove order-invariance on a set this small.

**Roadmap edit required if approved:** none. The audit's Part 5 wording changes; no issue changes.

### D3 — M-PRE's fixture-churn risk does not exist · **informational, downgrade**

**Roadmap says:** M-PRE — "stored profile bytes change. Regenerate golden fixtures once." Listed as the milestone's main risk.

**Repository evidence:** no test compares stored profile bytes. Every assertion goes through `json.loads(store._path.read_text())` (`test_company_store.py:260,266,272,278,287,791`). `grep -rn "read_text() ==\|read_bytes()" tests/` returns nothing. `tests/corpus/expectations/*.json` hold `expected_facts` lists — analyzer output, untouched by profile serialization.

**Consequence:** #61 (`sort_keys=True`) breaks zero tests and regenerates zero fixtures. M-PRE's stated risk is a non-event.

**Roadmap edit required:** downgrade M-PRE's risk paragraph. No resize — it was already S, and this makes it comfortable rather than tight.

### D4 — `#62` changes stored-profile content for existing repos · **informational, no action**

Calling `_finalize_profile()` from `merge()` re-sorts containers on every merge. Any profile built by incremental merges today has unsorted containers; after #62 it will not. That is the intended fix. Existing stored profiles are not migrated — they re-sort on next merge. No data loss; `save()` rewrites the whole file anyway. Worth stating so it is not mistaken for a bug during M-PRE.

---

## Global commit conventions

```
<type>(<scope>): <subject>
```
Types in use: `feat`, `fix`, `test`, `refactor`, `docs`, `ci`, `chore`. Scopes: `provenance`, `assertions`, `entities`, `company`, `rebuild`, `judgment`, `reasoning`, `query`, `cli`.

**Green rule applied to every commit below:** black clean, ruff clean, mypy strict clean on `src/`, `pytest -m "not integration"` passing including the ≥80% coverage gate.

---

# M9 — Ontology Version Freeze · XS · Week 1

### Checklist
- [ ] `ONTOLOGY_VERSION = "1.0"` in `analysis/base.py`, adjacent to `FactKind`, with the bump rule in the docstring
- [ ] Snapshot file of the sorted `FactKind` value list
- [ ] Test comparing live members to the snapshot
- [ ] Failure message names both required edits (bump the constant, update the snapshot)
- [ ] No `--update-snapshot` affordance

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/analysis/base.py` | `FactKind` lives here (line 29); constant goes beside it |
| `tests/unit/` | new test module location |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `feat(analysis): add ONTOLOGY_VERSION and FactKind snapshot test` | constant + snapshot data file + `tests/unit/test_ontology_version.py` | Single commit by C1 — the constant alone adds an uncovered line. Test ships with it. |

One commit. Splitting it would violate C1 for no benefit.

---

# M0 — Build Fingerprint · S · Week 1

### Checklist
- [ ] `SHARED_PARSER_VERSION = "1.0"` in `analysis/patterns.py` (#63)
- [ ] `analyzer_versions() -> Mapping[str, str]` in `analysis/registry.py`, covering all 11 `_REGISTRY` kinds (#4)
- [ ] `BuildFingerprint` frozen dataclass, six fields (#3)
- [ ] `digest()` — canonical JSON, sorted keys, `code_rev` excluded (#3, #5)
- [ ] `current_fingerprint()` with `git describe`, `None` outside a checkout (#5)
- [ ] Guard test: every analysis module imported by a registered analyzer contributes a component; `shareholding_trend.py` explicitly excluded with the reason inline (#64)
- [ ] `atlas fingerprint show [--explain] [--diff]` (#65)

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/analysis/patterns.py` | gains `SHARED_PARSER_VERSION`; 7 of 11 analyzers import it |
| `src/atlas/analysis/registry.py` | `_REGISTRY` is the authoritative kind→analyzer map (line 38) |
| `src/atlas/analysis/base.py` | supplies `ONTOLOGY_VERSION` from M9 |
| `src/atlas/knowledge/base.py` | supplies `PARSER_VERSION` (line 12) |
| `src/atlas/company/builder.py` | supplies `BUILDER_VERSION` (line 80) |
| `src/atlas/cli.py` | `@cli.command` pattern for #65 |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `feat(analysis): add SHARED_PARSER_VERSION to patterns` | constant + a test asserting it is a non-empty string | trivially covered |
| 2 | `feat(analysis): expose analyzer_versions from registry` | function + test asserting keys equal `supported_kinds()` | covered by its own test |
| 3 | `feat(provenance): add BuildFingerprint with stable digest` | `provenance.py` + `tests/unit/test_provenance.py` (stability, per-component sensitivity, `code_rev` exclusion) | module and tests together per C1 |
| 4 | `test(provenance): guard that every extraction module is versioned` | #64, including the `shareholding_trend` exclusion comment | test-only |
| 5 | `feat(cli): add fingerprint show command` | command + CLI test | covered |

**Ordering rationale:** commits 1–2 supply inputs that commit 3 consumes. Reversing them leaves `BuildFingerprint` referencing a constant that does not exist — red on mypy (C2), not just on tests.

---

# M-PRE — Determinism Pre-flight · S · Week 2

**Blocks M1.** Decide D1 and D2 before starting.

### Checklist
- [ ] `sort_keys=True` at `store.py:753` and `store.py:816` (#61)
- [ ] `sources` lists sorted inside `_finalize_profile()` — sort only, no dedupe (#66)
- [ ] Equivalence test: full `build_profile` vs repeated `merge()`, byte-identical (#32-PRE)
- [ ] Fixture must put at least two results in the **same** snapshot, or the test passes vacuously
- [ ] Synthetic variant unmarked (CI gate) + golden-corpus variant marked `integration` — per D1
- [ ] Tie-order test: two same-day filings of the same kind, both orders (#60)
- [ ] `atlas profile diff <a> <b>` (#67)
- [ ] ~~`_finalize_profile()` called from `CompanyStore.merge()` (#62)~~ — **retired, already implemented**

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/company/store.py` | both `json.dumps` sites (753, 816); `merge()` at 767; `_serialize_profile` at 121 |
| `src/atlas/company/builder.py` | `_finalize_profile` at 1040; 9 `sources.append` sites; `build_profile` sort at 1124 |
| `tests/unit/test_company_store.py` | existing merge-semantics tests — must stay green |
| `tests/conftest.py` | `test_settings` / `atlas` fixtures |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `test(company): add profile equivalence and tie-order tests (xfail)` | #32-PRE + #60, marked `xfail(strict=True)` | **xfail is what keeps this commit green.** It documents the defect before fixing it and proves the test actually detects it. |
| 2 | `fix(company): sort sources and serialize profiles deterministically` | #61 + #66, and **remove the xfail markers from commit 1** | sorting-only changes; existing tests parse JSON, never bytes (D3). `strict=True` guarantees this commit is what turns the tests green — an xfail that unexpectedly passes is itself a failure |
| 3 | `feat(cli): add profile diff command` | #67 + tests | covered |

**Corrected during implementation — the fix sequence collapsed from 3 commits to 2.** The original plan had a third fix commit for #62. That issue is retired (see below); its work already exists in the tree. #67 is unchanged and remains its own commit, being tooling rather than a fix.

**Why #62 was retired.** The plan asserted that `CompanyStore.merge()` never finalizes, making incremental profiles keep ingestion order. False: `merge()` calls `merge_result()` (`store.py:809`), and `merge_result()` ends with `_finalize_profile(profile)` (`builder.py:1101`) — its docstring already says "All collections are re-sorted after ingestion." The original reading stopped at `store.py:809` without opening `merge_result`.

Caught by the `strict=True` xfail on its first run: the test XPASSed instead of failing, which is exactly what strict mode exists to surface.

**The divergence is still real, with a different cause.** `_finalize_profile` sorts 16 containers and no `sources` list. Two results merging into the *same* snapshot, arriving newest-first, produce:

```
full  sources: [['fr-early', 'fr-late']]     # build_profile sorts by source_date
incr  sources: [['fr-late', 'fr-early']]     # arrival order, never sorted
```

So #66 is the fix, not #62.

**Fixture requirement, learned the same way.** The first fixture gave each result its own snapshot, so every `sources` list held one element and the test passed vacuously. At least two results must share a `(period, basis)` key or the equivalence test proves nothing.

---

# M1 — AssertionStore · L · Weeks 3–5

### Checklist
- [ ] `Assertion` / `AssertionRun` models, `value_type` explicit (#7)
- [ ] `assertion_id` including `ordinal`; `INSERT` raises on conflict (#69)
- [ ] `canonical_for_hash()` — single timestamp exclusion list (#70)
- [ ] `PRAGMA user_version` migrations; named exceptions only per C3 (#68)
- [ ] Schema: `assertions`, `assertion_runs`, two indices (#8)
- [ ] `write_run()` / `read_run()`, transactional, idempotent (#9)
- [ ] `writer.py` — `AnalysisResult` → rows (#10)
- [ ] `reader.py` — rows → facts, deterministic `(source_date, evidence_id, assertion_id)` order (#11)
- [ ] Multi-version rule: highest version matching current fingerprint, else raise (#71)
- [ ] `atlas analyze --company X [--kind K]` (#12)
- [ ] Round-trip across all 11 analyzers (#13)
- [ ] Idempotency + version-bump tests (#14)
- [ ] Value-type fidelity (#15)
- [ ] Failure path: `status='failed'`, zero assertion rows (#16)
- [ ] Store size / row count recorded (#17)
- [ ] `atlas assertion explain <id>` (#72)
- [ ] `atlas store status --company X` (#73)

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/analysis/base.py` | `AnalysisFact`, `AnalysisResult`, `Provenance`, `EntityMention` shapes |
| `src/atlas/analysis/registry.py` | `analyze()` dispatch for the writer's caller |
| `src/atlas/knowledge/base.py` | SQLite *shape* reference only — `_db_conn` contextmanager pattern (165). **Not** its migration mechanism |
| `src/atlas/provenance.py` | fingerprint stamped on every row |
| `src/atlas/acquisition/repository.py` | resolves the company root the DB sits in |
| `tests/corpus/expectations/*.json` | 11 files; the round-trip corpus for #13 |
| `tests/conftest.py` | `isolated_repo_factory` for integration variants |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `feat(assertions): add canonical_for_hash timestamp exclusion` | #70 + tests | standalone helper |
| 2 | `feat(assertions): add Assertion and AssertionRun models` | #7 + #69 ID derivation + tests incl. ordinal collision cases | models + tests together (C1) |
| 3 | `feat(assertions): add user_version migration runner` | #68 + tests: fresh create, idempotent re-run, failure raises | named exceptions only (C3) |
| 4 | `feat(assertions): add AssertionStore schema and open/create` | #8 on top of commit 3 + schema tests | migration runner already green |
| 5 | `feat(assertions): add write_run and read_run` | #9 + transactional/idempotent tests | store exists |
| 6 | `feat(assertions): add AnalysisResult writer` | #10 + #16 failure path + tests | |
| 7 | `feat(assertions): add reader with deterministic ordering` | #11 + #71 multi-version rule + property test | |
| 8 | `feat(cli): add atlas analyze command` | #12 + CLI test | full write path green |
| 9 | `test(assertions): round-trip all 11 analyzers` | #13 synthetic (CI) + golden variant marked `integration` per D1; #14, #15, #17 | |
| 10 | `feat(cli): add assertion explain` | #72 + tests | |
| 11 | `feat(cli): add store status` | #73 + tests | |

**Ordering rationale:** 1→2 because ID derivation calls the hash helper. 3→4 because the schema is created *by* a migration, so the runner must exist first — building the schema with ad-hoc DDL and retrofitting migrations later is how the `knowledge/base.py` situation arose. 6→7 because the reader's tests need something to read.

---

# M2 — EntityStore · M · Week 6

### Checklist
- [ ] `entity_mentions` table as migration #2 under #68 (#18)
- [ ] `mention_id` from surface form, **not** `entity_id` (#74)
- [ ] Writer persists mentions in the same transaction as facts (#19)
- [ ] Reader reattaches mentions to `AnalysisResult.entities` (#20)
- [ ] Round-trip preserves `role`, `affiliation`, `identifier`, `question_text`, `provenance` (#21)
- [ ] Writer atomicity under injected failure (#22)
- [ ] Ordering-stability confirmation test (#75)

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/knowledge/entities/model.py` | `Entity` shape; documents the order-dependent `entity_id` invariants that #74 routes around |
| `src/atlas/knowledge/entities/resolver.py` | read only — no changes |
| `src/atlas/analysis/base.py` | `EntityMention`, five context fields (382-416) |
| `src/atlas/assertions/store.py`, `writer.py`, `reader.py` | extended, not replaced |
| `tests/unit/test_entities.py`, `tests/unit/test_director_identity.py` | supply #21's fixtures |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `feat(assertions): add entity_mentions table migration` | #18 + #74 `mention_id` derivation + tests | migration runner from M1 handles it |
| 2 | `feat(assertions): persist entity mentions in writer transaction` | #19 + #22 atomicity | table exists |
| 3 | `feat(assertions): reattach mentions in reader` | #20 + #21 round-trip | |
| 4 | `test(assertions): mention_id stable across corpus orderings` | #75, two-process check | |

---

# M3 — Profile from Tier 1 · M · Weeks 7–8

### Checklist
- [ ] `reader.results_for(company_id)`, `excerpts={}` (#23)
- [ ] `profile_source: Literal["analyzers","assertions"]` on `Settings`, default `"analyzers"` (#24)
- [ ] `CompanyStore` routes through the configured source; `builder.py` untouched (#25)
- [ ] Byte-identity equivalence, both variants per D1 (#26)
- [ ] Reader determinism — ten reads, identical ordering (#27)
- [ ] Import-boundary test: `builder.py` has no `.excerpts` reference (#28)

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/config/settings.py` | pydantic `BaseSettings`, `env_prefix="ATLAS_"` — `profile_source` becomes `ATLAS_PROFILE_SOURCE` automatically |
| `src/atlas/company/store.py` | build/merge call sites |
| `src/atlas/company/builder.py` | **read-only.** Any diff here is a deviation |
| `src/atlas/assertions/reader.py` | from M1 |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `test(company): assert builder never reads excerpts` | #28 | passes today; locks the assumption before anything depends on it |
| 2 | `feat(assertions): add results_for reconstruction` | #23 + #27 determinism | |
| 3 | `feat(config): add profile_source setting` | #24 + test both values parse | default unchanged, no behaviour change |
| 4 | `feat(company): route profile build through configured source` | #25 + tests both paths | default still `analyzers`, so every existing test passes untouched |
| 5 | `test(company): profile source equivalence` | #26 synthetic + golden variant | |

**Ordering rationale:** #28 first — it is free, it passes now, and it is the tripwire for the assumption commits 2–5 rest on. Commit 3 before 4 because the setting must exist before it is read (C2: mypy).

---

# M4 — Rebuild Engine · M · Week 9

### Checklist
- [ ] `src/atlas/rebuild.py`, `--from evidence|assertions` (#29)
- [ ] `atlas rebuild` CLI with `--verify` writing nothing (#30)
- [ ] Canonical comparison helper reusing M1's `canonical_for_hash()` (#31)
- [ ] Equivalence gate: full / incremental / shuffled / reversed (#32)
- [ ] Residual order-dependence fixes, 1–2 day budget (#33)
- [ ] Idempotency — rebuild twice byte-identical (#34)
- [ ] Flip `profile_source` default to `assertions` (#35)

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/assertions/{writer,reader}.py` | pipeline stages |
| `src/atlas/knowledge/base.py` | parse stage for `--from evidence` |
| `src/atlas/analysis/registry.py` | analyze stage |
| `src/atlas/company/store.py` | project stage |
| `src/atlas/config/settings.py` | #35 default flip |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `feat(rebuild): add canonical comparison helper` | #31, reusing #70's exclusion list | no second exclusion list |
| 2 | `feat(rebuild): add rebuild orchestration` | #29 + tests | orchestration only, no new logic |
| 3 | `feat(cli): add rebuild command with verify` | #30 + test asserting mtimes unchanged | |
| 4 | `test(rebuild): equivalence gate across orderings` | #32 both variants + #34 | **may go red — that is the milestone's purpose.** If red, commit 4 lands with `xfail(strict=True)` and commit 5 removes it, mirroring M-PRE. |
| 5 | `fix(company): resolve residual order-dependence` | #33; scope unknown until commit 4 runs | |
| 6 | `feat(config): default profile_source to assertions` | #35 | only after 4 and 5 are green |

**Commit 6 is the cutover.** One line, one revert. Do not bundle anything with it.

---

# M5 — Judgment Store · M · parallel, any week after 1

### Checklist
- [ ] `Judgment` model, content-addressed, `supersedes` chain (#36)
- [ ] `judgment/store.py`, append-only JSON per subject, `store_version = "1"` (#37)
- [ ] `atlas judgment add|list|supersede`, `--force` for deletion (#38)
- [ ] Append-only + supersede-chain tests, cycle rejection (#39)
- [ ] Survives full rebuild byte-identical (#40)
- [ ] Import-boundary: rebuild path never imports `judgment/` (#41)

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/research/memory.py` | `ThesisStore` file conventions, `STORE_VERSION`, `IncompatibleStoreVersionError` — copy the shape |
| `src/atlas/reasoning/contracts.py` | `SubjectRef` |
| `src/atlas/cli.py` | command registration |

### Commits
| # | Commit | Contents |
|---|---|---|
| 1 | `feat(judgment): add Judgment model` | #36 + tests |
| 2 | `feat(judgment): add append-only JudgmentStore` | #37 + #39 |
| 3 | `feat(cli): add judgment commands` | #38 + tests |
| 4 | `test(judgment): survives rebuild, rebuild never imports store` | #40 + #41 |

Fully independent of M0–M4. Safe filler when M1 or M4 is blocked.

---

# M6 — Answer Pinning · M · Week 10

### Checklist
- [ ] Pinning fields on the answer envelope, additive with defaults (#42)
- [ ] Populate in `ask.py` and `thesis.py` (#43) — **split per the roadmap's own risk note:** `evidence_ids` (cheap, DoD-required) separate from `assertion_ids` (may slip)
- [ ] Footer rendering across three renderers (#44)
- [ ] Pre-pinning theses load with `fingerprint=None` (#45)
- [ ] Tests across `ask`, `research`, `investigate`, `thesis` (#46)

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/reasoning/contracts.py` | `ReasoningResult`, `Finding`, `Claim` |
| `src/atlas/reasoning/ask.py`, `render.py` | answer path |
| `src/atlas/research/thesis.py`, `render.py`, `memory.py` | thesis path; `memory.py` handles the `None` default |
| `src/atlas/reasoning/context.py`, `retrieval.py` | source of "actually consulted" — 484 + 533 lines, the risk area |
| `src/atlas/citation.py` | footer formatting conventions |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `feat(reasoning): add pinning fields to answer envelope` | #42 + #45 backward-compat load | additive with defaults — every existing test passes |
| 2 | `feat(reasoning): populate fingerprint and evidence_ids` | #43a — `evidence_ids` already tracked | cheap half, satisfies DoD |
| 3 | `feat(reasoning): render pinning footer` | #44 + updated renderer tests | |
| 4 | `test(reasoning): pinning across all four answer surfaces` | #46 | |
| 5 | `feat(reasoning): record consulted assertion_ids` | #43b — **may slip past M6 without blocking it** | |

---

# M7 — Selective Invalidation · M · Week 11

### Checklist
- [ ] `merge(result, *, allow_reanalysis=False)` (#76)
- [ ] `affects(kind)` sub-digests including `shared_parser_version` (#47)
- [ ] `stale_evidence()` (#48)
- [ ] `atlas rebuild --stale-only` (#49)
- [ ] Invalidation-scope tests (#50)
- [ ] Row-count invariant after `--stale-only` (#77)

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/company/store.py` | `merge()` at 767; `StaleResultError` at 96; raise at 801-806 |
| `src/atlas/provenance.py` | `affects()` |
| `src/atlas/assertions/store.py` | `stale_evidence()` |
| `src/atlas/rebuild.py` | `--stale-only` |
| `tests/unit/test_company_store.py` | must pass unchanged with the default |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `feat(company): add allow_reanalysis to CompanyStore.merge` | #76 + tests for both branches | default `False` preserves every caller; existing tests untouched |
| 2 | `feat(provenance): add per-kind affects sub-digests` | #47 + tests | |
| 3 | `feat(assertions): add stale_evidence query` | #48 + tests | |
| 4 | `feat(rebuild): add stale-only mode` | #49 + #50 + #77 | |

**Commit 1 is the unbudgeted work.** Land it first and alone — it touches a 3,400-test-covered class and its blast radius should be visible in isolation.

---

# M8 — Metrics Pinning · S · Week 11

### Checklist
- [ ] `fingerprint` on `QueryResult`, populated across ~30 query functions (#51)
- [ ] Renderer prints it; text fixtures updated (#52)
- [ ] Coverage test driven by `available_queries()` (#53)

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/query/engine.py` | 1,619 lines, `QueryResult`, `available_queries()`, `run_query()` |
| `src/atlas/query/render.py` | text renderer |
| `src/atlas/query/metrics.py` | 751 lines, secondary surface |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `test(query): assert every registered query returns a pinned result` | #53, `xfail(strict=True)` | fails for all ~30 — that is the inventory |
| 2 | `feat(query): pin fingerprint on QueryResult` | #51 across all functions, one commit; **remove xfail** | strict xfail proves completeness |
| 3 | `feat(query): render fingerprint in query output` | #52 + fixture updates | |

Write the test first so the mechanical sweep has a checklist that fails loudly on a miss.

---

# M10 — Backfill & Operator CLI · M · Week 12

### Checklist
- [ ] `atlas migrate assertions --company X [--dry-run]`, temp-DB-then-move (#54)
- [ ] Move gated on **normalized** profile equality (#55)
- [ ] `atlas store verify` (#57) — merge with `doctor` naming per the audit
- [ ] Safety tests: dry-run, interruption, re-run no-op (#58)
- [ ] Migrate existing repos, record before/after (#59)
- [ ] Remove the analyzer path and `profile_source` flag — **add as a new issue #78**, per the audit's failure mode 9

### Prerequisite files
| File | Why |
|---|---|
| `src/atlas/assertions/*` | full stack |
| `src/atlas/company/store.py` | comparison target; never mutated |
| `src/atlas/rebuild.py` | backfill reuses the pipeline |
| `src/atlas/cli.py` | commands |

### Commits
| # | Commit | Contents | Green because |
|---|---|---|---|
| 1 | `feat(cli): add migrate assertions with dry-run` | #54 + #58 dry-run/interruption/re-run tests | dry-run default in tests; nothing written |
| 2 | `feat(cli): gate migration on normalized profile equality` | #55 | |
| 3 | `feat(cli): add store verify` | #57 + tests | |
| 4 | `chore: migrate existing company repos` | #59 — data operation, record numbers in the commit body | no code change |
| 5 | `refactor(company): remove analyzer profile path and flag` | #78 (new) | only after #59 confirms every repo migrated |

---

## Summary of flagged deviations

| ID | Deviation | Status | Needs your call |
|----|-----------|--------|-----------------|
| D1 | Equivalence tests split synthetic (CI) / golden (`integration`) | **Blocking M-PRE** | **Yes** |
| D2 | `itertools.permutations` instead of adding Hypothesis | Blocking M-PRE | **Yes** |
| D3 | M-PRE fixture-churn risk does not exist — downgrade the roadmap text | Informational | No |
| D4 | #62 re-sorts existing profiles on next merge | Informational | No |
| — | M-PRE as 3 commits, not 1 (strictly more reversible) | Minor | Proceeding unless told otherwise |
| — | New issue #78: remove the analyzer path in M10 | Additive | Confirm |

D1 is the one that matters. Without it the plan's central invariant has no CI gate, and every "green in CI" claim downstream of M4 is false.
