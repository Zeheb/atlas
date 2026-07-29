# Review of IMPLEMENTATION_AUDIT.md

Verification pass. Every falsifiable claim in the audit re-checked against the tree. Judgment items (risk ratings, spikes, tooling ranking) are not claims and are not "verified" — where a correction changes a rating, it is noted.

**Result: 11 confirmed, 3 corrected, 1 upgraded from unverified, 1 withdrawn.**

> **Correction issued during implementation — C1 was itself wrong.** See "C1 retraction" at the end of this document. The `strict=True` xfail written for M-PRE commit 1 XPASSed on its first run, which surfaced the error before any production code was written.

---

## Verdict table

| # | Claim | Verdict | Severity | Changes |
|---|-------|---------|----------|---------|
| 1 | `json.dumps` without `sort_keys` at store.py:753, :816 | **CONFIRMED** | Critical | implementation |
| 2 | `_facts_out` preserves insertion order | **CONFIRMED** | Critical | implementation |
| 3 | `sources` lists never sorted | **CONFIRMED** (count wrong: 9 sites, not 10) | Critical | implementation |
| 4 | Profile nondeterminism is "certain" across all orderings | **CORRECTED** — narrower than stated | High | implementation + testing |
| 5 | `patterns.py` unversioned, 7 importers, invisible to fingerprint | **CONFIRMED** | Critical | schema (fingerprint shape) |
| 6 | `shareholding_trend.py` needs a fingerprint component | **WITHDRAWN** — wrong layer | Low | nothing |
| 7 | `merge()` raises `StaleResultError`, blocking M7 | **CONFIRMED** | High | milestone ordering |
| 8 | `ingested_results` keyed by `evidence_id` alone | **CONFIRMED** | High | schema |
| 9 | `_MIGRATE_V*` is blind try/except, no `user_version` | **CONFIRMED** | Critical | implementation |
| 10 | `assertion_id` collision exposure in `annual_report` RISK_FACTOR | **CONFIRMED** | High | schema |
| 11 | Six sites emit `char_offset=None` | **CONFIRMED** | High | schema |
| 12 | `analyzed_at` is non-deterministic, must be excluded from hashing | **CONFIRMED** | Medium | schema |
| 13 | `builder.py` never reads `.excerpts` | **CONFIRMED** | — | nothing (assumption holds) |
| 14 | `Entity.entity_id` stability unverified | **UPGRADED** — order-dependent by design | High | schema |
| 15 | Legacy profile byte-equality unachievable in M10 | **CONFIRMED** | Medium | testing |
| 16 | SQLite volume / TEXT round-trip concerns | **CONFIRMED as stated** (both hedged correctly) | Low | nothing |

---

## Corrections to the audit

### C1 — "Profile nondeterminism is certain" was too broad

**What the audit said:** M3's failure probability "isn't a risk — it's certain."

**What is actually true:** `build_profile()` sorts its input before dispatch (`builder.py:1124-1127`):

```python
priority = {"earnings_transcript": 2, "investor_presentation": 2}
ordered = sorted(results, key=lambda r: (priority.get(r.kind, 1), r.source_date))
```

So the nondeterminism splits into two cases:

| Comparison | Determinstic? | Why |
|---|---|---|
| full build vs full build, shuffled input | **Yes, except on ties** | internal sort normalizes order |
| full build vs incremental `merge()` | **No — certain divergence** | `merge()` appends one at a time, never passes through the sort |

`sorted()` is stable, so two results with the same `(priority, source_date)` retain input order. Ties are the residual full-vs-full exposure — plausible for same-day filings, which do occur.

**Consequence for the plan:** issue #32's *shuffled* and *reversed* variants will largely pass. The *incremental* variant is the one that fails. That is still a failure, and M-PRE is still the right response — but the audit overstated the blast radius. M4's #33 fix budget is more likely 1–2 days than 3.

**Severity: High, not Critical.** Changes: implementation + testing (the tie case needs its own test).

### C2 — `shareholding_trend.py` does not affect extraction. Withdraw.

**What the audit said:** it needs a fingerprint component alongside `patterns.py`.

**What is actually true:** its entry point is `analyze_trend(results: Sequence[AnalysisResult]) -> TrendResult` (`shareholding_trend.py:112`). It **consumes** `AnalysisResult` and emits no `AnalysisFact`. It is not in `_REGISTRY`. It is a Tier 2 consumer, structurally the same as `query/engine.py` — which its own module notes mirror (`query/engine.py:137`).

Versioning it would be pinning a *view*, not extraction. That belongs to M8 metrics pinning if anywhere, not to M0.

**Withdrawn.** Severity: Low. Changes: nothing. The `patterns.py` half of that finding is unaffected and stands.

### C3 — `sources.append` site count

9, not 10 (`grep -c` verified). Immaterial to the finding; noted for accuracy.

---

## Upgrade: `Entity.entity_id` is order-dependent by design

The audit hedged this as "UNVERIFIED, spike S4." It is now verifiable from the source. `knowledge/entities/model.py` states two test-enforced invariants:

> entity_id is assigned once, at creation… derived from the *first observed* name, never from the mutable `canonical_name`.

> The resolver guarantees [uniqueness] with a disambiguation suffix when a distinct entity would otherwise collide.

Both are **corpus-order-dependent**:
- "First observed name" means resolving document A before B yields a different `entity_id` than B before A.
- The disambiguation suffix depends on which collision the resolver hits first.

This is correct and intentional for in-session identity. It is a problem for M2 only, and only in one specific way: **a content-addressed `mention_id` that incorporates `entity_id` inherits that order-dependence.** Re-running a backfill in a different order produces different mention IDs for the same underlying mentions.

**Severity: High.** Changes: schema (M2's `mention_id` derivation).

**Minimal fix:** derive `mention_id` from the *observed surface form* plus provenance — `sha256(evidence_id | canonical_name_as_written | section | char_offset | analyzer_version)` — and store `entity_id` as an ordinary column, not as an ID component. Content-addressing then depends only on the document, which is immutable. No resolver change, no architecture change.

This also means spike S4 is no longer needed as an unknown-resolver; it becomes a confirmation test.

---

## Confirmations worth restating precisely

**#1/#2/#3 — serialization.** `store.py:753` and `:816` both call `json.dumps(envelope, indent=2, ensure_ascii=False)`. No `sort_keys`. `_facts_out` (`store.py:117-118`) is `{fk.value: fv for fk, fv in facts.items()}` — a plain comprehension, insertion-ordered. `"sources": s.sources` at `store.py:146, 156, 228` serializes the raw list. `_finalize_profile` (`builder.py:1040-1056`) sorts 16 containers and no `sources` list. All four confirmed.

**#5 — `patterns.py`.** Imported by `acquisition`, `annual_report`, `board_outcome`, `buyback`, `earnings_transcript`, `financial_results`, `investor_presentation`. Seven of eleven. No version constant. Confirmed exactly as stated. This remains the audit's strongest finding.

**#7 — `merge()`.** `store.py:801-806` raises `StaleResultError` when `stored_ver != result.analyzer_version`. Confirmed verbatim.

**#9 — migrations.** `knowledge/base.py:180-186` — `for stmt in _MIGRATE_V2 + _MIGRATE_V3 + _MIGRATE_V4: try: execute; except sqlite3.OperationalError: pass`. No `PRAGMA user_version` anywhere in the file. Confirmed.

**#13 — excerpts.** `grep excerpts src/atlas/company/builder.py` returns nothing. The plan's load-bearing assumption holds.

---

# Minimal patch plan

Smallest reversible change per finding. Ordered by when it must land. Nothing here touches architecture; the largest single diff is four lines.

## Before M1 writes a row (total ~1.5 days)

### P1 — Deterministic serialization · 2 lines · Critical
```
store.py:753   json.dumps(envelope, indent=2, ensure_ascii=False, sort_keys=True)
store.py:816   json.dumps(raw,      indent=2, ensure_ascii=False, sort_keys=True)
```
**Reversal:** delete two kwargs.
**Risk:** any checked-in golden profile JSON fixture will diff. Regenerate once, review the diff — key reordering only, no value changes.

### P2 — Sort `sources` in `_finalize_profile` · 3 lines · Critical
Append to `builder.py:1056`:
```python
for snap in (*profile.financial.snapshots, *profile.esg.snapshots, *profile.ownership.snapshots):
    snap.sources.sort()
```
**Reversal:** delete the loop.
**Note:** deliberately does not dedupe. Sorting is order-normalization; deduping is a semantic change and belongs in a separate decision.
**Gap:** `_finalize_profile` runs in `build_profile()` but **not** in `merge()` — `merge()` calls `merge_result()` directly (`store.py:809`). P2 alone therefore does not fix the incremental path. See P3.

### P3 — Call `_finalize_profile` from `merge()` · 1 line · Critical
`store.py:809`, after `merge_result(result, profile)`:
```python
_finalize_profile(profile)
```
**Why:** this is the actual full-vs-incremental divergence. Full builds finalize; incremental merges never do. Sorting containers on every merge is O(n log n) on small lists — irrelevant at this scale.
**Reversal:** delete the line.
**Risk:** medium — this changes stored-profile bytes for anyone who has merged. Expected and desirable, but it means P1+P2+P3 land as one commit with one golden-fixture regeneration, not three.

### P4 — Version the shared parsers · 1 constant + 1 line · Critical
```python
# analysis/patterns.py
SHARED_PARSER_VERSION = "1.0"
```
Include it in `BuildFingerprint`. Add the guard test: every module under `src/atlas/analysis/` imported by a registered analyzer contributes a fingerprint component.
**Reversal:** remove the field.
**Do not** version `shareholding_trend.py` — see C2.

### P5 — `PRAGMA user_version` migrations in the new store only · ~30 lines · Critical
Numbered migration functions, applied in order, `user_version` bumped per migration, failures raise. Scoped to `assertions/store.py`. **Do not touch `knowledge/base.py`** — it works, it is covered by tests, and changing it is unrelated risk.
**Reversal:** the new store has no data in the field yet; delete and rewrite freely.

### P6 — Ordinal in `assertion_id` · schema decision · High
```
assertion_id = sha256(evidence_id | kind | value | unit | period | section |
                      char_offset | analyzer_version | ordinal)
```
where `ordinal` is the 0-based index within `(evidence_id, kind, section)` in analyzer emission order. Deterministic because analyzer emission order is deterministic for a fixed document and version.
**Reversal:** none needed after the fact — but this must be decided before the schema ships, since changing it later rewrites every ID.
**Precondition:** spike S2 confirms whether collisions actually occur. If S2 finds none, the ordinal is still cheap insurance; ship it either way.

### P7 — `mention_id` excludes `entity_id` · schema decision · High
Derive from surface form + provenance, per the upgrade section above. Store `entity_id` as a column.
**Reversal:** none needed — decide before M2's schema ships.

### P8 — Exclude `analyzed_at` from all hashing · convention · Medium
`analyzed_at`, `built_at`, and `created_at` are stored, never hashed, never compared. One helper (`canonical_for_hash()`) used by the ID function, the fingerprint, and the comparison helper in issue #31 — so the exclusion list exists once.
**Reversal:** trivial.

## Before M3 (~0.5 day)

### P9 — Decide the multi-version reader rule · High · schema
Write it into `assertions/reader.py`'s docstring and enforce with a property test that the reader's choice is a pure function of store contents, independent of insertion order. Recommended rule: **highest `analyzer_version` matching the current fingerprint; if none matches, raise rather than guess.** Raising is correct here — a silent fallback to a stale version is the failure mode M7 is meant to prevent.

## Before M7 (~2 days, previously unbudgeted)

### P10 — `merge()` contract change · High · milestone ordering
Add `merge(result, *, allow_reanalysis=False)`. When true and the stored version differs, remove that evidence's contribution and re-merge instead of raising. Default `False` preserves every existing caller and test.
**Reversal:** the flag defaults to today's behaviour, so reversal is not calling it.
**Resize M7 from S to M** — already recommended in the audit, now with a specific issue attached.

## Testing changes

### P11 — Add the tie-order test · Medium
`build_profile()`'s sort is stable, so same-`(priority, source_date)` results retain input order. Add a case with two same-day filings of the same kind in both orders. This is the residual full-vs-full exposure C1 identified, and nothing in the 59 issues covers it.

### P12 — Specify M10's legacy comparison · Medium
Issue #55: normalize both sides through the post-P1/P2/P3 serializer before comparing. Byte-identity remains the standard for fresh-vs-fresh; legacy-vs-fresh compares normalized. Write this into the issue now so it is not decided under pressure in week 12.

---

## What changes in the plan

| Category | Items |
|---|---|
| **Implementation** | P1, P2, P3, P5 |
| **Schema** | P4, P6, P7, P8, P9 |
| **Milestone ordering** | P10 (M7 S→M); M-PRE still recommended, now sized ~1.5 days not 2 |
| **Testing** | P11, P12 |
| **Nothing** | C2 (withdrawn), #13 (assumption holds), #16 (correctly hedged) |

Total pre-implementation cost: **~2 days**, down from the audit's estimated 3, because C2 is withdrawn and C1 narrows the M-PRE scope.

The audit's three headline recommendations survive review, with one correction: M-PRE's justification is the **full-vs-incremental** divergence (certain, caused by `merge()` skipping `_finalize_profile`), not general order-dependence. The fix is P3 — one line — plus P1 and P2 to make the comparison meaningful.

---

# C1 retraction — `merge()` does finalize

Issued during M-PRE implementation, before any production code was written.

## What C1 claimed

> "The actual divergence: `merge()` appends one at a time, never passes through the sort."

and, in the patch plan:

> **P3 — Call `_finalize_profile` from `merge()` · 1 line · Critical.** "Full builds finalize; incremental merges never do."

That became issue #62 and the headline justification for the whole M-PRE milestone.

## Why it is wrong

`CompanyStore.merge()` calls `merge_result()` (`store.py:809`). `merge_result()` ends with `_finalize_profile(profile)` (`builder.py:1101`), and its docstring already says so:

> "All collections are re-sorted after ingestion."

Finalization happens on every incremental merge and always has.

**How the error was made:** the original review read `store.py:809`, saw `merge_result(result, profile)`, and compared it against `build_profile`'s explicit `_finalize_profile()` call at `builder.py:1134`. It concluded the incremental path skipped finalization without opening `merge_result` to check. A call one level down looked like an absent call.

## How it was caught

M-PRE commit 1 writes the equivalence test first, marked `xfail(strict=True)`. On its first run:

```
[XPASS(strict)] CompanyStore.merge() never calls _finalize_profile() ...
1 failed, 1 passed, 1 xfailed
```

`strict=True` turns an unexpected pass into a failure. A plain `xfail` would have reported `xpass` as a non-event and the wrong diagnosis would have survived into a production commit that changed nothing.

A second, weaker fixture problem surfaced in the same investigation: the first result set gave every result its own snapshot, so each `sources` list held one element and the test could not observe ordering at all. Both mistakes were caught before any source file was touched.

## What survives

The full-vs-incremental divergence is real. The cause is unsorted `sources` lists, not missing finalization. `_finalize_profile` sorts 16 containers and no `sources` list, so:

| Route | `sources` order |
|---|---|
| `build_profile` | `(priority, source_date)` — from its input sort at `builder.py:1124-1127` |
| `merge()` | arrival order |

Demonstrated with two results merging into one snapshot, arriving newest-first:

```
full  sources: [['fr-early', 'fr-late']]
incr  sources: [['fr-late', 'fr-early']]
identical: False
```

| Item | Status after retraction |
|---|---|
| #61 `sort_keys=True` | Confirmed, unchanged |
| #66 sort `sources` | Confirmed — **promoted to the actual fix** |
| #60 tie-order | Confirmed — xfails correctly |
| #62 finalize on merge | **Retired: already implemented.** Not renumbered |

M-PRE keeps its slot and its justification. Its fix sequence collapses from three commits to two.

## The transferable lesson

C1 was derived from a call-site reading rather than from running anything. The audit's own Part 5 argued for property tests over example tests for exactly this reason, and the first property test written disproved the audit. Where a claim about behaviour can be executed, execute it — `grep` shows where a function is called, never what it does.

This is also the second time the graph proved more reliable than a manual read: `graphify explain` on the builder would have shown the `merge_result -> _finalize_profile` edge directly.
