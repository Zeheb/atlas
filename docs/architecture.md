# Architecture

How Atlas is structured **today**. This document describes the current system:
which subsystem owns which responsibility, and where to find the decisions
behind that structure. Historical rationale — why a design was chosen, what was
rejected — lives in [`docs/adr/`](adr/), not here.

Atlas is a provenance-first equity-research platform. Its organising constraint:
**every claim must be traceable to a document Atlas actually acquired.** That
constraint, not layering fashion, is what shapes the subsystem boundaries below.

---

## 1. Layered architecture

Each layer depends only on layers below it. No layer knows about layers above.

```
┌──────────────────────────────────────────────────────────────┐
│  Interface            atlas.cli, atlas.app                   │
├──────────────────────────────────────────────────────────────┤
│  Evaluation           atlas.eval  ─────┐                     │
│  Benchmark            atlas.benchmark ─┘ measure the system   │
├──────────────────────────────────────────────────────────────┤
│  Research             atlas.research     what to investigate, │
│                                          fixed-shape reports  │
├──────────────────────────────────────────────────────────────┤
│  Reasoning/Retrieval  atlas.reasoning    how to retrieve,     │
│                                          how to answer        │
├──────────────────────────────────────────────────────────────┤
│  Company              atlas.company      the analysed profile │
│  Query                atlas.query        deterministic lookups│
├──────────────────────────────────────────────────────────────┤
│  Analysis             atlas.analysis     documents → facts    │
├──────────────────────────────────────────────────────────────┤
│  Knowledge            atlas.knowledge    documents → text     │
├──────────────────────────────────────────────────────────────┤
│  Acquisition          atlas.acquisition  the outside world    │
└──────────────────────────────────────────────────────────────┘
        atlas.config (settings) and atlas.citation (formatting)
        are consumed at every level.
```

Three dependency rules are enforced by test rather than convention:

- `atlas.benchmark` never imports `atlas.eval`, though `eval` imports
  `benchmark`. It consumes structural Protocols (`CaseLike`,
  `ResearchPlanLike`) so evaluation keeps working if benchmark tooling is
  absent.
- Planner modules import no knowledge base, no LLM client, and no
  network/filesystem library (§3).
- `atlas.reasoning` never imports `atlas.research` (M2.4). Research-specific
  vocabulary (dimensions, dispositions, run fingerprints) stays in
  `research.Thesis`; only its projection, `RecalledView` (C6), crosses into
  `reasoning.contracts`, via `Thesis.to_view()` — never the reverse.

---

## 2. Subsystem responsibilities

### Acquisition — *get the documents, and know what they are*

Fetches filings from external sources, deduplicates them, classifies each into
the frozen evidence ontology, and records what was acquired and when. Owns the
catalog: the authoritative list of documents Atlas holds for a company.

Every downstream claim ultimately cites an `evidence_id` minted here.

→ ADR-0001 (evidence ontology), ADR-0002 (acquisition v1 freeze)

### Knowledge — *turn documents into retrievable text*

Parses acquired documents into text and stores them in a per-company SQLite
`KnowledgeBase`. Owns the multi-stage extraction pipeline (native text →
quality scoring → OCR fallback) and the batch metadata reads retrieval depends
on.

### Analysis — *turn text into typed facts*

One analyzer per document kind (annual report, BRSR, shareholding pattern,
earnings transcript, credit rating, …), each emitting facts against the shared
`FactKind` vocabulary. Analyzers are deterministic and independently testable;
a document kind with no analyzer yields no facts rather than guessed ones.

### Company — *the analysed view of one business*

Assembles analyzer output into a `CompanyProfile`: financial time series,
risk entries, governance and ownership records, plus derived metrics. This is
the persisted, queryable state of what Atlas knows about a company.

### Query — *deterministic lookups and screens*

Rule-based metric queries, timelines, comparisons, and cross-company screening
over profiles. No LLM anywhere in this subsystem.

### Retrieval — *decide how to search, then search*

Lives inside `atlas.reasoning`. A `RetrievalPlanner` classifies a question's
intent and emits a frozen `SearchPlan` (preferred document kinds, period hints,
`top_k`); the retriever then generates candidates and ranks them.

Doc-type, date, and period preferences are **score boosts, never filters** — a
plan can never return fewer results than an unplanned query. Candidate
generation deliberately ignores plan preferences, which is what makes that
fallback guarantee structural rather than a promise.

→ ADR-0003 (retrieval planning)

### Reasoning — *answer a question from grounded context*

Assembles a `GroundingContext` from profile claims plus retrieved passages,
calls the configured LLM, and renders an `Answer` whose every citation resolves
to a real document. Refuses rather than guessing when the evidence does not
support an answer — including refusing findings that carry no supporting
evidence at all.

Provider selection (Anthropic, Gemini, Ollama, OmniRoute) is configuration, not
architecture: the reasoning layer sees one `LLMClient` interface.

### Research — *decide what to investigate; assemble what is known; remember what was concluded*

Three surfaces, deliberately not merged:

- **The fixed-shape report** (`atlas research`) runs the same nine section
  builders for every company, in the same order, every time. A section that
  finds nothing says so rather than being skipped. This constant shape is what
  makes the report trustworthy as an **audit**: a reader always sees the full
  extent of what Atlas checked. It performs no retrieval — it assembles what
  analysis already extracted.

- **Question-driven investigation** (`atlas investigate`) decomposes an
  open-ended question ("Should I invest in TCS?") into the dimensions that must
  be investigated before a view can be formed, routes each through the
  retrieval pipeline, and returns grounded findings.

- **Thesis synthesis and memory** (`atlas thesis`, `atlas memory`) forms an
  argued view from an investigation's findings (`research.thesis.synthesize`),
  gated by a completeness check that blocks rendering rather than warning —
  a thesis that silently drops a finding is not shown at all. `--remember`
  persists an accepted thesis (`ThesisStore`, one JSON file per subject);
  `atlas memory list/show/check` reads it back, and `check_staleness`
  (`research.staleness`, pure, no LLM) reports — advisorily — whether a
  view's cited evidence still resolves. `atlas ask --thesis <view_id>`
  re-injects a remembered view into reasoning as `RecalledView` (C6, see
  below) so a new answer can be checked against it; the view is shown to the
  model as reference only and never becomes citable evidence.

All three name the same nine research dimensions, enforced by test against
the real section builders so the vocabularies cannot drift.

→ ADR-0006 (research planning), ADR-0008 (thesis generation), ADR-0010 (C6
reasoning memory)

### Evaluation — *measure whether changes actually improve Atlas*

Runs the case suite, scores correctness/grounding/refusal plus retrieval and
planner diagnostics, and compares two runs. Supports a retrieval-only mode that
builds no LLM client at all, so retrieval changes can be measured without
spending model calls.

Recommendations are advisory: the harness reports a verdict, a human decides.

→ ADR-0004 (retrieval evaluation)

### Benchmark — *measure whether the evaluation suite itself is adequate*

Distinct from Evaluation, and the distinction is the point: evaluation asks
"did the system perform well," benchmark asks "is the suite capable of
detecting whether it did." Owns coverage analysis (which planner intents,
rules, and scenarios are exercised), redundancy detection, machine-checked case
provenance, and the anti-checklist gate on research plans.

Case provenance is verified, not declared: corpus-derived cases have every
evidence id checked against the real knowledge base, and negative cases are
confirmed absent by actually running retrieval.

→ ADR-0005 (benchmark framework)

---

## 3. Planner invariants

Atlas has two planners today — the `RetrievalPlanner` (*how* to retrieve) and
the `ResearchPlanner` (*what* to investigate) — and will gain more. Both
independently satisfy the same six invariants, which any future planner must
also satisfy. Full rationale and the anti-checklist measurement rule: ADR-0007.

**1. Inspectable.** Every plan carries the audit trail of the rules that built
it (`PlanningDecision` / `ResearchDecision`: rule, input, output). "Why did it
plan this?" is answerable from the plan itself, not from the source.

**2. Deterministic baseline.** The first implementation of any planner is
rule-based, with no LLM, no I/O, and no inference. An LLM planner may be added
later behind the same Protocol, but the deterministic floor remains — it is the
baseline any smarter planner must beat, and it is what makes the system
debuggable when the smarter one misbehaves.

**3. Independently evaluable.** A plan can be produced and scored without
executing it: `--retrieval-only` for retrieval plans, `--dry-run` for research
plans. Both build no LLM client at all. Planning quality is measurable
separately from execution quality, which is what allows a planner to be
improved against evidence.

**4. Planners never execute work.** A planner decides and stops. It does not
retrieve, does not call a model, does not synthesize. Enforced by import-boundary
tests, not convention.

**5. Frozen, self-validating output.** Every plan is an immutable dataclass that
validates in `__post_init__`. This is the boundary that makes a future LLM
planner safe: a hallucinated document kind or an absurd `top_k` raises
`ValueError` at construction rather than propagating a silently-wrong plan into
execution.

**6. Declared rule vocabulary.** Each planner declares every rule id it can emit
(`ALL_RULE_IDS`, `ALL_RESEARCH_RULE_IDS`) next to the rules themselves. The
evaluation harness diffs declared against fired to surface **dead rules** —
declared decisions that never produce any effect. Without a declared vocabulary
you can only count what fired, never what should have.

### Measuring whether a planner exercises judgment

A planner that emits the same output for every input passes every single-case
test and is worthless. Guarding against this requires care, because the obvious
metric is wrong:

> **A diversity metric that a degenerate maximum also satisfies is not a gate.**

A research planner naming *all* dimensions for *every* question produces a
perfectly uniform distribution and therefore near-maximal entropy — the
checklist scores as maximally diverse. So:

- **Structural constraints gate.** Bounded plan width (each planner names its
  own concrete limit at its own scale) and variation across inputs.
- **Distributional metrics describe.** Entropy is reported as a statistic, never
  as the pass/fail criterion.

---

## 4. Responsibility → package map

| Responsibility | Package | Key entry points |
|---|---|---|
| Acquisition | `atlas.acquisition` | `workflow.run_acquisition`, `repository.Repository`, `catalog`, `connectors/` |
| Knowledge | `atlas.knowledge` | `base.KnowledgeBase`, `pipeline`, `extractors` |
| Analysis | `atlas.analysis` | `registry.analyze`, `base.FactKind`, one module per document kind |
| Company | `atlas.company` | `builder.build_profile`, `model.CompanyProfile`, `store.CompanyStore` |
| Query | `atlas.query` | `engine.run_query`, `metrics`, `screen` |
| Retrieval | `atlas.reasoning` | `planner.plan_retrieval`, `plan.SearchPlan`, `retrieval.retrieve_with_plan` |
| Reasoning | `atlas.reasoning` | `context.build_context`, `ask.ask`, `render.to_answer`, `llm/`, `contracts.RecalledView` (C6) |
| Research | `atlas.research` | `report.generate_report`, `sections/`, `planner.plan_research`, `investigate.run_plan`, `thesis.synthesize`, `memory.ThesisStore`, `staleness.check_staleness` |
| Evaluation | `atlas.eval` | `runner.run_suite`, `report.Report`, `comparison`, `judge` |
| Benchmark | `atlas.benchmark` | `coverage.analyze_suite`, `coverage.analyze_research_plans`, `validation.validate_cases` |
| Configuration | `atlas.config` | `settings.Settings` |
| Citation formatting | `atlas.citation` | `build_citation` |
| Interface | `atlas.cli`, `atlas.app` | `cli`, `app.Atlas` |

---

## 5. Data flow

```
External source (BSE)
      │  acquisition: fetch, deduplicate, classify, catalog
      ▼
Evidence documents + catalog entries
      │  knowledge: parse → text (OCR fallback when needed)
      ▼
KnowledgeBase (per-company SQLite)
      │  analysis: one analyzer per document kind → typed facts
      ▼
CompanyProfile
      │
      ├──── query ──────────► deterministic metrics, timelines, screens
      │
      ├──── research ───────► fixed-shape briefing (no retrieval, no LLM)
      │
      └──── reasoning ──────► grounded answers
                │  retrieval planner → SearchPlan → ranked passages
                │  + profile claims  → GroundingContext → LLM → Answer
                │
                └── research planner → ResearchPlan → N investigations
                                        → grounded Findings
                                        → thesis.synthesize → Thesis
                                            │  --remember
                                            ▼
                                        ThesisStore (theses.json per subject)
                                            │  Thesis.to_view()
                                            ▼
                                        RecalledView (C6) ──┐
                                            │                │ atlas ask --thesis
                                            │ check_staleness│ (reference only,
                                            ▼ (advisory)     ▼  never citable)
                                        StalenessReport   GroundingContext.thesis
                                                              → contradicts_thesis/
                                                                counter_case on Findings

        eval + benchmark observe all of the above and score it.
```

---

## 6. Architecture Decision Records

| ADR | Subject |
|---|---|
| [0001](adr/0001-evidence-ontology.md) | Evidence ontology — the frozen document-kind vocabulary |
| [0002](adr/0002-acquisition-v1-freeze.md) | Acquisition v1 freeze, and its known limitations |
| [0003](adr/0003-retrieval-planning.md) | Retrieval planning: SearchPlan, the fallback guarantee |
| [0004](adr/0004-retrieval-evaluation.md) | Retrieval evaluation: strategies, comparison, advisory gate |
| [0005](adr/0005-benchmark-framework.md) | Benchmark framework: coverage, machine-checked provenance |
| [0006](adr/0006-research-planning.md) | Research planning: decomposition, the anti-checklist gate |
| [0007](adr/0007-planner-invariants.md) | Planner invariants: the six properties every Atlas planner satisfies |
| [0008](adr/0008-thesis-generation.md) | Thesis generation: synthesis as a reasoning pass, the completeness gate |
| [0009](adr/0009-orthogonal-concerns.md) | Orthogonal concerns: contracts stay consumer-agnostic |
| [0010](adr/0010-reasoning-memory.md) | C6 reasoning memory: `RecalledView`, `ThesisStore`, staleness, `atlas ask --thesis` |

New decisions go in `docs/adr/` using [the template](adr/0000-adr-template.md).
This document is updated to describe the resulting system; it does not record
the argument.
