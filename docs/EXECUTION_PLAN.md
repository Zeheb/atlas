# Atlas Execution Plan — Tiered Reproducibility

**Scope:** next 2–3 months, single engineer.
**Assumption:** architecture is approved and frozen. This document plans implementation only.

**Revision 2** — updated per `AUDIT_REVIEW.md`. Changes are implementation-level only; no architecture change. Issue numbers #1–59 are unchanged; new work is appended as #60+. Superseded items are struck and labelled, not deleted, so prior references stay resolvable.

Summary of what moved:
- New **M-PRE** milestone in week 2 (was: nothing). Justified by two verified defects — unsorted `sources` lists and `json.dumps` without `sort_keys`.
- **#62 retired during implementation** as already-implemented; see M-PRE. Downstream issue numbers deliberately unchanged.
- **M7** resized S → M (unbudgeted `merge()` contract change).
- **M4** issue #33 budget cut 3 days → 1–2 days (its known cause, unsorted `sources`, is now fixed in M-PRE).
- **M1/M2** no longer copy `knowledge/base.py`'s migration pattern.
- Withdrawn: versioning `shareholding_trend.py`. It consumes `AnalysisResult` and emits no facts — wrong layer.

**Sizing key**

| Size | Calendar |
|------|----------|
| XS | ≤ 1 day |
| S | 2–3 days |
| M | 1–2 weeks |
| L | 2–3 weeks |

---

## Starting position (verified against the tree)

| Tier | Concept | Today | Gap |
|------|---------|-------|-----|
| 0 | Evidence | `Repository` + `catalog.json` + local files. Immutable. | None. Already canonical. |
| 0 | User Judgments | **Does not exist.** `research/memory.py` stores model-generated `Thesis`. | Needs its own canonical, append-only store. |
| 1 | Assertions | **Does not exist as an artifact.** `AnalysisResult` is transient; `CompanyStore` persists only a stub in `ingested_results`. | Needs a store. This is the keystone. |
| 1 | Entities | `EntityMention` rides inside `AnalysisResult`, dies with it. | Needs persistence alongside assertions. |
| 2 | Facts / Profiles | `CompanyProfile` via `CompanyStore` JSON, `builder_version` + `store_version`. | Built from analyzers directly, not from Tier 1. |
| 2 | Metrics | `query/metrics.py`, computed on demand. | Not version-pinned. |

Two facts from the code that make this cheaper than it looks:

1. `company/builder.py` reads **only** `result.facts` and `result.entities`. It never touches `result.excerpts`. The assertion store therefore stores scalars and provenance pointers — no text blobs. Excerpts stay transient and remain re-derivable from `KnowledgeBase.get_content()` plus `Provenance.char_offset`.
2. `knowledge/base.py` already establishes the house *shape* for a versioned rebuildable SQLite cache: `PARSER_VERSION`, `_CREATE_TABLES`, one DB per repo. The assertion store follows that shape. It does **not** follow its migration mechanism — `base.py:180-186` runs every `ALTER` blind inside `try: … except sqlite3.OperationalError: pass`, with no `user_version`. That expresses `ADD COLUMN` and nothing else, and cannot tell "already applied" from "failed for a real reason." Fine for what it does today; unusable for a store that will churn its schema. See M1 / #68.

Version constants exist but are scattered across 18 modules with no single object binding them. Nothing downstream can currently answer "which code produced this profile?" in one value.

---

# Part 1 — Milestones

| ID | Milestone | Size | Ships |
|----|-----------|------|-------|
| M9 | Ontology version freeze | XS | `FactKind` changes become a versioned event |
| M0 | Build Fingerprint | S | A version object every later artifact embeds |
| **M-PRE** | **Determinism pre-flight** | **S** | **Profile serializes deterministically; equivalence test green on the existing path** |
| M1 | AssertionStore (Tier 1) | L | Persisted, content-addressed assertions |
| M2 | EntityStore (Tier 1) | M | Persisted entities, decoupled from AnalysisResult |
| M3 | Profile builds from Tier 1 | M | Tier 2 becomes a projection of Tier 1 |
| M4 | Rebuild engine + equivalence gate | M | `atlas rebuild`; full == incremental proven in CI |
| M5 | Judgment store (Tier 0) | M | User reasoning as canonical, append-only artifact |
| M6 | Answer pinning | M | Every answer cites the fingerprint that produced it |
| M7 | Staleness + selective invalidation | **M** *(was S)* | Version bump invalidates only affected rows |
| M8 | Metrics pinning | S | Tier 2 metrics carry a fingerprint |
| M10 | Backfill + operator CLI | M | Existing repos migrated, no data loss |

Every milestone below is independently shippable (main stays green), independently testable (own test module), and reversible (each has a named rollback that is a revert or a flag flip, never a data migration undo).

---

# Part 2 — Per-milestone detail

## M0 — Build Fingerprint (S)

**Affected modules:** `analysis/registry.py` (expose the version map), `analysis/base.py` (add `ONTOLOGY_VERSION`), `analysis/patterns.py` (add `SHARED_PARSER_VERSION`).

**New modules:** `src/atlas/provenance.py`.

```python
@dataclass(frozen=True)
class BuildFingerprint:
    ontology_version: str          # FactKind vocabulary version
    parser_version: str            # knowledge.base.PARSER_VERSION
    shared_parser_version: str     # analysis.patterns.SHARED_PARSER_VERSION
    analyzer_versions: Mapping[str, str]   # evidence kind -> ANALYZER_VERSION
    builder_version: str           # company.builder.BUILDER_VERSION
    code_rev: str | None           # git describe, None outside a checkout

    def digest(self) -> str:       # stable sha256 over canonical JSON
    def affects(self, kind: str) -> str:   # per-kind sub-digest
```

`shared_parser_version` closes a verified hole: `analysis/patterns.py` is 381 lines of shared parsers (`parse_indian_float`, `parse_iso_date`, `extract_n_values`, `split_reg30_sections`) imported by 7 of the 11 registered analyzers, carrying no version today. A fix there changes extracted values across seven analyzers while `analyzer_versions` stays byte-identical. Without this field, M7's invalidation is unsound.

**Not versioned:** `analysis/shareholding_trend.py`. Its entry point is `analyze_trend(Sequence[AnalysisResult]) -> TrendResult` — it consumes results and emits no `AnalysisFact`, and it is absent from `_REGISTRY`. It is a Tier 2 consumer, structurally a sibling of `query/engine.py`. Versioning it would pin a view, not extraction; that belongs to M8 if anywhere.

`digest()` must be stable across processes and machines: canonical JSON, sorted keys, no timestamps, no absolute paths.

**Migrations:** none. Nothing is written yet.

**Tests:** `tests/unit/test_provenance.py` — digest stability across two constructions; digest changes when any component version changes; `analyzer_versions` covers exactly `registry.supported_kinds()`; `code_rev=None` does not destabilise the digest.

**Risks:** low. One real trap — if `code_rev` participates in `digest()`, every commit invalidates every cache. **Decision: `code_rev` is recorded for forensics but excluded from `digest()`.** Only declared versions invalidate.

---

## M-PRE — Determinism pre-flight (S)

**Affected modules:** `company/store.py`, `company/builder.py`.

**New modules:** none.

Runs the M4 equivalence test **against the existing analyzer path**, before any storage work exists to confuse the diff. Two verified defects block it today:

1. `store.py:753` and `store.py:816` call `json.dumps(envelope, indent=2, ensure_ascii=False)` — no `sort_keys`. `_facts_out` (`store.py:117-118`) is a plain comprehension over `dict[FactKind, float]`, so fact keys serialize in merge order.
2. **The actual divergence:** `"sources": s.sources` (`store.py:146, 156, 228`) serializes a raw list. `sources.append()` fires at 9 sites in `builder.py`; `_finalize_profile` (`builder.py:1040-1056`) sorts 16 containers and no `sources` list. A full build appends in `(priority, source_date)` order; an incremental merge appends in arrival order.

**Corrected during implementation.** A third defect was claimed here — that `CompanyStore.merge()` never finalizes — and it does not exist. `merge()` calls `merge_result()` (`store.py:809`), and `merge_result()` ends with `_finalize_profile(profile)` (`builder.py:1101`), documented in its own docstring as "All collections are re-sorted after ingestion." The original reading stopped at the `merge_result` call without opening it. Issue #62 is retired as already-implemented; see `AUDIT_REVIEW.md` for how the `strict=True` xfail surfaced it.

Demonstrated divergence, two results merging into one snapshot, arriving newest-first:

```
full  sources: [['fr-early', 'fr-late']]
incr  sources: [['fr-late', 'fr-early']]
```

Defect 2 is the one that matters. Defect 1 is what makes the comparison legible.

**Fixture requirement.** At least two results must share a `(period, basis)` snapshot key. One result per snapshot leaves every `sources` list a single element, and the equivalence test passes while proving nothing — which is exactly what happened on the first attempt.

**Migrations:** none, but stored profile bytes change. Regenerate golden fixtures once.

**Tests:** the #32 equivalence test, run against `build_profile` vs repeated `merge()`, with a fixture whose results share a snapshot. Plus #60's tie case.

**Risks:** golden-fixture churn. Expected: key reordering and `sources` reordering only, no value changes — review the diff to confirm that.

**Rollback:** revert one commit. #61 and #66 ship together: sorting `sources` is only observable once key order is stable enough to diff.

---

## M1 — AssertionStore, Tier 1 (L)

**Affected modules:** `analysis/registry.py` (add a persisting wrapper; `analyze()` itself unchanged), `cli.py` (new `atlas analyze` command).

**New modules:** `src/atlas/assertions/` — `model.py`, `store.py`, `writer.py`, `reader.py`.

**The load-bearing design decision — content-addressed assertion IDs:**

```
assertion_id = sha256(evidence_id | kind | value | unit | period |
                      section | char_offset | analyzer_version | ordinal)[:16]
```

`ordinal` is the 0-based index within `(evidence_id, kind, section)` in analyzer emission order — deterministic, because emission order is fixed for a given document and analyzer version. It is required, not optional: `annual_report.py:634-645` emits every `RISK_FACTOR` in one loop sharing a single `char_offset` (the *section* offset, not per-risk) and a single `section="mda_risk"`, so without an ordinal the ID varies only by `value`. Six further sites emit `char_offset=None` outright (`shareholding_pattern.py:120,261`; `financial_results.py:597,781,1243,1251,1264`).

Deterministic IDs are what make "full rebuild == incremental rebuild" checkable by set equality rather than by fuzzy diffing. Do not use autoincrement. Do not use uuid4. Use `INSERT`, not `INSERT OR REPLACE` — a conflict must raise, because a silently replaced row is a fact that vanishes with no error at any layer.

**Timestamps are stored, never hashed.** `AnalysisResult.analyzed_at` uses `default_factory=datetime.now` (`base.py:486`) and is non-deterministic by construction. One helper — `canonical_for_hash()` — owns the exclusion list (`analyzed_at`, `built_at`, `created_at`) and is used by the ID function, the fingerprint, and issue #31's comparison helper, so the list exists in exactly one place.

**Schema** (SQLite, one DB per company repo, beside the existing knowledge DB):

```sql
CREATE TABLE assertions (
    assertion_id     TEXT PRIMARY KEY NOT NULL,
    evidence_id      TEXT NOT NULL,
    kind             TEXT NOT NULL,      -- FactKind.value
    value            TEXT,               -- scalar, stringified
    value_type       TEXT NOT NULL,      -- str|int|float|null
    unit             TEXT,               -- FactUnit.value or NULL
    period           TEXT,               -- ISO date or NULL
    confidence       TEXT NOT NULL,      -- high|medium|low
    section          TEXT NOT NULL,
    char_offset      INTEGER,
    ordinal          INTEGER NOT NULL,   -- emission-order index; an id input
    excerpt          TEXT,               -- ≤120 char micro-proof, per Provenance
    analyzer_version TEXT NOT NULL,
    fingerprint      TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX idx_assertions_evidence ON assertions(evidence_id);
CREATE INDEX idx_assertions_kind     ON assertions(kind, period);

CREATE TABLE assertion_runs (
    evidence_id      TEXT NOT NULL,
    kind             TEXT NOT NULL,      -- EvidenceKind.value
    analyzer_version TEXT NOT NULL,
    fingerprint      TEXT NOT NULL,
    result_confidence TEXT NOT NULL,
    source_date      TEXT NOT NULL,
    analyzed_at      TEXT NOT NULL,
    warnings_json    TEXT NOT NULL,
    status           TEXT NOT NULL,     -- ok|failed
    error            TEXT,
    PRIMARY KEY (evidence_id, analyzer_version)
);
```

**Schema corrections, made while implementing M1 commit 4.** Three columns as first written could not carry what the models and the reader need:

- `assertions.ordinal` was missing. It is an input to `assertion_id` and is recoverable from nothing else — stored rows do not preserve analyzer emission order — so without the column a row read back can never have its own id re-derived.
- `assertion_runs.kind` was missing. `AnalysisResult.kind` is required (`analysis/base.py:493`); reading it from `knowledge.db` instead would make an independently rebuildable store depend on a second file.
- `assertion_id TEXT PRIMARY KEY` alone permits NULL, and permits several: SQLite enforces NOT NULL on a primary key only for `INTEGER PRIMARY KEY`. Now declared explicitly.

`assertion_runs` carries everything on the `AnalysisResult` envelope that is not a fact: result-level confidence, warnings, source_date, analyzed_at. This is what lets `reader.py` reconstruct a faithful `AnalysisResult` in M3 without changing `builder.py`.

**Multi-version rule (decide here, not in M3):** the PK `(evidence_id, analyzer_version)` permits N versions per evidence document. `CompanyStore.ingested_results` permits exactly one, keyed on `evidence_id` alone (`store.py:792-795`). The reader's selection rule is therefore **highest `analyzer_version` whose stored fingerprint matches the current one; if none matches, raise.** Raising is deliberate — a silent fallback to a stale version is precisely the failure M7 exists to prevent. Enforced by a property test that the choice is a pure function of store contents, independent of insertion order.

**Migrations:** `PRAGMA user_version`, numbered migration functions applied in order, failures raise.

**Do not copy `knowledge/base.py`'s migration pattern.** That code (`base.py:180-186`) runs every `ALTER` unconditionally inside `try: … except sqlite3.OperationalError: pass`. It has no `user_version`, cannot express anything but `ADD COLUMN`, and cannot distinguish "already applied" from "failed because the disk is full or the SQL is wrong." It works for what it does today; it cannot carry a store that will churn its schema. Leave `knowledge/base.py` alone — it is covered by tests and changing it is unrelated risk.

New DB file, created on demand. No migration of existing data in this milestone — M10 handles backfill. Ship the store empty and dual-write.

**Tests:** `tests/unit/test_assertion_store.py`, `tests/unit/test_assertion_writer.py`, `tests/integration/test_assertion_roundtrip.py`.
- Same `AnalysisResult` written twice produces identical `assertion_id` sets and no duplicate rows.
- Writing under a bumped `analyzer_version` creates a new run row and new assertion IDs; the old rows survive.
- Every one of the 11 registered analyzers round-trips: `write(analyze(x))` then `read(x)` yields facts equal to the original by `(kind, value, unit, period, confidence, provenance)`.
- Value type fidelity: `int` and `float` do not become `str` on the round trip.
- Failed analyzer runs record `status='failed'` with the error and zero assertion rows.

**Risks:**
- **Value stringification is the highest-risk detail.** `AnalysisFact.value` is `str | int | float | None`. Storing everything as TEXT and inferring the type back is a silent corruption vector — a fact worth `1.10` returning as `"1.1"` breaks equality tests downstream. Mitigation: explicit `value_type` column, exercised by a round-trip test across all 11 analyzers on the golden corpus.
- Store size. TCS-scale repos with 11 analyzers produce a few tens of thousands of rows. SQLite is unbothered. No action, but measure in the acceptance test and record the number.
- Scope creep into "assertion conflict resolution". **Out of scope.** This milestone stores; it does not reconcile.

---

## M2 — EntityStore, Tier 1 (M)

**Affected modules:** `knowledge/entities/resolver.py` (unchanged logic, new call site), `assertions/writer.py` (write mentions in the same transaction as facts).

**New modules:** `src/atlas/assertions/entities.py` — or a second table in the same DB. **Same DB.** Entities and assertions share a lifecycle and must be invalidated together; splitting them into two files creates a two-phase-commit problem for no benefit.

**`mention_id` must not include `entity_id`.** `Entity.entity_id` is order-dependent by design — `knowledge/entities/model.py` states both invariants explicitly: the id derives from the *first observed* name, and uniqueness is guaranteed by "a disambiguation suffix when a distinct entity would otherwise collide." Both depend on corpus traversal order. That is correct for in-session identity and wrong for a content address: a backfill run in a different order would mint different mention IDs for the same underlying mentions. Derive instead from the immutable document:

```
mention_id = sha256(evidence_id | canonical_name_as_written | section |
                    char_offset | analyzer_version | ordinal)[:16]
```

Store `entity_id` as an ordinary column. No resolver change.

```sql
CREATE TABLE entity_mentions (
    mention_id       TEXT PRIMARY KEY NOT NULL,  -- content-addressed
    evidence_id      TEXT NOT NULL,
    entity_id        TEXT NOT NULL,      -- stored, never hashed
    entity_kind      TEXT NOT NULL,
    canonical_name   TEXT NOT NULL,
    aliases_json     TEXT NOT NULL,
    role             TEXT,
    affiliation      TEXT,
    identifier       TEXT,               -- e.g. DIN
    question_text    TEXT,
    section          TEXT,               -- NULL when the mention had no Provenance
    char_offset      INTEGER,
    excerpt          TEXT,
    ordinal          INTEGER NOT NULL,   -- emission-order index; an id input
    analyzer_version TEXT NOT NULL,
    fingerprint      TEXT NOT NULL
);
```

**Schema corrections, made while implementing M2 commit 1.** Three columns the prose above requires and the DDL as first written omitted, the same class of gap corrected in M1: `entity_id` ("Store `entity_id` as an ordinary column" — it was named in the text and absent from the table), `ordinal` (an input to `mention_id`, recoverable from nothing else), and `excerpt` (`Provenance` carries one, and #21 requires provenance to survive the round trip). `mention_id` is also `NOT NULL`: SQLite enforces it on a non-INTEGER primary key only when told.

**Migrations:** additive table on the M1 DB, applied as migration #2 under the `user_version` mechanism built in M1. Not the `_MIGRATE_V*` pattern — see M1.

**Tests:** `tests/unit/test_entity_store.py`. Mention round-trip preserves `role`, `affiliation`, `identifier`, `question_text`. Director DIN mentions survive (the existing `test_director_identity.py` fixtures are the input). Writer is atomic: a failure mid-write leaves neither facts nor mentions.

**Risks:** `Entity` identity resolution (`resolver.py`) is conservative by design per ADR-0012's under-emit convention. Persisting mentions must not accidentally introduce a merge step. Store what the resolver produced, verbatim.

---

## M3 — Profile builds from Tier 1 (M)

**Affected modules:** `company/store.py` (source swap), `cli.py`.

**New modules:** `assertions/reader.py::results_for(company_id) -> list[AnalysisResult]`.

The trick that keeps this reversible and small: **`builder.py` does not change at all.** The reader reconstructs `AnalysisResult` objects from `assertions` + `assertion_runs` + `entity_mentions` and hands them to the existing `build_profile()` / `merge_result()`. `excerpts` is reconstructed as `{}` — verified safe, `builder.py` never reads it.

Ship behind `ATLAS_PROFILE_SOURCE=analyzers|assertions`, defaulting to `analyzers`. Flip the default only after the equivalence test in M4 is green.

**Migrations:** none.

**Tests:** `tests/integration/test_profile_source_equivalence.py` — for every company in the golden corpus, the profile built from analyzers and the profile built from assertions serialise to byte-identical canonical JSON. This is the single most valuable test in the whole plan.

**Risks:**
- Ordering. `build_profile()` already sorts its input by `(priority, source_date)` (`builder.py:1124-1127`), so full builds normalize order internally. The residual exposure is `sorted()`'s stability on ties: two results with the same priority *and* the same `source_date` retain input order, and their `sources` entries append in that order. Same-day filings of the same kind are the real case. The reader must return results in a deterministic `(source_date, evidence_id)` order rather than relying on SQLite's natural order, and issue #60 covers the tie case explicitly.
- `excerpts={}` reconstruction is safe today because the builder ignores it — verified, `grep excerpts src/atlas/company/builder.py` returns nothing. If a future section reads excerpts, this breaks silently. Mitigation: an import-boundary test asserting `builder.py` contains no reference to `.excerpts` — cheap, and it fails loudly the day someone adds one.

---

## M4 — Rebuild engine + equivalence gate (M)

**Affected modules:** `cli.py`, `company/store.py`.

**New modules:** `src/atlas/rebuild.py`.

```
atlas rebuild --company TCS --from evidence      # parse → analyze → assert → project
atlas rebuild --company TCS --from assertions    # project only (fast path)
atlas rebuild --company TCS --verify             # rebuild to temp, diff, do not write
```

**Migrations:** none.

**Tests:** `tests/integration/test_rebuild_equivalence.py`, the invariant gate:
1. Full rebuild from evidence → profile A.
2. Fresh store, then evidence added one document at a time via `merge()` → profile B.
3. `canonical_json(A) == canonical_json(B)`.
4. Repeat with documents in reverse and in shuffled order — all must equal A.

Also: rebuild is idempotent (rebuild twice, byte-identical); `--verify` never writes (assert mtimes unchanged).

**Risks:**
- **Reduced by M-PRE.** The dominant known cause of full-vs-incremental divergence — `merge()` never calling `_finalize_profile()` — is fixed in M-PRE, and the equivalence test is already green against the analyzer path before this milestone starts. Budget for residual fixes here is **1–2 days, down from 3–4.** Anything this test finds now is genuinely new, caused by the assertion reader, and attributable.
- Do not weaken the test to make it pass. Written into the DoD: *if it cannot pass, the milestone stops and the cause gets fixed.*
- `analyzed_at` and `built_at` timestamps will differ between runs. Canonicalisation must exclude wall-clock fields from the comparison while still asserting they are present and well-formed — reuse M1's `canonical_for_hash()` exclusion list rather than defining a second one.

---

## M5 — Judgment store, Tier 0 (M)

**Affected modules:** `research/memory.py` (stays as-is, for model theses), `research/staleness.py`, `cli.py`.

**New modules:** `src/atlas/judgment/` — `model.py`, `store.py`.

The distinction to enforce in code, not just in docs:

| | `Thesis` (existing) | `Judgment` (new) |
|---|---|---|
| Author | model | human |
| Tier | rebuildable | canonical |
| On version bump | regenerate | never touched |
| Mutability | overwrite | append-only |
| Deletion | free | requires explicit `--force` |

```python
@dataclass(frozen=True)
class Judgment:
    judgment_id: str          # content-addressed
    subject: SubjectRef
    statement: str            # what the user concluded
    rationale: str
    evidence_ids: tuple[str, ...]
    asserted_at: datetime
    fingerprint: str          # what Atlas showed them at the time
    supersedes: str | None    # prior judgment_id, never deleted
```

Append-only with `supersedes` rather than update-in-place. A judgment made against a stale fingerprint is still a real historical fact about what the user believed.

**Migrations:** new JSON store per subject, `store_version = "1"`, matching the `ThesisStore` file convention.

**Tests:** `tests/unit/test_judgment_store.py` — append-only enforced (a second write with the same id raises); `supersedes` chains resolve to full history; a judgment survives a full Tier 1 + Tier 2 rebuild untouched; `atlas rebuild --all` never opens the judgment store (import-boundary test).

**Risks:** the temptation to unify `Judgment` and `Thesis` behind one interface. Resist. `research/memory.py`'s own docstring already argues the two lifecycles cannot share a store — the same argument applies here.

---

## M6 — Answer pinning (M)

**Affected modules:** `reasoning/contracts.py`, `reasoning/ask.py`, `reasoning/render.py`, `research/report.py`, `research/thesis.py`, `citation.py`.

**New modules:** none.

Add to the answer envelope: `fingerprint`, `assertion_ids` actually consulted, `evidence_ids`, `profile_built_at`. Render a one-line footer: `Atlas <digest> · 47 assertions · 12 documents · profile built 2026-07-14`.

**Migrations:** `ReasoningResult` gains fields. Persisted theses need a default for the old shape — read as `fingerprint=None` and treat as "pre-pinning".

**Tests:** `tests/unit/test_answer_pinning.py` — every answer path carries a non-null fingerprint; the assertion id set is a subset of what the store holds; a pre-pinning stored thesis loads without error; two identical questions against an unchanged store produce the same fingerprint.

**Risks:** touching `reasoning/` risks the existing grounding and prompt-injection tests. Add fields; change no existing behaviour. This milestone is additive or it is wrong.

---

## M7 — Staleness + selective invalidation (M) *(resized from S)*

**Affected modules:** `assertions/store.py`, `rebuild.py`, `research/staleness.py`, **`company/store.py`**.

**Unbudgeted work found in audit — this is why the milestone grew.** `CompanyStore.merge()` raises `StaleResultError` when an `evidence_id` is already tracked under a different `analyzer_version` (`store.py:96`, raise at `store.py:801-806`). Its own docstring directs the caller to "rebuild from scratch." That is exactly M7's happy path: re-run one analyzer at a bumped version and merge the result.

Minimal fix — add a keyword, do not change the default:

```python
def merge(self, result: AnalysisResult, *, allow_reanalysis: bool = False) -> CompanyProfile:
```

When `True` and the stored version differs, drop that evidence's contribution and re-merge instead of raising. `False` preserves every existing caller and every existing test. Reversal is not passing the flag.

`fingerprint.affects(kind)` gives a per-kind sub-digest, so bumping `financial_results` `ANALYZER_VERSION` invalidates financial_results assertions only — not all 11 analyzers' output.

```
atlas rebuild --company TCS --stale-only
```

**Tests:** bumping one analyzer version re-runs exactly one analyzer; bumping `PARSER_VERSION` or `ONTOLOGY_VERSION` invalidates everything; `--stale-only` on a clean store is a no-op that writes nothing.

**Risks:** an under-invalidating sub-digest silently serves stale data — worse than over-invalidating. Default to whole-store invalidation on any ambiguity, and make the per-kind path opt-in.

---

## M8 — Metrics pinning (S)

**Affected modules:** `query/metrics.py`, `query/engine.py`, `query/render.py`.

`QueryResult` gains `fingerprint`. Renderers print it.

**Tests:** every registered query returns a pinned result; `available_queries()` count matches the pinned-result test count so a new query cannot skip pinning.

**Risks:** minimal. `query/engine.py` is 1,619 lines with ~30 query functions; the mechanical change is wide. Do it as one commit, not thirty.

---

## M9 — Ontology version freeze (XS)

**Affected modules:** `analysis/base.py`.

Add `ONTOLOGY_VERSION = "1.0"` beside `FactKind`, plus a test that pins the member count and the sorted value list. Adding a `FactKind` must now be a deliberate version bump, exactly as ADR-0012 requires for the working-capital exception.

**Tests:** `tests/unit/test_ontology_version.py` — `FactKind` member set matches a checked-in snapshot; a mismatch fails with "bump ONTOLOGY_VERSION and update the snapshot".

**Risks:** none. Do this in the first week; it is one hour of work and it protects everything after it.

---

## M10 — Backfill + operator CLI (M)

**Affected modules:** `cli.py`.

```
atlas migrate assertions --company TCS [--dry-run]
atlas store status --company TCS       # tier sizes, fingerprints, staleness
atlas store verify --company TCS       # integrity: dangling evidence_ids, orphan mentions
```

Backfill re-runs the 11 analyzers over existing evidence and populates the assertion store. Evidence is immutable, so this is safe and repeatable.

**Migrations:** the real one. Per company: build assertions in a temp DB, verify the projected profile equals the stored profile, then atomically move into place. Never mutate the live store in flight.

**Legacy comparison is specified now, not decided under pressure in week 12.** Profiles stored before this project were written by an earlier `builder_version` under insertion-order serialization, so byte-identity against them is unachievable and the gate would get disabled to ship. Rule: **normalize both sides through the post-M-PRE serializer, then compare.** Byte-identity remains the standard for fresh-vs-fresh (#26, #32); legacy-vs-fresh compares normalized.

**Tests:** `tests/integration/test_backfill.py` — backfill of a golden-corpus company produces a profile byte-identical to the currently stored one; `--dry-run` writes nothing; interrupting a backfill leaves the original store intact; re-running a completed backfill is a no-op.

**Risks:** the one milestone with real data-loss potential. Mitigations: temp-DB-then-move, `--dry-run` first, and the profile-equality gate blocking the move. The old JSON profile remains on disk untouched throughout — that is the rollback.

---

# Part 3 — Critical path

```
M9 (XS) ──> M0 (S) ──> M-PRE (S) ──> M1 (L) ──> M3 (M) ──> M4 (M) ──> M7 (M)
                                        │                     │
                                        └──> M2 (M) ──────────┘
M5 (M) [independent of everything]
M6 (M), M8 (S), M10 (M) attach after M4.
```

**Dependency edges, and why each exists:**

| Edge | Reason |
|------|--------|
| M9 → M0 | `ONTOLOGY_VERSION` is a fingerprint component |
| M0 → M-PRE | not strictly required, but M-PRE's fixture regeneration is cheaper done once, after the fingerprint shape settles |
| **M-PRE → M1** | **new.** M1's round-trip tests compare serialized profiles. Comparing against a nondeterministic serializer wastes the test |
| M1 → M2 | shared DB, shared writer transaction, shared migration mechanism |
| M1 → M3 | M3 reads what M1 writes; also M1 fixes the multi-version selection rule M3 depends on |
| M2 → M4 | equivalence must cover entities, or it proves less than it claims |
| M3 → M4 | M4 compares the two sources M3 makes selectable |
| M4 → M7 | selective invalidation is unsafe without a working equivalence gate to verify it against |
| M0 → M7 | `affects(kind)` sub-digests need a complete fingerprint, `shared_parser_version` included |

**Highest leverage, in order:**

1. **M0 — Build Fingerprint.** Unlocks M1, M6, M7, M8. Now also carries `shared_parser_version`, without which M7 is not merely risky but incorrect. Worst retrofit curve in the plan, so it goes first.
2. **M-PRE — Determinism.** Unlocks honest comparison in M1, M3, M4, M10. One line of it (finalize on merge) is the difference between M4's gate being a week of bisection and an afternoon.
3. **M1 — AssertionStore.** Unlocks M2, M3, M4, M7, M10. Without it the tier model is a diagram, not a system.

**Do first:** M9 (one hour), M0, M-PRE, then M1.

**Unchanged:** M5 remains fully parallel — it shares no module with M0–M4. M8 can land any time after M0.

**Genuinely parallel:**
- **M5 (Judgments)** touches no shared module with M0–M4. Good work for a day when M1 is blocked on a decision.
- **M9** is independent of everything.
- **M8** can land any time after M0.

**Deliberately serial:** M1 → M3 → M4. Do not start M3 before M1's round-trip tests pass across all 11 analyzers — a reader built against an unstable schema is thrown away.

**Not parallel despite appearances:** M2 (Entities) looks independent of M1 but shares the DB and the writer transaction. Land M1 first, then M2 as an additive migration.

---

# Part 4 — Definition of Done, acceptance, regression, rollback

### M0 — Build Fingerprint
- **DoD:** `BuildFingerprint` exists; `current_fingerprint()` returns it; digest is stable; nothing consumes it yet.
- **Acceptance:** `current_fingerprint().digest() == current_fingerprint().digest()` across two processes. Changing any analyzer version changes the digest. Changing `code_rev` alone does not.
- **Regression risk:** none — nothing reads it yet.
- **Rollback:** delete the module. Zero callers.

### M-PRE — Determinism pre-flight
- **DoD:** the #32 equivalence test is green against the existing analyzer path. Profile serialization is order-independent. Golden fixtures regenerated and the diff reviewed.
- **Acceptance:** full build vs repeated `merge()` produces byte-identical profile JSON for every golden-corpus company. Two same-day filings of the same kind, ingested in both orders, produce identical output (#60). Serializing one profile twice is byte-identical.
- **Regression risk:** every checked-in profile fixture changes. Expected content of the diff: JSON key reordering plus `sources` list reordering, nothing else. If a *value* changes, stop — that is a real bug this milestone just uncovered.
- **Rollback:** revert one commit. #61 and #66 are not independently revertible in practice; they ship as one fix.

### M1 — AssertionStore
- **DoD:** `atlas analyze --company X` populates the store for all 11 analyzers; round-trip tests green; the multi-version selection rule is documented and test-enforced; nothing in the profile path reads it yet.
- **Acceptance:** for each of the 11 analyzers on the golden corpus — write, read, and assert facts equal by `(kind, value, unit, period, confidence, provenance)`; second write produces zero new rows; row count and DB size recorded in the test output.
- **Regression risk:** low. Analyzers unchanged. Only new risk is the writer raising on a fact shape no test covers — mitigated by running all 11 over the full golden corpus, not a subset.
- **Rollback:** stop calling the writer. Delete the DB file. Evidence and profiles are untouched; the store is pure derived state.

### M2 — EntityStore
- **DoD:** entity mentions persisted in the same transaction as assertions; round-trip preserves all five context fields.
- **Acceptance:** existing `test_entities.py` and `test_director_identity.py` fixtures round-trip with no field loss. Atomicity: an injected mid-write failure leaves zero rows of both kinds.
- **Regression risk:** the writer transaction now spans two tables. A partial write yields a profile missing entities but carrying facts — silent under-reporting. Mitigated by the atomicity test.
- **Rollback:** revert the migration; drop the table. Assertions are unaffected.

### M3 — Profile from Tier 1
- **DoD:** `ATLAS_PROFILE_SOURCE=assertions` produces a profile byte-identical to the analyzer path for every golden-corpus company. Default remains `analyzers`.
- **Acceptance:** the equivalence test above, plus a reader determinism test (same store, ten reads, identical result ordering).
- **Regression risk:** highest in the plan. If the reader loses a field, profiles silently degrade. Mitigated by byte-identity — not "close enough", not field-subset.
- **Rollback:** flip the env var. One line, no data change.

### M4 — Rebuild engine
- **DoD:** `atlas rebuild` in all three modes; the equivalence gate green in CI; the default for `ATLAS_PROFILE_SOURCE` flipped to `assertions`.
- **Acceptance:** full == incremental == shuffled-order == reverse-order, all byte-identical. Rebuild twice is byte-identical. `--verify` writes nothing.
- **Regression risk:** flipping the default makes assertions load-bearing for the first time. Keep the analyzer path importable and tested for one full milestone after the flip.
- **Rollback:** flip the default back. The analyzer path stays in the tree until M10 ships.

### M5 — Judgment store
- **DoD:** judgments created, listed, superseded via CLI; survive a full rebuild.
- **Acceptance:** append-only enforced; supersede chains resolve; `atlas rebuild --all` followed by a judgment read returns identical bytes; import-boundary test proves the rebuild path never imports the judgment store.
- **Regression risk:** none to existing paths — additive.
- **Rollback:** stop writing. Judgment files are Tier 0 and are never deleted, even on revert.

### M6 — Answer pinning
- **DoD:** every answer surface (`ask`, `research`, `investigate`, `thesis`) emits a fingerprint footer.
- **Acceptance:** all four CLI paths asserted to carry a non-null fingerprint; pre-pinning stored theses load with `fingerprint=None`; existing grounding, citation, and prompt-injection tests unchanged and green.
- **Regression risk:** `reasoning/` is the most test-covered area — breakage is loud, not silent. Acceptable.
- **Rollback:** revert. Footer disappears; nothing else depends on it.

### M7 — Selective invalidation
- **DoD:** `--stale-only` re-runs exactly the affected analyzers; `merge(allow_reanalysis=True)` lands with the default unchanged.
- **Acceptance:** bump one analyzer version → one analyzer runs, others' rows untouched. Bump `PARSER_VERSION` or `SHARED_PARSER_VERSION` → everything re-runs. Clean store → no-op, zero writes. After `--stale-only`, store row count equals a full rebuild's row count, or fail loudly. Every existing `merge()` caller and test passes unchanged with the default.
- **Regression risk:** under-invalidation serves stale data silently. Two controls: full invalidation stays the default with the narrow path opt-in, and the row-count invariant catches partial re-runs.
- **Rollback:** remove the flag; `rebuild` falls back to full. `allow_reanalysis` defaults to today's raising behaviour, so not passing it is the rollback.

### M8 — Metrics pinning
- **DoD:** `QueryResult.fingerprint` populated on every registered query.
- **Acceptance:** a test that iterates `available_queries()` and asserts a pinned result for each — so a newly added query cannot silently skip it.
- **Regression risk:** renderer output changes; golden text fixtures need updating. Mechanical.
- **Rollback:** revert. Field is additive.

### M10 — Backfill
- **DoD:** every existing company repo migrated; `store verify` clean.
- **Acceptance:** backfilled profile byte-identical to the pre-existing stored profile; `--dry-run` writes nothing; interrupted backfill leaves the original intact; re-run is a no-op.
- **Regression risk:** the only real data risk in the plan.
- **Rollback:** the pre-existing `CompanyStore` JSON is never modified — it is read, compared against, and left in place. Rollback is deleting the assertion DB and flipping `ATLAS_PROFILE_SOURCE` back.

---

# Part 5 — Solo-engineer optimisations

Choices made for velocity over elegance, stated so they are not re-litigated later:

1. **`builder.py` is not touched.** M3 adapts to the existing interface rather than rewriting 1,006 lines of working assembly logic. The adapter is throwaway code with a real job; the builder is 3,400-test-covered code that works.
2. **One SQLite DB per company for all of Tier 1.** Assertions and entities share invalidation, so they share storage. No Postgres, no separate services, no schema registry.
3. **Content-addressed IDs instead of a reconciliation engine.** Determinism by construction is cheaper than determinism by comparison.
4. **Env-var flag, not a plugin architecture.** `ATLAS_PROFILE_SOURCE` is one string. Rollback is one line.
5. **Dual-write before cutover, delete the old path last.** M1 writes without reading; M3 reads behind a flag; M4 flips the default; M10 retires the old path. Four separate reversible steps, never one big-bang switch.
6. **Excerpts stay transient.** Verified: `builder.py` ignores them. Persisting them would multiply store size for zero consumers. Re-derivable from `KnowledgeBase` + `char_offset` if ever needed.
7. **No assertion conflict resolution.** Two analyzers disagreeing on the same value is a real problem and is explicitly not in this plan. The store records both; nothing reconciles them yet. Adding reconciliation later is additive; guessing at it now is a rewrite.
8. **No API, no UI, no async, no queue.** CLI only, synchronous.
9. **The equivalence test is the deliverable, not the schema.** If M4's test is green, the invariant holds. Everything else is implementation detail that can change freely underneath it.

**Sequencing rule for a solo engineer:** never have two milestones half-done. Each is a branch that merges green or gets reverted whole.

---

# Part 6 — GitHub milestone roadmap

Paste-ready. Each issue is 1–3 days.

---

## Milestone: `M9 — Ontology Version Freeze` · XS · Week 1

- [ ] **#1 Add `ONTOLOGY_VERSION` to `analysis/base.py`** — constant beside `FactKind`, docstring stating the bump rule. `S:XS`
- [ ] **#2 Snapshot test pinning the `FactKind` member set** — checked-in sorted value list; failure message tells the developer to bump the version and update the snapshot. `S:XS`

## Milestone: `M0 — Build Fingerprint` · S · Week 1

- [ ] **#3 Create `src/atlas/provenance.py` with `BuildFingerprint`** — frozen dataclass, **six** fields (adds `shared_parser_version`), canonical-JSON `digest()`. `S:XS`
- [ ] **#4 Expose the analyzer version map from `analysis/registry.py`** — `analyzer_versions() -> Mapping[str, str]` covering all 11 registered kinds. `S:XS`
- [ ] **#5 Implement `current_fingerprint()` and `code_rev` capture** — `git describe`, `None` outside a checkout, excluded from `digest()`. `S:XS`
- [ ] **#6 Tests: digest stability, per-component sensitivity, registry coverage** — `tests/unit/test_provenance.py`. `S:XS`
- [ ] **#63 Add `SHARED_PARSER_VERSION` to `analysis/patterns.py` and wire into the fingerprint** — 381 lines imported by 7 of 11 analyzers, currently invisible to the digest. `S:XS`
- [ ] **#64 Guard test: every analysis module imported by a registered analyzer contributes a fingerprint component** — fails when a new shared module is added unversioned. Explicitly excludes `shareholding_trend.py` (Tier 2 consumer, emits no facts) with the reason in a comment. `S:XS`
- [ ] **#65 `atlas fingerprint show [--explain] [--diff <other>]`** — prints every component; ten minutes, and it is the first thing you want when a digest moves unexpectedly. `S:XS`

## Milestone: `M-PRE — Determinism Pre-flight` · S · Week 2

*New in revision 2. Blocks M1.*

- [ ] **#61 Add `sort_keys=True` to both `json.dumps` sites in `company/store.py`** — lines 753 and 816. No fixture regeneration needed (D3). `S:XS`
- [x] ~~**#62 Call `_finalize_profile()` from `CompanyStore.merge()`**~~ — **RETIRED: already implemented.** `merge()` calls `merge_result()` (`store.py:809`), which finalizes at `builder.py:1101`. Downstream issue numbers deliberately NOT renumbered. `S:—`
- [ ] **#66 Sort `sources` lists in `_finalize_profile()`** — 9 `append` sites in `builder.py`; `_finalize_profile` sorts 16 containers and no `sources` list. **This is the actual full-vs-incremental divergence**, not #62. Sort only — do not dedupe, that is a semantic change and a separate decision. `S:XS`
- [ ] **#32-PRE Run the equivalence test against the existing analyzer path** — full build vs repeated `merge()`, byte-identical. The fixture MUST place at least two results in the same `(period, basis)` snapshot; one result per snapshot makes every `sources` list a single element and the test passes vacuously. Same test body later reused verbatim as #32. `S:S`
- [ ] **#60 Tie-order test: two same-day filings of the same kind** — `build_profile()`'s sort is stable (`builder.py:1124-1127`), so equal `(priority, source_date)` keys retain input order. Ingest both ways, assert identical output. `S:XS`
- [ ] **#67 `atlas profile diff <a> <b>`** — semantic diff of two profiles. Needed by #32-PRE, #26, #32, #55 and every debugging session between them. A red boolean says nothing; a diff says where to look. `S:S`

## Milestone: `M1 — AssertionStore` · L · Weeks 3–5

- [ ] **#7 Define `Assertion` and `AssertionRun` models** — `assertions/model.py`, content-addressed `assertion_id` **including `ordinal`**, explicit `value_type`. `S:S`
- [ ] **#8 Create the SQLite schema and `AssertionStore` open/create** — `_CREATE_TABLES`, `STORE_VERSION`. ~~mirror `knowledge/base.py`'s `_MIGRATE_V*` list~~ **superseded by #68.** `S:S`
- [ ] **#68 Implement `PRAGMA user_version` migrations in `assertions/store.py`** — numbered functions, applied in order, failures raise. Do **not** modify `knowledge/base.py` (`base.py:180-186` swallows every `OperationalError`; it works today and changing it is unrelated risk). `S:S`
- [ ] **#69 Add `ordinal` to `assertion_id` and make `INSERT` raise on conflict** — 0-based index within `(evidence_id, kind, section)` in emission order. Required: `annual_report.py:634-645` gives every `RISK_FACTOR` in one loop the same `char_offset` and `section`; six further sites emit `char_offset=None`. `INSERT`, never `INSERT OR REPLACE`. `S:S`
- [ ] **#70 Implement `canonical_for_hash()` with the single timestamp exclusion list** — `analyzed_at` (`base.py:486`, `default_factory=datetime.now`), `built_at`, `created_at`. Used by the ID function, the fingerprint, and #31. One list, one place. `S:XS`
- [ ] **#71 Decide and enforce the multi-version reader rule** — highest `analyzer_version` matching the current fingerprint, raise if none matches. Property test: the choice is a pure function of store contents, independent of insertion order. Resolves the conflict between the assertion PK `(evidence_id, analyzer_version)` and `ingested_results` keyed on `evidence_id` alone (`store.py:792-795`). `S:S`
- [ ] **#9 Implement `AssertionStore.write_run()` / `read_run()`** — transactional per evidence document, idempotent on re-write. `S:S`
- [ ] **#10 Implement `assertions/writer.py`: `AnalysisResult` → rows** — value/type encoding, provenance flattening, warnings JSON. `S:S`
- [ ] **#11 Implement `assertions/reader.py`: rows → facts** — deterministic ordering by `(source_date, evidence_id, assertion_id)`. `S:S`
- [ ] **#12 Add `atlas analyze --company X [--kind K]` CLI command** — populate the store; no profile side effects. `S:S`
- [ ] **#13 Round-trip test across all 11 analyzers on the golden corpus** — fact equality by `(kind, value, unit, period, confidence, provenance)`. `S:S`
- [ ] **#14 Idempotency and version-bump tests** — same write twice yields zero new rows; bumped `analyzer_version` yields a new run and new IDs, old rows retained. `S:XS`
- [ ] **#15 Value-type fidelity test** — `int`/`float`/`str`/`None` survive the round trip for every quantitative `FactKind`. `S:XS`
- [ ] **#16 Failure-path handling** — analyzer raises → `status='failed'`, error recorded, zero assertion rows. `S:XS`
- [ ] **#17 Record store size and row count for a full TCS repo** — assertion in the integration test, number in the PR body. `S:XS`
- [ ] **#72 `atlas assertion explain <assertion_id>`** — full chain in one command: row → analyzer + version → evidence_id → source document → char_offset → surrounding text. Without it, every "why is this number wrong" is a manual six-layer trace. `S:S`
- [ ] **#73 `atlas store status --company X`** — tier sizes, row counts, fingerprints, staleness, last rebuild. ~~Was M10 (#56)~~ **moved forward**: nine weeks of flying blind is the wrong trade for a one-day tool. `S:S`

## Milestone: `M2 — EntityStore` · M · Week 6

- [ ] **#18 Add the `entity_mentions` table as an additive migration** — migration #2 under #68's `user_version` mechanism. ~~`_MIGRATE_V2` pattern~~ superseded. `S:XS`
- [ ] **#74 Derive `mention_id` from surface form, not `entity_id`** — `sha256(evidence_id | canonical_name_as_written | section | char_offset | analyzer_version | ordinal)`. `Entity.entity_id` is order-dependent by design: `knowledge/entities/model.py` documents that it derives from the *first observed* name and gets a resolver disambiguation suffix on collision. Both depend on corpus traversal order, so a reordered backfill would mint different IDs. Store `entity_id` as a plain column. No resolver change. `S:S`
- [ ] **#75 Confirmation test: `mention_id` is stable across corpus orderings** — resolve the same document set in two orders in separate processes, assert identical mention IDs. Downgraded from spike S4 (unknown) to a test (the invariant is now documented in the source). `S:XS`
- [ ] **#19 Extend the writer to persist `EntityMention` in the same transaction** — all five context fields. `S:S`
- [ ] **#20 Extend the reader to reattach mentions to reconstructed results** — `AnalysisResult.entities` populated. `S:S`
- [ ] **#21 Round-trip test using `test_entities.py` / `test_director_identity.py` fixtures** — no field loss, DIN preserved. `S:S`
- [ ] **#22 Writer atomicity test** — injected mid-write failure leaves zero rows in both tables. `S:XS`

## Milestone: `M3 — Profile from Tier 1` · M · Weeks 7–8

- [ ] **#23 Implement `reader.results_for(company_id) -> list[AnalysisResult]`** — full envelope reconstruction; `excerpts={}`. `S:S`
- [ ] **#24 Add the `ATLAS_PROFILE_SOURCE` setting** — `analyzers` (default) | `assertions`, wired through `config/settings.py`. `S:XS`
- [ ] **#25 Route `CompanyStore` build/merge through the configured source** — no `builder.py` changes. `S:S`
- [ ] **#26 Byte-identity equivalence test across the golden corpus** — analyzer-sourced profile vs assertion-sourced profile. `S:S`
- [ ] **#27 Reader determinism test** — ten reads of one store return identical ordering. `S:XS`
- [ ] **#28 Import-boundary test: `builder.py` must not reference `.excerpts`** — fails loudly the day that assumption breaks. `S:XS`

## Milestone: `M4 — Rebuild Engine` · M · Week 9

- [ ] **#29 Implement `src/atlas/rebuild.py` with `--from evidence|assertions`** — pipeline orchestration only, no new logic. `S:S`
- [ ] **#30 Add `atlas rebuild` CLI with `--verify`** — verify diffs against a temp build and writes nothing. `S:S`
- [ ] **#31 Canonical-JSON comparison helper excluding wall-clock fields** — asserts they exist and parse, excludes them from equality. `S:XS`
- [ ] **#32 Equivalence gate: full vs incremental vs shuffled vs reversed** — same test body as #32-PRE, now with `ATLAS_PROFILE_SOURCE=assertions`. `S:S`
- [ ] **#33 Fix residual order-dependence uncovered by #32** — **budget cut 3 days → 1–2 days.** The dominant known cause (unsorted `sources` lists) is fixed by #66, and #32-PRE was green before this milestone started, so anything found here is caused by the assertion reader and is attributable. `S:S`
- [ ] **#34 Rebuild idempotency test** — rebuild twice, byte-identical. `S:XS`
- [ ] **#35 Flip `ATLAS_PROFILE_SOURCE` default to `assertions`** — only after #32 and #33 are green. `S:XS`

## Milestone: `M5 — Judgment Store (Tier 0)` · M · Parallel, any week after 1

- [ ] **#36 Define the `Judgment` model** — content-addressed, `supersedes` chain, no update-in-place. `S:S`
- [ ] **#37 Implement `judgment/store.py`** — append-only JSON per subject, `store_version = "1"`, `ThesisStore` file conventions. `S:S`
- [ ] **#38 Add `atlas judgment add|list|supersede` CLI** — `--force` required for deletion. `S:S`
- [ ] **#39 Append-only and supersede-chain tests** — duplicate id raises; chains resolve to full history. `S:XS`
- [ ] **#40 Rebuild-survival test** — `atlas rebuild --all`, then judgments read back byte-identical. `S:XS`
- [ ] **#41 Import-boundary test: the rebuild path never imports `judgment/`** — enforces the Tier 0 boundary in code. `S:XS`

## Milestone: `M6 — Answer Pinning` · M · Week 10

- [ ] **#42 Add `fingerprint` / `assertion_ids` / `evidence_ids` to the answer envelope** — `reasoning/contracts.py`, additive with defaults. `S:S`
- [ ] **#43 Populate pinning fields in `reasoning/ask.py` and `research/thesis.py`** — record what was actually consulted, not what was available. `S:S`
- [ ] **#44 Render the pinning footer** — `reasoning/render.py`, `research/render.py`, `query/render.py`. `S:S`
- [ ] **#45 Backward-compatible load of pre-pinning stored theses** — `fingerprint=None`, no error. `S:XS`
- [ ] **#46 Pinning tests across all four answer surfaces** — `ask`, `research`, `investigate`, `thesis`. `S:S`

## Milestone: `M7 — Selective Invalidation` · M *(was S)* · Week 11

- [ ] **#76 Add `merge(result, *, allow_reanalysis=False)` to `CompanyStore`** — when `True` and the stored version differs, drop that evidence's contribution and re-merge instead of raising `StaleResultError` (`store.py:801-806`). Default `False` preserves every existing caller and test. **Unbudgeted work found in audit — this is why M7 grew from S to M.** `S:S`
- [ ] **#47 Implement `BuildFingerprint.affects(kind)` sub-digests** — per-kind digest over the components that can affect that kind, `shared_parser_version` included. `S:XS`
- [ ] **#48 Add `stale_evidence()` to the store** — rows whose stored fingerprint no longer matches. `S:S`
- [ ] **#49 Add `atlas rebuild --stale-only`** — narrow path is opt-in; default stays full invalidation. `S:S`
- [ ] **#50 Invalidation-scope tests** — one analyzer bump re-runs one analyzer; `PARSER_VERSION` or `SHARED_PARSER_VERSION` bump re-runs everything; clean store is a zero-write no-op. `S:XS`
- [ ] **#77 Row-count invariant after `--stale-only`** — store row count must equal a full rebuild's, or fail loudly. Catches partial re-runs, which are silent otherwise. `S:XS`

## Milestone: `M8 — Metrics Pinning` · S · Week 11 (parallel with M7)

- [ ] **#51 Add `fingerprint` to `QueryResult` and populate it in `query/engine.py`** — one commit across all query functions. `S:S`
- [ ] **#52 Render the fingerprint in `query/render.py` and update golden fixtures** — mechanical. `S:XS`
- [ ] **#53 Coverage test driven by `available_queries()`** — a new query cannot skip pinning. `S:XS`

## Milestone: `M10 — Backfill & Operator CLI` · M · Week 12

- [ ] **#54 Implement `atlas migrate assertions --company X [--dry-run]`** — temp DB, verify, atomic move. Never mutates in flight. `S:S`
- [ ] **#55 Gate the move on profile equality, normalized** — normalize both sides through the post-M-PRE serializer, then compare. Legacy profiles were written under insertion-order serialization by an earlier `builder_version`, so raw byte-identity is unachievable against them and the gate would get disabled to ship. Byte-identity stays the standard for fresh-vs-fresh (#26, #32). `S:S`
- [ ] ~~**#56 Add `atlas store status`**~~ — **moved to M1 as #73.** `S:—`
- [ ] **#57 Add `atlas store verify`** — dangling `evidence_id`s, orphan mentions, fingerprint mismatches. `S:S`
- [ ] **#58 Backfill safety tests** — dry-run writes nothing; interruption leaves the original intact; re-run is a no-op. `S:S`
- [ ] **#59 Migrate all existing company repos and record before/after** — run it, record numbers, close the milestone. `S:XS`

---

## Schedule

| Week | Milestone | Change from revision 1 |
|------|-----------|------------------------|
| 1 | M9, M0 | M0 gains #63–#65 |
| 2 | **M-PRE** | **new** |
| 3–5 | M1 | shifted +1 week; gains #68–#73 |
| 6 | M2 | shifted +1; gains #74, #75 |
| 7–8 | M3 | shifted +1 |
| 9 | M4 | **compressed 2 weeks → 1** (#33 budget cut) |
| 10 | M6 | unchanged |
| 11 | M7 + M8 | M7 now M-sized; #76 may push M8 to week 12 |
| 12 | M10 | unchanged |
| any | M5 (parallel filler when blocked) | unchanged |

Still twelve weeks. M-PRE's week is paid for by M4 compressing, because #33's fix budget moved to week 2 where the cause is unambiguous.

**Remaining uncertainty, ranked:** (1) #33 — smaller now but still the only estimate resting on unknown findings; (2) #76 — a contract change on a 3,400-test-covered class; (3) #43 — "assertions actually consulted" may exceed its estimate, which is why M6 splits it from the cheap `evidence_ids` half.

The equivalence gate ships green or the plan stops there, because every milestone after it assumes the invariant holds.
