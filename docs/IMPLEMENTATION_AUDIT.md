# Atlas Implementation Audit

**Role:** Principal Engineer, one-week pre-implementation audit.
**Constraint:** architecture approved, execution plan approved. No redesign. Findings are implementation risks only.
**Method:** every claim below is verified against the tree at `claude/graphify-a2c2a0`. File:line references are real. Where I could not verify, I say so and route it to a spike.

---

## Executive summary

The plan is sound. Three things in it are unsound, and all three are the same class of problem: **the plan assumes properties of the existing code that do not hold.**

1. **The profile is not currently deterministic.** Two verified sources of nondeterminism (`json.dumps` without `sort_keys`, and unsorted `sources` lists) mean M4's byte-identity gate will fail for reasons that have nothing to do with assertions. Discovering this in week 8, on top of three milestones of new storage, makes the diff unattributable.
2. **The fingerprint is incomplete by construction.** `analysis/patterns.py` — 381 lines of shared parsers imported by 7 of the 11 analyzers — has no version constant. A bug fix there changes extracted values across seven analyzers while the fingerprint stays identical. M7's selective invalidation is unsound on top of this.
3. **The migration pattern the plan says to copy cannot express what the plan needs.** `knowledge/base.py` migrations are a blind `try: ALTER TABLE; except OperationalError: pass`. No `user_version`, no ordering, no failure surface. It works for ADD COLUMN and nothing else, and it swallows real errors.

None require architecture changes. All three are cheap now and expensive in week 8.

---

# Part 1 — Milestone ordering

## Would I change the order? Yes. One change, and it is the whole audit's headline.

**Move the rebuild equivalence gate from M4 (week 8) to week 2, and run it against the *existing* analyzer path.**

The test in issue #32 does not depend on assertions. It asks: does `build_profile(all_results)` equal the result of repeated `CompanyStore.merge()`? Both sides of that comparison exist today. Running it now costs ~2 days and answers the plan's largest unknown before any storage work is built on top of it.

The current sequencing has M4 doing two jobs at once: proving the reader is faithful *and* proving the builder is order-independent. When #32 goes red in week 8, you cannot tell which. You will be bisecting a reader you wrote three weeks earlier against a builder nondeterminism that predates the project.

Run it first and the failure is unambiguous: it is the builder, every time, because there is nothing else in the loop yet. Then M3's byte-identity test in week 6 has a known-good baseline instead of a hope.

**Revised order:**

| Week | Was | Now |
|------|-----|-----|
| 1 | M9, M0 | M9, M0 |
| 2 | M1 starts | **M-PRE: determinism pre-flight** (new, S) |
| 3–5 | M1 | M1 |
| 6 | M2 | M2 |
| 7–8 | M3 | M3 |
| 9 | M4 | M4 (now mechanically small — the hard part already landed) |
| 10–12 | M6, M7+M8, M10 | unchanged |

Net calendar cost: zero. M4 shrinks by roughly what M-PRE costs, because issue #33's three-day fix budget moves to week 2 where it is cheaper.

## Milestones that depend on hidden work

### M7 — Selective invalidation. **Blocked by a raise the plan never mentions.**

`CompanyStore.merge()` raises `StaleResultError` when an `evidence_id` is already tracked under a *different* `analyzer_version` (`store.py:96`, `store.py:776`). Recovery, per its own docstring, is "rebuild from scratch."

M7's entire premise is re-running one analyzer at a bumped version and merging the result. That path throws today. M7 therefore contains unbudgeted work: either change `merge()`'s contract or route selective invalidation around it. Neither is in the 59 issues.

**Hidden work: ~2 days, plus a decision that touches a 3,400-test-covered contract.**

### M1 — AssertionStore. **Contains an unstated multi-version decision.**

Issue #14 requires that bumping `analyzer_version` creates new rows while "old rows survive" — the schema PK is `(evidence_id, analyzer_version)`, so N versions coexist.

`CompanyStore.ingested_results` is keyed by `evidence_id` alone (`store.py:792-795`). Exactly one version per evidence, ever.

So when M3's reader sees two versions of the same evidence, which does it project? The plan never says. Options are all defensible — latest version, fingerprint-matching version, explicit pin — but the choice must be made in M1's schema, not discovered in M3.

**Hidden work: a design decision, cheap if made in week 3, a schema migration if made in week 7.**

### M0 — Fingerprint. **Depends on a version that does not exist.**

`analysis/patterns.py` is imported by `acquisition`, `annual_report`, `board_outcome`, `buyback`, `earnings_transcript`, `financial_results`, `investor_presentation` — 7 of 11 analyzers — and carries no version constant. `shareholding_trend.py` likewise, imported via `analysis/__init__.py`.

`analyzer_versions()` as specified in issue #4 reads `_REGISTRY`, which contains neither. The fingerprint will be structurally blind to changes in the most widely shared parsing code in the system.

**Hidden work: ~half a day. Trivial now. Silently wrong forever if skipped.**

### M10 — Backfill. **Depends on a determinism property nothing has established.**

Issue #55 gates the atomic move on "projected profile byte-identical to the stored one." Stored profiles were written by earlier `builder_version`s under insertion-order serialization. Byte-identity against a historical artifact is a much stronger claim than byte-identity between two fresh builds, and the plan treats them as the same test.

**Hidden work: either a normalization step, or a weaker and explicitly-specified comparison for legacy profiles.**

---

# Part 2 — Per-milestone risk

| Milestone | Risk |
|-----------|------|
| M9 Ontology freeze | **LOW** |
| M0 Fingerprint | **HIGH** |
| M1 AssertionStore | **HIGH** |
| M2 EntityStore | **MEDIUM** |
| M3 Profile from Tier 1 | **CRITICAL** |
| M4 Rebuild equivalence | **CRITICAL** |
| M5 Judgment store | **LOW** |
| M6 Answer pinning | **MEDIUM** |
| M7 Selective invalidation | **HIGH** |
| M8 Metrics pinning | **LOW** |
| M10 Backfill | **HIGH** |

---

### M9 — Ontology freeze · LOW
- **Failure mode:** snapshot test becomes a rubber stamp — developer regenerates it reflexively on every `FactKind` addition without bumping `ONTOLOGY_VERSION`.
- **Probability:** high (~70%). This is what always happens to snapshot tests.
- **Impact:** low individually, but it silently disarms M7's invalidation.
- **Mitigation:** make the failure message name the exact two edits required, and put the snapshot in a file whose diff is obvious in review. Do not provide a `--update-snapshot` flag.

### M0 — Fingerprint · HIGH
- **Failure mode:** fingerprint omits `patterns.py` and `shareholding_trend.py`. A parser fix changes values across 7 analyzers; digest unchanged; M7 declares nothing stale; every downstream answer is pinned to a fingerprint that does not describe the code that produced it. The version-pinning invariant is false while appearing true.
- **Probability:** **certain if unaddressed** — verified absent today.
- **Impact:** critical and silent. Corrupts the guarantee the whole tier model exists to provide.
- **Mitigation:** add `SHARED_PARSER_VERSION` to `patterns.py` and a version to `shareholding_trend.py`; include both in the fingerprint; add a test asserting every module under `src/atlas/analysis/` that is imported by a registered analyzer contributes a version component. Half a day.

### M1 — AssertionStore · HIGH
- **Failure mode:** `assertion_id` collision silently drops rows. Verified exposure: `annual_report.py:634-645` emits every `RISK_FACTOR` in a loop sharing one `char_offset` (the *section* offset, not per-risk) and one `section="mda_risk"`. The ID tuple then varies only by `value`. Two identical risk strings in one document collapse to one row. Six sites emit `char_offset=None` entirely (`shareholding_pattern.py:120,261`; `financial_results.py:597,781,1243,1251,1264`).
- **Probability:** medium-high (~50%) that at least one real collision exists in the golden corpus.
- **Impact:** high and silent — a dropped assertion is a fact that vanishes from the profile with no error anywhere.
- **Mitigation:** Spike S2 (below) before writing the schema. Then add an ordinal: `assertion_id = sha256(… | ordinal_within_(evidence_id, kind, section))`. Preserves determinism, removes collision entirely. Add a hard `INSERT` conflict check that raises rather than `INSERT OR REPLACE`.

### M2 — EntityStore · MEDIUM
- **Failure mode:** the additive migration follows the `_MIGRATE_V*` pattern, which swallows every `sqlite3.OperationalError` (`knowledge/base.py:184-186`). A `CREATE TABLE` failing for a real reason — locked DB, disk full, SQL typo — is indistinguishable from "already exists." The table silently does not exist; entity writes fail; profiles quietly lose entities.
- **Probability:** medium (~35%).
- **Impact:** medium — under-populated profiles, no error.
- **Mitigation:** do not copy the pattern. Use `PRAGMA user_version` with ordered, non-swallowing migrations. See Part 8, change 2.

### M3 — Profile from Tier 1 · CRITICAL
- **Failure mode:** byte-identity fails and the cause is unattributable, because the profile is **already** nondeterministic. Two verified sources:
  - `store.py:753` and `store.py:816` call `json.dumps(..., indent=2, ensure_ascii=False)` with **no `sort_keys=True`**. Every dict serializes in insertion order.
  - `FinancialSnapshot.facts`, `ESGSnapshot.facts`, and the snapshot type at `model.py:216` are `dict[FactKind, float]` populated by merge order.
  - `sources.append()` fires at 10 sites in `builder.py` (135, 235, 281, 372, 421, 432, 495, 551, 576…). `_finalize()` (`builder.py:1041-1056`) sorts the *containers* but never the `sources` lists inside them.

  A full build ingests in one order, an incremental build in another, and the JSON differs while the profile is semantically identical.
- **Probability:** **certain.** This is not a risk; it is the current behaviour.
- **Impact:** critical to the plan's schedule. It is the difference between M3 taking two weeks and taking four.
- **Mitigation:** M-PRE (Part 1). Fix `sort_keys=True` and sort `sources` before M1 begins, and prove it with the equivalence test running against the analyzer path.

### M4 — Rebuild equivalence · CRITICAL
- **Failure mode:** issue #33's three-day fix budget is consumed entirely by the M3 nondeterminism above, and the *actual* order-dependence in `merge_result()` — the thing the test exists to find — is never reached. Or worse, the test is weakened to field-subset comparison to make the milestone close.
- **Probability:** high (~65%) under the current ordering; low if reordered.
- **Impact:** critical. Every milestone after M4 assumes this invariant holds. A weakened gate makes the rest of the plan rest on an assertion nobody has checked.
- **Mitigation:** reorder per Part 1. Write the weakening rule down now: *this test may not be relaxed; if it cannot pass, the milestone stops and the builder gets fixed.* Track `#33` as an explicit unknown with its own spike (S5).

### M5 — Judgment store · LOW
- **Failure mode:** `Judgment` and `Thesis` drift into near-duplicates and someone unifies them, reintroducing the Tier 0/Tier 1 confusion the split exists to prevent.
- **Probability:** low near-term (~20%), rising with time.
- **Impact:** medium — a lifecycle bug that is very hard to see.
- **Mitigation:** issue #41's import-boundary test is the right control. Keep it. Add a comment in `judgment/model.py` pointing at `research/memory.py`'s existing argument for why the two stores cannot merge.

### M6 — Answer pinning · MEDIUM
- **Failure mode:** "record what was actually consulted, not what was available" (issue #43) is harder than it reads. `reasoning/context.py` is 484 lines and `reasoning/retrieval.py` is 533; the set of assertions that actually influenced an answer is not currently tracked anywhere. Instrumenting it is a real change to a heavily-tested subsystem, not an additive field.
- **Probability:** medium (~45%) that this exceeds its estimate.
- **Impact:** medium — schedule, not correctness. Recording "available" instead of "consulted" is a weaker but still useful pin.
- **Mitigation:** split issue #43. Ship `evidence_ids` (already tracked, cheap) in week 10; make `assertion_ids` a separate issue that may slip without blocking the milestone. Decide up front which one the DoD requires.

### M7 — Selective invalidation · HIGH
- **Failure mode:** two compounding problems. (a) `merge()` throws `StaleResultError` on the exact path M7 needs. (b) Under-invalidation from an incomplete fingerprint (M0) serves stale data with no signal.
- **Probability:** high (~70%) that M7 overruns its S estimate.
- **Impact:** high — under-invalidation is worse than no invalidation, because it is silent and it undermines the pinning guarantee M6 just shipped.
- **Mitigation:** resize M7 from S to M. Add an explicit issue for the `merge()` contract change. Keep full invalidation as the default and make `--stale-only` opt-in — already in the plan, keep it there. Add an assertion-count invariant: after `--stale-only`, the store must hold the same row count as a full rebuild, or fail loudly.

### M8 — Metrics pinning · LOW
- **Failure mode:** `query/engine.py` is 1,619 lines with ~30 query functions; a one-commit mechanical change misses some, and #53's coverage test is the only thing catching it.
- **Probability:** low (~25%) given #53 exists.
- **Impact:** low.
- **Mitigation:** none beyond #53. Write #53 first, watch it fail for all 30, then fix.

### M10 — Backfill · HIGH
- **Failure mode:** the byte-equality gate (#55) is unsatisfiable against historical profiles written under a different `builder_version` and pre-`sort_keys` serialization, so it gets disabled to ship — removing the only safety control on the one milestone with real data-loss potential.
- **Probability:** high (~60%).
- **Impact:** high. Not data loss (the old JSON is never mutated), but loss of the verification that makes the migration trustworthy.
- **Mitigation:** specify the legacy comparison explicitly now: normalize both sides through the *new* canonical serializer before comparing, and compare semantically (sorted `sources`, sorted keys) rather than byte-wise for pre-existing profiles. Byte-identity stays the standard for fresh-vs-fresh.

---

# Part 3 — Assumptions in the plan that may not hold

Ruthless pass. Verified status on each.

### 3.1 "`builder.py` never reads `.excerpts`" — **TRUE, verified.**
`grep excerpts src/atlas/company/builder.py` returns nothing. The `excerpts={}` reconstruction is safe. Issue #28's boundary test is correctly targeted. **This assumption holds.**

### 3.2 "Profiles serialize deterministically" — **FALSE, verified.**
`store.py:753`, `store.py:816` — `json.dumps` without `sort_keys=True`. The plan's byte-identity tests (#26, #32, #55) all assume otherwise. **This is the single most consequential wrong assumption in the plan.**

### 3.3 "`build_profile()` is order-independent" — **NOT ESTABLISHED.**
Its docstring says results "may be in any order." `_finalize()` sorts containers, so semantic order-independence is plausibly true. But `sources` lists (10 append sites, never sorted) and insertion-ordered `facts` dicts mean *serialized* output is order-dependent even if the profile is semantically stable. The plan conflates these two claims. **Semantic: probably true. Byte: false.**

### 3.4 "`_MIGRATE_V*` is a reusable migration pattern" — **FALSE.**
`knowledge/base.py:180-186` runs every ALTER unconditionally inside `try/except sqlite3.OperationalError: pass`. There is no `PRAGMA user_version`, no migration ordering, no way to express anything but ADD COLUMN, and no way to distinguish "already applied" from "failed for a real reason." M1 and M2 both say to copy it. **Do not.**

### 3.5 "`analyzer_versions()` covers everything that affects extraction" — **FALSE, verified.**
`patterns.py` (381 lines, 7 importers) and `shareholding_trend.py` carry no version. Neither is in `_REGISTRY`. **The fingerprint is blind to the most-shared parsing code in the system.**

### 3.6 "Content-addressing yields unique IDs" — **NOT ESTABLISHED, with a concrete counterexample path.**
`annual_report.py:634-645`: all `RISK_FACTOR` facts in one loop share `char_offset=risk_offset` and `section="mda_risk"`. Six further sites emit `char_offset=None`. Uniqueness rests entirely on `value` being distinct within a `(evidence_id, kind, section, period)` group. **Unverified. Spike S2.**

### 3.7 "`merge()` supports incremental rebuild for the equivalence test" — **PARTIALLY FALSE.**
It supports it for *new* evidence at a *stable* analyzer version. It raises `StaleResultError` otherwise (`store.py:96`). M4's test is fine (fresh store, new evidence). M7 is not.

### 3.8 "Multiple analyzer versions can coexist per evidence" — **CONTRADICTED by CompanyStore.**
Assertion store PK is `(evidence_id, analyzer_version)`. `ingested_results` is keyed by `evidence_id` alone (`store.py:792-795`). The reader's version-selection rule is undefined.

### 3.9 "SQLite handles the row volume" — **LIKELY TRUE, unmeasured.**
11 analyzers × a TCS-scale repo. Nothing here worries me; SQLite handles millions of rows. But the plan asserts it without a number. Spike S1 produces the number.

### 3.10 "Storing `value` as TEXT round-trips safely" — **MOSTLY TRUE, with one real trap.**
Python 3's `repr(float)` is shortest-round-trip, so `float ↔ str` is exact. The actual trap is **int/float conflation**: `5` and `5.0` both stringify distinguishably, but if `value_type` is inferred rather than stored, `"5"` reconstructs as `int` where the analyzer emitted `float`, changing the assertion_id and every downstream equality. The plan's explicit `value_type` column is the right call — **keep it, and make issue #15 assert type identity, not just value equality.**

### 3.11 "`analyzed_at` is a benign timestamp" — **FALSE for hashing.**
`AnalysisResult.analyzed_at` uses `default_factory=lambda: datetime.now(timezone.utc)` (`base.py:486`). It is non-deterministic by construction. It must be excluded from `assertion_id`, excluded from the fingerprint, and excluded from byte-identity comparison — while still being stored. The plan's #31 handles the comparison case. It does not mention the hashing case.

### 3.12 "The 11 registered analyzers are all the analyzers" — **TRUE for dispatch, misleading for versioning.**
`_REGISTRY` has 11 entries. But `analysis/__init__.py` re-exports from `shareholding_trend`, and `query/engine.py:137` notes it "mirrors the signal logic in shareholding_trend.py" — logic duplicated across two modules, one of which is invisible to the fingerprint and to the registry.

### 3.13 "Entity mentions are deduplicated consistently" — **UNVERIFIED.**
`shareholding_pattern.py:111-113` dedupes on `entity.entity_id` within one document via a `seen` set. Whether every analyzer does this, and whether entity_id is stable across runs, is unchecked. If entity_id derives from anything non-deterministic, M2's content-addressed `mention_id` inherits it. **Spike S4.**

### 3.14 "Backfill is safe because evidence is immutable" — **TRUE but incomplete.**
Evidence immutability makes re-analysis safe. It does not make the *comparison* meaningful — see 3.2 and M10's failure mode. Immutability protects the input, not the verification.

---

# Part 4 — Spike projects

Each is one day, answers exactly one unknown, and produces a number or a yes/no. Run S1–S3 in week 1, before M0 closes.

### S1 — Assertion volume and store size · **Day 1, before M1 schema**
- **Unknown:** how many assertion rows does a real company produce, and how big is the DB?
- **Method:** run all 11 analyzers over the largest golden-corpus company, count `AnalysisFact` instances by kind, estimate rows, write a throwaway SQLite table with the proposed schema, measure file size and a full-table read.
- **Answers:** whether SQLite is fine (expected yes), whether indices are needed on day one, and whether the M3 reader can afford to load everything into memory.
- **Kill criterion:** > 5M rows or > 500 MB per company changes the M1 schema.

### S2 — `assertion_id` collision · **Day 1, before M1 schema. Highest value spike.**
- **Unknown:** does the proposed content-address tuple actually produce unique IDs on real documents?
- **Method:** run all 11 analyzers over the entire golden corpus; compute `sha256(evidence_id|kind|value|unit|period|section|char_offset|analyzer_version)` for every fact; count collisions; print every colliding group with its source file.
- **Answers:** whether an ordinal is required, and where.
- **Prediction:** collisions will appear in `annual_report` `RISK_FACTOR` and possibly `shareholding_pattern` ownership facts.
- **Kill criterion:** any collision at all ⇒ add the ordinal to the ID scheme before writing the schema.

### S3 — Profile serialization determinism · **Day 1, before M-PRE**
- **Unknown:** how far is the current profile from byte-identity, and is the gap only serialization or also semantics?
- **Method:** build one company's profile twice from shuffled result orders. Diff raw JSON. Then diff again after normalizing (`sort_keys=True`, sorted `sources`). Count residual differences.
- **Answers:** whether M-PRE is a 2-day serialization fix or a 2-week builder fix.
- **Kill criterion:** residual semantic differences after normalization ⇒ M4's #33 budget is far too small; resize before committing to the schedule.

### S4 — Entity ID stability · **Day 1, before M2**
- **Unknown:** is `Entity.entity_id` deterministic across processes?
- **Method:** resolve the same entity set in two separate processes; compare IDs; check whether resolution depends on iteration order, `hash()` (PYTHONHASHSEED-sensitive), or insertion order.
- **Answers:** whether `mention_id` can be content-addressed at all.
- **Kill criterion:** any process-dependent component ⇒ M2 needs an ID scheme fix first.

### S5 — Incremental vs full profile equivalence · **Day 2, this is M-PRE's core**
- **Unknown:** is `merge_result()` genuinely order-independent?
- **Method:** the #32 test, run today against the analyzer path. Full build vs one-at-a-time merge vs reverse order vs shuffled. Compare after S3's normalization.
- **Answers:** the true size of issue #33.
- **Kill criterion:** more than ~5 distinct order-dependence bugs ⇒ escalate M4 to L and cut M2 or M8 from the 12 weeks.

### S6 — Migration rehearsal on a real repo copy · **Day 1, before M10**
- **Unknown:** does backfill reproduce an existing stored profile?
- **Method:** copy a real company repo; backfill to a temp assertion DB; project a profile; diff against the stored one, normalized.
- **Answers:** whether #55's byte-equality gate is achievable or must be specified as semantic equality.
- **Kill criterion:** differences that are not explained by serialization ⇒ investigate before writing the migration, not during.

### S7 — Full rebuild wall-clock · **Day 1, before M4**
- **Unknown:** how long does `atlas rebuild --from evidence` take?
- **Method:** time parse → analyze → assert → project for the largest company.
- **Answers:** whether the equivalence test can run in CI on every PR or must be nightly. This shapes the CI gate design in #32.
- **Kill criterion:** > 10 minutes ⇒ CI runs a sampled subset per PR and the full matrix nightly.

---

# Part 5 — Testing strategy gaps

The plan's tests are good example-based tests. They are thin on properties, have no fuzzing, and their golden coverage is narrower than it looks.

## Missing property tests

1. **Order invariance of the profile.** For any permutation of results, `canonical(build_profile(perm)) == canonical(build_profile(sorted))`. Hypothesis over permutations of a fixed result set. This is the invariant; #32 only samples four orderings of it.
2. **Assertion ID determinism.** For any `AnalysisFact`, `id(f) == id(deepcopy(f))`, and IDs are stable across processes (subprocess, not just re-call — catches `PYTHONHASHSEED` dependence).
3. **Write/read round-trip identity.** For any `AnalysisResult`, `read(write(r)) == r` modulo the excluded timestamp fields. Generated, not just golden-corpus.
4. **Fingerprint monotonicity.** Changing any one version component changes the digest; changing none leaves it identical. Parametrized over every component, so a new component added later cannot silently escape the test.
5. **Invalidation completeness.** For any version bump, the set of assertions M7 marks stale ⊇ the set that actually differ on re-extraction. Over-invalidation passes; under-invalidation fails. This is the property that makes M7 safe.
6. **Judgment immutability.** For any sequence of rebuilds, the judgment store bytes are unchanged.

## Missing fuzz tests

1. **Value encoding fuzz.** Random `str | int | float | None` through `write → SQLite → read`, asserting both value *and* type identity. Include: `-0.0`, `1e308`, `float('inf')`, embedded NUL, embedded newline, 10 KB strings, unicode surrogate pairs, `"None"` as a literal string.
2. **Provenance fuzz.** `char_offset` of `None`, `0`, negative, beyond document length. Assert the writer either stores it faithfully or rejects it — never silently coerces.
3. **Malformed store fuzz.** Truncated SQLite file, wrong `user_version`, missing table, corrupted row. Assert a clear error, never a silently-empty profile. This is the failure mode that makes debugging in Part 6 miserable.
4. **Judgment supersede-chain fuzz.** Random DAGs of `supersedes` including cycles and dangling references. Assert cycles are rejected at write time.

## Missing golden tests

1. **Per-analyzer assertion golden files.** One checked-in JSON per analyzer per golden document, holding the exact assertion rows. Any extraction change shows up as a reviewable diff. The current golden corpus tests analyzer *output*; nothing pins the *stored* form.
2. **Canonical profile golden per company.** The normalized profile JSON, checked in. Makes M3, M4, and M10 diffs reviewable rather than a boolean.
3. **Fingerprint golden.** The digest for a known version set, checked in. Catches accidental fingerprint-shape changes.
4. **CLI output golden for `store status` / `store verify`.** Operator tooling that nobody tests rots fastest.

## Missing migration tests

1. **Forward migration from every historical schema version**, not just the current one. Requires `user_version` to exist (Part 8, change 2) — with the current blind-ALTER pattern this test is not even expressible.
2. **Migration idempotency.** Run twice, identical result.
3. **Migration interruption.** Kill mid-migration; assert the DB is either fully old or fully new, never in between.
4. **Legacy profile compatibility.** A `store_version=1` profile written before this project loads without error after all 11 milestones.
5. **Downgrade behaviour.** A newer store opened by older code must fail loudly with a version message, not silently misread. `IncompatibleStoreVersionError` already exists in `research/memory.py` — reuse that pattern in the assertion store.

## One structural gap

There is no test that the *tier boundaries* hold. Add import-boundary tests as a set, not one-offs:
- Tier 2 modules may not import analyzers directly once M4 lands.
- The rebuild path may not import `judgment/`.
- `builder.py` may not reference `.excerpts`.

Three cheap tests that encode the architecture in executable form. #28 and #41 already do two of these — make it a deliberate suite rather than two isolated tests.

---

# Part 6 — Ten most likely failure modes, six months out

Ranked by probability × impact.

### 1. The equivalence gate was weakened to ship M4
The test went red for reasons that felt unrelated to the milestone. Under schedule pressure it became a field-subset comparison. Every later milestone assumed an invariant nobody was checking.
**Prevention:** run it in week 2 against the existing path, when there is nothing to blame but the builder. Write the no-weakening rule into the milestone DoD before starting.

### 2. Silent staleness through the incomplete fingerprint
A `patterns.py` fix changed values across 7 analyzers. The digest never moved. Answers stayed pinned to a fingerprint describing code that no longer existed. Discovered months later via a number that would not reconcile.
**Prevention:** version `patterns.py` and `shareholding_trend.py` in week 1. Add the test that every extraction-affecting module contributes a component.

### 3. Assertion ID collisions eating rows
Facts disappeared from profiles with no error at any layer. Debugging started at the profile — three layers from the cause.
**Prevention:** spike S2 before the schema. Ordinal in the ID. `INSERT` raises on conflict rather than replacing.

### 4. Schema churn against a migration mechanism that cannot express it
The assertion schema changed five times in three months, as new-storage schemas always do. The blind-ALTER pattern handled the first two and silently corrupted the third.
**Prevention:** `PRAGMA user_version` and ordered non-swallowing migrations before the first table ships.

### 5. Debugging became too expensive
A wrong number in a profile required tracing profile → reader → assertion rows → analyzer → parsed document → PDF. Six layers, no tooling. Each investigation cost a day, so investigations stopped happening.
**Prevention:** build `atlas assertion explain <id>` and `atlas profile diff` in M1, not after M10. See Part 7.

### 6. Developer fatigue in the M1 → M3 stretch
Five weeks of plumbing with no visible product improvement, no user-facing change, and a red equivalence test at the end. Motivation collapsed.
**Prevention:** M5 exists in the plan as parallel filler — use it deliberately, not as a fallback. Ship one operator tool per milestone so every week produces something usable. Keep `atlas store status` in M1, not M10.

### 7. Backfill verification disabled to ship M10
The byte-equality gate could not pass against historical profiles. It was commented out. The migration ran unverified.
**Prevention:** specify the legacy comparison as semantic-after-normalization now. Rehearse with spike S6 in week 1.

### 8. Feature creep into assertion reconciliation
Two analyzers disagreed on one value. It was obviously wrong. Fixing it "properly" grew into a conflict-resolution subsystem that consumed a month and was never finished.
**Prevention:** the plan already declares this out of scope. Keep it out. When it comes up, record both rows and file an issue for after the 12 weeks.

### 9. The feature flag became permanent
`ATLAS_PROFILE_SOURCE` was never removed. Both paths were maintained for months. Every bug had to be reproduced twice, and the analyzer path silently rotted.
**Prevention:** set a removal date at the same commit that introduces the flag. Make deleting the analyzer path an explicit issue in M10 with a deadline.

### 10. Multi-version reader ambiguity surfaced as wrong numbers
Two analyzer versions coexisted for one evidence document. The reader picked by SQLite's natural row order. Profiles changed depending on write history.
**Prevention:** decide the version-selection rule in M1's schema. Add a property test that the reader's choice is a pure function of the store contents, independent of insertion order.

---

# Part 7 — Operator tooling, ranked

Ranked by how much pain each hour of building removes. The top three should exist before M3, not after M10 — they are the debugging surface for everything that follows.

### 1. `atlas assertion explain <assertion_id>` — **build in M1**
Full provenance chain in one command: assertion row → analyzer + version → evidence_id → source document → char_offset → the surrounding text. Without this, every "why is this number wrong" starts with a manual six-layer trace. This single tool is the difference between failure mode 5 happening and not happening.

### 2. `atlas profile diff <a> <b>` — **build in M-PRE, week 2**
Semantic diff of two profiles: which snapshots, which fact kinds, which values changed. Needed by M3, M4, M10 and by every debugging session in between. Building it in week 2 means the equivalence tests can *report* rather than just fail — a red boolean tells you nothing; a diff tells you where to look.

### 3. `atlas store status --company X` — **build in M1**
Tier sizes, row counts, fingerprints present, staleness counts, last rebuild. The first command you run when anything looks wrong. Currently scheduled for M10; that is nine weeks of flying blind.

### 4. `atlas rebuild --verify` — **already in M4 (#30). Keep it there.**
Rebuild to temp, diff, write nothing. Correctly placed.

### 5. `atlas analyzer replay <evidence_id> --version X` — **M1 or M7**
Re-run one analyzer on one document and diff its assertions against what is stored, without touching the store. This is how you investigate a suspected extraction regression, and how you validate a version bump before committing to invalidation.

### 6. `atlas doctor` — **M10**
Aggregate health check: dangling `evidence_id`s, orphan mentions, fingerprint mismatches, missing analyzers for present evidence kinds, stale rows. Overlaps `store verify` in the plan — merge them under one name and pick `doctor`, since that is what people will type.

### 7. `atlas fingerprint show [--explain]` — **M0, ten minutes**
Print the current fingerprint and every component. Trivial to build, and it is the first thing you want when a digest changed unexpectedly. Add `--diff <other>` to show which component moved.

### 8. `atlas assertion query --kind X --period Y` — **M1**
Ad-hoc assertion browsing. Lower priority than `explain` because `sqlite3` on the DB covers most of it — but only if the schema is legible, which is another argument for readable column names over compact ones.

### 9. `atlas migrate --dry-run` — **M10 (#54, already planned)**
Correctly placed.

### 10. `atlas judgment log <subject>` — **M5**
Chronological view of the supersede chain. Low urgency, high value the first time you need to answer "what did I believe about this company in March, and why."

**Reordering recommendation:** move items 1, 2, 3 and 7 forward into M-PRE/M0/M1. Total cost roughly three days. They pay for themselves the first week M3 is red.

---

# Part 8 — Three changes before the first line of code

If I owned delivery, these three, in this order, before writing anything.

## Change 1 — Insert M-PRE: prove determinism before building on it

**What:** a new S-sized milestone in week 2, before M1.
- Add `sort_keys=True` to `store.py:753` and `store.py:816`.
- Sort every `sources` list in `_finalize()` alongside the existing container sorts.
- Run spikes S3 and S5.
- Land the #32 equivalence test **against the existing analyzer path** and get it green.

**Why:** the plan's three most important tests (#26, #32, #55) all assert byte-identity on a serializer that does not currently produce stable bytes. Verified: `json.dumps` without `sort_keys`, `dict[FactKind, float]` in insertion order, and 10 `sources.append()` sites that `_finalize()` never sorts.

Under the current plan this surfaces in week 8, underneath three milestones of new storage, and the diff cannot be attributed to a cause. In week 2 there is only one possible cause.

**Cost:** two days, and it comes back out of M4's issue #33 budget. Net calendar impact: approximately zero.

**This is the change that most reduces the probability of the project failing.**

## Change 2 — Replace the migration mechanism before the first table exists

**What:** write `PRAGMA user_version`-based ordered migrations in `assertions/store.py`. Do not copy `knowledge/base.py`'s pattern. Failed migrations raise. Each migration is a numbered function, applied in order, recorded in `user_version`.

**Why:** the existing pattern (`knowledge/base.py:180-186`) runs every ALTER blind and swallows `sqlite3.OperationalError` wholesale. It cannot express a `CREATE TABLE`, an index change, a backfill, or a `NOT NULL` addition, and it cannot distinguish "already applied" from "failed because the disk is full." M1 and M2 both instruct copying it.

A new store will churn its schema — that is normal and expected. The migration mechanism is the one piece you cannot retrofit cheaply, because by the time you need it there are databases in the field written by the old one.

**Cost:** half a day. Retrofitting after three schema versions ship: a week, plus a data-integrity investigation.

**Secondary benefit:** it makes the migration tests in Part 5 expressible at all.

## Change 3 — Close the version model before M1 writes a row

Three unresolved version questions, all cheap now, all schema-affecting later.

**3a. Version the shared parsers.** Add `SHARED_PARSER_VERSION` to `analysis/patterns.py` and a version to `shareholding_trend.py`; include both in the fingerprint; add a test that every module imported by a registered analyzer contributes a component. *Verified gap: `patterns.py` is 381 lines imported by 7 of 11 analyzers and is invisible to the fingerprint.* Without this, M7 is not merely risky — it is incorrect.

**3b. Decide the multi-version reader rule.** The assertion PK `(evidence_id, analyzer_version)` permits N versions per evidence; `CompanyStore.ingested_results` permits exactly one (`store.py:792-795`). Write down which version M3's reader projects — latest, fingerprint-matching, or explicitly pinned — and encode it as a property test that the choice is independent of insertion order.

**3c. Resolve `StaleResultError` against M7.** `merge()` raises when an `evidence_id` reappears at a different `analyzer_version` (`store.py:96`, `776`). That is precisely M7's happy path. Add an explicit issue for the contract change and resize M7 from S to M.

**Cost:** one day total. Each of the three becomes a schema migration or a silent-correctness bug if deferred.

---

## What I am explicitly not changing

The tier model, the content-addressing approach, the flag-based cutover, the decision not to touch `builder.py`, and the choice to keep excerpts transient are all sound and verified against the code. The `builder.py`-never-reads-excerpts assumption in particular — the one load-bearing claim I most expected to break — holds.

The plan's structure is right. Its assumptions about the existing code are what need fixing, and all of that fits in the three days above.
