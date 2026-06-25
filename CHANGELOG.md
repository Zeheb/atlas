# Architecture Decision Log

This file records significant design and engineering decisions made during Atlas development.
It is not a release changelog. Every entry answers: what was decided, why, what was considered, and what it makes harder.

---

## 2026-06-25 — atlas.acquisition, not atlas.repository

**Decision:** The Python package for all company data acquisition is `atlas.acquisition`. The on-disk folder remains `repositories/`. Only the package name changes.

**Why:** A package should be named after its responsibility, not the artifact it manages. `atlas.acquisition` will eventually contain: scaffolding, downloading, syncing, deduplication, crawling, repair, and verification. None of those are well-described by "repository". "Acquisition" describes what this package does: it acquires data. "Repository" describes what it produces — which is the job of the on-disk naming convention, not the Python package name.

**Alternatives considered:** `atlas.repository` (rejected — confuses the package with the on-disk concept; also collides semantically with "git repository" and "research repository"). `atlas.ingest` (rejected — ingestion is one step within acquisition, not the whole thing). `atlas.collector` (considered — accurate, but "acquisition" carries the right connotation of deliberate, structured data gathering).

**Consequences:** Callers write `from atlas.acquisition.scaffold import build_repository`. The on-disk path is always `repositories/TCS/`, never `acquisition/TCS/`. This distinction must be maintained consistently.

---

## 2026-06-25 — Dataclasses for internal domain models; Pydantic reserved for system boundaries

**Decision:** Internal Atlas domain objects — `CompanyRecord`, `Catalog`, and all future equivalents — are Python `dataclasses`. Pydantic is used only at system boundaries: configuration (`Settings`), external API responses, and any payload that requires validation against an untrusted schema.

**Why:** Pydantic is a validation and serialization library. Applying it to internal objects that are constructed by trusted code adds overhead and introduces implicit behaviour (field coercion, validators firing on construction) that can be surprising. `dataclasses` are stdlib, lightweight, fully typed under mypy, and sufficient when the code constructing the object is the code that owns the invariants. The boundary where Pydantic earns its cost is the boundary between Atlas and the outside world.

**Alternatives considered:** Pydantic for everything (rejected — couples internal structure to serialization concerns; makes testing heavier; triggers validators in contexts where the data is already trusted). Plain dicts (rejected — untyped, not introspectable by mypy, harder to refactor). Named tuples (rejected — immutable, which is wrong for objects that will acquire more fields over time).

**Consequences:** `CompanyRecord.to_dict()` must be maintained manually when fields are added. There is no automatic JSON serialization. This is acceptable — the serialization surface is small and explicit, which makes schema changes visible and deliberate.

---

## 2026-06-25 — Immutable prefixed UUIDs for internal company identity

**Decision:** Every company record is assigned a stable internal identifier at scaffold time: `cmp_<uuid4_hex>`. This ID is written to `company.json` and must never be regenerated or changed.

**Why:** Tickers are external identifiers that can and do change. A company listed as `GOOGL` becomes `GOOG`. A company delists and relists. A merger creates a new ticker for a surviving entity. Atlas must be able to maintain research continuity across these changes. The internal ID provides that stability. The `cmp_` prefix makes the ID's domain visible in logs, database rows, and debugging sessions without needing to inspect surrounding context — a pattern proven at scale by Stripe, Linear, and others.

**Alternatives considered:** Using the ticker as the primary key (rejected — tickers change; this would break all foreign key relationships on rename). UUID without prefix (considered — valid, but loses the "what kind of thing is this" signal at a glance). ULID (considered — sortable by creation time, which is useful; rejected for now because it requires an external dependency; can be adopted later if sort order matters).

**Consequences:** The ID must be treated as opaque and immutable by all code. No logic should parse the `cmp_` prefix. If a ticker changes, Atlas updates the ticker field in `company.json` — the ID never changes. All foreign references in future tables, indexes, and knowledge records must use the internal ID, not the ticker.

---

## 2026-06-25 — Minimal catalog.json schema

**Decision:** `catalog.json` is initialized with only `{"schema_version": "1"}`. No document index, no ticker field, no embedded metadata.

**Why:** We do not yet know what the catalog will index. Candidates include: downloaded documents, extracted entities, knowledge objects, OCR outputs, vector embeddings, structured tables. Designing the schema before these requirements are concrete would produce a schema that fits our current imagination rather than the actual access patterns. `schema_version` exists only to support future migrations — it is the minimum viable contract.

**Alternatives considered:** Including a `documents: []` array now (rejected — assumes the catalog indexes documents; it may index other things). Including the ticker (rejected — redundant; the ticker is in `company.json` and in the directory name). A richer schema to "future-proof" the catalog (rejected — premature design is technical debt, not investment).

**Consequences:** Future tasks will define the catalog schema incrementally. The `schema_version` field gives us a migration hook. Any code that reads `catalog.json` must treat unknown fields as valid and must check `schema_version` before making assumptions about structure.

---

## 2026-06-25 — Atlas as the application object, not a context

**Decision:** The shared infrastructure holder is named `Atlas`, not `AtlasContext` or `AppContext`. It lives in `src/atlas/app.py` and is re-exported from `src/atlas/__init__.py` so callers write `from atlas import Atlas`.

**Why:** `Atlas` is the application itself — the thing that holds everything the application needs to run. `AtlasContext` implies a scoped execution context (like a request context in a web framework), which is a different concept. Naming it `Atlas` makes the intent clear: there is one of these per process, and it represents the application.

**Alternatives considered:** `AppContext` (too generic — could belong to any project), `AtlasContext` (implies request/execution scope, which is wrong), `Container` (DI framework terminology, implies more machinery than we have).

**Consequences:** `from atlas import Atlas` is the cleanest possible import. The class name matches the project name, which is either elegant or confusing depending on taste. Future maintainers should understand that `Atlas` is infrastructure only — it must never hold domain state like the current company or research session.

---

## 2026-06-25 — from_environment() factory; no setup_* methods

**Decision:** `Atlas` is always fully constructed. `Atlas.from_environment()` is the production factory that loads all services. There are no `setup_logging()`, `setup_http()`, or similar partial-initialization methods. The constructor accepts keyword-only arguments for each service, enabling tests to inject controlled values directly.

**Why:** An object with optional setup methods can exist in a partially-initialized state. Code that calls `atlas.logger` before `atlas.setup_logging()` either silently gets `None` or raises a `RuntimeError` — both are worse than making initialization explicit and complete at construction time. `from_environment()` is the composition root: it knows how to assemble all services from environment configuration. Test code skips the factory and builds `Atlas` directly with test doubles.

**Alternatives considered:** `setup_*` methods (rejected — allows partially initialized objects, which are a source of runtime errors and test complexity). Lazy property initialization with `@cached_property` (rejected — hides initialization order and makes it impossible to inject test doubles cleanly). A separate `Builder` or `Factory` class (rejected — unnecessary abstraction for the current scale).

**Consequences:** When F-T3 adds logging, `from_environment()` grows by two lines and the constructor gains a `logger` parameter. This is the expected cost. Tests that construct `Atlas` directly will need to supply the logger if they test code that uses it; tests that only test configuration do not need to change.

---

## 2026-06-25 — ATLAS_ prefix for all environment variables

**Decision:** All Atlas configuration environment variables are prefixed with `ATLAS_`. Example: `ATLAS_ENVIRONMENT`, `ATLAS_LOG_LEVEL`, `ATLAS_REPOSITORY_BASE_PATH`.

**Why:** Unprefixed names like `LOG_LEVEL` or `ENVIRONMENT` collide with variables set by shells, CI systems, and other tools. A consistent prefix makes Atlas variables immediately recognizable in a process environment and eliminates the risk of silent misconfiguration from an unrelated tool's variable.

**Alternatives considered:** No prefix (rejected — `LOG_LEVEL=DEBUG` is already set by many tools and CI environments). `ATLAS_APP_` prefix (rejected — redundant). Per-subsystem prefixes like `ATLAS_HTTP_` for HTTP vars (this is actually what we do for clarity within the prefix namespace, e.g., `ATLAS_HTTP_TIMEOUT_SECONDS`).

**Consequences:** Slightly more verbose `.env` files. The payoff is zero ambiguity about which variables belong to Atlas.

---

## 2026-06-25 — Adopt Conventional Commits as the commit message standard

**Decision:** All commits must follow the Conventional Commits specification. Allowed types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `style`, `perf`, `ci`, `build`. Enforced via a `commit-msg` pre-commit hook using `conventional-pre-commit`.

**Why:** A consistent commit history makes it possible to understand the project's evolution at a glance, generate structured changelogs automatically, and filter history by intent (e.g., `git log --grep "^feat"`). The cost is near-zero on a single-developer project and pays compound interest on a long-lived codebase.

**Alternatives considered:** No standard (rejected — commit history becomes noise after 6 months). SemVer-tagged releases with a traditional CHANGELOG (rejected — adds release ceremony overhead not appropriate for a research tool with no external consumers).

**Consequences:** Every commit requires a type prefix. The pre-commit hook rejects non-conforming messages, so `git commit -m "fix stuff"` will fail. This is intentional friction.

---

## 2026-06-25 — 80% test coverage floor enforced from day one

**Decision:** `pytest-cov` is configured with `--cov-fail-under=80`. Tests fail — locally and in CI — if coverage drops below 80%. This applies from the first line of source code.

**Why:** Retrofitting a coverage requirement onto an existing codebase is painful. Establishing it on day one means every new module is written with testability in mind. The 80% floor is not a target — it is a floor. The goal is meaningful tests, not line coverage for its own sake.

**Alternatives considered:** CI-only coverage gate (rejected — local feedback loop matters). 100% coverage (rejected — some code is genuinely hard to test without integration infrastructure and would incentivise trivial tests). No coverage requirement (rejected — the history of this decision is that it always gets regretted).

**Consequences:** The coverage threshold will cause friction when adding infrastructure code (e.g., HTTP clients, config loaders) before writing their tests. This is the correct friction — it means tests are written alongside the code, not after.

---

## 2026-06-25 — Four separate CI jobs for format, lint, type check, and tests

**Decision:** GitHub Actions runs four independent jobs: `format-check` (black), `lint` (ruff), `type-check` (mypy), `test` (pytest). They run in parallel. Each job has an independent pass/fail status in the PR checks UI.

**Why:** When CI fails, the failure should be immediately diagnosable without reading logs. A single "CI" job that runs all checks forces you to read output to find which tool failed. Four jobs surface the failure type in the PR check name itself.

**Alternatives considered:** One job with four sequential steps (rejected — steps are not independently visible in the GitHub PR checks summary; a failure in step 1 hides steps 2–4 entirely). Three jobs combining lint + format (rejected — black and ruff failures have different remediation paths and should be reported separately).

**Consequences:** Each job performs its own `checkout` and `uv sync`, adding overhead per run. For a project of this scale, the tradeoff favours diagnostic clarity over CI speed. This can be revisited if CI minutes become a constraint.

---

## 2026-06-25 — ruff for linting, black for formatting (not ruff format)

**Decision:** ruff handles linting only (rules: `E4`, `E7`, `E9`, `F`, `I`, `BLE`). black handles all formatting. ruff's own formatter (`ruff format`) is not used.

**Why:** The user explicitly specified both tools. Keeping them with separate, non-overlapping responsibilities avoids configuration conflicts and makes each tool's role unambiguous. The `E4/E7/E9` ruff rule selection is the subset of pycodestyle checks that are safe to use alongside black (they do not conflict with black's formatting decisions).

**Alternatives considered:** ruff format only, dropping black (viable — ruff format is black-compatible; rejected because the user specified both). black only, dropping ruff lint (rejected — ruff catches bugs and import order issues that black does not). pylint instead of ruff (rejected — too slow, too opinionated for a fresh project).

**Consequences:** Two formatting-adjacent tools in the chain. `make fmt` runs black then ruff `--fix`. If ruff's fix introduces a formatting change, a subsequent `black --check` run could fail. In practice this does not occur with the selected rule set, but it is a potential fragility.
