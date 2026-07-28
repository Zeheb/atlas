# Atlas

Atlas is software for investment research.

The goal is to reduce the manual work involved in understanding a business by collecting information from many sources, organizing it, extracting useful information, and building a long-term knowledge base that improves over time.

It is designed around four stages.

## Stage 1 — Data Collection

Collect information from every relevant public source for a company.

Examples include:

* Annual reports
* Investor presentations
* Quarterly financial results
* Earnings call transcripts
* Exchange filings
* Shareholding patterns
* Credit rating reports
* Broker research
* Industry reports
* Government records
* News
* Community discussions

The objective is to acquire as much relevant information as possible while preserving where it came from.

Output:
A complete repository of raw evidence for a company.

---

## Stage 2 — Information Extraction

Read the collected evidence and extract structured information from it.

Examples include:

* Customers
* Suppliers
* Capex announcements
* Guidance
* Risks
* Management commentary
* Margin drivers
* Capacity additions
* Shareholding changes
* Key hires
* Product launches

The extracted information should be linked back to the evidence it came from.

Output:
A structured database of facts with supporting evidence.

---

## Stage 3 — Knowledge Repository

Connect information across documents, companies and time.

Examples:

* Track how management commentary changes over multiple years.
* Group documents relating to the same business event.
* Link facts mentioned across annual reports, presentations and conference calls.
* Keep a history of previous research and investment notes.
* Preserve evidence even as new information becomes available.

The repository should become more useful as more companies and more years of data are added.

Output:
A searchable knowledge base for long-term investment research.

---

## Stage 4 — Research

Use the knowledge repository to answer investment questions.

Examples:

* Who are the company's major customers?
* Has promoter ownership increased?
* Has management consistently met guidance?
* How have margins behaved over time?
* What risks keep recurring?
* What has changed since the last quarter?
* What did I conclude about this business two years ago?
* How does this company compare with its peers?

The aim is to bring together the relevant evidence so that an investor can make an informed decision.

---

## Current Status

Atlas has completed Stages 1 and 2, a working Stage 3 (`CompanyProfile` + `CompanyStore` + an entity model over an OCR-hardened knowledge layer), and a substantial Stage 4: a deterministic query engine, an LLM-backed grounded reasoning layer with citation validation, a research engine that plans and executes multi-step investigations into a written thesis, a reasoning-memory layer that recalls and re-checks prior views, and an evaluation harness with a capability benchmark that grades what the system cannot yet do. Three companies are used as the reference set, chosen to span sectors: **TCS** (IT services), **Tata Steel** (manufacturing), **SBI** (banking).

Engineering baseline: 3,430 tests across 155 files, clean under `ruff`, `black` and `mypy --strict`, enforced by pre-commit and CI. Fourteen ADRs in `docs/adr/` record the decisions behind the design.

---

### Stage 1 — Data Collection: Complete

* BSE integration: filing discovery, download, deduplication, verification
* Evidence catalog across TCS (156 documents), Tata Steel (334), and SBI (307), spanning 13+ filing types
* Acquisition pipeline: `AcquisitionPolicy`, per-run records, incremental updates
* Knowledge base: multi-stage PDF extraction — native text layer first, objective quality scoring (density + garbled-word coherence), automatic Tesseract OCR fallback below threshold. Validated against real filings: clean PDFs stay native, scanned/broken-encoding filings (common in older SBI filings) correctly trigger OCR, with zero false positives observed across 742 PDFs / 16,891 pages

Filing types in the TCS catalog:

| Filing type | Count |
|---|---|
| Investor presentations | 50 |
| Annual reports | 29 |
| AGM notices and voting results | 28 |
| Regulatory filings | 9 |
| Acquisitions (Reg 30) | 6 |
| Earnings transcripts | 6 |
| Dividend notices | 6 |
| Financial results (Reg 33) | 5 |
| Buyback filings | 5 |
| BRSR | 4 |
| Board outcomes (Reg 30) | 4 |
| Credit rating reports | 3 |
| Shareholding pattern (XBRL) | 1 |

---

### Stage 2 — Information Extraction: Complete

A typed fact ontology (`FactKind`) with 132 members and 13 units (`FactUnit`), spanning financial, capital allocation, ESG, governance, ownership, credit, strategy, and segment domains — including a banking-ratio family (NIM, NPA, PCR, CASA, credit cost, capital adequacy, slippage) and physical production/delivery volume for industrial companies.

The ontology is now formally frozen (ADR-0012): new `FactKind` members require a recorded justification, which is what kept the four most recent extraction milestones honest about whether they were adding investment signal or vocabulary. Those milestones added:

* **Notes to accounts** (M-P3.2) — auditor history, cash tax paid vs. book tax, intangibles and gross block
* **Related-party disclosures** (M-P3.3) — RPT extraction from annual reports plus RPT tagging of AGM resolutions
* **Input-cost line items** (M-P3.4) — cost of materials, purchases of stock-in-trade, changes in inventory
* **Borrowings maturity schedule** (M-P3.6) — six disclosed repayment buckets

`AnalysisResult` also carries an `entities` channel (ADR-0014) alongside `facts` and `excerpts`, so analyzers can emit resolved people and organizations without routing them through the fact ontology.

Eleven analyzers, each implementing `analyze(evidence_id, kb) → AnalysisResult`:

| Analyzer | Document type | Notes |
|---|---|---|
| `financial_results` | Quarterly / annual Reg 33 | Full P&L, balance sheet, cash flow, segments, EPS, audit; dedicated Banking Regulation Act path for bank filings |
| `annual_report` | Annual report (Board's/Director's Report, MDA, auditor's report) | CSR spend, KAM titles, workforce attrition, risk factors |
| `brsr` | Business Responsibility & Sustainability Report | GHG, energy, water, waste, workforce, safety, SBTi targets |
| `agm_notice` | AGM voting results (Reg 44) | Resolution title, type, outcome, vote percentages |
| `investor_presentation` | Investor decks, press-release-style filings, IR schedules | **v2.0** — rebuilt around cross-sector concepts (forward guidance, ROE/FCF, a banking-ratio family, production/delivery volume, segment growth) rather than v1's TCS-specific slide titles, after v1 was found to extract nothing from the large majority of Tata Steel/SBI presentations. Validated against real TCS, Tata Steel, and SBI filings with dedicated regression tests for the layout quirks each surfaced (interleaved bar-chart pairing, ambiguous section headings, footnote markers, stray connector words) |
| `credit_rating` | ESG and debt rating rationales | Agency, instrument, amount, rating, outlook, action |
| `board_outcome` | Board meeting Reg 30 filings | Dividends, M&A events, subsidiary investments, fundraising, director changes |
| `acquisition` | Acquisition Reg 30 filings | Target, consideration type, enterprise value, stake, timeline |
| `buyback` | Buyback filings | Amount, price, shares offered/bought, record date |
| `shareholding_pattern` | BSE XBRL quarterly SHP | Promoter, FPI, DII, MF, insurance, retail, HNI, NRI holdings |
| `earnings_transcript` | Earnings call transcripts | **v2.0** — rebuilt around cross-sector concepts (revenue, margins, TCV, forward guidance, quarterly headcount/diversity) rather than v1's TCS-only speaker structure, after a filing survey found v1's core abstraction — gating extraction behind identifying "the CFO's speaker turn" — doesn't generalize: SBI has no CEO or CFO at all (a Chairman plus four Managing Directors), and Tata Steel's CFO gives one continuous narrative with no clean quarterly/annual split. Fact extraction is now content-window-bound (prepared remarks vs. Q&A) rather than speaker-gated. No new `FactKind`s were needed — forward guidance and workforce facts reuse `STRATEGY_GUIDANCE` and BRSR's `ESG_WORKFORCE_*` kinds, since a transcript supplies a materially higher-frequency (quarterly vs. annual) version of facts the ontology already models. Validated against real TCS, Tata Steel, and SBI filings, including a data-catalog fix (7 SBI transcripts were mis-catalogued as `investor_presentation`) and two `CompanyProfile`-layer bugs a full profile rebuild surfaced: a USD-denominated revenue fact silently corrupting a crore-denominated display column, and a quarterly-scoped figure getting mislabeled as annual when no authoritative snapshot yet existed for that period |

A `shareholding_trend` module (`analyze_trend`) aggregates multiple SHP results into QoQ and YoY holding deltas and directional signals.

A golden corpus of real TCS documents with expected facts validates extraction quality on every test run.

---

### Stage 3 — Knowledge Repository: Working

A `CompanyProfile` assembles `AnalysisResult` objects from multiple filings into a structured, time-ordered knowledge object:

```
CompanyProfile
├── FinancialTimeSeries     — quarterly and annual P&L, balance sheet, cash flow snapshots
├── ESGTimeSeries           — GHG, energy, water, waste, workforce snapshots
├── CapitalEventLedger      — dividends, buybacks, acquisitions, investments
├── CreditHistory           — rating entries sorted by date
├── OwnershipTimeSeries     — promoter, FPI, DII, retail holding snapshots
├── SegmentTimeSeries       — revenue and EBIT per business segment
├── StrategyProfile         — priorities, guidance, aspiration, CSAT
└── GovernanceProfile       — resolutions, director changes, audit KAMs, risk factors
```

A `derived` module computes net debt/cash, EBIT, EBITDA, margins (EBIT, EBITDA, PAT), capex intensity, GAAP FCF, and employee cost percentage from the snapshot facts.

`CompanyStore` persists a `CompanyProfile` to disk as JSON, with idempotent incremental merge (`store.merge(result)`) so a new filing updates the profile without a full rebuild from all historical results.

An **entity model** (`atlas.knowledge.entities`, ADR-0013) resolves people and organizations to stable `entity_id`s under two test-enforced invariants: an id is derived from the first observed name and never changes as fuller names or aliases accrue, and no two distinct entities ever share one. This activates the `knowledge/entities` scaffold laid down at project start. It currently delivers **identity only** — attributes such as role, affiliation and tenure, and persistence to disk, are not yet built, and `annual_report` is so far the only analyzer emitting entities.

---

### Stage 4 — Research: Working

Four layers now sit on top of `CompanyProfile`, in increasing order of freedom.

**Deterministic query engine** (`atlas.query.engine`) — no LLM calls, no raw document access, 18 named queries: `revenue`, `leverage`, `ownership` (with QoQ/streak signal detection), `capital`, `acquisitions`, `ratings`, `rating_risk_timeline`, `risks`, `risk_recurrence`, `strategy`, `auditor_history`, `related_party_disclosures`, `rpt_resolutions`, `former_answerers`, `summary`, `timeline`, `compare`, `drilldown`. Plus `atlas screen` and `atlas metrics` for cross-company filtering and derived-metric readout.

**Grounded reasoning** (`atlas.reasoning`) — a provider-agnostic LLM layer (Anthropic, Google AI Studio, Ollama, and an OmniRoute gateway), a `GroundingContext` assembled from the profile, prompt construction, and citation validation that rejects answers whose citations do not resolve to real evidence. Retrieval is deterministic raw-text search over the knowledge base, extended with question-conditioned top-K passage retrieval and a rule-based `RetrievalPlanner` that emits an inspectable `SearchPlan` before any document is read (ADR-0003). `atlas ask --show-evidence` drills from an answer back to the source excerpt.

**Research engine** (`atlas.research`) — a `ResearchPlan` model with a deterministic `HeuristicResearchPlanner` (runnable with `--dry-run` and zero LLM calls), an investigation executor, `Finding` widened into five kinds with an obligation map, a completeness gate that forbids silent omission, and `synthesize()` producing a `Thesis`. An anti-checklist gate rejects plans that merely restate a template (ADR-0006, ADR-0007, ADR-0008).

**Reasoning memory** (`atlas.research.memory`, ADR-0010) — `ThesisStore` persists a written view; `RecalledView`/`RecalledClaim` feed a prior thesis back into a later answer, present-gated so absence is never faked; deterministic staleness checking flags views overtaken by newer filings; and `contradicts_thesis` / `counter_case` surface where fresh evidence cuts against what you previously concluded.

**Evaluation and benchmark** (`atlas.eval`, `atlas.benchmark`) — an acceptance suite of graded cases with deterministic correctness and grounding scorers, an evidence-aware LLM-as-judge scoring reasoning quality, usefulness and evidence use, refusal judging with an `honest_negative` expected-behaviour class, machine-readable run reports, and `ComparisonEngine` for milestone-over-milestone diffs. A response cache and `--judge-sample` make the harness runnable on free-tier API quotas. On the benchmark side, two orthogonal taxonomies (ADR-0005, ADR-0011): six `RetrievalScenario` classes describing the retrieval problem a case poses, and 24 `AtlasCapability` ids describing what the system must be able to do at all — grouped `acq.*` (acquisition coverage), `struct.*` (structured extraction), `reason.*`, `mem.*`, `ext.*` (genuinely external data), `eval.*`. `CoverageAnalyzer` reports suite coverage against both axes, and provenance validation machine-checks that a case's claimed evidence actually exists in the corpus rather than being an abstract exercise.

CLI: `atlas repository build`, `atlas acquire`, `atlas profile build`, `atlas query`, `atlas screen`, `atlas metrics`, `atlas ask`, `atlas research`, `atlas investigate`, `atlas thesis`, `atlas memory list/show/diff/check`, `atlas eval run/compare/compare-retrieval/coverage/validate-cases`.

**Measured position.** The last frozen baseline (`eval_reports/M1.5-baseline.json`, gemini-2.5-flash) scored 84.6% correctness and 92.3% grounding on 31 active cases out of 44, at 70.5% suite coverage. The suite has since grown to 99 cases at 85.9% coverage, but **no baseline has been re-frozen against it** — the numbers above are the honest last-known-good, not current.

---

### Where it stands against real questions

A 45-question investor questionnaire was run end-to-end against the TCS repository (July 2026) as an external check. Result: **15 fully answered, 16 partially answered, 14 unanswerable.**

What that exercise established, in rough order of how much it costs:

* The **binding constraint is corpus breadth, not extraction quality.** Every one of the 14 unanswerable questions failed on information Atlas never ingests — price and valuation, peer financials, broker research, forum and expert commentary, trade data, promoter background. No amount of better parsing reaches them.
* **Single-company silos block comparative questions.** `repositories/` holds three companies with no cross-repository query path, so any "versus peers" question is structurally unattemptable even where the data exists.
* **Corpus depth is uneven inside a single company.** TCS has 6 earnings transcripts, all Q2/Q4 — every Q1 and Q3 call is missing, so "what changed since last quarter" silently answers a six-month delta. One shareholding pattern exists, so no ownership movement can be computed.
* **The derived fact layer under-serves the raw text it was built from.** Several questions were answerable only by falling back to raw-document search: `profile.json`'s `risk_factors` array is largely extraction noise (footnote fragments, committee-membership lines), `segments` held one quarter where the annual report carries a full multi-year vertical table, and `debt_ratings` was empty. More documents flowing into a lossy analyzer will not improve answers.
* **Table-structure fidelity is the top extraction defect.** Observed in one report: a lease-liability line internally inconsistent between balance sheet and notes, order-scrambled revenue-by-geography labels, and dropped rows in investor-meeting schedules.
* **There is no user memory in practice.** `research/` contains only a `.gitkeep`, so "what did I conclude two years ago" — a Stage 4 goal question in this README — has no substrate yet, even though `ThesisStore` is built and ready to hold one.

---

### Next

Ranked by incremental investment insight, not engineering elegance. The top three come directly from the questionnaire run above and displace what was previously queued.

**Corpus and coverage — where the answers actually are**

* **Backfill quarterly coverage before adding new document types.** Q1/Q3 transcripts and results, and the full quarterly shareholding-pattern series, are missing across all three companies. This is the cheapest large gain available: it converts "what changed since last quarter" and "has ownership moved" from partial to full, needs no new analyzer, and every downstream layer already handles the shapes. Related-party Reg. 23(9) half-yearly filings are similarly thin — 3 of ~14 half-years for TCS.
* **Cross-repository comparative queries.** The three reference companies were deliberately chosen to span sectors, but nothing can currently read two of them at once. `atlas screen` is the seam this should grow from. Until it exists, one full class of investment question is closed regardless of corpus quality.
* **Re-freeze an evaluation baseline against the 99-case suite.** The suite grew 44 → 99 cases while the last frozen baseline stayed at M1.5, so there is currently no defensible answer to "did the last five milestones make Atlas better." Every capability claim above is unmeasured against current code.

**Extraction quality — closing the gap to the raw text**

* **Table-structure fidelity in PDF extraction.** The highest-value defect class: financial-statement figures that disagree between statement and note, order-scrambled label/value pairs, and dropped table rows. These are silent — they produce plausible wrong numbers rather than visible failures — which makes them worse than missing data.
* **A real risk-register extractor.** `annual_report`'s risk-factor capture currently returns footnote fragments. Targeting the MD&A risk-management section and Key Audit Matters, with year-over-year diffing, would make `risk_recurrence` load-bearing instead of decorative.
* **Multi-year segment coverage in the profile.** Annual reports carry full vertical revenue and margin tables; the profile holds isolated quarters. This is an analyzer-coverage gap, not a source gap.
* Fix `brsr`'s workforce-headcount extraction for Tata Steel — values of 144-152 for a ~30,000-employee company. Pre-existing, unrelated to the transcript redesign, still open.

**Knowledge layer**

* **Entity attributes and persistence.** The entity model delivers identity only, and `annual_report` is the sole emitter. Roles, affiliations and tenure — plus emission from `earnings_transcript`, `board_outcome` and `agm_notice` — are what turn `former_answerers` from a text heuristic into a graph query, and what would let Atlas answer who runs a newly announced business line.
* `corporate_governance_report` analyzer — SEBI LODR Reg. 27(2) board-composition filing. Fills the reserved `GOVERNANCE_DIRECTOR` gap and has real volume (37+ filings for Tata Steel alone), though its table layout carries the same alignment risk noted above.

**Deferred, deliberately**

* Client-concentration band tracking ($100M+/$50M+ accounts) — real, non-duplicated investment value and it did carry a questionnaire answer, but still observed in one company only. Revisit when a second company shows the convention; not worth ontology surface area on a sample of one.
* `investor_presentation`'s STRATEGY_PRIORITY heading-anchor and STRATEGY_GUIDANCE patterns remain conservative by design (precision over recall) — revisit with more cross-company sample filings.
* Market data, peer financials, broker research and forum content are the largest measured gap by question count, but they are out-of-scope by design for now: each needs a licensing or scraping decision, not an engineering one. Recording them as known-absent — so Atlas says "outside the corpus" rather than guessing — is the current answer, and the `ext.*` capability family exists to keep that honest.
